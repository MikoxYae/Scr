import os
import time
import tempfile
import requests
from pyrogram import filters, enums
from app.bot import app
from app.scraper import extract_video_from_page, scrape_page_info, HEADERS
from app.utils.logger import logger

MD = enums.ParseMode.MARKDOWN


def progress_bar(done: int, total: int) -> str:
    if total <= 0:
        return f"{done // (1024 * 1024)} MB"
    pct = done / total
    filled = int(pct * 10)
    bar = "█" * filled + "░" * (10 - filled)
    return f"[{bar}] {int(pct * 100)}%  ({done // (1024*1024)}MB / {total // (1024*1024)}MB)"


def extract_url_from_message(message) -> str | None:
    text = message.text or message.caption or ""
    entities = message.entities or []

    for ent in entities:
        if ent.type.name == "BOT_COMMAND":
            continue
        if ent.type.name == "URL":
            return text[ent.offset: ent.offset + ent.length]
        if ent.type.name == "TEXT_LINK" and ent.url:
            return ent.url

    parts = text.split(maxsplit=1)
    if len(parts) >= 2:
        return parts[1].strip()
    return None


@app.on_message(filters.command("start"))
async def start_cmd(client, message):
    await message.reply_text(
        "🤖 *Bot Online Hai!*\n\n"
        "Bas ek command:\n"
        "`/get <url>` — Page se saari videos dhundega, download karega aur yahan bhejega!\n\n"
        "Example:\n"
        "`/get https://desihub.to/post/xyz`\n\n"
        "Other commands:\n"
        "`/scrape <url>` — Page info + links\n"
        "`/video <url>` — Sirf video links list karo",
        parse_mode=MD,
    )


@app.on_message(filters.command("get"))
async def get_cmd(client, message):
    url = extract_url_from_message(message)
    if not url:
        await message.reply_text("URL do bhai: `/get https://example.com/post/xyz`", parse_mode=MD)
        return

    logger.info(f"/get called: {url}")
    status = await message.reply_text(
        f"🔍 Page scan kar raha hoon...\n`{url}`",
        parse_mode=MD,
        disable_web_page_preview=True,
    )

    try:
        title, videos, iframes = extract_video_from_page(url)
    except Exception as e:
        logger.error(f"Page load error: {e}")
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
        disable_web_page_preview=True,
    )

    for idx, video_url in enumerate(videos, 1):
        tmp_path = None
        try:
            await status.edit_text(
                f"📥 *Video {idx}/{len(videos)}*\n`{video_url[:90]}`\n\n⬇️ Download shuru...",
                parse_mode=MD,
                disable_web_page_preview=True,
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

                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False, dir="data") as tmp:
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
                                        parse_mode=MD,
                                    )
                                except Exception:
                                    pass
                                last_edit = now

            logger.info(f"Downloaded video {idx}: {video_url}")

            await status.edit_text(
                f"📤 *Uploading {idx}/{len(videos)}...*\nTelegram pe bhej raha hoon...",
                parse_mode=MD,
            )

            last_up = [0]

            async def upload_progress(current, total, i=idx):
                now = time.time()
                if now - last_up[0] > 3:
                    bar = progress_bar(current, total)
                    try:
                        await status.edit_text(
                            f"📤 *Uploading {i}/{len(videos)}*\n{bar}",
                            parse_mode=MD,
                        )
                    except Exception:
                        pass
                    last_up[0] = now

            await message.reply_video(
                video=tmp_path,
                caption=f"🎬 Video {idx}/{len(videos)} — {title}\n🔗 {url}",
                supports_streaming=True,
                progress=upload_progress,
            )

        except Exception as e:
            logger.error(f"Video {idx} error: {e}")
            try:
                await status.edit_text(f"❌ Video {idx} error: {e}")
            except Exception:
                pass
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)

    await status.edit_text(
        f"✅ *Sab {len(videos)} videos bhej di gayi!*\n📄 {title[:80]}",
        parse_mode=MD,
    )


@app.on_message(filters.command("scrape"))
async def scrape_cmd(client, message):
    url = extract_url_from_message(message)
    if not url:
        await message.reply_text("URL do: `/scrape https://example.com`", parse_mode=MD)
        return

    logger.info(f"/scrape called: {url}")
    status = await message.reply_text("⏳ Scraping...")
    try:
        title, desc, links = scrape_page_info(url)
        msg = f"🔗 {url}\n📄 {title}\n"
        if desc:
            msg += f"📝 {desc}\n"
        msg += f"\n🔗 Links ({len(links)}):\n" + "\n".join(links[:15])
        await status.edit_text(msg[:3900], disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"/scrape error: {e}")
        await status.edit_text(f"❌ Error: {e}")


@app.on_message(filters.command("video"))
async def video_cmd(client, message):
    url = extract_url_from_message(message)
    if not url:
        await message.reply_text("URL do: `/video https://example.com/post/xyz`", parse_mode=MD)
        return

    logger.info(f"/video called: {url}")
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
        logger.error(f"/video error: {e}")
        await status.edit_text(f"❌ Error: {e}")
