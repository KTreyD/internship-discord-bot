import categorizer
import database
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
import os

from sources.adzuna import fetch_all_adzuna_jobs
from sources.ats import fetch_all_ats_jobs
from sources.github_repos import fetch_all_github_jobs

# Load environment variables (expects a .env file in the project root)
load_dotenv()
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

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')

    # Initialize database table if it doesn't exist
    conn = database.create_connection()
    try:
        database.create_table(conn)
    finally:
        conn.close()
    print('Database initialized!')

    check_for_jobs.start()  # Start the scheduled loop


@tasks.loop(hours=24)  # Run every 24 hours
async def check_for_jobs():
    """Scheduled task to check for new jobs across all sources"""
    print(f"\n⏰ Checking for new jobs at {discord.utils.utcnow()}")

    jobs = fetch_all_adzuna_jobs() + fetch_all_github_jobs() + fetch_all_ats_jobs()

    job_count = 0
    for job in jobs:
        try:
            await process_job(job)
            job_count += 1
        except Exception as e:
            print(f"❌ Error: {e}")

    print(f"✅ Finished! Checked {len(jobs)} jobs, processed {job_count} new ones")

@check_for_jobs.before_loop
async def before_check_jobs():
    await bot.wait_until_ready()  # Wait for bot to be ready before first run


# ==================== JOB PROCESSING FUNCTION ====================

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
    embed.set_footer(text=f"Source: {job.source}" + (f" • Posted {job.posted_date}" if job.posted_date else ""))
    return embed


async def process_job(job):
    """Process a single job: categorize, check duplicates, post to Discord, save to database"""
    conn = database.create_connection()
    try:
        # Check if already exists
        if database.check_job_exists(conn, job.url):
            return

        # Categorize by major, ranked by relevance score
        scored_majors = categorizer.categorize_job(job.title, job.description)
        if not scored_majors:
            return

        # Filter to only majors with configured channels
        valid_majors = [(major, score) for major, score in scored_majors if major in CHANNEL_IDS]
        if not valid_majors:
            return

        major_names = [major for major, _ in valid_majors]

        # Prepare data for database
        db_job_data = {
            "url": job.url,
            "title": job.title,
            "company": job.company,
            "majors": ",".join(major_names),
            "posted": 0,
            "channelIDs": ""
        }

        # Insert into database
        database.insert_job(conn, db_job_data)
        print(f"✅ New job: {job.title} → {', '.join(major_names)}")

        # Post to Discord channels
        posted_channels = []
        for major, score in valid_majors:
            channel_id = CHANNEL_IDS[major]
            channel = bot.get_channel(channel_id)

            if channel is None:
                print(f"❌ ERROR: Could not find channel for {major}")
                continue

            embed = build_job_embed(job, major, score)
            await channel.send(embed=embed)
            posted_channels.append(channel_id)

        # Update database with posted status
        database.update_posted_status(conn, job.url, posted_channels)
    finally:
        conn.close()


# ==================== MAIN EXECUTION ====================

if __name__ == "__main__":
    bot.run(TOKEN)
