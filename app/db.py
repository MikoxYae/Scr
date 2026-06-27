import os
from datetime import datetime, timezone
from pymongo import MongoClient
from app.utils.logger import logger

_client = None
_col = None


def _get_col():
    global _client, _col
    if _col is None:
        uri = os.getenv("MONGO_URI", "")
        if not uri:
            raise RuntimeError("MONGO_URI not set")
        _client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        db = _client["scraper_bot"]
        _col = db["processed_posts"]
        _col.create_index("url", unique=True)
        logger.info("MongoDB connected")
    return _col


def is_processed(url: str) -> bool:
    try:
        return _get_col().find_one({"url": url}, {"_id": 1}) is not None
    except Exception as e:
        logger.error(f"DB is_processed error: {e}")
        return False


def mark_processed(url: str, title: str = "", video_count: int = 0):
    try:
        _get_col().update_one(
            {"url": url},
            {"$set": {
                "url": url,
                "title": title,
                "video_count": video_count,
                "processed_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )
    except Exception as e:
        logger.error(f"DB mark_processed error: {e}")


def get_stats() -> dict:
    try:
        col = _get_col()
        total = col.count_documents({})
        return {"total": total}
    except Exception as e:
        logger.error(f"DB stats error: {e}")
        return {"total": 0}
