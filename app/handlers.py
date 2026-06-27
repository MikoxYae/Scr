import os
import time
import asyncio
import tempfile
import requests
from pyrogram import filters, enums
from pyrogram.errors import FloodWait, MessageNotModified
from app.bot import app
from app.scraper import extract_post_metadata, extract_post_links, scrape_page_info, HEADERS
from app.config import get_channel, set_channel
from app.utils.logger import logger
from app.utils.thumb import make_collage, download_thumb

MD = enums.ParseMode.MARKDOWN

SEND_DELAY = 3


def progress_bar(done: int, total: int) -> str:
    if total <= 0:
        return f"{done // (1024 * 1024)} MB"
    pct = done / total
    filled = int(pct * 10)
    bar = "█" * filled + "░" * (10 - filled)
    return f"[{bar}] {int(pct * 100)}%  ({done // (1024*1024)}MB / {total // (1024*1024)}MB)"


def build_caption(title: str, desc: str, tags: list, video_count: int, videos: list) -> str:
    ext = "MP4"
    if videos:
        for e in [".mp4", ".webm", ".mkv", ".mov"]:
            if e in videos[0].lower():
                ext = e.lstrip(".").upper()
                break
    tag_str = " ".join(f"#{t.replace(' ', '_')}" for t in tags[:8]) if tags else ""
    parts = [f"📹 *{title}*"]
    if desc:
        parts.append(f"\n📝 {desc[:250]}")
    if tag_str:
        parts.append(f"\n🏷 {tag_str}")
    parts.append(f"\n🎬 {video_count} Video{'s' if video_count > 1 else ''} · {ext}")
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


async def safe_send_video(client, chat_id, video, caption, status_msg=None):
    """Send video with FloodWait retry."""
    for attempt in range(3):
        try:
            await client.send_video(
                chat_id=chat_id,
                video=video,
                caption=caption,
                supports_streaming=True,
            )
            await asyncio.sleep(SEND_DELAY)
            return True
        except FloodWait as e:
            wait = e.value + 2
            logger.warning(f"FloodWait {wait}s — waiting...")
            if status_msg:
                try:
                    await status_msg.edit_text(f"⏳ Flood limit — {wait}s wait kar raha hoon...", parse_mode=MD)
                except Exception:
                    pass
            await asyncio.sleep(wait)
        except Exception as e:
            logger.error(f"send_video error: {e}")
            return False
    return False


async def safe_send_photo(client, chat_id, photo, caption):
    """Send photo with FloodWait retry."""
    for attempt in range(3):
        try:
            await client.send_photo(chat_id=chat_id, photo=photo, caption=caption, parse_mode=MD)
            await asyncio.sleep(SEND_DELAY)
            return True
        except FloodWait as e:
            await asyncio.sleep(e.value + 2)
        except Exception as e:
            logger.error(f"send_photo error: {e}")
            return False
    return False


async def download_video(video_url: str, referer: str, status_msg, label: str) -> str | None:
    tmp_path = None
    try:
        dl_headers = {**HEADERS, "Referer": referer}
        suffix = ".mp4"
        for ext in [".mp4", ".webm", ".mkv", ".mov", ".flv"]:
            if ext in video_url.lower():
                suffix = ext
                break

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
                                await status_msg.edit_text(f"⬇️ *{label}*\n{bar}", parse_mode=MD)
                            except (MessageNotModified, Exception):
                                pass
                            last_edit = now
        return tmp_path
    except Exception as e:
        logger.error(f"Download error: {e}")
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)
        return None


@app.on_message(filters.command("start"))
async def start_cmd(client, message):
    ch = get_channel()
    ch_info = f"📡 Connected: `{ch}`" if ch else "📡 Channel: not connected"
    await message.reply_text(
        "🤖 *Bot Online Hai!*\n\n"
        "Commands:\n"
        "`/get <url>` — Ek post ke saare videos download + bhejo\n"
        "`/mget <url>` — Page ke saare posts ke videos bulk download\n"
        "`/setchannel <id>` — Upload channel set karo\n"
        "`/getchannel` — Current channel dekho\n"
        "`/video <url>` — Sirf video links list\n"
        "`/scrape <url>` — Page info\n\n"
        f"{ch_info}",
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
    set_channel(channel_id)
    logger.info(f"Channel set: {channel_id}")
    await message.reply_text(f"✅ Channel set ho gaya:\n`{channel_id}`", parse_mode=MD)


@app.on_message(filters.command("getchannel"))
async def getchannel_cmd(client, message):
    ch = get_channel()
    if ch:
        await message.reply_text(f"📡 Current channel: `{ch}`", parse_mode=MD)
    else:
        await message.reply_text("❌ Koi channel connect nahi hai.\n`/setchannel <id>` se connect karo.", parse_mode=MD)


@app.on_message(filters.command("get"))
async def get_cmd(client, message):
    url = extract_url_from_message(message)
    if not url:
        await message.reply_text("URL do: `/get https://desihub.to/post/xyz`", parse_mode=MD)
        return

    channel = get_channel()
    dest = channel or message.chat.id
    logger.info(f"/get {url} → {dest}")

    status = await message.reply_text(
        f"🔍 *Scan kar raha hoon...*", parse_mode=MD, disable_web_page_preview=True
    )

    try:
        meta = extract_post_metadata(url)
    except Exception as e:
        logger.error(f"/get error: {e}")
        await status.edit_text(f"❌ Page load error: {e}")
        return

    title = meta["title"]
    desc = meta["desc"]
    tags = meta["tags"]
    thumbnail = meta["thumbnail"]
    videos = meta["videos"]
    iframes = meta["iframes"]

    if not videos:
        if iframes:
            msg = f"⚠️ Direct video nahi mila.\n\n🖼 Player links ({len(iframes)}):\n"
            for i, v in enumerate(iframes[:5], 1):
                msg += f"\n{i}. {v}"
            await status.edit_text(msg, disable_web_page_preview=True)
        else:
            await status.edit_text("❌ Koi video link nahi mila.")
        return

    caption = build_caption(title, desc, tags, len(videos), videos)

    await status.edit_text(
        f"✅ *{title[:70]}*\n🎬 {len(videos)} video(s) mili\n📤 Upload ho rahi hain...",
        parse_mode=MD,
        disable_web_page_preview=True,
    )

    thumb_path = download_thumb(thumbnail) if thumbnail else None
    if thumb_path:
        try:
            await safe_send_photo(client, dest, thumb_path, caption)
        except Exception:
            pass
        finally:
            if os.path.exists(thumb_path):
                os.remove(thumb_path)

    for idx, video_url in enumerate(videos, 1):
        tmp_path = await download_video(
            video_url, url, status,
            f"Downloading {idx}/{len(videos)} — {title[:40]}"
        )
        if not tmp_path:
            continue
        try:
            await status.edit_text(f"📤 *Uploading {idx}/{len(videos)}...*", parse_mode=MD)
            vid_cap = f"🎬 {idx}/{len(videos)} — {title}" if len(videos) > 1 else title
            await safe_send_video(client, dest, tmp_path, vid_cap, status)
            logger.info(f"Sent video {idx}/{len(videos)}")
        except Exception as e:
            logger.error(f"Upload error vid {idx}: {e}")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    await status.edit_text(
        f"✅ *Done!*\n📄 {title[:70]}\n🎬 {len(videos)} videos bheje → `{dest}`",
        parse_mode=MD,
    )


@app.on_message(filters.command("mget"))
async def mget_cmd(client, message):
    url = extract_url_from_message(message)
    if not url:
        await message.reply_text(
            "URL do: `/mget https://desihub.to/explore/1`\n\nPage ke saare posts bulk download karega.",
            parse_mode=MD,
        )
        return

    channel = get_channel()
    dest = channel or message.chat.id
    logger.info(f"/mget {url} → {dest}")

    status = await message.reply_text(
        f"🔍 *Posts dhundh raha hoon...*", parse_mode=MD, disable_web_page_preview=True
    )

    try:
        post_links = extract_post_links(url)
    except Exception as e:
        await status.edit_text(f"❌ Page error: {e}")
        return

    if not post_links:
        await status.edit_text("❌ Koi post link nahi mila.")
        return

    total_posts = len(post_links)
    await status.edit_text(
        f"✅ *{total_posts} posts mile!*\nMetadata + thumbnails collect kar raha hoon...",
        parse_mode=MD,
    )

    all_meta = []
    all_thumbs = []

    for i, post_url in enumerate(post_links, 1):
        try:
            meta = extract_post_metadata(post_url)
            meta["url"] = post_url
            all_meta.append(meta)
            if meta["thumbnail"]:
                all_thumbs.append(meta["thumbnail"])
            try:
                await status.edit_text(
                    f"📊 *Collecting {i}/{total_posts}*\n📄 {meta['title'][:60]}",
                    parse_mode=MD,
                )
            except (MessageNotModified, Exception):
                pass
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"Meta error post {i}: {e}")
            continue

    if all_thumbs:
        await status.edit_text("🖼 *Thumbnail collage bana raha hoon...*", parse_mode=MD)
        collage_path = make_collage(all_thumbs)
        if collage_path:
            total_vids = sum(len(m["videos"]) for m in all_meta)
            all_tags = list(dict.fromkeys(t for m in all_meta for t in m["tags"]))[:12]
            tag_str = " ".join(f"#{t.replace(' ', '_')}" for t in all_tags)
            collage_cap = (
                f"📦 *Bulk Upload — {total_posts} Posts*\n\n"
                f"🎬 Total Videos: {total_vids}\n"
                f"🏷 {tag_str}"
            )
            try:
                await safe_send_photo(client, dest, collage_path, collage_cap)
            except Exception as e:
                logger.error(f"Collage send error: {e}")
            finally:
                if os.path.exists(collage_path):
                    os.remove(collage_path)

    videos_sent = 0
    skipped = 0

    for post_idx, meta in enumerate(all_meta, 1):
        post_url = meta["url"]
        title = meta["title"]
        desc = meta["desc"]
        tags = meta["tags"]
        thumbnail = meta["thumbnail"]
        videos = meta["videos"]

        if not videos:
            skipped += 1
            continue

        caption = build_caption(title, desc, tags, len(videos), videos)

        thumb_path = download_thumb(thumbnail) if thumbnail else None
        if thumb_path:
            try:
                await safe_send_photo(client, dest, thumb_path, caption)
            except Exception:
                pass
            finally:
                if os.path.exists(thumb_path):
                    os.remove(thumb_path)

        for vid_idx, video_url in enumerate(videos, 1):
            try:
                await status.edit_text(
                    f"⬇️ *Post {post_idx}/{total_posts} · Vid {vid_idx}/{len(videos)}*\n"
                    f"📄 {title[:50]}\n\n"
                    f"✅ Bheje: {videos_sent} | ⏭ Skip: {skipped}",
                    parse_mode=MD,
                )
            except (MessageNotModified, Exception):
                pass

            tmp_path = await download_video(
                video_url, post_url, status,
                f"P{post_idx}/{total_posts} V{vid_idx}/{len(videos)}"
            )
            if not tmp_path:
                continue
            try:
                vid_cap = f"🎬 {vid_idx}/{len(videos)} — {title}" if len(videos) > 1 else title
                sent = await safe_send_video(client, dest, tmp_path, vid_cap, status)
                if sent:
                    videos_sent += 1
            except Exception as e:
                logger.error(f"Upload P{post_idx} V{vid_idx}: {e}")
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

        skipped_this = len(videos) == 0
        if not skipped_this:
            await asyncio.sleep(2)

    await status.edit_text(
        f"✅ *Sab ho gaya!*\n\n"
        f"📄 Posts: {total_posts}\n"
        f"🎬 Videos bheje: {videos_sent}\n"
        f"⏭ Skip: {skipped}\n"
        f"📡 Channel: `{dest}`",
        parse_mode=MD,
    )


@app.on_message(filters.command("video"))
async def video_cmd(client, message):
    url = extract_url_from_message(message)
    if not url:
        await message.reply_text("URL do: `/video https://desihub.to/post/xyz`", parse_mode=MD)
        return
    status = await message.reply_text("🎬 Video links dhundh raha hoon...")
    try:
        meta = extract_post_metadata(url)
        videos = meta["videos"]
        iframes = meta["iframes"]
        title = meta["title"]
        if videos:
            msg = f"✅ *{title}*\n\n🎬 Video Links ({len(videos)}):\n"
            for i, v in enumerate(videos[:15], 1):
                msg += f"\n{i}. `{v}`"
        elif iframes:
            msg = f"⚠️ Direct MP4 nahi mila.\n\n🖼 Player ({len(iframes)}):\n"
            for i, v in enumerate(iframes[:5], 1):
                msg += f"\n{i}. {v}"
        else:
            msg = f"❌ Koi video nahi mila.\nTitle: {title}"
        await status.edit_text(msg[:3900], parse_mode=MD, disable_web_page_preview=True)
    except Exception as e:
        await status.edit_text(f"❌ Error: {e}")


@app.on_message(filters.command("scrape"))
async def scrape_cmd(client, message):
    url = extract_url_from_message(message)
    if not url:
        await message.reply_text("URL do: `/scrape https://example.com`", parse_mode=MD)
        return
    status = await message.reply_text("⏳ Scraping...")
    try:
        title, desc, links = scrape_page_info(url)
        msg = f"🔗 {url}\n📄 {title}\n"
        if desc:
            msg += f"📝 {desc}\n"
        msg += f"\n🔗 Links ({len(links)}):\n" + "\n".join(links[:15])
        await status.edit_text(msg[:3900], disable_web_page_preview=True)
    except Exception as e:
        await status.edit_text(f"❌ Error: {e}")
