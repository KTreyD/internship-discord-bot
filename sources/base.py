from dataclasses import dataclass


@dataclass
class Job:
    url: str
    title: str
    company: str
    description: str = ""
    location: str = ""
    work_model: str = ""
    posted_date: str = ""
    source: str = ""
