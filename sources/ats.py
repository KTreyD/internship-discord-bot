"""Fetches internship postings directly from company ATS (applicant tracking
system) job boards. Most career pages are built on a handful of ATS platforms
that expose free, public, unauthenticated JSON APIs, so a handful of company
slugs gets full coverage of that company's postings without scraping HTML.

Company slugs below were verified live (200 response with a plausible
internship count) against the public Greenhouse/Lever board APIs. Add more
by finding a company's board slug from their careers page URL, e.g. a
Greenhouse careers page at boards.greenhouse.io/acme -> slug "acme"; a
Lever page at jobs.lever.co/acme -> slug "acme". Verify with
`python -m sources.ats` before committing a new slug - a dead slug is a
404 logged daily forever.
"""
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from sources.base import Job
from sources.util import get_json, strip_tags

log = logging.getLogger(__name__)

# Matches "intern"/"internship"/"co-op"/"coop" as a whole word, not as a
# substring of "international" or similar. Non-tech employers (energy,
# manufacturing, AEC, biotech) overwhelmingly title postings things like
# "Engineering Co-Op - Summer 2026" rather than "Intern".
_INTERN_RE = re.compile(r"\b(intern(ship)?|co-?op)\b", re.IGNORECASE)

# --- Sector-grouped Greenhouse slugs -----------------------------------
# Existing, previously-verified tech/startup set.
GREENHOUSE_COMPANIES_TECH = [
    "stripe", "airbnb", "robinhood", "asana", "coinbase", "figma",
    "databricks", "cloudflare", "affirm", "gusto", "instacart", "brex",
    "pinterest", "reddit", "samsara", "mongodb", "elastic", "gitlab",
    "squarespace", "duolingo", "chime", "toast", "lyft",
]

# Verified live (2026-09-22) against https://boards-api.greenhouse.io/v1/boards/{slug}/jobs.
# Energy (fusion/nuclear/geothermal hardware) -> chemical, electrical, petroleum.
GREENHOUSE_COMPANIES_ENERGY = ["lunarenergy", "kairospower", "quaise"]

# Verified live (2026-09-22). Defense/auto/aero/robotics hardware
# manufacturers -> mechanical, industrial, electrical.
GREENHOUSE_COMPANIES_MANUFACTURING = [
    "astranis", "waymo", "nuro", "vannevarlabs", "formic", "figureai", "apptronik",
]

# TODO: verify slugs live before populating. Searched a broad list of
# construction-tech / civil engineering / AEC companies' Greenhouse boards
# (buildots, procore, katerra, icon, dpr-construction, truebeck, siteline,
# and ~20 more slug guesses) and found none with a live board returning a
# nonzero internship count as of 2026-09-22 - either 404 (not on
# Greenhouse) or 0 open internships. Leaving empty rather than committing
# an unverified or dead slug. Revisit with better-sourced company names
# (e.g. from an AEC-tech company directory) rather than guessed slugs.
GREENHOUSE_COMPANIES_AEC: list[str] = []

# Verified live (2026-09-22). Biotech / medical device companies ->
# biomedical, chemical.
GREENHOUSE_COMPANIES_BIOTECH = ["ginkgobioworks", "abcellera"]

GREENHOUSE_COMPANIES = [
    *GREENHOUSE_COMPANIES_TECH,
    *GREENHOUSE_COMPANIES_ENERGY,
    *GREENHOUSE_COMPANIES_MANUFACTURING,
    *GREENHOUSE_COMPANIES_AEC,
    *GREENHOUSE_COMPANIES_BIOTECH,
]

LEVER_COMPANIES = ["palantir"]

_MAX_WORKERS = 8


def fetch_greenhouse_jobs(company: str) -> list[Job]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true"
    data = get_json(url)
    if data is None:
        log.error("Error fetching Greenhouse/%s", company)
        return []

    jobs = []
    for raw in data.get("jobs", []):
        title = raw.get("title", "")
        if not _INTERN_RE.search(title):
            continue

        jobs.append(Job(
            url=raw.get("absolute_url", ""),
            title=title,
            company=raw.get("company_name") or company.title(),
            description=strip_tags(raw.get("content", "")),
            location=(raw.get("location") or {}).get("name", ""),
            source=f"Greenhouse/{company}",
        ))
    return jobs


def fetch_lever_jobs(company: str) -> list[Job]:
    url = f"https://api.lever.co/v0/postings/{company}?mode=json"
    data = get_json(url)
    if data is None:
        log.error("Error fetching Lever/%s", company)
        return []

    jobs = []
    for raw in data:
        title = raw.get("text", "")
        categories = raw.get("categories", {})
        is_internship = _INTERN_RE.search(title) or _INTERN_RE.search(categories.get("commitment", ""))
        if not is_internship:
            continue

        jobs.append(Job(
            url=raw.get("hostedUrl", ""),
            title=title,
            company=company.title(),
            description=raw.get("descriptionPlain", ""),
            location=categories.get("location", ""),
            work_model=categories.get("workplaceType", ""),
            source=f"Lever/{company}",
        ))
    return jobs


def fetch_all_ats_jobs() -> list[Job]:
    jobs: list[Job] = []

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
        futures = {
            executor.submit(fetch_greenhouse_jobs, company): ("Greenhouse", company)
            for company in GREENHOUSE_COMPANIES
        }
        futures.update({
            executor.submit(fetch_lever_jobs, company): ("Lever", company)
            for company in LEVER_COMPANIES
        })

        for future in as_completed(futures):
            platform, company = futures[future]
            try:
                company_jobs = future.result()
            except Exception as e:
                log.exception("Error fetching %s/%s: %s", platform, company, e)
                continue
            jobs.extend(company_jobs)
            log.info("%s/%s: %d internships", platform, company, len(company_jobs))

    log.info("Total ATS jobs fetched: %d", len(jobs))
    return jobs


if __name__ == "__main__":
    # configure_logging() reconfigures stdout to UTF-8; without it this CLI
    # crashes on a cp1252 Windows console as soon as a title or company name
    # contains a non-ASCII character. This is the slug-verification loop, so
    # it has to survive real-world data.
    from logging_setup import configure_logging

    configure_logging()
    for job in fetch_all_ats_jobs():
        print(f"[{job.source}] {job.title} @ {job.company} ({job.location}) -> {job.url}")
