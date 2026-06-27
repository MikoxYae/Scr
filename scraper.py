import os
import time
import requests
from bs4 import BeautifulSoup
from pyrogram import Client

URL = "https://t.me/+FGb29j_u1bpmMjEx"
CHAT_ID = "-1004453461157"   # ya numeric group id
BOT_TOKEN = "8603042415:AAGjOKwH8uDaLG5AWjP-CTh0hQ6qHGTJ_2Y"
API_ID = 32947515
API_HASH = "cc73af06049861e86e404ddd1fc6da35"

HEADERS = {"User-Agent": "Mozilla/5.0"}

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

def build_message(title, desc, links):
    msg = f"**Title:** {title}
"
    if desc:
        msg += f"**Description:** {desc}
"
    msg += f"**Links found:** {len(links)}

"
    for i, (t, h) in enumerate(links, 1):
        msg += f"{i}. {t or 'No text'}
{h}

"
    return msg[:3900]

def main():
    title, desc, links = scrape_page(URL)
    message = build_message(title, desc, links)

    app = Client("scraper_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
    with app:
        app.send_message(CHAT_ID, message, disable_web_page_preview=True)

if __name__ == "__main__":
    main()
