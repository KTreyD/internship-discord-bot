"""Fetches internship postings directly from company ATS (applicant tracking
system) job boards. Most career pages are built on a handful of ATS platforms
that expose free, public, unauthenticated JSON APIs, so a handful of company
slugs gets full coverage of that company's postings without scraping HTML.

Company slugs below were verified live (200 response) against the public
Greenhouse/Lever board APIs. Add more by finding a company's board slug from
their careers page URL, e.g. a Greenhouse careers page at
boards.greenhouse.io/acme -> slug "acme"; a Lever page at
jobs.lever.co/acme -> slug "acme".
"""
import re
import sys

import requests

from sources.base import Job
from sources.util import strip_tags

# Matches "intern"/"internship" as a whole word, not as a substring of
# "international" or similar.
_INTERN_RE = re.compile(r"\bintern(ship)?\b", re.IGNORECASE)

GREENHOUSE_COMPANIES = [
    "stripe", "airbnb", "robinhood", "asana", "coinbase", "figma",
    "databricks", "cloudflare", "affirm", "gusto", "instacart", "brex",
    "pinterest", "reddit", "samsara", "mongodb", "elastic", "gitlab",
    "squarespace", "duolingo", "chime", "toast", "lyft",
]

LEVER_COMPANIES = ["palantir"]


def fetch_greenhouse_jobs(company: str) -> list[Job]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true"
    response = requests.get(url)
    if response.status_code != 200:
        print(f"Error fetching Greenhouse/{company}: {response.status_code}")
        return []

    jobs = []
    for raw in response.json().get("jobs", []):
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
    response = requests.get(url)
    if response.status_code != 200:
        print(f"Error fetching Lever/{company}: {response.status_code}")
        return []

    jobs = []
    for raw in response.json():
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

    for company in GREENHOUSE_COMPANIES:
        company_jobs = fetch_greenhouse_jobs(company)
        jobs.extend(company_jobs)
        print(f"Greenhouse/{company}: {len(company_jobs)} internships")

    for company in LEVER_COMPANIES:
        company_jobs = fetch_lever_jobs(company)
        jobs.extend(company_jobs)
        print(f"Lever/{company}: {len(company_jobs)} internships")

    print(f"Total ATS jobs fetched: {len(jobs)}")
    return jobs


if __name__ == "__main__":
    for job in fetch_all_ats_jobs():
        line = f"[{job.source}] {job.title} @ {job.company} ({job.location}) -> {job.url}"
        print(line.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(sys.stdout.encoding or "utf-8"))
