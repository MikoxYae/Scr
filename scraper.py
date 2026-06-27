import os
import argparse
import asyncio
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from pyrogram import Client, filters

load_dotenv()

URL = os.getenv("DEFAULT_URL", "https://t.me/+FGb29j_u1bpmMjEx")
CHAT_ID = os.getenv("CHAT_ID", "-1004453461157")
BOT_TOKEN = os.getenv("BOT_TOKEN", "8603042415:AAGjOKwH8uDaLG5AWjP-CTh0hQ6qHGTJ_2Y")
API_ID = int(os.getenv("API_ID", "32947515"))
API_HASH = os.getenv("API_HASH", "cc73af06049861e86e404ddd1fc6da35")

HEADERS = {"User-Agent": "Mozilla/5.0"}

app = Client(
    "scraper_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

def scrape_page(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    title = soup.title.get_text(strip=True) if soup.title else "No title"

    desc = ""
    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        desc = meta["content"].strip()

    links = []
    for a in soup.select("a[href]"):
        href = a.get("href", "").strip()
        text = " ".join(a.get_text(" ", strip=True).split())
        if href:
            links.append((text[:80], href))

    return title, desc, links[:20]

def build_message(url, title, desc, links):
    parts = [
        f"URL: {url}",
        f"Title: {title}",
    ]
    if desc:
        parts.append(f"Description: {desc}")
    parts.append(f"Links found: {len(links)}")
    parts.append("")
    for i, (t, h) in enumerate(links, 1):
        parts.append(f"{i}. {t or 'No text'}")
        parts.append(h)
        parts.append("")
    return "
".join(parts)[:3900]

async def send_result(url, target_chat_id=CHAT_ID):
    title, desc, links = scrape_page(url)
    message = build_message(url, title, desc, links)
    await app.send_message(target_chat_id, message, disable_web_page_preview=True)

@app.on_message(filters.command("scrape"))
async def scrape_cmd(client, message):
    text = message.text or ""
    parts = text.split(maxsplit=1)
    url = parts[1].strip() if len(parts) > 1 else URL
    await message.reply_text("Scraping started...")
    await send_result(url, message.chat.id)

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url", nargs="?", default=URL, help="Page URL to scrape")
    args = parser.parse_args()

    async with app:
        await send_result(args.url, CHAT_ID)

if __name__ == "__main__":
    asyncio.run(main())
