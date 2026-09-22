import pytest

import dedup
from sources.base import Job


@pytest.mark.parametrize(
    "title_a,title_b",
    [
        ("Software Engineer Intern (Req#12345)", "Software Engineer Intern"),
        ("Mechanical Engineering Intern - Summer 2026", "Mechanical Engineering Intern"),
        ("Data Intern [Remote]", "Data Intern"),
        ("Intern, Mechanical Engineering", "Mechanical Engineering Intern"),
        ("Software Engineering Co-Op", "Software Engineering Internship"),
    ],
)
def test_normalize_title_equivalences(title_a, title_b):
    assert dedup.normalize_title(title_a) == dedup.normalize_title(title_b)


@pytest.mark.parametrize(
    "title_a,title_b",
    [
        ("Mechanical Engineer Intern", "Electrical Engineer Intern"),
        ("Software Engineer Intern I", "Software Engineer Intern II"),
        ("Data Analyst Intern", "Data Scientist Intern"),
    ],
)
def test_normalize_title_negative_cases(title_a, title_b):
    assert dedup.normalize_title(title_a) != dedup.normalize_title(title_b)


def test_normalize_title_req_id_stripping():
    assert "12345" not in dedup.normalize_title("Intern - JR-12345")


def test_normalize_title_year_and_season():
    key = dedup.normalize_title("Summer 2026 Marketing Intern")
    assert "2026" not in key
    assert "summer" not in key


@pytest.mark.parametrize(
    "company_a,company_b",
    [
        ("Stripe, Inc.", "STRIPE"),
        ("The Stripe Company", "Stripe"),
        ("Acme Technologies LLC", "Acme"),
        ("Acme Labs, Inc.", "Acme"),
    ],
)
def test_normalize_company_equivalences(company_a, company_b):
    assert dedup.normalize_company(company_a) == dedup.normalize_company(company_b)


def test_normalize_company_distinct():
    assert dedup.normalize_company("Acme") != dedup.normalize_company("Acme Robotics")


def test_fingerprint_combines_company_and_title():
    fp = dedup.fingerprint("Stripe, Inc.", "Software Engineer Intern")
    assert fp == (
        f"{dedup.normalize_company('Stripe, Inc.')}"
        f"|{dedup.normalize_title('Software Engineer Intern')}|"
    )


def test_fingerprint_includes_location():
    fp = dedup.fingerprint("Stripe, Inc.", "Software Engineer Intern", "Dallas, TX")
    assert fp == (
        f"{dedup.normalize_company('Stripe, Inc.')}"
        f"|{dedup.normalize_title('Software Engineer Intern')}"
        f"|{dedup.normalize_location('Dallas, TX')}"
    )


# ==================== normalize_url ====================

_ADZUNA_URLS = [
    "https://www.adzuna.com/land/ad/5884753588?se=rm8Waeqx8RGW7Jd0wGJW9Q&utm_medium=api&utm_source=f9499d93&v=53AF3297120DEDA59B827C4AEF71BA8513C4FD2E",
    "https://www.adzuna.com/land/ad/5884753588?se=pphZ6-qx8RGkw8jFwVa0WA&utm_medium=api&utm_source=f9499d93&v=53AF3297120DEDA59B827C4AEF71BA8513C4FD2E",
    "https://www.adzuna.com/land/ad/5884753588?se=CByJgu6x8RGRr_JonSYGrg&utm_medium=api&utm_source=f9499d93&v=53AF3297120DEDA59B827C4AEF71BA8513C4FD2E",
]


def test_normalize_url_collapses_adzuna_session_token():
    normalized = {dedup.normalize_url(u) for u in _ADZUNA_URLS}
    assert len(normalized) == 1


def test_normalize_url_strips_utm_keeps_meaningful_params():
    normalized = dedup.normalize_url(_ADZUNA_URLS[0])
    assert "se=" not in normalized
    assert "utm_medium" not in normalized
    assert "utm_source" not in normalized
    assert "v=53AF3297120DEDA59B827C4AEF71BA8513C4FD2E" in normalized


def test_normalize_url_keeps_gh_jid_and_unknown_params():
    url = "https://boards.greenhouse.io/foo/jobs/123?gh_jid=456&custom_unknown=xyz"
    normalized = dedup.normalize_url(url)
    assert "gh_jid=456" in normalized
    assert "custom_unknown=xyz" in normalized


def test_normalize_url_lowercases_and_strips_www_and_trailing_slash():
    assert dedup.normalize_url("HTTPS://WWW.Example.com/Path/") == "https://example.com/Path"


def test_normalize_url_idempotent():
    for url in _ADZUNA_URLS + ["", "not a url at all", "https://example.com/a?b=2&a=1"]:
        once = dedup.normalize_url(url)
        twice = dedup.normalize_url(once)
        assert once == twice


@pytest.mark.parametrize("bad", ["", None, "not a url", "::::", "   "])
def test_normalize_url_never_raises(bad):
    dedup.normalize_url(bad)  # must not raise


# ==================== normalize_location ====================

def test_normalize_location_state_name_and_abbreviation_match():
    assert dedup.normalize_location("Dallas, Texas") == dedup.normalize_location("Dallas, TX")


@pytest.mark.parametrize("location", ["Remote", "Remote - US", "Fully Remote, Anywhere"])
def test_normalize_location_remote(location):
    assert dedup.normalize_location(location) == "remote"


@pytest.mark.parametrize("location", ["", None])
def test_normalize_location_empty(location):
    assert dedup.normalize_location(location) == ""


# ==================== parenthetical handling ====================

def test_parenthetical_tokens_kept_distinct_wsp_titles():
    titles = [
        "Electrical Engineering (Substation) Intern",
        "Electrical Engineering (Distribution) Intern",
        "Electrical Engineering (ESSP) Intern",
        "Electrical Engineering (Distribution Design) Intern",
    ]
    fingerprints = {dedup.fingerprint("WSP", t) for t in titles}
    assert len(fingerprints) == 4


def test_summer_year_parenthetical_still_normalizes_away():
    assert dedup.normalize_title("Marketing Intern (Summer 2027)") == dedup.normalize_title("Marketing Intern")


def test_fingerprint_distinct_locations_for_same_company_and_title():
    fp_a = dedup.fingerprint("Kimley-Horn", "Civil Engineering Intern", "Dallas, TX")
    fp_b = dedup.fingerprint("Kimley-Horn", "Civil Engineering Intern", "Austin, TX")
    assert fp_a != fp_b


def _job(url, title, company, source="", description=""):
    return Job(url=url, title=title, company=company, description=description, source=source)


def test_dedupe_batch_collapses_cross_source_duplicate():
    jobs = [
        _job("https://adzuna.example/1", "Intern, Mechanical Engineering", "Stripe, Inc.",
             source="Adzuna", description="short"),
        _job("https://github.example/1", "Mechanical Engineering Intern", "STRIPE",
             source="org/repo", description="a bit longer description here"),
        _job("https://boards.greenhouse.io/stripe/1", "Mechanical Engineering Intern (Summer 2026)",
             "Stripe", source="Greenhouse/stripe",
             description="the longest and most detailed description of all three postings by far"),
    ]

    kept, dropped = dedup.dedupe_batch(jobs)

    assert dropped == 2
    assert len(kept) == 1
    assert kept[0].url == "https://boards.greenhouse.io/stripe/1"


def test_dedupe_batch_keeps_distinct_majors():
    jobs = [
        _job("https://a.example/1", "Mechanical Engineer Intern", "Acme"),
        _job("https://a.example/2", "Electrical Engineer Intern", "Acme"),
    ]
    kept, dropped = dedup.dedupe_batch(jobs)
    assert dropped == 0
    assert len(kept) == 2


def test_dedupe_batch_keeps_distinct_companies():
    jobs = [
        _job("https://a.example/1", "Software Engineer Intern", "Acme"),
        _job("https://b.example/1", "Software Engineer Intern", "Globex"),
    ]
    kept, dropped = dedup.dedupe_batch(jobs)
    assert dropped == 0
    assert len(kept) == 2
