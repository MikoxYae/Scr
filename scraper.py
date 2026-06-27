import os
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from pyrogram import Client, filters

load_dotenv()

URL = os.getenv("DEFAULT_URL", "https://t.me/+FGb29j_u1bpmMjEx")
CHAT_ID = int(os.getenv("CHAT_ID", "-1004453461157"))
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
    return "\n".join(parts)[:3900]

@app.on_message(filters.command("start"))
async def start_cmd(client, message):
    await message.reply_text(
        "Bot online hai!\n\n"
        "Use karo: /scrape <url>\n"
        "Example: /scrape https://example.com"
    )

@app.on_message(filters.command("scrape"))
async def scrape_cmd(client, message):
    text = message.text or ""
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply_text("URL do: /scrape https://example.com")
        return
    url = parts[1].strip()
    status = await message.reply_text(f"Scraping: {url} ...")
    try:
        title, desc, links = scrape_page(url)
        result = build_message(url, title, desc, links)
        await status.edit_text(result, disable_web_page_preview=True)
    except Exception as e:
        await status.edit_text(f"Error: {e}")

if __name__ == "__main__":
    print("[*] Bot chal raha hai... Ctrl+C se band karo")
    app.run()
