# Prompts Directory

> Editable prompt templates for the equity research pipeline.

## File Index

| File | Stage | Agent | Purpose |
|------|-------|-------|---------|
| `discovery_system.md` | 2 | Discovery | System prompt for 7-lens analysis |
| `discovery_user.md` | 2 | Discovery | User prompt template with variables |
| `deep_research.md` | 3 | Vertical Analyst | Deep research subagent prompt |
| `synthesis.md` | 4 | Synthesizer | Final report synthesis prompt |

## Variable Reference

### Discovery Prompts
- `{ticker}` - Stock ticker (e.g., "GOOGL")
- `{company_name}` - Full company name
- `{date}` - Today's date (YYYY-MM-DD)
- `{current_month}` - Current month name (e.g., "January")
- `{current_year}` - Current year (e.g., "2026")
- `{latest_quarter}` - Latest reported quarter (e.g., "Q3 2025")
- `{quarter_context}` - Formatted quarterly data context
- `{company_context}` - JSON-serialized company financial data

### Deep Research Prompts
All discovery variables plus:
- `{group_name}` - Research group name
- `{group_theme}` - Unifying theme for the group
- `{group_focus}` - Specific focus area
- `{verticals_detail}` - Details of verticals to research
- `{other_groups_detail}` - What co-analysts are researching
- `{review_guidance_section}` - Optional reviewer guidance

### Synthesis Prompts
- `{date}` - Today's date
- `{ticker}` - Stock ticker
- `{company_name}` - Full company name
- `{vertical_analyses}` - All deep research outputs
- `{verified_facts_section}` - Pre-verified facts with evidence IDs
- `{cross_vertical_section}` - Cross-vertical dependencies and risks

## Usage

These prompts are loaded by the pipeline agents. To modify behavior:

1. Edit the relevant `.md` file
2. The agent will load the updated prompt on next run
3. No code changes required for prompt iterations

## Design Principles

1. **Ground truth first** - Financial data comes from JSON, never from web search
2. **Recency matters** - Always use quarterly data over annual
3. **Cite everything** - Every claim needs evidence IDs
4. **Be specific** - Numbers, dates, sources required
5. **Admit gaps** - Unknown is better than hallucinated
