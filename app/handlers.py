import os
import re
import time
import shutil
import asyncio
import tempfile
import requests
from pyrogram import filters, enums
from pyrogram.errors import FloodWait, MessageNotModified
from app.bot import app
from app.scraper import extract_post_metadata, extract_post_links, scrape_page_info, HEADERS
from app.config import get_channel, set_channel
from app.db import mongo
from app.utils.logger import logger
from app.utils.thumb import make_collage, download_thumb

MD = enums.ParseMode.MARKDOWN
SEND_DELAY = 3
MIN_FREE_MB = 200

_stop_flags: dict[int, bool] = {}
_current_jobs: dict[int, str] = {}


def progress_bar(done: int, total: int) -> str:
    if total <= 0:
        return f"{done // (1024 * 1024)} MB"
    pct = done / total
    filled = int(pct * 10)
    bar = "█" * filled + "░" * (10 - filled)
    return f"[{bar}] {int(pct * 100)}%  ({done // (1024*1024)}MB / {total // (1024*1024)}MB)"


def free_mb() -> int:
    return shutil.disk_usage("/home/runner/workspace").free // (1024 * 1024)


def build_caption(title: str, desc: str, tags: list, video_count: int, videos: list) -> str:
    ext = "MP4"
    if videos:
        for e in [".mp4", ".webm", ".mkv", ".mov"]:
            if e in videos[0].lower():
                ext = e.lstrip(".").upper()
                break
    tag_str = " ".join(f"#{t.replace(' ', '_')}" for t in tags[:8]) if tags else ""
    parts = [
        "━━━━━━━━━━━━━━━━━━━━",
        f"🎬 *{title.upper()}*",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    if desc:
        parts.append(f"\n📝 _{desc[:250]}_")
    if tag_str:
        parts.append(f"\n🏷 {tag_str}")
    parts.append(f"\n📦 *{video_count} Video{'s' if video_count > 1 else ''}*  |  `{ext}`")
    parts.append("━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(parts)


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


def next_page_url(url: str) -> str | None:
    """Auto-detect and increment page number in URL."""
    m = re.search(r'(/\w*?)(\d+)(/?)$', url)
    if m:
        return url[:m.start()] + m.group(1) + str(int(m.group(2)) + 1) + m.group(3)
    if url.endswith("/"):
        return url + "2"
    return url + "/2"


_peer_cache: dict = {}


async def resolve_peer(client, chat_id):
    key = str(chat_id)
    if key not in _peer_cache:
        try:
            chat = await client.get_chat(chat_id)
            _peer_cache[key] = chat.id
            logger.info(f"Peer resolved: {chat_id} → {chat.id} ({getattr(chat, 'title', '')})")
        except Exception as e:
            logger.error(f"Peer resolve failed {chat_id}: {e}")
            return None
    return _peer_cache[key]


async def flood_wait(e: FloodWait, status_msg=None):
    wait = e.value + 2
    logger.warning(f"FloodWait {wait}s")
    for remaining in range(wait, 0, -5):
        if status_msg:
            try:
                await status_msg.edit_text(
                    f"⏳ *Flood limit!*\n{remaining}s baad automatically resume hoga...",
                    parse_mode=MD,
                )
            except Exception:
                pass
        await asyncio.sleep(min(5, remaining))


async def safe_send_video(client, chat_id, video, caption, status_msg=None) -> bool:
    resolved = await resolve_peer(client, chat_id)
    if resolved is None:
        if status_msg:
            try:
                await status_msg.edit_text(
                    f"❌ *Channel access error!*\nBot ko `{chat_id}` mein admin banao phir `/setchannel` dobara karo.",
                    parse_mode=MD,
                )
            except Exception:
                pass
        return False

    for attempt in range(5):
        try:
            await client.send_video(
                chat_id=resolved, video=video, caption=caption, supports_streaming=True,
            )
            await asyncio.sleep(SEND_DELAY)
            return True
        except FloodWait as e:
            await flood_wait(e, status_msg)
        except Exception as e:
            logger.error(f"send_video attempt {attempt+1}: {e}")
            if attempt == 4:
                return False
            await asyncio.sleep(2)
    return False


async def safe_send_photo(client, chat_id, photo, caption) -> bool:
    resolved = await resolve_peer(client, chat_id)
    if resolved is None:
        return False
    for attempt in range(5):
        try:
            await client.send_photo(chat_id=resolved, photo=photo, caption=caption, parse_mode=MD)
            await asyncio.sleep(SEND_DELAY)
            return True
        except FloodWait as e:
            await flood_wait(e)
        except Exception as e:
            logger.error(f"send_photo attempt {attempt+1}: {e}")
            if attempt == 4:
                return False
            await asyncio.sleep(2)
    return False


async def download_video(video_url: str, referer: str, status_msg, label: str) -> str | None:
    if free_mb() < MIN_FREE_MB:
        logger.warning(f"Low disk: {free_mb()}MB free — skipping download")
        if status_msg:
            try:
                await status_msg.edit_text(
                    f"⚠️ *Disk space low!* ({free_mb()}MB free)\nDownload skip kar raha hoon...",
                    parse_mode=MD,
                )
            except Exception:
                pass
        return None

    tmp_path = None
    try:
        suffix = ".mp4"
        for ext in [".mp4", ".webm", ".mkv", ".mov", ".flv"]:
            if ext in video_url.lower():
                suffix = ext
                break

        dl_headers = {**HEADERS, "Referer": referer}
        with requests.get(video_url, headers=dl_headers, stream=True, timeout=120) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            done = 0
            last_edit = 0

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
                                await status_msg.edit_text(
                                    f"⬇️ *{label}*\n{bar}\n💾 Free: {free_mb()}MB",
                                    parse_mode=MD,
                                )
                            except (MessageNotModified, Exception):
                                pass
                            last_edit = now
        return tmp_path
    except Exception as e:
        logger.error(f"Download error: {e}")
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)
        return None


@app.on_message(filters.command("stop"))
async def stop_cmd(client, message):
    chat_id = message.chat.id
    _stop_flags[chat_id] = True
    job_id = _current_jobs.get(chat_id)
    if job_id:
        await mongo.mark_stopped(job_id)
    await message.reply_text(
        "🛑 *Stop signal bhej diya!*\n\nCurrent job ruk jayega — thoda wait karo...",
        parse_mode=MD,
    )


@app.on_message(filters.command("help"))
async def help_cmd(client, message):
    ch = get_channel()
    ch_info = f"`{ch}`" if ch else "Not set"
    db_status = "✅ Connected" if mongo.is_connected() else "❌ Disabled"
    await message.reply_text(
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🤖 *SCRAPER BOT — HELP*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "*📥 Download Commands:*\n"
        "`/get <url>` — Ek post ke saare videos download karo\n"
        "`/mget <url>` — Page ke saare posts bulk download karo (auto multi-page)\n\n"
        "*🔍 Info Commands:*\n"
        "`/video <url>` — Sirf video links list karo\n"
        "`/scrape <url>` — Page title, desc, links dekho\n\n"
        "*📡 Channel Commands:*\n"
        "`/setchannel <id>` — Upload channel set karo\n"
        "`/getchannel` — Current channel dekho\n\n"
        "*📊 Stats:*\n"
        "`/stats` — Bot stats aur MongoDB status\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "*⚙️ Features:*\n"
        "• Auto multi-page — `/mget` khud pages badlata hai\n"
        "• MongoDB tracking — processed posts skip karta hai\n"
        "• FloodWait auto-resume — flood aye toh ruk kar resume karta hai\n"
        "• Disk guard — storage full hone se pehle warn karta hai\n"
        "• Thumbnail collage — saare thumbs ek pic mein\n\n"
        f"📡 Channel: {ch_info}\n"
        f"🗄 MongoDB: {db_status}\n"
        "━━━━━━━━━━━━━━━━━━━━",
        parse_mode=MD,
    )


@app.on_message(filters.command("stats"))
async def stats_cmd(client, message):
    ch = get_channel()
    db_status = "✅ Connected" if mongo.is_connected() else "❌ Disconnected"

    if mongo.is_connected():
        stats = await mongo.get_stats()
        current_job = await mongo.get_current_job()
        last_job = await mongo.get_last_job() if not current_job else None

        job_info = ""
        if current_job:
            job_info = (
                f"\n\n🔄 *Running Job:*\n"
                f"  Command: `{current_job.get('command', '?')}`\n"
                f"  Processed: {current_job.get('processed_count', 0)} | "
                f"Sent: {current_job.get('sent_count', 0)} | "
                f"Skipped: {current_job.get('skipped_count', 0)}"
            )
        elif last_job:
            job_info = (
                f"\n\n📋 *Last Job:*\n"
                f"  Command: `{last_job.get('command', '?')}` — {last_job.get('status', '?')}\n"
                f"  Sent: {last_job.get('sent_count', 0)} | "
                f"Skipped: {last_job.get('skipped_count', 0)} | "
                f"Failed: {last_job.get('failed_count', 0)}"
            )

        await message.reply_text(
            f"📊 *Bot Stats*\n\n"
            f"🗄 MongoDB: {db_status}\n\n"
            f"*Lifetime Stats:*\n"
            f"📥 Scraped: *{stats.get('total_scraped', 0)}*\n"
            f"✅ Sent: *{stats.get('total_sent', 0)}*\n"
            f"❌ Failed: *{stats.get('total_failed', 0)}*\n"
            f"⏭ Skipped: *{stats.get('total_skipped', 0)}*\n"
            f"🗂 Total Jobs: *{stats.get('total_jobs', 0)}*\n\n"
            f"📡 Channel: `{ch or 'Not set'}`\n"
            f"💾 Free disk: *{free_mb()} MB*"
            f"{job_info}",
            parse_mode=MD,
        )
    else:
        await message.reply_text(
            f"📊 *Bot Stats*\n\n"
            f"🗄 MongoDB: {db_status}\n\n"
            f"📡 Channel: `{ch or 'Not set'}`\n"
            f"💾 Free disk: *{free_mb()} MB*\n\n"
            f"_Add MONGO\\_URI secret to enable stats tracking._",
            parse_mode=MD,
        )


@app.on_message(filters.command("start"))
async def start_cmd(client, message):
    await message.reply_text(
        "🤖 *Bot Online Hai!*\n\n"
        "`/help` — Sab commands dekho\n"
        "`/get <url>` — Single post download\n"
        "`/mget <url>` — Bulk download (auto multi-page)\n"
        "`/setchannel <id>` — Channel connect karo",
        parse_mode=MD,
    )


@app.on_message(filters.command("setchannel"))
async def setchannel_cmd(client, message):
    text = message.text or ""
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply_text(
            "Channel ID ya username do:\n`/setchannel -1001234567890`\n`/setchannel @mychannel`",
            parse_mode=MD,
        )
        return
    raw = parts[1].strip()
    channel_id = int(raw) if raw.lstrip("-").isdigit() else raw
    _peer_cache.clear()
    set_channel(channel_id)
    await mongo.save_channel(message.from_user.id, channel_id)
    logger.info(f"Channel set: {channel_id}")
    await message.reply_text(f"✅ Channel set:\n`{channel_id}`", parse_mode=MD)


@app.on_message(filters.command("getchannel"))
async def getchannel_cmd(client, message):
    ch = await mongo.get_channel(message.from_user.id)
    if ch is None:
        ch = get_channel()
    if ch:
        await message.reply_text(f"📡 Current channel: `{ch}`", parse_mode=MD)
    else:
        await message.reply_text(
            "❌ Channel set nahi hai.\n`/setchannel <id>` se set karo.", parse_mode=MD
        )


@app.on_message(filters.command("get"))
async def get_cmd(client, message):
    url = extract_url_from_message(message)
    if not url:
        await message.reply_text("URL do: `/get https://desihub.to/post/xyz`", parse_mode=MD)
        return

    channel = get_channel()
    dest = channel or message.chat.id
    dest_str = str(dest)
    chat_id = message.chat.id
    logger.info(f"/get {url} → {dest}")

    job_id = await mongo.create_job("/get", url, dest)
    _current_jobs[chat_id] = job_id
    _stop_flags[chat_id] = False

    status = await message.reply_text("🔍 *Scan kar raha hoon...*", parse_mode=MD)

    try:
        meta = extract_post_metadata(url)
    except Exception as e:
        await status.edit_text(f"❌ Page load error: {e}")
        await mongo.finish_job(job_id, status="failed", error_message=str(e))
        _current_jobs.pop(chat_id, None)
        return

    title = meta["title"]
    videos = meta["videos"]
    iframes = meta["iframes"]

    if not videos:
        msg = f"⚠️ Direct video nahi mila.\n\n🖼 Players ({len(iframes)}):\n" + "\n".join(iframes[:5]) if iframes else "❌ Koi video nahi mila."
        await status.edit_text(msg, disable_web_page_preview=True)
        await mongo.finish_job(job_id, status="completed")
        _current_jobs.pop(chat_id, None)
        return

    if await mongo.is_post_processed(url, dest_str):
        await status.edit_text(
            f"⏭ *Already processed!*\n\n`{url}`\n\nYe post pehle hi is channel pe bheja ja chuka hai.",
            parse_mode=MD,
        )
        await mongo.update_job(job_id, skipped_count=1)
        await mongo.increment_stats(skipped=1)
        await mongo.finish_job(job_id, status="completed")
        _current_jobs.pop(chat_id, None)
        return

    await mongo.update_job(job_id, total_found=len(videos))
    caption = build_caption(title, meta["desc"], meta["tags"], len(videos), videos)

    await status.edit_text(
        f"✅ *{title[:60]}*\n🎬 {len(videos)} video(s)\n📤 Upload shuru...",
        parse_mode=MD, disable_web_page_preview=True,
    )

    thumb_path = download_thumb(meta["thumbnail"]) if meta["thumbnail"] else None
    if thumb_path:
        try:
            await safe_send_photo(client, dest, thumb_path, caption)
        finally:
            if os.path.exists(thumb_path):
                os.remove(thumb_path)

    sent_count = 0
    failed_count = 0

    for idx, video_url in enumerate(videos, 1):
        if _stop_flags.get(chat_id):
            _stop_flags[chat_id] = False
            await mongo.mark_stopped(job_id)
            _current_jobs.pop(chat_id, None)
            await status.edit_text(f"🛑 *Job stopped!* ({idx-1}/{len(videos)} videos sent)", parse_mode=MD)
            return

        tmp_path = await download_video(video_url, url, status, f"Downloading {idx}/{len(videos)}")
        if not tmp_path:
            failed_count += 1
            await mongo.update_job(job_id, processed_count=idx, failed_count=failed_count, sent_count=sent_count)
            await mongo.increment_stats(failed=1)
            continue
        try:
            await status.edit_text(f"📤 *Uploading {idx}/{len(videos)}...*", parse_mode=MD)
            vid_cap = f"🎬 {idx}/{len(videos)} — {title}" if len(videos) > 1 else title
            sent = await safe_send_video(client, dest, tmp_path, vid_cap, status)
            if sent:
                sent_count += 1
                await mongo.increment_stats(sent=1)
            else:
                failed_count += 1
                await mongo.increment_stats(failed=1)
        except Exception as e:
            logger.error(f"Upload error: {e}")
            failed_count += 1
            await mongo.increment_stats(failed=1)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        await mongo.update_job(job_id, processed_count=idx, sent_count=sent_count, failed_count=failed_count)

    await mongo.save_processed_post(url, url, dest_str, "video", "sent")
    await mongo.increment_stats(scraped=1)
    await mongo.finish_job(job_id, status="completed")
    _current_jobs.pop(chat_id, None)

    await status.edit_text(
        f"✅ *Done!* — {title[:60]}\n🎬 {len(videos)} videos → `{dest}`", parse_mode=MD,
    )


@app.on_message(filters.command("mget"))
async def mget_cmd(client, message):
    url = extract_url_from_message(message)
    if not url:
        await message.reply_text(
            "URL do: `/mget https://desihub.to/explore/1`\n\nBot khud saare pages scan karega jab tak posts milte rahein.",
            parse_mode=MD,
        )
        return

    channel = get_channel()
    dest = channel or message.chat.id
    dest_str = str(dest)
    logger.info(f"/mget {url} → {dest}")

    chat_id = message.chat.id
    job_id = await mongo.create_job("/mget", url, dest)
    _current_jobs[chat_id] = job_id
    _stop_flags[chat_id] = False

    status = await message.reply_text(
        "🔍 *Bulk scrape shuru ho raha hai...*\nBot tab tak chalega jab tak saare posts khatam na ho jayein.",
        parse_mode=MD,
    )

    current_url = url
    page_num = 1
    total_videos_sent = 0
    total_skipped = 0
    total_already_done = 0
    total_failed = 0
    empty_pages = 0
    MAX_EMPTY_PAGES = 2

    try:
        while True:
            if _stop_flags.get(chat_id):
                _stop_flags[chat_id] = False
                await mongo.mark_stopped(job_id)
                _current_jobs.pop(chat_id, None)
                await status.edit_text(
                    f"🛑 *Job rok diya!*\n\n"
                    f"📄 Pages: *{page_num}* | 🎬 Videos: *{total_videos_sent}* | 🔁 Skip: *{total_already_done}*",
                    parse_mode=MD,
                )
                return

            try:
                await status.edit_text(
                    f"📄 *Page {page_num} scan kar raha hoon...*\n`{current_url}`\n\n"
                    f"✅ Bheje: {total_videos_sent} | ⏭ Skip: {total_skipped} | 🔁 Already done: {total_already_done}",
                    parse_mode=MD, disable_web_page_preview=True,
                )
            except (MessageNotModified, Exception):
                pass

            try:
                post_links = extract_post_links(current_url)
            except Exception as e:
                logger.error(f"Page {page_num} error: {e}")
                break

            if not post_links:
                empty_pages += 1
                logger.info(f"Empty page {page_num} ({empty_pages}/{MAX_EMPTY_PAGES})")
                if empty_pages >= MAX_EMPTY_PAGES:
                    break
                current_url = next_page_url(current_url)
                page_num += 1
                continue

            empty_pages = 0

            new_posts = []
            for link in post_links:
                if await mongo.is_post_processed(link, dest_str):
                    total_already_done += 1
                else:
                    new_posts.append(link)

            if not new_posts:
                logger.info(f"Page {page_num} — all already processed, moving to next")
                current_url = next_page_url(current_url)
                page_num += 1
                await asyncio.sleep(1)
                continue

            all_thumbs = []
            all_meta = []

            for i, post_url in enumerate(new_posts, 1):
                try:
                    meta = extract_post_metadata(post_url)
                    meta["url"] = post_url
                    all_meta.append(meta)
                    if meta["thumbnail"]:
                        all_thumbs.append(meta["thumbnail"])
                    try:
                        await status.edit_text(
                            f"📊 *Page {page_num} — Collecting {i}/{len(new_posts)}*\n📄 {meta['title'][:60]}\n\n"
                            f"✅ Bheje: {total_videos_sent} | 🔁 Done: {total_already_done}",
                            parse_mode=MD,
                        )
                    except (MessageNotModified, Exception):
                        pass
                    await asyncio.sleep(0.5)
                except Exception as e:
                    logger.error(f"Meta error {post_url}: {e}")
                    continue

            if all_thumbs and len(all_thumbs) > 1:
                collage_path = make_collage(all_thumbs)
                if collage_path:
                    total_vids = sum(len(m["videos"]) for m in all_meta)
                    all_tags = list(dict.fromkeys(t for m in all_meta for t in m["tags"]))[:10]
                    tag_str = " ".join(f"#{t.replace(' ', '_')}" for t in all_tags)
                    collage_cap = (
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"📦 *PAGE {page_num} — {len(new_posts)} POSTS*\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n\n"
                        f"🎬 Total Videos: *{total_vids}*\n"
                        f"🏷 {tag_str}"
                    )
                    try:
                        await safe_send_photo(client, dest, collage_path, collage_cap)
                    finally:
                        if os.path.exists(collage_path):
                            os.remove(collage_path)

            for post_idx, meta in enumerate(all_meta, 1):
                if _stop_flags.get(chat_id):
                    _stop_flags[chat_id] = False
                    await mongo.mark_stopped(job_id)
                    _current_jobs.pop(chat_id, None)
                    await status.edit_text(
                        f"🛑 *Job rok diya!*\n\n"
                        f"📄 Pages: *{page_num}* | 🎬 Videos: *{total_videos_sent}* | 🔁 Skip: *{total_already_done}*",
                        parse_mode=MD,
                    )
                    return

                post_url = meta["url"]
                title = meta["title"]
                videos = meta["videos"]

                if not videos:
                    total_skipped += 1
                    await mongo.update_job(job_id, skipped_count=total_skipped)
                    await mongo.increment_stats(skipped=1)
                    continue

                caption = build_caption(title, meta["desc"], meta["tags"], len(videos), videos)

                resolved = await resolve_peer(client, dest)
                if resolved:
                    try:
                        await client.send_message(
                            chat_id=resolved,
                            text=(
                                f"━━━━━━━━━━━━━━━━━━━━\n"
                                f"📌 *POST {post_idx} OF {len(all_meta)}*\n"
                                f"━━━━━━━━━━━━━━━━━━━━"
                            ),
                            parse_mode=MD,
                        )
                        await asyncio.sleep(SEND_DELAY)
                    except Exception as e:
                        logger.error(f"Separator send error: {e}")

                thumb_path = download_thumb(meta["thumbnail"]) if meta["thumbnail"] else None
                if thumb_path:
                    try:
                        await safe_send_photo(client, dest, thumb_path, caption)
                    finally:
                        if os.path.exists(thumb_path):
                            os.remove(thumb_path)

                for vid_idx, video_url in enumerate(videos, 1):
                    try:
                        await status.edit_text(
                            f"⬇️ *P{page_num} · Post {post_idx}/{len(all_meta)} · Vid {vid_idx}/{len(videos)}*\n"
                            f"📄 {title[:50]}\n💾 Free: {free_mb()}MB\n\n"
                            f"✅ Bheje: {total_videos_sent} | ⏭ Skip: {total_skipped}",
                            parse_mode=MD,
                        )
                    except (MessageNotModified, Exception):
                        pass

                    tmp_path = await download_video(
                        video_url, post_url, status,
                        f"P{page_num} Post{post_idx} Vid{vid_idx}"
                    )
                    if not tmp_path:
                        total_failed += 1
                        await mongo.increment_stats(failed=1)
                        continue
                    try:
                        if len(videos) > 1:
                            vid_cap = f"🎬 *{title.upper()}*\n📹 Video {vid_idx} of {len(videos)}"
                        else:
                            vid_cap = f"🎬 *{title.upper()}*"
                        sent = await safe_send_video(client, dest, tmp_path, vid_cap, status)
                        if sent:
                            total_videos_sent += 1
                            await mongo.increment_stats(sent=1)
                        else:
                            total_failed += 1
                            await mongo.increment_stats(failed=1)
                    except Exception as e:
                        logger.error(f"Upload error: {e}")
                        total_failed += 1
                        await mongo.increment_stats(failed=1)
                    finally:
                        if os.path.exists(tmp_path):
                            os.remove(tmp_path)

                await mongo.save_processed_post(post_url, post_url, dest_str, "video", "sent")
                await mongo.increment_stats(scraped=1)
                await mongo.update_job(
                    job_id,
                    processed_count=post_idx,
                    sent_count=total_videos_sent,
                    failed_count=total_failed,
                    skipped_count=total_skipped,
                )
                await asyncio.sleep(1)

            current_url = next_page_url(current_url)
            page_num += 1
            await asyncio.sleep(2)

    except Exception as e:
        logger.error(f"/mget fatal error: {e}")
        await mongo.finish_job(job_id, status="failed", error_message=str(e))
        _current_jobs.pop(chat_id, None)
        raise

    await mongo.finish_job(job_id, status="completed")
    _current_jobs.pop(chat_id, None)

    await status.edit_text(
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ *MGET COMPLETE!*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📄 Pages scanned: *{page_num - 1}*\n"
        f"🎬 Videos bheje: *{total_videos_sent}*\n"
        f"⏭ Skip (no video): *{total_skipped}*\n"
        f"🔁 Already processed: *{total_already_done}*\n"
        f"📡 Channel: `{dest}`\n"
        f"💾 Free disk: *{free_mb()} MB*",
        parse_mode=MD,
    )


@app.on_message(filters.command("video"))
async def video_cmd(client, message):
    url = extract_url_from_message(message)
    if not url:
        await message.reply_text("URL do: `/video https://desihub.to/post/xyz`", parse_mode=MD)
        return

    channel = get_channel()
    dest = channel or message.chat.id
    chat_id = message.chat.id

    job_id = await mongo.create_job("/video", url, dest)
    _current_jobs[chat_id] = job_id

    status = await message.reply_text("🎬 Video links dhundh raha hoon...")
    try:
        meta = extract_post_metadata(url)
        videos, iframes, title = meta["videos"], meta["iframes"], meta["title"]
        if videos:
            msg = f"✅ *{title}*\n\n🎬 Video Links ({len(videos)}):\n" + "\n".join(f"\n{i}. `{v}`" for i, v in enumerate(videos[:15], 1))
        elif iframes:
            msg = f"⚠️ Direct MP4 nahi mila.\n\n🖼 Players ({len(iframes)}):\n" + "\n".join(f"\n{i}. {v}" for i, v in enumerate(iframes[:5], 1))
        else:
            msg = f"❌ Koi video nahi mila.\nTitle: {title}"
        await status.edit_text(msg[:3900], parse_mode=MD, disable_web_page_preview=True)
        await mongo.update_job(job_id, total_found=len(videos))
        await mongo.finish_job(job_id, status="completed")
    except Exception as e:
        await status.edit_text(f"❌ Error: {e}")
        await mongo.finish_job(job_id, status="failed", error_message=str(e))
    finally:
        _current_jobs.pop(chat_id, None)


@app.on_message(filters.command("scrape"))
async def scrape_cmd(client, message):
    url = extract_url_from_message(message)
    if not url:
        await message.reply_text("URL do: `/scrape https://example.com`", parse_mode=MD)
        return

    channel = get_channel()
    dest = channel or message.chat.id
    chat_id = message.chat.id

    job_id = await mongo.create_job("/scrape", url, dest)
    _current_jobs[chat_id] = job_id

    status = await message.reply_text("⏳ Scraping...")
    try:
        title, desc, links = scrape_page_info(url)
        msg = f"🔗 {url}\n📄 {title}\n"
        if desc:
            msg += f"📝 {desc}\n"
        msg += f"\n🔗 Links ({len(links)}):\n" + "\n".join(links[:15])
        await status.edit_text(msg[:3900], disable_web_page_preview=True)
        await mongo.finish_job(job_id, status="completed")
    except Exception as e:
        await status.edit_text(f"❌ Error: {e}")
        await mongo.finish_job(job_id, status="failed", error_message=str(e))
    finally:
        _current_jobs.pop(chat_id, None)
