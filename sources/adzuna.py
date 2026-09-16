import os

import requests

from sources.base import Job

ADZUNA_APP_ID = os.getenv('ADZUNA_ID')
ADZUNA_KEY = os.getenv('ADZUNA_KEY')

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
    base_url = "https://api.adzuna.com/v1/api/jobs/us/search/1"
    params = {
        "app_id": ADZUNA_APP_ID,
        "app_key": ADZUNA_KEY,
        "what": keywords,
        "where": location,
        "results_per_page": 5,
    }
    response = requests.get(base_url, params=params)

    if response.status_code == 200:
        return response.json()["results"]

    print(f"Error fetching Adzuna jobs: {response.status_code}")
    return []


def _to_job(raw: dict) -> Job:
    return Job(
        url=raw["redirect_url"],
        title=raw["title"],
        company=raw["company"]["display_name"],
        description=raw.get("description", ""),
        location=raw.get("location", {}).get("display_name", ""),
        source="Adzuna",
    )


def fetch_all_adzuna_jobs() -> list[Job]:
    """Fetch jobs from Adzuna using all configured search terms."""
    jobs: list[Job] = []
    for keyword in ADZUNA_SEARCH_TERMS:
        print(f"Searching for: {keyword}")
        raw_jobs = fetch_adzuna_jobs(keywords=keyword)
        jobs.extend(_to_job(raw) for raw in raw_jobs)
        print(f"  Found {len(raw_jobs)} jobs")

    print(f"Total Adzuna jobs fetched: {len(jobs)}")
    return jobs
