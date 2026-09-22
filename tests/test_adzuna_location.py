"""Adzuna returns "Fairborn, Greene County" in display_name; the bot shows
"Fairborn, OH" instead, built from the structured `area` hierarchy."""
import pytest

from sources.adzuna import _format_location


@pytest.mark.parametrize("area,expected", [
    (["US", "Ohio", "Greene County", "Fairborn"], "Fairborn, OH"),
    (["US", "Ohio", "Montgomery County", "Dayton"], "Dayton, OH"),
    (["US", "Texas", "Dallas County", "Dallas"], "Dallas, TX"),
    # Non-"County" civil divisions must be skipped too.
    (["US", "Louisiana", "Orleans Parish", "New Orleans"], "New Orleans, LA"),
    (["US", "District of Columbia", "Washington"], "Washington, DC"),
    # Too shallow to name a city -> state alone, never a county name.
    (["US", "Ohio", "Montgomery County"], "OH"),
    (["US", "Alaska", "Juneau Borough"], "AK"),
    (["US", "Ohio"], "OH"),
])
def test_area_hierarchy_yields_city_state(area, expected):
    assert _format_location({"area": area, "display_name": "ignored"}) == expected


def test_country_only_falls_back_to_display_name():
    assert _format_location({"area": ["US"], "display_name": "US"}) == "US"


def test_missing_or_empty_area_does_not_raise():
    assert _format_location({}) == ""
    assert _format_location({"area": [], "display_name": ""}) == ""


def test_county_never_leaks_into_output():
    for area in (["US", "Ohio", "Greene County", "Fairborn"],
                 ["US", "Ohio", "Montgomery County"]):
        assert "county" not in _format_location({"area": area}).lower()
