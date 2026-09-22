import asyncio
import logging
import os
from dataclasses import dataclass

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

# load_dotenv() must run before any source module that reads credentials
# from the environment is imported/used, so it comes before those imports.
load_dotenv()

import categorizer
import database
import dedup
import logging_setup
from sources.adzuna import fetch_all_adzuna_jobs
from sources.ats import fetch_all_ats_jobs
from sources.base import Job
from sources.github_repos import fetch_all_github_jobs

logging_setup.configure_logging(log_dir=os.path.dirname(database.DB_PATH) or ".")
log = logging.getLogger(__name__)

TOKEN = os.getenv('DISCORD_TOKEN')

# Channel IDs mapping
CHANNEL_IDS = {
    "chemical": 1454242155307733163,
    "mechanical": 1454242243803087000,
    "electrical": 1454242306268987597,
    "biomedical": 1455476385740226570,
    "civil": 1455476559715631197,
    "industrial": 1455476602279428215,
    "computer": 1455476699952320567,
    "petroleum": 1455476755237437614,
    "construction management": 1455476817929572425,
    "MIS": 1455476841732116685,
    "CIS": 1455476873143517342,
    "computer science": 1455476906966126691
}


def _apply_channel_overrides(channel_ids: dict) -> dict:
    """Lets a test run retarget Discord output without editing this file.

    TEST_CHANNEL_ID sends every major to one channel, which is all a smoke
    test needs. CHANNEL_IDS_JSON overrides individual majors for finer
    control. With neither set the production mapping above is used
    unchanged, so this is inert in deployment.
    """
    test_channel = os.getenv("TEST_CHANNEL_ID")
    if test_channel:
        log.warning(
            "TEST_CHANNEL_ID set - routing ALL majors to channel %s", test_channel
        )
        return {major: int(test_channel) for major in channel_ids}

    raw = os.getenv("CHANNEL_IDS_JSON")
    if raw:
        import json

        overrides = {major: int(cid) for major, cid in json.loads(raw).items()}
        unknown = set(overrides) - set(channel_ids)
        if unknown:
            log.warning("CHANNEL_IDS_JSON has unknown majors, ignoring: %s", sorted(unknown))
        merged = dict(channel_ids)
        merged.update({m: c for m, c in overrides.items() if m in channel_ids})
        log.warning("CHANNEL_IDS_JSON overrode %d channel(s)", len(merged) - len(
            [1 for m, c in channel_ids.items() if merged[m] == c]))
        return merged

    return channel_ids


CHANNEL_IDS = _apply_channel_overrides(CHANNEL_IDS)

# Embed accent color per major, used to make the Discord "job card" scannable at a glance
MAJOR_COLORS = {
    "chemical": discord.Color.dark_gold(),
    "mechanical": discord.Color.dark_grey(),
    "electrical": discord.Color.gold(),
    "biomedical": discord.Color.red(),
    "civil": discord.Color.dark_orange(),
    "industrial": discord.Color.teal(),
    "computer": discord.Color.blurple(),
    "petroleum": discord.Color.dark_green(),
    "construction management": discord.Color.orange(),
    "MIS": discord.Color.purple(),
    "CIS": discord.Color.magenta(),
    "computer science": discord.Color.blue(),
}

# Discord bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# ==================== POSTING / RETRY CONFIG ====================

POST_DELAY = 1.0          # seconds between sends, globally
MAX_SEND_ATTEMPTS = 4
MAX_POST_ATTEMPTS = 5      # across runs, before status 2 (abandoned)

_send_semaphore = asyncio.Semaphore(1)


@dataclass
class PendingPost:
    job: Job
    majors: list  # list[tuple[str, int]], already filtered to CHANNEL_IDS
    fingerprint: str


@bot.event
async def on_ready():
    log.info('%s has connected to Discord!', bot.user)

    conn = database.create_connection()
    try:
        database.create_table(conn)
        # A previous process may have been killed mid-run (Ctrl+C, OOM, or an
        # Azure container restart), leaving its runs row open forever.
        database.mark_interrupted_runs(conn)
    finally:
        conn.close()
    log.info('Database initialized!')

    check_for_jobs.start()  # Start the scheduled loop


@tasks.loop(hours=24)  # Run every 24 hours
async def check_for_jobs():
    """Scheduled task to check for new jobs across all sources."""
    conn = database.create_connection()
    run_id = database.start_run(conn)
    counts = {"fetched": 0, "deduped": 0, "new_jobs": 0, "posted": 0, "errors": 0}
    try:
        log.info("Checking for new jobs at %s", discord.utils.utcnow())

        retried = await retry_unposted(conn)
        log.info("Retried %d previously-unposted jobs", retried)

        jobs = await fetch_all_jobs()
        counts["fetched"] = len(jobs)

        jobs, dropped = dedup.dedupe_batch(jobs)
        counts["deduped"] = dropped

        jobs = select_new_jobs(conn, jobs)
        counts["new_jobs"] = len(jobs)

        pending = await categorize_all(jobs)

        rows = [
            {
                "url": p.job.url,
                "title": p.job.title,
                "company": p.job.company,
                "majors": ",".join(major for major, _ in p.majors),
                "posted": 0,
                "channelIDs": "",
                "fingerprint": p.fingerprint,
                "source": p.job.source,
                "location": p.job.location,
                "work_model": p.job.work_model,
                "posted_date": p.job.posted_date,
                "normalized_url": dedup.normalize_url(p.job.url),
            }
            for p in pending
        ]
        database.insert_jobs(conn, rows)

        posted = await post_pending(conn, pending)
        counts["posted"] = posted

        database.finish_run(conn, run_id, status="ok", **counts)
        log.info(
            "Finished! fetched=%d deduped=%d new=%d posted=%d",
            counts["fetched"], counts["deduped"], counts["new_jobs"], counts["posted"],
        )
    except Exception:
        # An unhandled exception inside a tasks.loop silently kills the
        # loop forever, so this is the single most important except-clause
        # in the module.
        log.exception("check_for_jobs failed")
        counts["errors"] += 1
        database.finish_run(conn, run_id, status="error", **counts)
    finally:
        conn.close()


@check_for_jobs.before_loop
async def before_check_jobs():
    await bot.wait_until_ready()  # Wait for bot to be ready before first run


# ==================== FETCH / DEDUP / CATEGORIZE ====================

async def fetch_all_jobs() -> list:
    """Fetches all sources concurrently (each source's blocking requests calls
    run in a worker thread so they never block the Discord heartbeat). A
    source that raises is logged and skipped, never aborts the run."""
    fetchers = {
        "Adzuna": fetch_all_adzuna_jobs,
        "GitHub": fetch_all_github_jobs,
        "ATS": fetch_all_ats_jobs,
    }
    results = await asyncio.gather(
        *(asyncio.to_thread(fn) for fn in fetchers.values()),
        return_exceptions=True,
    )

    jobs = []
    for name, result in zip(fetchers.keys(), results):
        if isinstance(result, Exception):
            log.exception("Source %s failed", name, exc_info=result)
            continue
        jobs.extend(result)
    return jobs


def select_new_jobs(conn, jobs: list) -> list:
    """Filters out jobs that already exist by normalized URL (volatile query
    params like Adzuna's `se=` session token stripped) or exact normalized
    fingerprint (one indexed DB lookup for the whole batch)."""
    if not jobs:
        return []

    normalized_urls = [dedup.normalize_url(job.url) for job in jobs]
    fingerprints = [dedup.fingerprint(job.company, job.title, job.location) for job in jobs]
    existing_urls, existing_fingerprints = database.find_existing(conn, normalized_urls, fingerprints)

    new_jobs = []
    seen_urls_in_batch: set[str] = set()
    for job, norm_url, fp in zip(jobs, normalized_urls, fingerprints):
        if norm_url in existing_urls or fp in existing_fingerprints:
            continue
        # A single fetch can contain the same posting twice under two
        # different `se=` tokens - dedupe within the batch too.
        if norm_url in seen_urls_in_batch:
            continue
        seen_urls_in_batch.add(norm_url)
        new_jobs.append(job)
    return new_jobs


async def categorize_all(jobs: list) -> list:
    """Categorizes jobs in prompt-packed chunks of categorizer.BATCH_SIZE,
    up to 3 chunks concurrently (bounded by a semaphore so a big backlog
    doesn't fan out into dozens of simultaneous Anthropic calls)."""
    if not jobs:
        return []

    semaphore = asyncio.Semaphore(3)
    chunk_size = categorizer.BATCH_SIZE
    chunks = [jobs[i:i + chunk_size] for i in range(0, len(jobs), chunk_size)]

    async def process(chunk):
        async with semaphore:
            pairs = [(job.title, job.description) for job in chunk]
            return await asyncio.to_thread(categorizer.categorize_jobs, pairs)

    chunk_results = await asyncio.gather(*(process(chunk) for chunk in chunks))

    pending = []
    for chunk, results in zip(chunks, chunk_results):
        for job, scored in zip(chunk, results):
            valid_majors = [(major, score) for major, score in scored if major in CHANNEL_IDS]
            if not valid_majors:
                continue
            fingerprint = dedup.fingerprint(job.company, job.title, job.location)
            pending.append(PendingPost(job=job, majors=valid_majors, fingerprint=fingerprint))
    return pending


# ==================== DISCORD POSTING ====================

def build_job_embed(job, major, score):
    """Builds a Jobright-style job card embed for a single major posting."""
    embed = discord.Embed(
        title=job.title,
        url=job.url,
        color=MAJOR_COLORS.get(major, discord.Color.light_grey()),
    )
    embed.add_field(name="Company", value=job.company or "Unknown", inline=True)
    embed.add_field(name="Location", value=job.location or "N/A", inline=True)
    if job.work_model:
        embed.add_field(name="Work Model", value=job.work_model, inline=True)
    if score > 1:
        embed.add_field(name="Match score", value=str(score), inline=True)
    embed.set_footer(text=f"Source: {job.source}" + (f" - Posted {job.posted_date}" if job.posted_date else ""))
    return embed


async def send_embed(channel, embed) -> None:
    """Sends one embed, capping the global send rate at ~1 msg/s (discord.py
    already handles per-route 429s; this guards the global 50/s limit and
    burst-flagging). Retries on 429 (honoring Retry-After) and 5xx; gives up
    immediately on 403/404 (missing perms, deleted channel)."""
    async with _send_semaphore:
        last_exc = None
        for attempt in range(MAX_SEND_ATTEMPTS):
            try:
                await channel.send(embed=embed)
                await asyncio.sleep(POST_DELAY)
                return
            except discord.HTTPException as e:
                last_exc = e
                status = getattr(e, "status", None)
                if status == 429:
                    retry_after = 5.0
                    response = getattr(e, "response", None)
                    if response is not None:
                        try:
                            retry_after = float(response.headers.get("Retry-After", 5))
                        except (TypeError, ValueError):
                            pass
                    log.warning("Rate limited sending embed, sleeping %.1fs", retry_after)
                    await asyncio.sleep(retry_after)
                    continue
                if status is not None and status >= 500:
                    backoff = (2, 4, 8)[min(attempt, 2)]
                    log.warning("Discord 5xx (%s), retrying in %ds", status, backoff)
                    await asyncio.sleep(backoff)
                    continue
                # 403/404 or anything else not worth retrying.
                log.error("Send failed permanently (status=%s): %s", status, e)
                raise
        raise last_exc


async def post_pending(conn, pending: list) -> int:
    """Posts each PendingPost to its majors' channels. Fully-succeeded jobs
    are marked posted_to_discord=1; anything partial/failed stays at 0 with
    post_attempts incremented so retry_unposted picks it up next run."""
    posted_count = 0

    for item in pending:
        succeeded_ids = []
        for major, score in item.majors:
            channel_id = CHANNEL_IDS[major]
            channel = bot.get_channel(channel_id)
            if channel is None:
                try:
                    channel = await bot.fetch_channel(channel_id)
                except Exception as e:
                    log.error("Could not find channel for %s (%s): %s", major, channel_id, e)
                    continue

            try:
                await send_embed(channel, build_job_embed(item.job, major, score))
                succeeded_ids.append(channel_id)
            except Exception as e:
                log.error("Failed to post %r to %s: %s", item.job.title, major, e)

        complete = len(succeeded_ids) == len(item.majors)
        database.mark_posted(conn, item.job.url, succeeded_ids, complete=complete)
        if complete:
            posted_count += 1
        else:
            database.record_post_failure(conn, item.job.url, "one or more channel sends failed")

    return posted_count


async def retry_unposted(conn) -> int:
    """Rebuilds and re-attempts jobs left at posted_to_discord=0 from a
    previous run (crash, transient Discord outage, etc). This is the fix
    for rows that used to be permanently lost: inserted before posting
    (crash-safe), but never revisited if the post failed."""
    rows = database.get_unposted_jobs(conn, max_attempts=MAX_POST_ATTEMPTS)
    retried_count = 0

    for row in rows:
        job = Job(
            url=row["job_url"],
            title=row["title"],
            company=row["company"],
            description="",
            location=row["location"] or "",
            work_model=row["work_model"] or "",
            posted_date=row["posted_date"] or "",
            source=row["source"] or "",
        )
        majors = [m for m in (row["majors"] or "").split(",") if m in CHANNEL_IDS]
        already_ids = {cid for cid in (row["discord_channel_ids"] or "").split(",") if cid}
        remaining = [(m, CHANNEL_IDS[m]) for m in majors if str(CHANNEL_IDS[m]) not in already_ids]

        if not remaining:
            # Nothing left to send but somehow not marked complete - close it out.
            database.mark_posted(conn, row["job_url"], [int(c) for c in already_ids], complete=True)
            continue

        newly_succeeded = []
        any_failed = False
        for major, channel_id in remaining:
            channel = bot.get_channel(channel_id)
            if channel is None:
                try:
                    channel = await bot.fetch_channel(channel_id)
                except Exception as e:
                    log.error("Could not find channel for %s (%s): %s", major, channel_id, e)
                    any_failed = True
                    continue

            # Scores aren't persisted across runs, so the retry embed passes
            # score=1, which suppresses the "Match score" field via the
            # `if score > 1` check in build_job_embed.
            try:
                await send_embed(channel, build_job_embed(job, major, 1))
                newly_succeeded.append(channel_id)
            except Exception as e:
                log.error("Retry post failed for %r to %s: %s", job.title, major, e)
                any_failed = True

        all_succeeded_ids = [int(c) for c in already_ids] + newly_succeeded
        complete = not any_failed and len(all_succeeded_ids) == len(majors)
        database.mark_posted(conn, row["job_url"], all_succeeded_ids, complete=complete)

        if complete:
            retried_count += 1
        else:
            database.record_post_failure(conn, row["job_url"], "retry: one or more channel sends failed")
            new_attempts = row["post_attempts"] + 1
            if new_attempts >= MAX_POST_ATTEMPTS:
                database.abandon_job(conn, row["job_url"])
                log.error("Abandoning %r after %d attempts", job.title, new_attempts)

    return retried_count


# ==================== MAIN EXECUTION ====================

if __name__ == "__main__":
    bot.run(TOKEN)
