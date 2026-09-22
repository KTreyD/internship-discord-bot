#Disclaimer
I did plug this into Claude AI and tell it to write this README so this is the result and probably why you see emojis and stuff. Also during troubleshooting I told the same AI to remove my troubleshooting
code and thus it organized my code and put little comments that you can see. Other than that, everything else has been figured out and coded by my self with little to no usage from my copilot on vscode.

# Discord Internship Bot

Automatically fetches engineering internship postings from the Adzuna API, community-maintained GitHub internship lists, and company ATS boards (Greenhouse/Lever), then posts them to Discord channels organized by major as rich job cards.

## Features

- 🔍 Searches Adzuna API for internships across multiple engineering disciplines
- 🐙 Scrapes GitHub internship-tracker READMEs ([jobright-ai/2026-Engineer-Internship](https://github.com/jobright-ai/2026-Engineer-Internship) for broad engineering coverage, [SimplifyJobs/Summer2026-Internships](https://github.com/SimplifyJobs/Summer2026-Internships) for CS/software) for majors Adzuna alone doesn't surface well
- 🏢 Pulls directly from company ATS boards (Greenhouse, Lever) for a curated list of companies — no scraping needed, these are public JSON APIs
- 🤖 Categorizes jobs by major using Claude Haiku (semantic understanding, disambiguates overlapping majors like CIS/MIS/CS), automatically falling back to word-boundary keyword matching if no `ANTHROPIC_API_KEY` is set or the API call fails
- 🃏 Posts each job as a Discord embed "card" (company, location, work model, source, match score) instead of plain text
- 📢 Posts to specific Discord channels based on major
- 🗄️ Stores jobs in SQLite database to prevent duplicates
- ⏰ Runs on a 24-hour schedule to check for new postings

## Prerequisites

- Python 3.11+
- Discord bot token
- Adzuna API credentials (App ID and API Key)
- Anthropic API key (optional but recommended — from [console.anthropic.com](https://console.anthropic.com); without it, categorization falls back to keyword matching)

## Installation

1. Clone the repository:
```bash
git clone https://github.com/KTreyD/internship-discord-bot.git
cd internship-discord-bot
```

2. Create a virtual environment:
```bash
python -m venv venv
```

3. Activate the virtual environment:
   - Windows: `venv\Scripts\activate`
   - Mac/Linux: `source venv/bin/activate`

4. Install dependencies:
```bash
pip install -r requirements.txt
```

5. Create a `.env` file in the project root with your credentials:
```
DISCORD_TOKEN=your_discord_bot_token
ADZUNA_KEY=your_adzuna_api_key
ADZUNA_ID=your_adzuna_app_id
ANTHROPIC_API_KEY=your_anthropic_api_key
```

## Configuration

### Discord Channel IDs

Update `CHANNEL_IDS` in `bot.py` with your Discord channel IDs:
```python
CHANNEL_IDS = {
    "mechanical": YOUR_CHANNEL_ID,
    "electrical": YOUR_CHANNEL_ID,
    # ... add more
}
```

### Search Terms

Modify `ADZUNA_SEARCH_TERMS` in `sources/adzuna.py` to customize job searches:
```python
ADZUNA_SEARCH_TERMS = [
    "mechanical engineer intern",
    "software engineer intern",
    # ... add more
]
```

### GitHub Sources

Add or remove repos in `GITHUB_REPOS` in `sources/github_repos.py`. Each entry needs the raw README URL and a `format` of `"markdown"` (pipe-delimited tables) or `"html"` (raw `<table>` markup) depending on how that repo's README is written:
```python
GITHUB_REPOS = [
    {"name": "org/repo", "url": "https://raw.githubusercontent.com/org/repo/branch/README.md", "format": "markdown"},
    # ... add more
]
```

### ATS Sources (Greenhouse/Lever)

`sources/ats.py` fetches concurrently (`ThreadPoolExecutor`, 8 workers) with timeouts and retries, so a bad slug or slow host can't hang the daily run. Company slugs are grouped by sector so non-CS majors get real coverage:

```python
GREENHOUSE_COMPANIES_TECH = [...]           # -> computer science, computer, CIS, MIS
GREENHOUSE_COMPANIES_ENERGY = [...]         # -> chemical, electrical, petroleum
GREENHOUSE_COMPANIES_MANUFACTURING = [...]  # -> mechanical, industrial, electrical
GREENHOUSE_COMPANIES_AEC = [...]            # -> civil, construction management (currently empty, see Known Limitations)
GREENHOUSE_COMPANIES_BIOTECH = [...]        # -> biomedical, chemical
LEVER_COMPANIES = ["palantir", ...]
```

Find a company's slug from their careers page URL — `boards.greenhouse.io/acme` → `"acme"`, `jobs.lever.co/acme` → `"acme"`. **Verify live before committing a slug** — run `python -m sources.ats` and keep only slugs that return `200` with a plausible (nonzero) internship count; a dead slug is a 404 logged daily forever. `_INTERN_RE` matches `intern`, `internship`, `co-op`, and `coop`, since non-tech employers frequently title postings "Engineering Co-Op — Summer".

### Categorization

By default, jobs are categorized by Claude Haiku (`categorize_job_llm` in `categorizer.py`) using the definitions in `MAJOR_DESCRIPTIONS` — edit those to change how majors are distinguished. Without an `ANTHROPIC_API_KEY`, or if the API call fails, it falls back to `categorize_job_keywords`, which matches against `MAJOR_KEYWORDS`:
```python
MAJOR_KEYWORDS = {
    "mechanical": ["mechanical", "CAD", "manufacturing", ...],
    # ... add more
}
```

## Usage

Run the bot:
```bash
python bot.py
```

The bot will:
1. Connect to Discord
2. Immediately check for new internships
3. Continue checking every 24 hours automatically

Stop the bot with `Ctrl+C`.

## Deployment (Azure Container Instances)

The bot runs 24/7 on Azure so it doesn't depend on this machine being on. Resources (all in `eastus`, resource group `internship-bot-rg`):

- **ACR** `internshipbotacr` — holds the built image (`internship-bot:latest`)
- **Storage account** `internshipbotsa`, file share `internship-data` — mounted at `/data` in the container so `internships.db` survives redeploys (see `DB_PATH` in `database.py`)
- **Container group** `internship-bot` — 0.5 vCPU / 1GB, `--restart-policy Always`

To ship a code change:
```bash
az acr build --registry internshipbotacr --image internship-bot:latest .
az container restart --resource-group internship-bot-rg --name internship-bot
```

To view logs (the `az container logs` command has a known Windows console Unicode bug with emoji output — fetch via REST instead if it crashes):
```bash
az container logs --resource-group internship-bot-rg --name internship-bot
```

Secrets (`DISCORD_TOKEN`, `ADZUNA_ID`, `ADZUNA_KEY`, `ANTHROPIC_API_KEY`) live as secure environment variables on the container group, set via `az container create --secure-environment-variables ...` — not from the `.env` file, which is only used for local runs.

## Project Structure
```
internship-discord-bot/
├── bot.py                     # Discord bot, scheduling, fetch/dedup/categorize/post pipeline
├── categorizer.py             # Job categorization by major (batched Claude Haiku, keyword fallback)
├── database.py                # SQLite schema migration + batch-shaped queries
├── dedup.py                   # Pure normalization/fingerprinting + in-batch near-dup collapse
├── logging_setup.py           # Rotating file + stdout logging configuration
├── sources/
│   ├── base.py                 # Shared Job dataclass returned by every source
│   ├── util.py                  # Shared HTTP helper (timeouts, retries) + HTML-stripping
│   ├── adzuna.py                # Adzuna API fetcher
│   ├── ats.py                   # Greenhouse/Lever direct ATS fetcher (threaded, sector-grouped)
│   └── github_repos.py          # GitHub README scraper (markdown + HTML table parsers)
├── dashboard/                  # Local-only, read-only Flask monitoring UI (not deployed)
│   ├── app.py
│   └── templates/
├── tests/                      # pytest suite (dedup, categorizer, database, ATS slug hygiene)
├── .github/workflows/ci.yml    # Runs pytest on push/PR
├── requirements.txt            # Pinned production dependencies
├── requirements-dev.txt        # requirements.txt + pytest + flask
├── .env                        # Environment variables (not in git)
├── .gitignore                  # Git ignore file
└── internships.db              # SQLite database (auto-created)
```

## Development

Install dev dependencies and run the test suite:
```bash
pip install -r requirements-dev.txt
pytest
```

Run the local monitoring dashboard against a copy of the database (never point it at the live DB the bot is writing to and expect write access — it's opened read-only by design):
```bash
flask --app dashboard.app run
```

## How It Works

1. **Retry backlog**: Any job left unposted from a previous run (crash, transient Discord outage) is retried first, before new volume is fetched.
2. **Fetching**: Bot queries the Adzuna API, scrapes each configured GitHub README, and hits each configured Greenhouse/Lever company board concurrently (each source runs in a worker thread so a slow host never blocks the Discord heartbeat), normalizing everything into a common `Job` shape.
3. **In-batch dedup**: `dedup.py` collapses near-duplicate postings within the same fetch (e.g. the same posting worded slightly differently across sources).
4. **Duplicate check against history**: The remaining batch is checked against the database by exact URL and exact normalized company+title fingerprint, in one indexed lookup, to prevent posting the same job twice across runs.
5. **Categorization**: New jobs are prompt-packed into chunks of ~15 and sent to Claude Haiku in one call per chunk (falling back to per-job, then keyword matching, on any failure or misalignment) to determine relevant majors, ranked by confidence/relevance.
6. **Storage**: Job details are bulk-inserted into SQLite before posting (crash-safe).
7. **Posting**: Jobs are posted as Discord embeds to the appropriate channel(s) based on major, rate-limited to ~1 message/second globally; failures are retried in-run and, if still incomplete, picked up by the next run's retry pass.

## API Rate Limits

- **Adzuna Free Tier**: 250 API calls/month
- **Current usage**: `ADZUNA_SEARCH_TERMS` has 49 terms, fired once per daily run = ~1,470 calls/month — well over the free tier. Reduce the term list or the run frequency if you're on the free tier, or upgrade the plan.

## Known Limitations

- Greenhouse/Lever coverage is still tech/startup-skewed by nature of which companies use those ATS platforms. Sector-grouped slug lists for energy, manufacturing, and biotech add some non-software coverage (`sources/ats.py`), but an AEC/construction-tech list is still empty — none of the candidate company boards checked had a live, nonzero internship count at the time. GitHub sources remain the primary non-CS coverage.
- LLM categorization runs `messages.parse` synchronously per prompt-packed chunk (up to 15 jobs) rather than through the Anthropic Message Batches API, which trades a larger latency win for simplicity — acceptable at this volume (once/day, a few hundred new jobs).

## Future Improvements

- [x] Add GitHub README scraping as a second (and third) data source
- [x] Add direct ATS (Greenhouse/Lever) source
- [x] Replace keyword categorization with an LLM (Claude Haiku), with keyword fallback
- [x] Fuzzy dedup across sources (match on company + normalized title) — see `dedup.py`
- [x] Batch LLM categorization calls to cut latency/API overhead — see `categorizer.categorize_jobs`
- [x] Implement error logging to file — see `logging_setup.py`
- [x] Add retry logic for failed Discord posts — see `retry_unposted` in `bot.py`
- [x] Add web dashboard for monitoring — see `dashboard/`, run locally only

## Contributing

This is a personal project, but suggestions are welcome!

## License

MIT License - feel free to use and modify for your own Discord server.

## Author

Built by Trey De'De'

## Acknowledgments

- [SimplifyJobs](https://github.com/SimplifyJobs/Summer2026-Internships) and [jobright-ai](https://github.com/jobright-ai/2026-Engineer-Internship) for the community-maintained internship lists this bot scrapes
- [Adzuna API](https://developer.adzuna.com/) for job data
- [discord.py](https://discordpy.readthedocs.io/) for Discord integration
