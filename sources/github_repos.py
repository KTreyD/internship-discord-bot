"""Fetches internship postings from community-maintained GitHub README lists.

Two README table styles are supported:
  - "markdown": pipe-delimited tables, e.g. jobright-ai/2026-Engineer-Internship.
    Broad engineering coverage (mechanical, civil, electrical, biomedical, etc.)
  - "html": raw <table>/<tr>/<td> markup, e.g. SimplifyJobs/Summer2026-Internships.
    Heavy CS/software/data coverage.
"""
import logging
import re

from sources.base import Job
from sources.util import get_text, strip_tags

log = logging.getLogger(__name__)

GITHUB_REPOS = [
    {
        "name": "jobright-ai/2026-Engineer-Internship",
        "url": "https://raw.githubusercontent.com/jobright-ai/2026-Engineer-Internship/master/README.md",
        "format": "markdown",
    },
    {
        "name": "SimplifyJobs/Summer2026-Internships",
        "url": "https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships/dev/README.md",
        "format": "html",
    },
]

_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
_TR_RE = re.compile(r"<tr>(.*?)</tr>", re.DOTALL)
_TD_RE = re.compile(r"<td>(.*?)</td>", re.DOTALL)
_HREF_RE = re.compile(r'href="([^"]+)"')


def _extract_link(cell: str) -> tuple[str, str]:
    """Returns (text, url) from a markdown "[text](url)" cell, or ("", "") if absent."""
    match = _LINK_RE.search(cell)
    if not match:
        return "", ""
    return match.group(1).strip("* "), match.group(2)


def _parse_markdown_table(text: str, repo_name: str) -> list[Job]:
    jobs = []
    last_company = ""
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|") or set(line.replace("|", "").strip()) <= {"-", " "}:
            continue

        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 5 or cells[0].lower() in ("company", ""):
            continue

        company_text, _ = _extract_link(cells[0])
        if company_text:
            last_company = company_text
        elif "↳" not in cells[0]:
            continue

        title_text, title_url = _extract_link(cells[1])
        if not title_url:
            continue

        jobs.append(Job(
            url=title_url,
            title=title_text,
            company=last_company,
            location=cells[2],
            work_model=cells[3],
            posted_date=cells[4],
            source=repo_name,
        ))
    return jobs


def _parse_html_table(text: str, repo_name: str) -> list[Job]:
    jobs = []
    for table_match in re.finditer(r"<tbody>(.*?)</tbody>", text, re.DOTALL):
        last_company = ""
        for row_match in _TR_RE.finditer(table_match.group(1)):
            cells = _TD_RE.findall(row_match.group(1))
            if len(cells) < 4:
                continue

            company = strip_tags(cells[0])
            if company and company != "↳":
                last_company = company
            else:
                company = last_company

            title = strip_tags(cells[1])
            location = strip_tags(cells[2])
            age = strip_tags(cells[-1])

            href_match = _HREF_RE.search(cells[3])
            if not href_match or not title or not company:
                continue

            jobs.append(Job(
                url=href_match.group(1),
                title=title,
                company=company,
                location=location,
                posted_date=age,
                source=repo_name,
            ))
    return jobs


def fetch_github_repo_jobs(repo: dict) -> list[Job]:
    text = get_text(repo["url"])
    if text is None:
        log.error("Error fetching %s", repo["name"])
        return []

    if repo["format"] == "markdown":
        return _parse_markdown_table(text, repo["name"])
    return _parse_html_table(text, repo["name"])


def fetch_all_github_jobs() -> list[Job]:
    jobs: list[Job] = []
    for repo in GITHUB_REPOS:
        log.info("Fetching GitHub source: %s", repo["name"])
        repo_jobs = fetch_github_repo_jobs(repo)
        jobs.extend(repo_jobs)
        log.info("  Found %d jobs", len(repo_jobs))

    log.info("Total GitHub jobs fetched: %d", len(jobs))
    return jobs


if __name__ == "__main__":
    # See the note in sources/ats.py: stdout must be reconfigured to UTF-8
    # before printing real job titles on a Windows console.
    from logging_setup import configure_logging

    configure_logging()
    for job in fetch_all_github_jobs():
        print(f"[{job.source}] {job.title} @ {job.company} ({job.location}) -> {job.url}")
