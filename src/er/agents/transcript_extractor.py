"""
Transcript Extraction Agent.

Extracts structured information from earnings call transcripts using
a fast, cheap model (gpt-5.2-mini). Produces targeted excerpts that are
significantly smaller than full transcripts while preserving key information.

This runs after Data Orchestrator but before Discovery, allowing downstream
agents to use compact, structured transcript data instead of raw text.
"""

from __future__ import annotations

import json
import re
from typing import Any

from er.agents.base import Agent, AgentContext
from er.llm.base import LLMRequest
from er.llm.openai_client import OpenAIClient
from er.logging import get_logger
from er.types import RunState, TranscriptExtract

logger = get_logger(__name__)

# Prompt for transcript extraction
EXTRACTION_PROMPT = """You are a financial analyst assistant specializing in extracting key information from earnings call transcripts.

Analyze the following transcript and extract structured information. Be thorough but concise.

## Transcript ({quarter} {year})
{transcript_text}

## Instructions
Extract the following information in JSON format:

1. **kpi_mentions**: List of key metrics mentioned with their values
   - Format: {{"metric": "ARR", "value": "$5.2B", "context": "brief context", "change_yoy": "+15%"}}
   - Include: Revenue, margins, growth rates, customer metrics, etc.

2. **guidance_changes**: Any changes to forward guidance
   - Format: {{"metric": "FY Revenue", "old": "$20B", "new": "$21B", "direction": "raised", "quote": "verbatim quote"}}

3. **heated_exchanges**: Contentious Q&A exchanges (analyst pushback, skeptical questions)
   - List of brief summaries (50-100 words each)

4. **deflected_questions**: Questions that received vague or non-answers
   - List of brief summaries

5. **repeated_themes**: Topics mentioned 3+ times
   - List of theme names

6. **new_initiatives**: First-time mentions of products, markets, strategies
   - List of initiative names/descriptions

7. **key_quotes**: Most important verbatim quotes (max 10)
   - Management statements on strategy, outlook, competition

8. **tone_indicators**: Management's tone on key topics
   - Format: {{"overall": "confident/cautious/defensive", "on_guidance": "...", "on_competition": "..."}}

Respond with ONLY valid JSON matching this structure:
```json
{{
  "kpi_mentions": [...],
  "guidance_changes": [...],
  "heated_exchanges": [...],
  "deflected_questions": [...],
  "repeated_themes": [...],
  "new_initiatives": [...],
  "key_quotes": [...],
  "tone_indicators": {{...}}
}}
```"""


class TranscriptExtractorAgent(Agent):
    """Agent for extracting structured information from transcripts.

    Uses gpt-5.2-mini for fast, cheap extraction. Produces TranscriptExtract
    objects that are ~10x smaller than raw transcripts.
    """

    def __init__(self, context: AgentContext) -> None:
        """Initialize the transcript extractor agent."""
        super().__init__(context)
        self._openai_client: OpenAIClient | None = None

    @property
    def name(self) -> str:
        return "transcript_extractor"

    @property
    def role(self) -> str:
        return "Extract structured information from earnings call transcripts"

    async def _get_openai_client(self) -> OpenAIClient:
        """Get or create OpenAI client."""
        if self._openai_client is None:
            self._openai_client = OpenAIClient(
                api_key=self.settings.openai_api_key,
            )
        return self._openai_client

    async def run(
        self,
        run_state: RunState,
        transcripts: list[dict[str, Any]],
    ) -> list[TranscriptExtract]:
        """Extract structured information from transcripts.

        Args:
            run_state: Current run state.
            transcripts: List of transcript dicts with 'quarter', 'year', 'text' keys.

        Returns:
            List of TranscriptExtract objects.
        """
        if not transcripts:
            self.log_info("No transcripts to extract", ticker=run_state.ticker)
            return []

        self.log_info(
            "Starting transcript extraction",
            ticker=run_state.ticker,
            transcript_count=len(transcripts),
        )

        extracts = []
        for transcript in transcripts:
            try:
                extract = await self._extract_single(run_state, transcript)
                extracts.append(extract)
            except Exception as e:
                self.log_error(
                    "Failed to extract transcript",
                    ticker=run_state.ticker,
                    quarter=transcript.get("quarter"),
                    year=transcript.get("year"),
                    error=str(e),
                )
                # Create minimal fallback extract
                extracts.append(self._create_fallback_extract(transcript))

        self.log_info(
            "Transcript extraction complete",
            ticker=run_state.ticker,
            extracted_count=len(extracts),
        )

        return extracts

    async def _extract_single(
        self,
        run_state: RunState,
        transcript: dict[str, Any],
    ) -> TranscriptExtract:
        """Extract information from a single transcript."""
        quarter = transcript.get("quarter", 0)
        year = transcript.get("year", 0)
        text = transcript.get("text", "")

        # Truncate text if too long (gpt-5.2-mini has 128K context but we want speed)
        max_chars = 60000  # ~15K tokens
        if len(text) > max_chars:
            text = text[:max_chars] + "\n[... transcript truncated for extraction ...]"

        prompt = EXTRACTION_PROMPT.format(
            quarter=f"Q{quarter}",
            year=year,
            transcript_text=text,
        )

        client = await self._get_openai_client()

        request = LLMRequest(
            messages=[{"role": "user", "content": prompt}],
            model="gpt-5.2-mini",
            temperature=0.1,  # Low temp for consistency
            max_tokens=4000,  # Plenty for JSON response
        )

        response = await client.complete(request)

        # Track usage
        self.budget_tracker.record_usage(
            provider="openai",
            model="gpt-5.2-mini",
            input_tokens=response.usage.get("input_tokens", 0),
            output_tokens=response.usage.get("output_tokens", 0),
            agent=self.name,
            phase="transcript_extraction",
        )

        # Parse JSON response
        parsed = self._parse_response(response.content, transcript)

        return TranscriptExtract(
            quarter=f"Q{quarter} {year}",
            year=year,
            quarter_num=quarter,
            kpi_mentions=parsed.get("kpi_mentions", []),
            guidance_changes=parsed.get("guidance_changes", []),
            heated_exchanges=parsed.get("heated_exchanges", []),
            deflected_questions=parsed.get("deflected_questions", []),
            repeated_themes=parsed.get("repeated_themes", []),
            new_initiatives=parsed.get("new_initiatives", []),
            key_quotes=parsed.get("key_quotes", []),
            tone_indicators=parsed.get("tone_indicators", {}),
            raw_excerpt=text[:2000],  # Keep first 2000 chars as fallback
        )

    def _parse_response(
        self,
        content: str,
        transcript: dict[str, Any],
    ) -> dict[str, Any]:
        """Parse JSON response from LLM."""
        # Try to extract JSON from response
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', content)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Try direct JSON parse
            json_str = content.strip()

        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            self.log_warning(
                "Failed to parse extraction JSON, using fallback",
                error=str(e),
                quarter=transcript.get("quarter"),
            )
            return {}

    def _create_fallback_extract(
        self,
        transcript: dict[str, Any],
    ) -> TranscriptExtract:
        """Create a minimal fallback extract when extraction fails."""
        quarter = transcript.get("quarter", 0)
        year = transcript.get("year", 0)
        text = transcript.get("text", "")

        return TranscriptExtract(
            quarter=f"Q{quarter} {year}",
            year=year,
            quarter_num=quarter,
            raw_excerpt=text[:4000],  # Longer excerpt for fallback
        )

    async def close(self) -> None:
        """Close resources."""
        if self._openai_client:
            await self._openai_client.close()
            self._openai_client = None
