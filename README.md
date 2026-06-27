# Scraper Bot

Telegram bot that scrapes web pages and downloads/sends videos to a Telegram channel.

## Commands

| Command | Description |
|---------|-------------|
| `/get <url>` | Download all videos from a single post and send them |
| `/mget <url>` | Bulk download all posts on a page (auto multi-page) |
| `/video <url>` | List all video links found on a page |
| `/scrape <url>` | Get page title, description and links |
| `/setchannel <id>` | Set the target upload channel |
| `/getchannel` | Show the current channel |
| `/stats` | Show MongoDB status and lifetime stats |
| `/stop` | Stop a running scrape job |
| `/help` | Show all commands |

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
│   ├── config.py     # File-based channel config (data/config.json)
│   ├── db.py         # Async MongoDB helper (motor)
│   ├── scraper.py    # Page scraping + video extraction logic
│   ├── handlers.py   # All bot command handlers
│   └── utils/
│       ├── logger.py # Shared logger
│       └── thumb.py  # Thumbnail collage helper
├── data/             # Temp download directory (auto-cleaned)
├── main.py           # Entry point
├── requirements.txt
├── .gitignore
└── .replit
```

## Bot Config

Bot credentials are set in `app/bot.py`. Optionally override via `.env`:

```
BOT_TOKEN=your_token
API_ID=your_api_id
API_HASH=your_api_hash
```

MongoDB is configured only via environment variables (see below). The bot runs fine without MongoDB.

---

## MongoDB Setup (Optional)

MongoDB adds persistent progress tracking, lifetime stats, duplicate prevention, job history, and channel settings storage. The bot works fully without it — MongoDB is entirely optional.

### What MongoDB stores

| Collection | What it stores |
|---|---|
| `bot_stats` | Lifetime totals: scraped, sent, failed, skipped, total jobs |
| `jobs` | Every `/get`, `/mget`, `/scrape`, `/video` job with status and counters |
| `processed_posts` | Each processed post/URL per target channel (for duplicate prevention) |
| `channel_settings` | Per-user target channel set via `/setchannel` |

### Duplicate prevention

Before sending a post, the bot checks `processed_posts`. If the same URL was already sent to the same target channel, it is skipped and counted. The check is scoped to `url + target_channel` — the same post can be sent to a different channel without being skipped.

### Setup steps

**1. Create a MongoDB Atlas cluster**

- Go to [mongodb.com/cloud/atlas](https://www.mongodb.com/cloud/atlas) and sign in
- Create a free cluster (M0 is fine)
- Under **Database Access**, create a user with read/write permissions
- Under **Network Access**, allow access from anywhere (`0.0.0.0/0`) or your Replit IP

**2. Copy your connection string**

In Atlas → your cluster → **Connect** → **Drivers**, copy the connection string. It looks like:

```
mongodb+srv://username:password@cluster0.abc123.mongodb.net/?retryWrites=true&w=majority
```

Replace `<password>` with your actual database user password.

**3. Add Replit Secrets**

In your Replit project, go to **Secrets** (lock icon in the sidebar) and add:

| Key | Value |
|-----|-------|
| `MONGO_URI` | `mongodb+srv://username:password@cluster.mongodb.net/?retryWrites=true&w=majority` |
| `DB_NAME` | `telegram_scraper_bot` *(optional — this is already the default)* |

**4. Restart the bot**

Stop and re-run `python main.py`. On startup you will see:

```
MongoDB connected — db: telegram_scraper_bot
```

If the connection string is wrong or MongoDB is unreachable, you will see an error log and the bot continues running normally without MongoDB.

### Verify it's working

Send `/stats` to the bot. When MongoDB is connected you will see:

```
🗄 MongoDB: ✅ Connected

Lifetime Stats:
📥 Scraped: 0
✅ Sent: 0
❌ Failed: 0
⏭ Skipped: 0
🗂 Total Jobs: 0
```
