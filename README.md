#Disclaimer
I did plug this into Claude AI and tell it to write this README so this is the result and probably why you see emojis and stuff. Also during troubleshooting I told the same AI to remove my troubleshooting
code and thus it organized my code and put little comments that you can see. Other than that, everything else has been figured out and coded by my self with little to no usage from my copilot on vscode.

# Discord Internship Bot

Automatically fetches engineering internship postings from Adzuna API and posts them to Discord channels organized by major.

## Features

- 🔍 Searches Adzuna API for internships across multiple engineering disciplines
- 🤖 Automatically categorizes jobs by major (mechanical, electrical, chemical, etc.)
- 📢 Posts to specific Discord channels based on major
- 🗄️ Stores jobs in SQLite database to prevent duplicates
- ⏰ Runs on a 24-hour schedule to check for new postings

## Prerequisites

- Python 3.11+
- Discord bot token
- Adzuna API credentials (App ID and API Key)

## Installation

1. Clone the repository:
```bash
git clone https://github.com/KTreyD/internship-discord-bot.git
cd internship-discord-bot
```

2. Create a virtual environment:
```bash
python -m venv venv
```

3. Activate the virtual environment:
   - Windows: `venv\Scripts\activate`
   - Mac/Linux: `source venv/bin/activate`

4. Install dependencies:
```bash
pip install discord.py python-dotenv requests
```

5. Create a `.env` file in the project root with your credentials:
```
DISCORD_TOKEN=your_discord_bot_token
ADZUNA_KEY=your_adzuna_api_key
ADZUNA_ID=your_adzuna_app_id
```

## Configuration

### Discord Channel IDs

Update `CHANNEL_IDS` in `bot.py` with your Discord channel IDs:
```python
CHANNEL_IDS = {
    "mechanical": YOUR_CHANNEL_ID,
    "electrical": YOUR_CHANNEL_ID,
    # ... add more
}
```

### Search Terms

Modify `ADZUNA_SEARCH_TERMS` in `bot.py` to customize job searches:
```python
ADZUNA_SEARCH_TERMS = [
    "mechanical engineer intern",
    "software engineer intern",
    # ... add more
]
```

### Categorization Keywords

Edit `MAJOR_KEYWORDS` in `categorizer.py` to adjust job categorization:
```python
MAJOR_KEYWORDS = {
    "mechanical": ["mechanical", "CAD", "manufacturing", ...],
    # ... add more
}
```

## Usage

Run the bot:
```bash
python bot.py
```

The bot will:
1. Connect to Discord
2. Immediately check for new internships
3. Continue checking every 24 hours automatically

Stop the bot with `Ctrl+C`.

## Project Structure
```
job bot/
├── bot.py              # Main Discord bot and scheduling logic
├── categorizer.py      # Job categorization by major
├── database.py         # SQLite database operations
├── .env               # Environment variables (not in git)
├── .gitignore         # Git ignore file
└── internships.db     # SQLite database (auto-created)
```

## How It Works

1. **Fetching**: Bot searches Adzuna API with predefined keywords
2. **Categorization**: Each job is analyzed using keyword matching to determine relevant majors
3. **Duplicate Check**: Database is checked to prevent posting the same job twice
4. **Posting**: Jobs are posted to appropriate Discord channels based on major
5. **Storage**: Job details are saved to SQLite database with posting status

## API Rate Limits

- **Adzuna Free Tier**: 250 API calls/month
- **Current usage**: ~450 calls/month with all search terms
- **Recommendation**: Adjust search terms or frequency if hitting limits

## Future Improvements

- [ ] Add SimplifyJobs GitHub scraping as second data source
- [ ] Implement error logging to file
- [ ] Add retry logic for failed Discord posts
- [ ] Expand keyword lists for better categorization
- [ ] Add web dashboard for monitoring

## Contributing

This is a personal project, but suggestions are welcome!

## License

MIT License - feel free to use and modify for your own Discord server.

## Author

Built by [Your Name]

## Acknowledgments

- [SimplifyJobs](https://github.com/SimplifyJobs/Summer2025-Internships) for internship list inspiration
- [Adzuna API](https://developer.adzuna.com/) for job data
- [discord.py](https://discordpy.readthedocs.io/) for Discord integration
