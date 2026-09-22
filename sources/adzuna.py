import logging
import os

from dedup import _US_STATES
from sources.base import Job
from sources.util import get_json

log = logging.getLogger(__name__)

ADZUNA_SEARCH_TERMS = [
    "mechanical engineer intern",
    "electrical engineer intern",
    "chemical engineer intern",
    "computer science intern",
    "software engineer intern",
    "IT intern",
    "information systems intern",
    "civil engineer intern",
    "biomedical engineer intern",
    "industrial engineer intern",
    "petroleum engineer intern",
    "construction management intern",
    "software development intern",
    "data science intern",
    "machine learning intern",
    "AI intern",
    "cybersecurity intern",
    "network engineer intern",
    "systems engineer intern",
    "data engineer intern",
    "cloud engineer intern",
    "DevOps intern",
    "full stack intern",
    "backend engineer intern",
    "frontend engineer intern",
    "mobile developer intern",
    "embedded systems intern",
    "hardware engineer intern",
    "robotics intern",
    "aerospace engineer intern",
    "manufacturing engineer intern",
    "process engineer intern",
    "quality engineer intern",
    "project management intern",
    "product management intern",
    "environmental engineer intern",
    "structural engineer intern",
    "transportation engineer intern",
    "materials engineer intern",
    "nuclear engineer intern",
    "mining engineer intern",
    "web developer intern",
    "database administrator intern",
    "business analyst intern",
    "systems analyst intern",
    "infrastructure intern",
    "automation engineer intern",
    "control systems intern",
    "mechatronics intern",
    "reliability engineer intern",
]


def fetch_adzuna_jobs(keywords="engineering intern", location="United States"):
    """Fetch jobs from Adzuna API for a single search term."""
    # Read credentials lazily (not at module import time) so load_dotenv()
    # in bot.py, which runs before these fetchers are called but after this
    # module is first imported, has already populated the environment.
    app_id = os.getenv("ADZUNA_ID")
    app_key = os.getenv("ADZUNA_KEY")

    base_url = "https://api.adzuna.com/v1/api/jobs/us/search/1"
    params = {
        "app_id": app_id,
        "app_key": app_key,
        "what": keywords,
        "where": location,
        "results_per_page": 5,
    }
    data = get_json(base_url, params=params)
    if data is None:
        log.error("Error fetching Adzuna jobs for %r", keywords)
        return []
    return data.get("results", [])


# Adzuna's location.display_name walks the county level of their hierarchy,
# producing "Fairborn, Greene County" instead of "Fairborn, OH". The structured
# `area` list has what we actually want:
#   ['US', 'Ohio', 'Montgomery County', 'Dayton']
#    [0]    [1]=state      [2]=county    [-1]=city
# Skipping the county also helps dedup, since other sources say "Dayton, OH".
_COUNTY_SUFFIXES = ("county", "parish", "borough", "census area", "municipality")


def _format_location(raw_location: dict) -> str:
    """Builds "City, ST" from Adzuna's area hierarchy.

    Falls back to the state alone, then to display_name, when the hierarchy
    is too shallow to name a city (some postings are only tagged "US").
    """
    area = raw_location.get("area") or []
    display = raw_location.get("display_name", "") or ""

    if len(area) < 2:
        return display

    state_name = area[1]
    state = _US_STATES.get(state_name.strip().lower(), state_name).upper()

    # Walk back from the most specific entry, skipping county-style levels
    # and anything that just repeats the state.
    for candidate in reversed(area[2:]):
        name = candidate.strip()
        low = name.lower()
        if low == state_name.strip().lower():
            continue
        if low.endswith(_COUNTY_SUFFIXES):
            continue
        return f"{name}, {state}"

    return state


def _to_job(raw: dict) -> Job:
    return Job(
        url=raw["redirect_url"],
        title=raw["title"],
        company=raw["company"]["display_name"],
        description=raw.get("description", ""),
        location=_format_location(raw.get("location", {})),
        source="Adzuna",
    )


def fetch_all_adzuna_jobs() -> list[Job]:
    """Fetch jobs from Adzuna using all configured search terms."""
    jobs: list[Job] = []
    for keyword in ADZUNA_SEARCH_TERMS:
        log.info("Searching Adzuna for: %s", keyword)
        raw_jobs = fetch_adzuna_jobs(keywords=keyword)
        jobs.extend(_to_job(raw) for raw in raw_jobs)
        log.info("  Found %d jobs", len(raw_jobs))

    log.info("Total Adzuna jobs fetched: %d", len(jobs))
    return jobs
