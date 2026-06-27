import os
import re
import time
import asyncio
import tempfile
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from pyrogram import Client, filters, enums
from urllib.parse import urljoin

MD = enums.ParseMode.MARKDOWN

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "8603042415:AAGjOKwH8uDaLG5AWjP-CTh0hQ6qHGTJ_2Y")
API_ID    = int(os.getenv("API_ID",  "32947515"))
API_HASH  = os.getenv("API_HASH",    "cc73af06049861e86e404ddd1fc6da35")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.google.com/",
}

VIDEO_RE = re.compile(
    r'https?://[^\s\'"<>]+\.(?:mp4|webm|mkv|avi|mov|flv|ts)(?:[?#][^\s\'"<>]*)?',
    re.IGNORECASE
)

app = Client("scraper_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)


def progress_bar(done, total):
    if total <= 0:
        return f"{done // (1024*1024)} MB"
    pct = done / total
    filled = int(pct * 10)
    bar = "█" * filled + "░" * (10 - filled)
    return f"[{bar}] {int(pct*100)}%  ({done//(1024*1024)}MB / {total//(1024*1024)}MB)"


def extract_video_from_page(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    title = soup.title.get_text(strip=True) if soup.title else "Video"

    found = []

    for tag in soup.find_all(["video", "source"]):
        for attr in ["src", "data-src", "data-url", "data-video", "data-mp4"]:
            val = tag.get(attr, "").strip()
            if val and val.startswith("http"):
                found.append(val)
            elif val:
                found.append(urljoin(url, val))

    for tag in soup.find_all(True):
        for attr in ["data-src", "data-video", "data-mp4", "data-stream", "data-hls", "data-file"]:
            val = tag.get(attr, "").strip()
            if val and val.startswith("http") and any(ext in val.lower() for ext in [".mp4", ".webm", ".m3u8", ".mkv"]):
                found.append(val)

    for match in VIDEO_RE.findall(r.text):
        found.append(match)

    seen = []
    for v in found:
        if v not in seen:
            seen.append(v)

    iframes = []
    if not seen:
        for iframe in soup.find_all("iframe"):
            src = iframe.get("src", "").strip()
            if src and "javascript" not in src.lower():
                iframes.append(urljoin(url, src))

    return title, seen, iframes


@app.on_message(filters.command("start"))
async def start_cmd(client, message):
    await message.reply_text(
        "🤖 *Bot Online Hai!*\n\n"
        "Bas ek command:\n"
        "`/get <url>` — Page se video dhundega, download karega aur yahan bhejega!\n\n"
        "Example:\n"
        "`/get https://desihub.to/post/xyz`\n\n"
        "Other commands:\n"
        "`/scrape <url>` — Sirf page info + links\n"
        "`/video <url>` — Sirf video links list karo",
        parse_mode=MD
    )


def extract_url_from_message(message):
    """
    Telegram truncates long URLs in message.text.
    The correct full URL lives in message.entities (type=url)
    or message.entities (type=text_link, url field).
    We skip the command entity (index 0) and return the first URL found.
    """
    text = message.text or message.caption or ""
    entities = message.entities or []

    for ent in entities:
        # skip the /command entity itself
        if ent.type.name == "BOT_COMMAND":
            continue
        if ent.type.name == "URL":
            return text[ent.offset: ent.offset + ent.length]
        if ent.type.name == "TEXT_LINK" and ent.url:
            return ent.url

    # fallback: split by whitespace after the command word
    parts = text.split(maxsplit=1)
    if len(parts) >= 2:
        return parts[1].strip()
    return None


@app.on_message(filters.command("get"))
async def get_cmd(client, message):
    url = extract_url_from_message(message)
    if not url:
        await message.reply_text("URL do bhai: `/get https://example.com/post/xyz`", parse_mode=MD)
        return

    status = await message.reply_text(f"🔍 Page scan kar raha hoon...\n`{url}`", parse_mode=MD, disable_web_page_preview=True)

    try:
        title, videos, iframes = extract_video_from_page(url)
    except Exception as e:
        await status.edit_text(f"❌ Page load error: {e}")
        return

    if not videos:
        if iframes:
            msg = f"⚠️ Direct .mp4 nahi mila.\n\n🖼 Player/Iframe mila ({len(iframes)}):\n"
            for i, v in enumerate(iframes[:5], 1):
                msg += f"\n{i}. {v}"
            await status.edit_text(msg, disable_web_page_preview=True)
        else:
            await status.edit_text("❌ Is page pe koi video link nahi mila.")
        return

    await status.edit_text(
        f"✅ *{title[:80]}*\n\n🎬 {len(videos)} video(s) mili!\nSab download ho rahi hain...",
        parse_mode=MD,
        disable_web_page_preview=True
    )

    for idx, video_url in enumerate(videos, 1):
        tmp_path = None
        try:
            await status.edit_text(
                f"📥 *Video {idx}/{len(videos)}*\n`{video_url[:90]}`\n\n⬇️ Download shuru...",
                parse_mode=MD,
                disable_web_page_preview=True
            )

            dl_headers = {**HEADERS, "Referer": url}
            with requests.get(video_url, headers=dl_headers, stream=True, timeout=120) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length", 0))
                done = 0
                last_edit = 0

                suffix = ".mp4"
                for ext in [".mp4", ".webm", ".mkv", ".mov", ".flv"]:
                    if ext in video_url.lower():
                        suffix = ext
                        break

                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                    tmp_path = tmp.name
                    for chunk in r.iter_content(chunk_size=512 * 1024):
                        if chunk:
                            tmp.write(chunk)
                            done += len(chunk)
                            now = time.time()
                            if now - last_edit > 2:
                                bar = progress_bar(done, total)
                                try:
                                    await status.edit_text(
                                        f"⬇️ *Downloading {idx}/{len(videos)}*\n{bar}",
                                        parse_mode=MD
                                    )
                                except Exception:
                                    pass
                                last_edit = now

            await status.edit_text(
                f"📤 *Uploading {idx}/{len(videos)}...*\nTelegram pe bhej raha hoon...",
                parse_mode=MD
            )

            last_up = [0]

            async def upload_progress(current, total, i=idx):
                now = time.time()
                if now - last_up[0] > 3:
                    bar = progress_bar(current, total)
                    try:
                        await status.edit_text(
                            f"📤 *Uploading {i}/{len(videos)}*\n{bar}",
                            parse_mode=MD
                        )
                    except Exception:
                        pass
                    last_up[0] = now

            await message.reply_video(
                video=tmp_path,
                caption=f"🎬 Video {idx}/{len(videos)} — {title}\n🔗 {url}",
                supports_streaming=True,
                progress=upload_progress
            )

        except Exception as e:
            try:
                await status.edit_text(f"❌ Video {idx} error: {e}")
            except Exception:
                pass
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)

    await status.edit_text(f"✅ *Sab {len(videos)} videos bhej di gayi!*\n📄 {title[:80]}", parse_mode=MD)


@app.on_message(filters.command("scrape"))
async def scrape_cmd(client, message):
    url = extract_url_from_message(message)
    if not url:
        await message.reply_text("URL do: `/scrape https://example.com`", parse_mode=MD)
        return
    status = await message.reply_text(f"⏳ Scraping...")
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        title = soup.title.get_text(strip=True) if soup.title else "No title"
        desc = ""
        meta = soup.find("meta", attrs={"name": "description"})
        if meta and meta.get("content"):
            desc = meta["content"].strip()[:200]
        links = []
        for a in soup.select("a[href]"):
            href = a.get("href", "").strip()
            txt = " ".join(a.get_text(" ", strip=True).split())[:60]
            if href:
                links.append(f"{txt or 'link'} → {href}")
        msg = f"🔗 {url}\n📄 {title}\n"
        if desc:
            msg += f"📝 {desc}\n"
        msg += f"\n🔗 Links ({len(links)}):\n" + "\n".join(links[:15])
        await status.edit_text(msg[:3900], disable_web_page_preview=True)
    except Exception as e:
        await status.edit_text(f"❌ Error: {e}")


@app.on_message(filters.command("video"))
async def video_cmd(client, message):
    url = extract_url_from_message(message)
    if not url:
        await message.reply_text("URL do: `/video https://example.com/post/xyz`", parse_mode=MD)
        return
    status = await message.reply_text("🎬 Video links dhundh raha hoon...")
    try:
        title, videos, iframes = extract_video_from_page(url)
        if videos:
            msg = f"✅ *{title}*\n\n🎬 Video Links ({len(videos)}):\n"
            for i, v in enumerate(videos[:15], 1):
                msg += f"\n{i}. `{v}`"
        elif iframes:
            msg = f"⚠️ Direct MP4 nahi mila.\n\n🖼 Player/Iframe ({len(iframes)}):\n"
            for i, v in enumerate(iframes[:5], 1):
                msg += f"\n{i}. {v}"
        else:
            msg = f"❌ Koi video nahi mila.\nTitle: {title}"
        await status.edit_text(msg[:3900], parse_mode=MD, disable_web_page_preview=True)
    except Exception as e:
        await status.edit_text(f"❌ Error: {e}")


if __name__ == "__main__":
    print("[*] Bot chal raha hai... Ctrl+C se band karo")
    app.run()
