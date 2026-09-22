import logging
import os
import sqlite3
from datetime import datetime, timezone

log = logging.getLogger(__name__)

# On Azure this is pointed at the mounted file share (e.g. /data/internships.db)
# so the dedup database survives redeploys instead of resetting on the
# ephemeral container filesystem and re-posting every job.
DB_PATH = os.getenv("DB_PATH", "internships.db")

SCHEMA_VERSION = 3

# SQLite's default limit is 999 host parameters per statement (some builds
# raise it, some lower it) - chunk any `IN (...)` list well under that.
_SQLITE_MAX_VARS = 900


def create_connection(readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        uri = f"file:{DB_PATH}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
    else:
        connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def _existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    cursor = conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cursor.fetchall()}


def _ensure_column(conn: sqlite3.Connection, table: str, name: str, decl: str) -> bool:
    """Adds `name` to `table` if missing. Returns True if it was added."""
    if name in _existing_columns(conn, table):
        return False
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
    return True


def _compute_fingerprint(company: str, title: str, location: str = "") -> str:
    # Imported lazily to avoid a hard dependency from every caller of
    # database.py (e.g. simple scripts/tests) on the dedup module.
    import dedup
    return dedup.fingerprint(company or "", title or "", location or "")


def _compute_normalized_url(url: str) -> str:
    import dedup
    return dedup.normalize_url(url or "")


def create_table(conn: sqlite3.Connection) -> None:
    """Idempotent schema migration. Safe to call on every startup."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
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
    )
    conn.commit()

    _ensure_column(conn, "jobs", "fingerprint", "TEXT")
    _ensure_column(conn, "jobs", "source", "TEXT")
    _ensure_column(conn, "jobs", "location", "TEXT")
    _ensure_column(conn, "jobs", "work_model", "TEXT")
    _ensure_column(conn, "jobs", "posted_date", "TEXT")
    _ensure_column(conn, "jobs", "post_attempts", "INTEGER DEFAULT 0")
    _ensure_column(conn, "jobs", "last_error", "TEXT")
    _ensure_column(conn, "jobs", "last_attempt_at", "TIMESTAMP")
    _ensure_column(conn, "jobs", "normalized_url", "TEXT")
    conn.commit()

    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_fingerprint ON jobs(fingerprint)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_unposted ON jobs(posted_to_discord, post_attempts)"
    )
    # Deliberately NOT unique: the same posting can legitimately produce many
    # rows sharing one normalized URL (e.g. historical rows inserted before
    # this column existed, or a source that reuses a landing-page URL across
    # postings) - this index is a dedup lookup key, not an identity
    # constraint. job_url stays the UNIQUE identity column.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_normalized_url ON jobs(normalized_url)"
    )
    conn.commit()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TIMESTAMP,
            finished_at TIMESTAMP,
            fetched INTEGER,
            deduped INTEGER,
            new_jobs INTEGER,
            posted INTEGER,
            errors INTEGER,
            status TEXT
        )
        """
    )
    conn.commit()

    user_version = conn.execute("PRAGMA user_version").fetchone()[0]
    if user_version < 2:
        rows = conn.execute(
            "SELECT job_url, company, title FROM jobs WHERE fingerprint IS NULL"
        ).fetchall()
        if rows:
            updates = [
                (_compute_fingerprint(row["company"], row["title"]), row["job_url"])
                for row in rows
            ]
            conn.executemany(
                "UPDATE jobs SET fingerprint = ? WHERE job_url = ?", updates
            )
            conn.commit()
            log.info("Backfilled fingerprint for %d existing rows", len(updates))

    if user_version < 3:
        # normalized_url is self-healing: only fill rows missing it.
        url_rows = conn.execute(
            "SELECT job_url FROM jobs WHERE normalized_url IS NULL"
        ).fetchall()
        if url_rows:
            url_updates = [
                (_compute_normalized_url(row["job_url"]), row["job_url"])
                for row in url_rows
            ]
            conn.executemany(
                "UPDATE jobs SET normalized_url = ? WHERE job_url = ?", url_updates
            )
            conn.commit()
            log.info("Backfilled normalized_url for %d existing rows", len(url_updates))

        # fingerprint's formula changed (now includes location) - recompute
        # for every row, not just the ones missing it. Historical rows have
        # no location value, so they fingerprint with an empty location
        # segment; that's expected.
        all_rows = conn.execute("SELECT job_url, company, title, location FROM jobs").fetchall()
        if all_rows:
            fp_updates = [
                (
                    _compute_fingerprint(row["company"], row["title"], row["location"]),
                    row["job_url"],
                )
                for row in all_rows
            ]
            conn.executemany(
                "UPDATE jobs SET fingerprint = ? WHERE job_url = ?", fp_updates
            )
            conn.commit()
            log.info("Recomputed fingerprint for %d existing rows (v3 schema change)", len(fp_updates))

    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()


def _chunk(items, size=_SQLITE_MAX_VARS):
    items = list(items)
    for i in range(0, len(items), size):
        yield items[i:i + size]


def insert_jobs(conn: sqlite3.Connection, rows: list[dict]) -> None:
    """Bulk insert. Ignores rows whose job_url already exists (crash-safe
    insert-before-post ordering relies on this being idempotent)."""
    if not rows:
        return
    sql = """
    INSERT OR IGNORE INTO jobs
        (job_url, title, company, majors, posted_to_discord, discord_channel_ids,
         fingerprint, source, location, work_model, posted_date, normalized_url)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    values = [
        (
            row["url"],
            row["title"],
            row["company"],
            row["majors"],
            row.get("posted", 0),
            row.get("channelIDs", ""),
            row.get("fingerprint", ""),
            row.get("source", ""),
            row.get("location", ""),
            row.get("work_model", ""),
            row.get("posted_date", ""),
            row.get("normalized_url") or _compute_normalized_url(row["url"]),
        )
        for row in rows
    ]
    conn.executemany(sql, values)
    conn.commit()


def find_existing(conn: sqlite3.Connection, normalized_urls, fingerprints) -> tuple[set[str], set[str]]:
    """Returns (existing_normalized_urls, existing_fingerprints) already
    present in the DB, looked up against the `normalized_url` column (not
    the raw `job_url`) so volatile query params like Adzuna's `se=` session
    token don't defeat dedup."""
    normalized_urls = [u for u in set(normalized_urls) if u]
    fingerprints = [f for f in set(fingerprints) if f]

    existing_urls: set[str] = set()
    for batch in _chunk(normalized_urls):
        placeholders = ",".join("?" * len(batch))
        cursor = conn.execute(
            f"SELECT DISTINCT normalized_url FROM jobs WHERE normalized_url IN ({placeholders})", batch
        )
        existing_urls.update(row["normalized_url"] for row in cursor.fetchall())

    existing_fingerprints: set[str] = set()
    for batch in _chunk(fingerprints):
        placeholders = ",".join("?" * len(batch))
        cursor = conn.execute(
            f"SELECT DISTINCT fingerprint FROM jobs WHERE fingerprint IN ({placeholders})", batch
        )
        existing_fingerprints.update(row["fingerprint"] for row in cursor.fetchall())

    return existing_urls, existing_fingerprints


def check_job_exists(conn: sqlite3.Connection, job_url: str) -> bool:
    cursor = conn.execute("SELECT job_url FROM jobs WHERE job_url = ?", (job_url,))
    return cursor.fetchone() is not None


def get_unposted_jobs(conn: sqlite3.Connection, max_attempts: int = 5, limit: int = 200):
    cursor = conn.execute(
        """
        SELECT * FROM jobs
        WHERE posted_to_discord = 0 AND post_attempts < ?
        ORDER BY date_found ASC
        LIMIT ?
        """,
        (max_attempts, limit),
    )
    return cursor.fetchall()


def mark_posted(conn: sqlite3.Connection, job_url: str, channel_ids: list[int], complete: bool) -> None:
    channel_ids_str = ",".join(str(cid) for cid in channel_ids)
    status = 1 if complete else 0
    conn.execute(
        """
        UPDATE jobs
        SET posted_to_discord = ?, discord_channel_ids = ?, last_attempt_at = ?
        WHERE job_url = ?
        """,
        (status, channel_ids_str, datetime.now(timezone.utc).isoformat(), job_url),
    )
    conn.commit()


def record_post_failure(conn: sqlite3.Connection, job_url: str, error: str) -> None:
    conn.execute(
        """
        UPDATE jobs
        SET post_attempts = post_attempts + 1, last_error = ?, last_attempt_at = ?
        WHERE job_url = ?
        """,
        (error, datetime.now(timezone.utc).isoformat(), job_url),
    )
    conn.commit()


def abandon_job(conn: sqlite3.Connection, job_url: str) -> None:
    """Marks a job posted_to_discord = 2 (abandoned after MAX_POST_ATTEMPTS)."""
    conn.execute("UPDATE jobs SET posted_to_discord = 2 WHERE job_url = ?", (job_url,))
    conn.commit()


def start_run(conn: sqlite3.Connection) -> int:
    cursor = conn.execute(
        "INSERT INTO runs (started_at, status) VALUES (?, ?)",
        (datetime.now(timezone.utc).isoformat(), "running"),
    )
    conn.commit()
    return cursor.lastrowid


def mark_interrupted_runs(conn: sqlite3.Connection) -> int:
    """Closes out runs left at 'running' by a hard stop, returning the count.

    finish_run() only executes on a clean exit. A Ctrl+C, an OOM kill, or an
    Azure container restart leaves the row open forever, so the dashboard's
    "last run" would report a phantom run in progress. Called at startup,
    before this process opens a run of its own.
    """
    cursor = conn.execute(
        "UPDATE runs SET status = 'interrupted', finished_at = ? "
        "WHERE status = 'running' AND finished_at IS NULL",
        (datetime.now(timezone.utc).isoformat(),),
    )
    conn.commit()
    if cursor.rowcount:
        log.warning(
            "Marked %d previous run(s) as interrupted (process stopped before finishing)",
            cursor.rowcount,
        )
    return cursor.rowcount


def finish_run(conn: sqlite3.Connection, run_id: int, **counts) -> None:
    fields = {"fetched": 0, "deduped": 0, "new_jobs": 0, "posted": 0, "errors": 0, "status": "ok"}
    fields.update(counts)
    conn.execute(
        """
        UPDATE runs
        SET finished_at = ?, fetched = ?, deduped = ?, new_jobs = ?, posted = ?, errors = ?, status = ?
        WHERE id = ?
        """,
        (
            datetime.now(timezone.utc).isoformat(),
            fields["fetched"],
            fields["deduped"],
            fields["new_jobs"],
            fields["posted"],
            fields["errors"],
            fields["status"],
            run_id,
        ),
    )
    conn.commit()
