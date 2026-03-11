# ClaimFlow AI

**Dual-sided Agentic System for Insurance Claim Resolution**

Built with [WISE Framework](https://www.spjimr.org/) principles - serving both claimants and insurers for better outcomes.

## The Problem

Insurance claim rejections often trap claimants in automated grievance loops:
- Templated responses that don't address specific issues
- No escalation to medical/legal review
- Rejection reasons that lack causal analysis
- High barriers (literacy, time, emotional bandwidth) to persist

## The Solution

ClaimFlow AI is a dual-sided system:

### For Claimants
- **Guided intake** - Structure your case properly
- **Precedent matching** - Find relevant IRDAI/Ombudsman rulings
- **Auto-escalation** - Detect templated responses, keep pushing
- **Public accountability** - LinkedIn post drafts when stuck

### For Insurers (Future)
- Document processing with gap identification
- Structured decision tables for consistency
- Audit trails for compliance

## Quick Start

### 1. Installation

```bash
cd claimflow-ai
pip install -r requirements.txt

# Install Playwright browsers (for web scraping)
playwright install chromium
```

### 2. Configuration

```bash
# Copy example config
cp .env.example .env

# Edit .env with your credentials
```

Required:
- `GEMINI_API_KEY` - Get from [Google AI Studio](https://aistudio.google.com/apikey)

Optional (for email features):
- `YAHOO_EMAIL` - Your Yahoo email address
- `YAHOO_APP_PASSWORD` - [Generate app password](https://login.yahoo.com/account/security)

### 3. Initialize

```bash
python -m src.main init
```

### 4. Build Knowledge Base

```bash
# Scrape precedents from news sources
python -m src.main scrape --max-articles 30
```

### 5. Create Your Case

```bash
# Interactive case builder
python -m src.main new-case

# Or import from JSON
# See data/cases/example_case.json
```

### 6. Analyze & Draft

```bash
# Analyze rejection and find precedents
python -m src.main analyze CASE_ID

# Draft escalation email
python -m src.main draft CASE_ID --level 1 --output draft.txt

# Send email (requires Yahoo config)
python -m src.main send CASE_ID --to grievance@insurer.com
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `init` | Verify configuration and test connections |
| `new-case` | Create a new case interactively |
| `list-cases` | List all saved cases |
| `view-case CASE_ID` | View case details |
| `scrape` | Scrape precedents from news sources |
| `analyze CASE_ID` | Analyze rejection and find precedents |
| `draft CASE_ID` | Draft an escalation email |
| `send CASE_ID` | Send escalation email via Yahoo |
| `check-replies CASE_ID` | Check for and analyze replies |
| `stats` | Show system statistics |

## Project Structure

```
claimflow-ai/
├── src/
│   ├── llm/              # Gemini LLM client
│   ├── knowledge/        # Scraper + Vector store
│   ├── intake/           # Case builder
│   ├── analyzer/         # Rejection parser + Precedent matcher
│   ├── escalation/       # Email client + Drafter + Response detector
│   └── utils/            # Config, logging
├── data/
│   ├── cases/            # Your case files (JSON)
│   ├── precedents/       # Scraped articles
│   └── chroma/           # Vector embeddings
├── config/
│   └── settings.yaml     # Application config
└── templates/
    └── emails/           # Email templates
```

## Tech Stack

- **LLM**: Google Gemini (gemini-2.5-flash / gemini-3-pro-preview)
- **Vector DB**: ChromaDB (local)
- **Email**: Yahoo Mail (IMAP/SMTP with App Password)
- **Scraping**: httpx + BeautifulSoup
- **CLI**: Typer + Rich

## Models Used

| Task | Model | Why |
|------|-------|-----|
| General tasks | `gemini-2.5-flash` | Fast, cost-effective |
| Complex analysis | `gemini-3-pro-preview` | Better reasoning |
| Embeddings | `text-embedding-004` | Semantic search |

## Dashboard

ClaimFlow AI includes an interactive Streamlit dashboard that visualizes:
- Communication timeline (sent vs received, templated vs unique)
- Response repetition analysis (donut chart)
- Template phrase detection (bar chart)
- Response time analysis with IRDAI 15-day benchmark
- Key findings summary

```bash
streamlit run dashboard.py
```

Connect your Yahoo Mail or load demo data to explore.

## Roadmap

- [x] MVP: Case intake, precedent scraping, email drafting
- [x] Interactive dashboard with Plotly visualizations
- [ ] Email monitoring daemon
- [ ] LinkedIn post automation
- [ ] Insurer-side document processor
- [ ] Multi-language support

## Contributing

This started as a personal project to resolve my own claim. If you've faced similar issues or want to help build this:

1. Fork the repo
2. Create a feature branch
3. Submit a PR

## Legal Disclaimer

This tool is for educational and personal use. It does not constitute legal advice. Consult a professional for legal matters.

## Author

**Pratham Sharma**
Head of Product & Strategy | SPJIMR
[LinkedIn](https://www.linkedin.com/in/pratham-sharma-spjimr/)

---

*Built with frustration, shipped with purpose.*
