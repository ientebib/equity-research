# Equity Research

An AI-powered equity research platform that produces institutional-grade investment analysis using a multi-agent pipeline with Claude, GPT, and Gemini.

## Overview

This system automates the equity research process through a 6-stage pipeline that combines financial data collection, competitive intelligence, deep segment analysis, and dual synthesis to produce comprehensive investment reports with evidence-backed recommendations.

```text
Stage 1: Data Collection → Financial statements, transcripts, market data
Stage 2: Discovery       → Internal analysis + external competitive intelligence
Stage 3: Deep Research   → Vertical analysts for each business segment
Stage 4: Dual Synthesis  → Claude Opus + GPT-5.2 generate independent reports
Stage 5: Editorial       → Judge agent compares and selects best analysis
Stage 6: Revision        → Final report with incorporated feedback
```

## Features

- **Multi-Agent Architecture** - Specialized AI agents for different research tasks
- **Multi-LLM Support** - Claude for reasoning, GPT for web search, Gemini for deep research
- **Evidence Tracking** - All claims are cited with source URLs and content hashes
- **Quant Metrics** - Pre-computed financial ratios, scores, and red flag detection
- **Budget Management** - Hard limits on LLM spending per analysis run
- **Resume Capability** - Checkpoint-based recovery for long-running analyses
- **Real-time Dashboard** - Next.js frontend with live pipeline visualization

## Quick Start

### Prerequisites

- Python 3.11 or 3.12
- Node.js 18+ (for frontend only)

### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/equity-research.git
cd equity-research

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install the package
pip install -e ".[dev]"

# Configure environment
cp .env.example .env
# Edit .env with your API keys
```

### Configuration

Create a `.env` file with your API keys:

```bash
# Required
SEC_USER_AGENT="YourName your@email.com"

# LLM Providers (at least one required)
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=...

# Data Sources (recommended)
FMP_API_KEY=...

# Optional
MAX_BUDGET_USD=25.0
OUTPUT_DIR=output/
```

### Usage

```bash
# Run analysis on a stock
er analyze AAPL

# With custom budget
er analyze GOOGL --budget 50.0

# Load transcripts from files instead of fetching
er analyze MSFT --transcripts-dir ./transcripts

# Resume from checkpoint
er analyze NVDA --resume output/run_NVDA_20250104_120000

# Dry run (no API calls)
er analyze AMZN --dry-run

# Show configuration
er config

# Show version
er version
```

## Architecture

### Pipeline Stages

| Stage | Agent | Purpose |
|-------|-------|---------|
| 1 | Data Orchestrator | Fetches financials, transcripts, market data from FMP |
| 2A | Discovery | Internal analysis of business segments and drivers |
| 2B | External Discovery | Competitive intelligence, analyst sentiment, news |
| 2C | Discovery Merger | Merges findings, identifies variant perceptions |
| 3 | Vertical Analysts | Deep research on individual business segments |
| 4 | Synthesizers | Two independent full reports (Claude + GPT) |
| 5 | Judge | Editorial review, selects best synthesis |
| 6 | Revision | Final polished report with feedback incorporated |

### Data Sources

- **FMP (Financial Modeling Prep)** - Financial statements, transcripts, analyst estimates
- **Yahoo Finance** - Real-time market data and pricing
- **Web Search** - News, competitor announcements, market discourse

### Quant Metrics

The system computes financial ratios and scores including:

- **Valuation**: P/E, PEG, EV/EBITDA, FCF yield
- **Quality**: Income quality, DSO, DIO, SBC/revenue
- **Capital Allocation**: ROIC, Capex/revenue, R&D/revenue
- **Health**: Debt/equity, interest coverage, current ratio
- **Scores**: Altman Z-score, Piotroski score
- **Red Flags**: Buyback distortion, earnings quality issues

## Project Structure

```text
equity-research/
├── src/er/
│   ├── agents/          # AI agent implementations
│   ├── coordinator/     # Pipeline orchestration
│   ├── llm/             # LLM provider wrappers
│   ├── data/            # Data fetching clients
│   ├── evidence/        # Evidence tracking
│   ├── cli/             # Command-line interface
│   └── types.py         # Core data types
├── frontend/            # Next.js dashboard
├── tests/               # Test suite
├── docs/                # Documentation
└── prompts/             # Agent prompt templates
```

## Frontend

The project includes a real-time dashboard for monitoring pipeline execution:

```bash
# Start the API server
cd frontend/api
python server.py

# Start the frontend (separate terminal)
cd frontend
npm install
npm run dev
# Open http://localhost:3000
```

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Type checking
mypy src/er

# Linting
ruff check src/er
```

## Output

Each analysis run produces:

- `report.md` - Final investment research report
- `manifest.json` - Run metadata and configuration
- Stage JSON files - Intermediate results from each pipeline stage
- `debug.log` - Detailed execution log

Output is saved to `output/run_{TICKER}_{timestamp}/`.

## License

MIT
