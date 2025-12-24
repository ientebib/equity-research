"""
Transcript client with tiered resolution.

Attempts to fetch earnings call transcripts from multiple sources
in order of preference and reliability.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from er.config import get_settings
from er.evidence.store import EvidenceStore
from er.logging import get_logger
from er.types import SourceTier, ToSRisk

logger = get_logger(__name__)


class TranscriptClient:
    """Client for fetching earnings call transcripts.

    Tiered resolution:
    1. Check if transcript is in SEC filing (8-K exhibits)
    2. Financial Modeling Prep API (if FMP_API_KEY configured)
    3. Finnhub API (if FINNHUB_API_KEY configured)
    4. Return None (will fall back to web search in research phase)
    """

    def __init__(self, evidence_store: EvidenceStore) -> None:
        """Initialize transcript client.

        Args:
            evidence_store: Store for persisting fetched content.
        """
        self.evidence_store = evidence_store
        self.settings = get_settings()
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def get_transcript(
        self,
        ticker: str,
        quarter: int,
        year: int,
    ) -> dict[str, Any] | None:
        """Get earnings call transcript for a specific quarter.

        Tries multiple sources in order of preference.

        Args:
            ticker: Stock ticker symbol.
            quarter: Quarter number (1-4).
            year: Fiscal year.

        Returns:
            Dict with: text, date, participants, qa_section
            Or None if not available.
        """
        ticker = ticker.upper()
        quarter_str = f"Q{quarter}"

        logger.info(
            "Fetching transcript",
            ticker=ticker,
            quarter=quarter_str,
            year=year,
        )

        # Tier 1: SEC 8-K exhibits (not implemented yet - complex to parse)
        # transcript = await self._try_sec_transcript(ticker, quarter, year)
        # if transcript:
        #     return transcript

        # Tier 2: Financial Modeling Prep
        if self.settings.FMP_API_KEY:
            transcript = await self._try_fmp_transcript(ticker, quarter, year)
            if transcript:
                return transcript

        # Tier 3: Finnhub
        if self.settings.FINNHUB_API_KEY:
            transcript = await self._try_finnhub_transcript(ticker, quarter, year)
            if transcript:
                return transcript

        # Tier 4: Return None (will fall back to web search)
        logger.warning(
            "Transcript not found in any source",
            ticker=ticker,
            quarter=quarter_str,
            year=year,
        )
        return None

    async def _try_fmp_transcript(
        self,
        ticker: str,
        quarter: int,
        year: int,
    ) -> dict[str, Any] | None:
        """Try to fetch transcript from Financial Modeling Prep.

        Args:
            ticker: Stock ticker symbol.
            quarter: Quarter number (1-4).
            year: Fiscal year.

        Returns:
            Transcript dict or None if not found.
        """
        if not self.settings.FMP_API_KEY:
            return None

        try:
            client = await self._get_client()
            url = (
                f"https://financialmodelingprep.com/api/v3/earning_call_transcript/{ticker}"
                f"?quarter={quarter}&year={year}&apikey={self.settings.FMP_API_KEY}"
            )

            response = await client.get(url)
            response.raise_for_status()

            data = response.json()

            if not data or len(data) == 0:
                logger.debug("No FMP transcript found", ticker=ticker)
                return None

            transcript_data = data[0]
            content = transcript_data.get("content", "")

            if not content:
                return None

            # Parse into sections
            transcript = {
                "ticker": ticker,
                "quarter": quarter,
                "year": year,
                "date": transcript_data.get("date"),
                "text": content,
                "source": "fmp",
                "participants": self._extract_participants(content),
                "qa_section": self._extract_qa_section(content),
            }

            # Store as evidence
            import orjson

            await self.evidence_store.store(
                url=f"fmp://transcript/{ticker}/{year}/Q{quarter}",
                content=orjson.dumps(transcript),
                content_type="application/json",
                snippet=content[:2000],
                title=f"Earnings Call Transcript - {ticker} Q{quarter} {year}",
                tos_risk=ToSRisk.NONE,
                source_tier=SourceTier.INSTITUTIONAL,
            )

            logger.info(
                "Found FMP transcript",
                ticker=ticker,
                quarter=f"Q{quarter}",
                year=year,
                length=len(content),
            )

            return transcript

        except httpx.HTTPStatusError as e:
            logger.debug("FMP API error", status=e.response.status_code)
            return None
        except Exception as e:
            logger.warning("FMP transcript fetch failed", error=str(e))
            return None

    async def _try_finnhub_transcript(
        self,
        ticker: str,
        quarter: int,
        year: int,
    ) -> dict[str, Any] | None:
        """Try to fetch transcript from Finnhub.

        Args:
            ticker: Stock ticker symbol.
            quarter: Quarter number (1-4).
            year: Fiscal year.

        Returns:
            Transcript dict or None if not found.
        """
        if not self.settings.FINNHUB_API_KEY:
            return None

        try:
            client = await self._get_client()

            # First get list of available transcripts
            list_url = (
                f"https://finnhub.io/api/v1/stock/transcripts/list"
                f"?symbol={ticker}&token={self.settings.FINNHUB_API_KEY}"
            )

            response = await client.get(list_url)
            response.raise_for_status()

            transcripts_list = response.json()

            if not transcripts_list:
                logger.debug("No Finnhub transcripts found", ticker=ticker)
                return None

            # Find matching quarter
            target_quarter = f"Q{quarter} {year}"
            matching_id = None

            for t in transcripts_list:
                if t.get("quarter") == quarter and str(t.get("year")) == str(year):
                    matching_id = t.get("id")
                    break

            if not matching_id:
                logger.debug("No matching Finnhub transcript", ticker=ticker, quarter=quarter, year=year)
                return None

            # Fetch the transcript
            transcript_url = (
                f"https://finnhub.io/api/v1/stock/transcripts"
                f"?id={matching_id}&token={self.settings.FINNHUB_API_KEY}"
            )

            response = await client.get(transcript_url)
            response.raise_for_status()

            data = response.json()

            if not data or not data.get("transcript"):
                return None

            # Combine transcript parts into full text
            parts = data.get("transcript", [])
            full_text = "\n\n".join(
                f"[{p.get('name', 'Unknown')}]: {p.get('speech', '')}"
                for p in parts
            )

            transcript = {
                "ticker": ticker,
                "quarter": quarter,
                "year": year,
                "date": data.get("time"),
                "text": full_text,
                "source": "finnhub",
                "participants": [p.get("name") for p in parts if p.get("name")],
                "qa_section": self._extract_qa_section(full_text),
            }

            # Store as evidence
            import orjson

            await self.evidence_store.store(
                url=f"finnhub://transcript/{ticker}/{year}/Q{quarter}",
                content=orjson.dumps(transcript),
                content_type="application/json",
                snippet=full_text[:2000],
                title=f"Earnings Call Transcript - {ticker} Q{quarter} {year}",
                tos_risk=ToSRisk.NONE,
                source_tier=SourceTier.INSTITUTIONAL,
            )

            logger.info(
                "Found Finnhub transcript",
                ticker=ticker,
                quarter=f"Q{quarter}",
                year=year,
                length=len(full_text),
            )

            return transcript

        except httpx.HTTPStatusError as e:
            logger.debug("Finnhub API error", status=e.response.status_code)
            return None
        except Exception as e:
            logger.warning("Finnhub transcript fetch failed", error=str(e))
            return None

    async def get_available_transcripts(
        self,
        ticker: str,
    ) -> list[dict[str, Any]]:
        """Get list of available transcripts for a ticker.

        Args:
            ticker: Stock ticker symbol.

        Returns:
            List of dicts with: quarter, year, date, source
        """
        ticker = ticker.upper()
        available: list[dict[str, Any]] = []

        # Try FMP
        if self.settings.FMP_API_KEY:
            try:
                client = await self._get_client()
                url = (
                    f"https://financialmodelingprep.com/api/v3/earning_call_transcript/{ticker}"
                    f"?apikey={self.settings.FMP_API_KEY}"
                )

                response = await client.get(url)
                response.raise_for_status()

                data = response.json()

                for item in data or []:
                    available.append({
                        "quarter": item.get("quarter"),
                        "year": item.get("year"),
                        "date": item.get("date"),
                        "source": "fmp",
                    })

            except Exception as e:
                logger.debug("FMP list fetch failed", error=str(e))

        # Try Finnhub
        if self.settings.FINNHUB_API_KEY:
            try:
                client = await self._get_client()
                url = (
                    f"https://finnhub.io/api/v1/stock/transcripts/list"
                    f"?symbol={ticker}&token={self.settings.FINNHUB_API_KEY}"
                )

                response = await client.get(url)
                response.raise_for_status()

                data = response.json()

                for item in data or []:
                    # Check if not already in list from FMP
                    q = item.get("quarter")
                    y = item.get("year")
                    if not any(a["quarter"] == q and a["year"] == y for a in available):
                        available.append({
                            "quarter": q,
                            "year": y,
                            "date": item.get("time"),
                            "source": "finnhub",
                        })

            except Exception as e:
                logger.debug("Finnhub list fetch failed", error=str(e))

        # Sort by date descending
        available.sort(key=lambda x: (x.get("year", 0), x.get("quarter", 0)), reverse=True)

        logger.info(
            "Found available transcripts",
            ticker=ticker,
            count=len(available),
        )

        return available

    def _extract_participants(self, text: str) -> list[str]:
        """Extract participant names from transcript text.

        Args:
            text: Full transcript text.

        Returns:
            List of participant names.
        """
        import re

        # Common patterns for speaker identification
        patterns = [
            r"\[([A-Z][a-zA-Z\s]+)\]:",  # [Name]:
            r"^([A-Z][a-zA-Z\s]+):\s",  # Name: at line start
            r"-- ([A-Z][a-zA-Z\s]+),",  # -- Name, Title
        ]

        participants = set()

        for pattern in patterns:
            matches = re.findall(pattern, text, re.MULTILINE)
            participants.update(m.strip() for m in matches if len(m.strip()) > 2)

        return list(participants)[:20]  # Limit to avoid noise

    def _extract_qa_section(self, text: str) -> str | None:
        """Extract Q&A section from transcript.

        Args:
            text: Full transcript text.

        Returns:
            Q&A section text or None if not found.
        """
        import re

        # Common markers for Q&A section
        qa_markers = [
            r"(?:Question[s]?[\s-]+and[\s-]+Answer|Q[\s&]+A|Q&A Session)",
            r"(?:Operator:.*?first question)",
            r"(?:We.ll now take questions)",
        ]

        for marker in qa_markers:
            match = re.search(marker, text, re.IGNORECASE)
            if match:
                # Return everything from the marker to the end
                qa_text = text[match.start():]
                # Limit length
                if len(qa_text) > 30000:
                    qa_text = qa_text[:30000] + "\n... [truncated]"
                return qa_text

        return None
