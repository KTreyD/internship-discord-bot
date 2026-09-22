"""finish_run() only runs on a clean exit, so a killed process leaves its
runs row at 'running' forever. Startup must close those out."""
import database


def _db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "t.db"))
    conn = database.create_connection()
    database.create_table(conn)
    return conn


def test_open_run_is_marked_interrupted(tmp_path, monkeypatch):
    conn = _db(tmp_path, monkeypatch)
    run_id = database.start_run(conn)

    assert database.mark_interrupted_runs(conn) == 1

    row = conn.execute("SELECT status, finished_at FROM runs WHERE id = ?", (run_id,)).fetchone()
    assert row["status"] == "interrupted"
    assert row["finished_at"] is not None


def test_finished_runs_are_left_alone(tmp_path, monkeypatch):
    conn = _db(tmp_path, monkeypatch)
    run_id = database.start_run(conn)
    database.finish_run(conn, run_id, posted=5)

    assert database.mark_interrupted_runs(conn) == 0
    assert conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()["status"] == "ok"


def test_is_idempotent_and_handles_no_runs(tmp_path, monkeypatch):
    conn = _db(tmp_path, monkeypatch)
    assert database.mark_interrupted_runs(conn) == 0  # empty table

    database.start_run(conn)
    assert database.mark_interrupted_runs(conn) == 1
    assert database.mark_interrupted_runs(conn) == 0  # nothing left to close


def test_multiple_stale_runs_all_closed(tmp_path, monkeypatch):
    conn = _db(tmp_path, monkeypatch)
    for _ in range(3):
        database.start_run(conn)

    assert database.mark_interrupted_runs(conn) == 3
    assert conn.execute("SELECT COUNT(*) FROM runs WHERE status = 'running'").fetchone()[0] == 0
