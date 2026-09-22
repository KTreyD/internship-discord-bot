"""Local, read-only monitoring dashboard.

Not deployed in the container and not exposed publicly - run locally with:
    flask --app dashboard.app run

Read-only is enforced at the SQLite driver level (`mode=ro` URI), not just
by discipline, so the dashboard can never take a write lock on the DB the
bot is actively using.
"""
import os
import sqlite3

from flask import Flask, g, render_template, jsonify

import database
import logging_setup

app = Flask(__name__)


def _get_db():
    if "db" not in g:
        uri = f"file:{database.DB_PATH}?mode=ro"
        g.db = sqlite3.connect(uri, uri=True)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def _close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _major_counts(rows):
    counts = {}
    for row in rows:
        majors = (row["majors"] or "").split(",")
        for major in majors:
            major = major.strip()
            if not major:
                continue
            counts[major] = counts.get(major, 0) + 1
    return counts


def _gather_stats():
    db = _get_db()

    recent_rows = db.execute(
        "SELECT * FROM jobs ORDER BY date_found DESC LIMIT 50"
    ).fetchall()

    source_counts = {
        row["source"] or "unknown": row["c"]
        for row in db.execute(
            "SELECT source, COUNT(*) AS c FROM jobs GROUP BY source ORDER BY c DESC"
        ).fetchall()
    }

    all_rows_for_majors = db.execute("SELECT majors FROM jobs").fetchall()
    major_counts = _major_counts(all_rows_for_majors)

    last_run = db.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()

    status_counts = {0: 0, 1: 0, 2: 0}
    for row in db.execute(
        "SELECT posted_to_discord, COUNT(*) AS c FROM jobs GROUP BY posted_to_discord"
    ).fetchall():
        status_counts[row["posted_to_discord"]] = row["c"]

    return {
        "recent_jobs": recent_rows,
        "source_counts": source_counts,
        "major_counts": major_counts,
        "last_run": last_run,
        "status_counts": status_counts,
    }


@app.route("/")
def index():
    stats = _gather_stats()
    return render_template("index.html", **stats)


@app.route("/failed")
def failed():
    db = _get_db()
    rows = db.execute(
        "SELECT * FROM jobs WHERE posted_to_discord IN (0, 2) ORDER BY post_attempts DESC, date_found DESC"
    ).fetchall()
    return render_template("failed.html", jobs=rows)


@app.route("/logs")
def logs():
    log_dir = os.path.dirname(database.DB_PATH) or "."
    log_path = os.path.join(os.path.abspath(log_dir), "bot.log")
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-200:]
    except FileNotFoundError:
        lines = ["(no log file found at " + log_path + ")"]
    return render_template("logs.html", lines=lines, log_path=log_path)


@app.route("/api/stats")
def api_stats():
    stats = _gather_stats()
    return jsonify({
        "source_counts": stats["source_counts"],
        "major_counts": stats["major_counts"],
        "status_counts": stats["status_counts"],
        "last_run": dict(stats["last_run"]) if stats["last_run"] else None,
        "recent_job_count": len(stats["recent_jobs"]),
    })


if __name__ == "__main__":
    app.run(debug=True)
