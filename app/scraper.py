import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

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


def extract_video_from_page(url: str):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    title = soup.title.get_text(strip=True) if soup.title else "Video"

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

    seen = list(dict.fromkeys(found))

    iframes = []
    if not seen:
        for iframe in soup.find_all("iframe"):
            src = iframe.get("src", "").strip()
            if src and "javascript" not in src.lower():
                iframes.append(urljoin(url, src))

    return title, seen, iframes


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
