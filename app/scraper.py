import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.google.com/",
}

VIDEO_RE = re.compile(
    r'https?://[^\s\'"<>]+\.(?:mp4|webm|mkv|avi|mov|flv|ts)(?:[?#][^\s\'"<>]*)?',
    re.IGNORECASE,
)


def extract_post_metadata(url: str) -> dict:
    """
    Full metadata extraction for a single post page.
    Returns: title, desc, tags, thumbnail, videos, iframes
    """
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    # Title
    title = ""
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        title = og_title["content"].strip()
    if not title and soup.title:
        title = soup.title.get_text(strip=True)
    title = title or "Untitled"

    # Description
    desc = ""
    og_desc = soup.find("meta", property="og:description")
    if og_desc and og_desc.get("content"):
        desc = og_desc["content"].strip()
    if not desc:
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            desc = meta_desc["content"].strip()

    # Tags from category links
    tags = []
    seen_tags = set()
    for a in soup.select("a[href*='/category/']"):
        t = a.get_text(strip=True).lower()
        if t and t not in seen_tags:
            tags.append(t)
            seen_tags.add(t)

    # Thumbnail
    thumbnail = ""
    og_img = soup.find("meta", property="og:image")
    if og_img and og_img.get("content"):
        thumbnail = og_img["content"].strip()

    # Videos
    found = []
    for tag in soup.find_all(["video", "source"]):
        for attr in ["src", "data-src", "data-url", "data-video", "data-mp4"]:
            val = tag.get(attr, "").strip()
            if val:
                found.append(val if val.startswith("http") else urljoin(url, val))

    for tag in soup.find_all(True):
        for attr in ["data-src", "data-video", "data-mp4", "data-stream", "data-hls", "data-file"]:
            val = tag.get(attr, "").strip()
            if val and val.startswith("http") and any(
                ext in val.lower() for ext in [".mp4", ".webm", ".m3u8", ".mkv"]
            ):
                found.append(val)

    for match in VIDEO_RE.findall(r.text):
        found.append(match)

    videos = list(dict.fromkeys(found))

    iframes = []
    if not videos:
        for iframe in soup.find_all("iframe"):
            src = iframe.get("src", "").strip()
            if src and "javascript" not in src.lower():
                iframes.append(urljoin(url, src))

    return {
        "title": title,
        "desc": desc,
        "tags": tags,
        "thumbnail": thumbnail,
        "videos": videos,
        "iframes": iframes,
    }


def extract_video_from_page(url: str):
    meta = extract_post_metadata(url)
    return meta["title"], meta["videos"], meta["iframes"]


def extract_post_links(url: str) -> list:
    r = requests.get(url, headers={**HEADERS, "Referer": url}, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"

    post_keywords = ["/post/", "/video/", "/videos/", "/p/", "/watch/", "/content/", "/media/"]
    seen = set()
    post_links = []
    all_internal = []

    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        if not href or href.startswith("#") or href.startswith("javascript"):
            continue
        full = href if href.startswith("http") else urljoin(base, href)
        if urlparse(full).netloc != urlparse(url).netloc:
            continue
        if full in seen:
            continue
        seen.add(full)
        if any(kw in full for kw in post_keywords):
            post_links.append(full)
        else:
            all_internal.append(full)

    return post_links if post_links else all_internal


def scrape_page_info(url: str):
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

    return title, desc, links
