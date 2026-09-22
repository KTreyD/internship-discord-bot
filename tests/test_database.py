import sqlite3

import pytest

import database
import dedup

_V1_SCHEMA = """
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_url TEXT UNIQUE NOT NULL,
    title TEXT,
    company TEXT,
    majors TEXT,
    date_found TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    posted_to_discord INTEGER DEFAULT 0,
    discord_channel_ids TEXT
)
"""


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setattr(database, "DB_PATH", str(path))
    return str(path)


def _v1_conn(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(_V1_SCHEMA)
    conn.execute(
        "INSERT INTO jobs (job_url, title, company, majors, posted_to_discord, discord_channel_ids) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("https://example.com/1", "Mechanical Engineer Intern", "Stripe, Inc.", "mechanical", 0, ""),
    )
    conn.execute(
        "INSERT INTO jobs (job_url, title, company, majors, posted_to_discord, discord_channel_ids) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("https://example.com/2", "Software Engineer Intern", "Acme", "computer science", 1, "111"),
    )
    conn.commit()
    return conn


def test_migration_adds_columns_and_backfills(db_path):
    conn = _v1_conn(db_path)
    database.create_table(conn)

    columns = database._existing_columns(conn, "jobs")
    for col in ("fingerprint", "source", "location", "work_model", "posted_date",
                "post_attempts", "last_error", "last_attempt_at"):
        assert col in columns

    rows = conn.execute("SELECT job_url, fingerprint FROM jobs ORDER BY job_url").fetchall()
    assert all(row["fingerprint"] for row in rows)

    user_version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert user_version == database.SCHEMA_VERSION


def test_migration_v2_to_v3_backfills_normalized_url_and_fingerprint(db_path):
    conn = _v1_conn(db_path)
    # Simulate a v2 DB: run the old-style v2 migration steps manually so we
    # land on user_version=2 with fingerprint populated but no
    # normalized_url column at all.
    conn.execute("ALTER TABLE jobs ADD COLUMN fingerprint TEXT")
    conn.execute("ALTER TABLE jobs ADD COLUMN location TEXT")
    conn.execute(
        "UPDATE jobs SET fingerprint = ? WHERE job_url = ?",
        ("stale|fingerprint", "https://example.com/1"),
    )
    conn.execute("PRAGMA user_version = 2")
    conn.commit()

    database.create_table(conn)

    columns = database._existing_columns(conn, "jobs")
    assert "normalized_url" in columns

    rows = conn.execute("SELECT job_url, normalized_url, fingerprint FROM jobs ORDER BY job_url").fetchall()
    assert all(row["normalized_url"] for row in rows)
    # Fingerprint must be recomputed under the new 3-segment formula, not
    # left as the stale 2-segment value from before.
    for row in rows:
        assert row["fingerprint"] != "stale|fingerprint"
        assert row["fingerprint"].count("|") == 2

    assert conn.execute("PRAGMA user_version").fetchone()[0] == 3


def test_migration_v3_index_present_and_second_create_table_is_noop(db_path):
    conn = _v1_conn(db_path)
    database.create_table(conn)

    indexes = {
        row["name"]
        for row in conn.execute("PRAGMA index_list(jobs)").fetchall()
    }
    assert "idx_jobs_normalized_url" in indexes

    rows_before = [
        dict(row) for row in conn.execute("SELECT * FROM jobs ORDER BY job_url").fetchall()
    ]
    database.create_table(conn)  # second call must be a clean no-op
    rows_after = [
        dict(row) for row in conn.execute("SELECT * FROM jobs ORDER BY job_url").fetchall()
    ]
    assert rows_before == rows_after
    assert conn.execute("PRAGMA user_version").fetchone()[0] == database.SCHEMA_VERSION


def test_migration_idempotent(db_path):
    conn = _v1_conn(db_path)
    database.create_table(conn)
    fps_before = [row["fingerprint"] for row in conn.execute("SELECT fingerprint FROM jobs ORDER BY job_url")]

    # Running again must not error and must not change anything.
    database.create_table(conn)
    fps_after = [row["fingerprint"] for row in conn.execute("SELECT fingerprint FROM jobs ORDER BY job_url")]
    assert fps_before == fps_after


def test_create_table_fresh_db(db_path):
    conn = database.create_connection()
    database.create_table(conn)
    columns = database._existing_columns(conn, "jobs")
    assert "fingerprint" in columns
    assert conn.execute("PRAGMA user_version").fetchone()[0] == database.SCHEMA_VERSION
    conn.close()


def test_insert_jobs_and_find_existing(db_path):
    conn = database.create_connection()
    database.create_table(conn)

    rows = [
        {"url": "https://example.com/a", "title": "T1", "company": "C1", "majors": "mechanical",
         "fingerprint": "c1|t1", "source": "Adzuna"},
        {"url": "https://example.com/b", "title": "T2", "company": "C2", "majors": "civil",
         "fingerprint": "c2|t2", "source": "Adzuna"},
    ]
    database.insert_jobs(conn, rows)

    existing_urls, existing_fps = database.find_existing(
        conn, ["https://example.com/a", "https://example.com/z"], ["c1|t1", "nope"]
    )
    assert existing_urls == {"https://example.com/a"}
    assert existing_fps == {"c1|t1"}
    conn.close()


def test_find_existing_matches_on_normalized_url(db_path):
    conn = database.create_connection()
    database.create_table(conn)

    row = {
        "url": "https://www.adzuna.com/land/ad/123?se=abc123&utm_medium=api&v=DEADBEEF",
        "title": "T1", "company": "C1", "majors": "mechanical",
        "fingerprint": "c1|t1|",
    }
    database.insert_jobs(conn, [row])

    # Same ad, different se= session token - must be recognized as existing.
    lookup_url = "https://www.adzuna.com/land/ad/123?se=zzz999&utm_medium=api&v=DEADBEEF"
    existing_urls, _ = database.find_existing(conn, [dedup.normalize_url(lookup_url)], [])
    assert dedup.normalize_url(lookup_url) in existing_urls
    conn.close()


def test_normalized_url_index_is_not_unique_multiple_rows_survive(db_path):
    conn = database.create_connection()
    database.create_table(conn)

    rows = [
        {"url": f"https://jobright.ai/job/{i}", "title": "Civil Engineering Intern",
         "company": "Kimley-Horn", "majors": "civil", "fingerprint": f"fp{i}",
         "normalized_url": "https://www.adzuna.com/land/ad/999"}
        for i in range(3)
    ]
    database.insert_jobs(conn, rows)
    count = conn.execute(
        "SELECT COUNT(*) AS c FROM jobs WHERE normalized_url = ?",
        ("https://www.adzuna.com/land/ad/999",),
    ).fetchone()["c"]
    assert count == 3
    conn.close()


def test_insert_jobs_ignores_duplicate_url(db_path):
    conn = database.create_connection()
    database.create_table(conn)
    row = {"url": "https://example.com/a", "title": "T1", "company": "C1", "majors": "mechanical",
           "fingerprint": "c1|t1", "source": "Adzuna"}
    database.insert_jobs(conn, [row])
    database.insert_jobs(conn, [row])  # should not raise
    count = conn.execute("SELECT COUNT(*) AS c FROM jobs").fetchone()["c"]
    assert count == 1
    conn.close()


def test_mark_posted_and_record_post_failure_state_machine(db_path):
    conn = database.create_connection()
    database.create_table(conn)
    row = {"url": "https://example.com/a", "title": "T1", "company": "C1", "majors": "mechanical",
           "fingerprint": "c1|t1", "source": "Adzuna"}
    database.insert_jobs(conn, [row])

    database.record_post_failure(conn, "https://example.com/a", "boom")
    job = conn.execute("SELECT * FROM jobs WHERE job_url = ?", ("https://example.com/a",)).fetchone()
    assert job["post_attempts"] == 1
    assert job["last_error"] == "boom"
    assert job["posted_to_discord"] == 0

    database.mark_posted(conn, "https://example.com/a", [111, 222], complete=True)
    job = conn.execute("SELECT * FROM jobs WHERE job_url = ?", ("https://example.com/a",)).fetchone()
    assert job["posted_to_discord"] == 1
    assert job["discord_channel_ids"] == "111,222"

    conn.close()


def test_get_unposted_jobs_respects_max_attempts(db_path):
    conn = database.create_connection()
    database.create_table(conn)
    rows = [
        {"url": "https://example.com/a", "title": "T1", "company": "C1", "majors": "m",
         "fingerprint": "fp1", "source": "Adzuna"},
        {"url": "https://example.com/b", "title": "T2", "company": "C2", "majors": "m",
         "fingerprint": "fp2", "source": "Adzuna"},
    ]
    database.insert_jobs(conn, rows)
    for _ in range(5):
        database.record_post_failure(conn, "https://example.com/b", "boom")

    unposted = database.get_unposted_jobs(conn, max_attempts=5)
    urls = {row["job_url"] for row in unposted}
    assert "https://example.com/a" in urls
    assert "https://example.com/b" not in urls
    conn.close()


def test_check_job_exists(db_path):
    conn = database.create_connection()
    database.create_table(conn)
    row = {"url": "https://example.com/a", "title": "T1", "company": "C1", "majors": "m",
           "fingerprint": "fp1", "source": "Adzuna"}
    database.insert_jobs(conn, [row])
    assert database.check_job_exists(conn, "https://example.com/a") is True
    assert database.check_job_exists(conn, "https://example.com/nope") is False
    conn.close()


def test_start_and_finish_run(db_path):
    conn = database.create_connection()
    database.create_table(conn)
    run_id = database.start_run(conn)
    database.finish_run(conn, run_id, fetched=10, deduped=2, new_jobs=8, posted=8, errors=0, status="ok")
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    assert row["status"] == "ok"
    assert row["new_jobs"] == 8
    conn.close()
