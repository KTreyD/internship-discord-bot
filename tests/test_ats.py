import re

from sources import ats

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$")


def test_greenhouse_slugs_no_duplicates():
    assert len(ats.GREENHOUSE_COMPANIES) == len(set(ats.GREENHOUSE_COMPANIES))


def test_lever_slugs_no_duplicates():
    assert len(ats.LEVER_COMPANIES) == len(set(ats.LEVER_COMPANIES))


def test_all_slugs_lowercase():
    for slug in ats.GREENHOUSE_COMPANIES + ats.LEVER_COMPANIES:
        assert slug == slug.lower()


def test_all_slugs_no_url_fragments():
    for slug in ats.GREENHOUSE_COMPANIES + ats.LEVER_COMPANIES:
        assert "/" not in slug
        assert ":" not in slug
        assert " " not in slug
        assert not slug.startswith("http")
        assert _SLUG_RE.match(slug), f"{slug!r} doesn't look like a bare board slug"


def test_intern_re_matches_co_op():
    assert ats._INTERN_RE.search("Engineering Co-Op - Summer 2026")
    assert ats._INTERN_RE.search("Manufacturing Coop Program")
    assert ats._INTERN_RE.search("Software Engineering Internship")
    assert not ats._INTERN_RE.search("International Relations Analyst")
