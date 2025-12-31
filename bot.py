import categorizer
import database
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
import os
import requests

# Load environment variables
load_dotenv("C:/Users/kerry/Python Code/internship-discord-bot/.env")
TOKEN = os.getenv('DISCORD_TOKEN')
ADZUNA_APP_ID = os.getenv('ADZUNA_ID')
ADZUNA_KEY = os.getenv('ADZUNA_KEY')

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
ADZUNA_SEARCH_TERMS = [
    "mechanical engineer intern",
    "electrical engineer intern",
    "chemical engineer intern",
    "computer science intern",
    "software engineer intern",
    "IT intern",
    "information systems intern",
    "civil engineer intern",
    "biomedical engineer intern",
    "industrial engineer intern",
    "petroleum engineer intern",
    "construction management intern",
    "software development intern",
    "data science intern",
    "machine learning intern",
    "AI intern",
    "cybersecurity intern",
    "network engineer intern",
    "systems engineer intern",
    "data engineer intern",
    "cloud engineer intern",
    "DevOps intern",
    "full stack intern",
    "backend engineer intern",
    "frontend engineer intern",
    "mobile developer intern",
    "embedded systems intern",
    "hardware engineer intern",
    "robotics intern",
    "aerospace engineer intern",
    "manufacturing engineer intern",
    "process engineer intern",
    "quality engineer intern",
    "project management intern",
    "product management intern",
    "environmental engineer intern",
    "structural engineer intern",
    "transportation engineer intern",
    "materials engineer intern",
    "nuclear engineer intern",
    "mining engineer intern",
    "web developer intern",
    "database administrator intern",
    "business analyst intern",
    "systems analyst intern",
    "infrastructure intern",
    "automation engineer intern",
    "control systems intern",
    "mechatronics intern",
    "reliability engineer intern"
]

# Discord bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')

    # Initialize database table if it doesn't exist
    conn = database.create_connection()
    database.create_table(conn)
    conn.close()
    print('Database initialized!')

    check_for_jobs.start()  # Start the scheduled loop


@tasks.loop(hours=24)  # Run every 24 hours
async def check_for_jobs():
    """Scheduled task to check for new jobs"""
    print(f"\n⏰ Checking for new jobs at {discord.utils.utcnow()}")
    
    jobs = fetch_all_adzuna_jobs()
    
    job_count = 0
    for adzuna_job in jobs:
        try: 
            job_data = {
                "url": adzuna_job["redirect_url"],
                "title": adzuna_job["title"],
                "company": adzuna_job["company"]["display_name"],
                "description": adzuna_job.get("description", "")
            }
            await process_job(job_data)
            job_count += 1
        except Exception as e:
            print(f"❌ Error: {e}")
    
    print(f"✅ Finished! Checked {len(jobs)} jobs, processed {job_count} new ones")

@check_for_jobs.before_loop
async def before_check_jobs():
    await bot.wait_until_ready()  # Wait for bot to be ready before first run


# ==================== JOB FETCHING FUNCTIONS ====================

def fetch_simplifyjobs():
    """Fetch jobs from SimplifyJobs GitHub README"""
    response = requests.get("https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships/refs/heads/dev/README.md")
    text = response.text
    return text


def fetch_adzuna_jobs(keywords="engineering intern", location="United States"):
    """Fetch jobs from Adzuna API"""
    base_url = "https://api.adzuna.com/v1/api/jobs/us/search/1"
    params = {
        "app_id": ADZUNA_APP_ID,
        "app_key": ADZUNA_KEY,
        "what": keywords,
        "where": location,
        "results_per_page": 5
    }
    response = requests.get(base_url, params=params)
    
    if response.status_code == 200:
        data = response.json()
        return data["results"]
    else:
        print(f"Error fetching Adzuna jobs: {response.status_code}")
        return []
    
def fetch_all_adzuna_jobs():
    """Fetch jobs from Adzuna using multiple search terms"""
    all_jobs = []
    for keyword in ADZUNA_SEARCH_TERMS:
        print(f"Searching for: {keyword}")
        jobs = fetch_adzuna_jobs(keywords=keyword)
        all_jobs.extend(jobs)
        print(f"  Found {len(jobs)} jobs")
    
    print(f"Total jobs fetched: {len(all_jobs)}")
    return all_jobs


# ==================== JOB PROCESSING FUNCTION ====================

async def process_job(job_data):
    """Process a single job: categorize, check duplicates, post to Discord, save to database"""
    conn = database.create_connection()

    # Extract job data
    title = job_data["title"]
    description = job_data.get("description", "")
    url = job_data["url"]
    
    # Check if already exists
    if database.check_job_exists(conn, url):
        return
    
    # Categorize by major
    majors = categorizer.categorize_job(title, description)
    if not majors:
        return
    
    # Filter to only majors with configured channels
    valid_majors = [major for major in majors if major in CHANNEL_IDS]
    if not valid_majors:
        return
    
    # Prepare data for database
    db_job_data = {
        "url": url,
        "title": title,
        "company": job_data["company"],
        "majors": ",".join(valid_majors),
        "posted": 0,
        "channelIDs": ""
    }
    
    # Insert into database
    database.insert_job(conn, db_job_data)
    print(f"✅ New job: {title} → {', '.join(valid_majors)}")
    
    # Post to Discord channels
    posted_channels = []
    for major in valid_majors:
        channel_id = CHANNEL_IDS[major]
        channel = bot.get_channel(channel_id)
        
        if channel is None:
            print(f"❌ ERROR: Could not find channel for {major}")
            continue
        
        message = f"**New {major.title()} Internship!**\n{title} at {job_data['company']}\n{url}"
        await channel.send(message)
        posted_channels.append(channel_id)
    
    # Update database with posted status
    database.update_posted_status(conn, url, posted_channels)


# ==================== MAIN EXECUTION ====================

if __name__ == "__main__":
    bot.run(TOKEN)
