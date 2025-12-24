# Equity Research

Institutional-grade AI-powered equity research system.

## Overview

`equity-research` is a Python-based system that leverages multiple LLM providers to conduct comprehensive equity research analysis. It automates the process of gathering financial data, analyzing company fundamentals, and producing institutional-quality research reports.

## Features

- **Multi-provider LLM support**: OpenAI, Anthropic, and Google Gemini
- **Automated data gathering**: SEC EDGAR filings, market data, earnings transcripts
- **Structured research pipeline**: Discovery, decomposition, research, synthesis, deliberation
- **Evidence-based analysis**: All findings backed by citable evidence
- **Budget controls**: Configurable spending limits per analysis run
- **Rich outputs**: Markdown reports, Excel models, evidence appendix

## Requirements

- Python 3.11 or higher
- macOS or Ubuntu
- At least one LLM provider API key (OpenAI, Anthropic, or Google)

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd equity-research
```

2. Create and activate a virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate
```

3. Install the package with development dependencies:
```bash
pip install -e ".[dev]"
```

4. Copy the example environment file and configure:
```bash
cp .env.example .env
# Edit .env with your API keys
```

## Configuration

Create a `.env` file with the following variables:

### Required
- `SEC_USER_AGENT`: Your email for SEC EDGAR API identification (SEC requirement)
- At least one of:
  - `OPENAI_API_KEY`: OpenAI API key
  - `ANTHROPIC_API_KEY`: Anthropic API key
  - `GEMINI_API_KEY`: Google Gemini API key

### Optional
- `FMP_API_KEY`: Financial Modeling Prep API key (for transcripts)
- `FINNHUB_API_KEY`: Finnhub API key (for transcripts)
- `MAX_BUDGET_USD`: Maximum budget per run (default: 25.0)
- `MAX_DELIBERATION_ROUNDS`: Maximum deliberation rounds (default: 5)
- `MAX_CONCURRENT_AGENTS`: Maximum concurrent agents (default: 6)
- `CACHE_DIR`: Cache directory (default: .cache)
- `OUTPUT_DIR`: Output directory (default: output)
- `LOG_LEVEL`: Logging level (default: INFO)

See `.env.example` for a complete list of options.

## Quick Start

1. Verify your configuration:
```bash
er config
```

2. Run analysis on a stock:
```bash
er analyze AAPL
```

3. Check the output directory for results:
```bash
ls output/
```

## CLI Commands

### `er analyze TICKER`

Run equity research analysis on a stock ticker.

Options:
- `--budget, -b`: Maximum budget in USD
- `--max-rounds, -r`: Maximum deliberation rounds
- `--dry-run, -n`: Create run folder without calling APIs
- `--output-dir, -o`: Output directory

### `er config`

Display current configuration with API keys redacted.

### `er version`

Print the version number.

## Development

### Running Tests

```bash
pytest tests/ -v
```

### Running Tests with Coverage

```bash
pytest tests/ --cov=er --cov-report=html
```

### Linting and Formatting

```bash
ruff check src/ tests/
ruff format src/ tests/
```

### Type Checking

```bash
mypy src/
```

### Pre-commit Hooks

Install pre-commit hooks:
```bash
pre-commit install
```

## Project Structure

```
equity-research/
├── src/er/
│   ├── __init__.py
│   ├── config.py          # Configuration management
│   ├── exceptions.py      # Custom exceptions
│   ├── types.py           # Core data types
│   ├── logging.py         # Structured logging
│   ├── cli/               # Command-line interface
│   ├── cache/             # Caching layer
│   ├── evidence/          # Evidence management
│   ├── data/              # Data fetching
│   ├── llm/               # LLM clients
│   ├── agents/            # Research agents
│   ├── coordinator/       # Orchestration
│   └── outputs/           # Output generation
├── tests/
├── scripts/
├── pyproject.toml
└── README.md
```

## License

MIT License
