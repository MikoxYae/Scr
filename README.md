# Scraper Bot

Telegram bot that scrapes web pages and downloads/sends videos.

## Commands

| Command | Description |
|---------|-------------|
| `/get <url>` | Find all videos on a page, download and send them all |
| `/video <url>` | List all video links found on a page |
| `/scrape <url>` | Get page title, description and links |

## Run on Replit

1. Open the Replit project
2. Click **Run** — Replit will execute `python main.py`
3. Bot starts automatically

## Run Locally

```bash
pip install -r requirements.txt
python main.py
```

## Project Structure

```
.
├── app/
│   ├── bot.py        # Pyrogram Client setup + run()
│   ├── scraper.py    # Page scraping + video extraction logic
│   ├── handlers.py   # All bot command handlers
│   └── utils/
│       └── logger.py # Shared logger
├── data/             # Temp download directory (auto-cleaned)
├── main.py           # Entry point
├── requirements.txt
├── .gitignore
└── .replit
```

## Config

Bot credentials are set in `app/bot.py`. Optionally override via `.env`:

```
BOT_TOKEN=your_token
API_ID=your_api_id
API_HASH=your_api_hash
```
