import pytest

import categorizer


def test_chemical_keywords():
    result = categorizer.categorize_job_keywords("Chemical Engineer Intern", "Entry level position")
    assert any(major == "chemical" for major, _ in result)


def test_chemical_engineering_variant():
    result = categorizer.categorize_job_keywords("Chemical Engineering Intern", "")
    assert any(major == "chemical" for major, _ in result)


def test_chemical_engineer_dash_intern():
    result = categorizer.categorize_job_keywords("Chemical Engineer - Intern", "")
    assert any(major == "chemical" for major, _ in result)


def test_mis_word_boundary_regression():
    """'Admissions' must not false-positive-match the 'MIS' keyword."""
    result = categorizer.categorize_job_keywords("College Admissions Counselor Intern", "")
    assert result == []


def test_api_word_boundary_regression():
    """'Rapids' must not false-positive-match the 'API' keyword."""
    result = categorizer.categorize_job_keywords("Data Rapids Intern", "")
    assert result == []


# ---------------------------------------------------------------------------
# _align
# ---------------------------------------------------------------------------

def _item(index, major="mechanical", confidence=3):
    return categorizer._BatchItem(index=index, majors=[{"major": major, "confidence": confidence}])


def test_align_short_list_leaves_none():
    results = [_item(0)]
    aligned = categorizer._align(results, size=3)
    assert len(aligned) == 3
    assert aligned[0] is not None
    assert aligned[1] is None
    assert aligned[2] is None


def test_align_out_of_range_index_dropped():
    results = [_item(0), _item(5)]
    aligned = categorizer._align(results, size=2)
    assert len(aligned) == 2
    assert aligned[0] is not None
    assert aligned[1] is None


def test_align_duplicated_index_first_wins():
    results = [_item(0, major="mechanical"), _item(0, major="electrical")]
    aligned = categorizer._align(results, size=1)
    assert aligned[0][0][0] == "mechanical"


def test_align_empty_list():
    aligned = categorizer._align([], size=3)
    assert aligned == [None, None, None]


# ---------------------------------------------------------------------------
# categorize_jobs fallback ladder
# ---------------------------------------------------------------------------

def test_categorize_jobs_no_api_key_uses_keywords(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    jobs = [("Chemical Engineer Intern", ""), ("Data Rapids Intern", "")]
    results = categorizer.categorize_jobs(jobs)
    assert len(results) == 2
    assert all(r is not None for r in results)
    assert any(major == "chemical" for major, _ in results[0])
    assert results[1] == []


def _raise(*args, **kwargs):
    raise RuntimeError("stubbed: no network in tests")


def test_categorize_jobs_always_raises_falls_back_to_keywords(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
    monkeypatch.setattr(categorizer, "_categorize_chunk_llm", lambda chunk: None)
    monkeypatch.setattr(categorizer, "categorize_job_llm", _raise)
    jobs = [("Chemical Engineer Intern", ""), ("Mechanical Engineer Intern", "")]
    results = categorizer.categorize_jobs(jobs)
    assert len(results) == 2
    assert all(r is not None for r in results)
    assert any(major == "chemical" for major, _ in results[0])
    assert any(major == "mechanical" for major, _ in results[1])


def test_categorize_jobs_half_missing_slots_fallback_individually(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")

    def fake_chunk(chunk):
        # First three slots aligned, last two missing (< half so not a
        # wholesale discard - only the missing slots fall back individually).
        out = [None] * len(chunk)
        out[0] = [("mechanical", 5)]
        out[1] = [("mechanical", 4)]
        out[2] = [("mechanical", 3)]
        return out

    monkeypatch.setattr(categorizer, "_categorize_chunk_llm", fake_chunk)
    monkeypatch.setattr(categorizer, "categorize_job_llm", _raise)
    jobs = [("Mechanical Engineer Intern", "")] * 3 + [("Chemical Engineer Intern", "")] * 2
    results = categorizer.categorize_jobs(jobs)
    assert len(results) == len(jobs)
    assert all(r is not None for r in results)
    assert results[0] == [("mechanical", 5)]
    assert results[1] == [("mechanical", 4)]
    assert results[2] == [("mechanical", 3)]
    for r in results[3:]:
        assert any(major == "chemical" for major, _ in r)


def test_categorize_jobs_garbage_indices_wholesale_fallback(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")

    def fake_chunk(chunk):
        # Everything missing -> more than half None -> wholesale chunk fallback.
        return [None] * len(chunk)

    monkeypatch.setattr(categorizer, "_categorize_chunk_llm", fake_chunk)
    monkeypatch.setattr(categorizer, "categorize_job_llm", _raise)
    jobs = [("Chemical Engineer Intern", ""), ("Mechanical Engineer Intern", "")]
    results = categorizer.categorize_jobs(jobs)
    assert len(results) == 2
    assert all(r is not None for r in results)


def test_categorize_jobs_output_length_always_matches_input(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
    monkeypatch.setattr(categorizer, "_categorize_chunk_llm", lambda chunk: None)
    monkeypatch.setattr(categorizer, "categorize_job_llm", _raise)
    jobs = [(f"Title {i}", "") for i in range(37)]
    results = categorizer.categorize_jobs(jobs)
    assert len(results) == 37
    assert all(r is not None for r in results)
