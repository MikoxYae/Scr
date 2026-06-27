import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.utils.logger import logger


def _now():
    return datetime.now(timezone.utc)


class MongoDB:
    def __init__(self):
        self._client = None
        self._db = None
        self._connected = False

    async def connect(self) -> None:
        uri = os.getenv("MONGO_URI", "")
        if not uri:
            logger.info("MONGO_URI not set — MongoDB disabled, bot running without it")
            return
        try:
            import motor.motor_asyncio as motor_asyncio
        except ImportError:
            logger.warning("motor not installed — MongoDB disabled")
            return
        try:
            db_name = os.getenv("DB_NAME", "telegram_scraper_bot")
            self._client = motor_asyncio.AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000)
            self._db = self._client[db_name]
            await self._client.admin.command("ping")
            await self._db["processed_posts"].create_index(
                [("post_id", 1), ("target_channel", 1)], unique=True
            )
            await self._db["channel_settings"].create_index("user_id", unique=True)
            await self._db["jobs"].create_index("job_id", unique=True)
            self._connected = True
            logger.info(f"MongoDB connected — db: {db_name}")
        except Exception as e:
            logger.error(f"MongoDB connect failed: {e} — bot running without MongoDB")
            self._connected = False

    async def disconnect(self) -> None:
        if self._client:
            try:
                self._client.close()
                logger.info("MongoDB disconnected")
            except Exception:
                pass
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    # ── channel_settings ──────────────────────────────────────────────────────

    async def save_channel(self, user_id: int, target_channel) -> None:
        if not self._connected:
            return
        try:
            await self._db["channel_settings"].update_one(
                {"user_id": user_id},
                {"$set": {"user_id": user_id, "target_channel": str(target_channel), "updated_at": _now()}},
                upsert=True,
            )
        except Exception as e:
            logger.error(f"save_channel error: {e}")

    async def get_channel(self, user_id: int) -> Optional[str]:
        if not self._connected:
            return None
        try:
            doc = await self._db["channel_settings"].find_one({"user_id": user_id})
            if doc:
                val = doc["target_channel"]
                try:
                    return int(val)
                except (ValueError, TypeError):
                    return val
            return None
        except Exception as e:
            logger.error(f"get_channel error: {e}")
            return None

    # ── jobs ──────────────────────────────────────────────────────────────────

    async def create_job(self, command: str, source_url: str, target_channel, total_found: int = 0) -> str:
        job_id = str(uuid.uuid4())
        if not self._connected:
            return job_id
        try:
            now = _now()
            await self._db["jobs"].insert_one({
                "job_id": job_id,
                "command": command,
                "source_url": source_url,
                "target_channel": str(target_channel),
                "status": "running",
                "total_found": total_found,
                "processed_count": 0,
                "sent_count": 0,
                "failed_count": 0,
                "skipped_count": 0,
                "started_at": now,
                "updated_at": now,
                "completed_at": None,
                "error_message": None,
            })
            await self.increment_stats(jobs=1)
        except Exception as e:
            logger.error(f"create_job error: {e}")
        return job_id

    async def update_job(self, job_id: str, **fields) -> None:
        if not self._connected or not job_id:
            return
        try:
            fields["updated_at"] = _now()
            await self._db["jobs"].update_one({"job_id": job_id}, {"$set": fields})
        except Exception as e:
            logger.error(f"update_job error: {e}")

    async def finish_job(self, job_id: str, status: str = "completed", error_message: Optional[str] = None) -> None:
        if not self._connected or not job_id:
            return
        try:
            now = _now()
            update = {"status": status, "updated_at": now, "completed_at": now}
            if error_message:
                update["error_message"] = error_message
            await self._db["jobs"].update_one({"job_id": job_id}, {"$set": update})
        except Exception as e:
            logger.error(f"finish_job error: {e}")

    async def mark_stopped(self, job_id: str) -> None:
        await self.finish_job(job_id, status="stopped")

    async def get_last_job(self) -> Optional[dict]:
        if not self._connected:
            return None
        try:
            cursor = self._db["jobs"].find().sort("started_at", -1).limit(1)
            docs = await cursor.to_list(length=1)
            return docs[0] if docs else None
        except Exception as e:
            logger.error(f"get_last_job error: {e}")
            return None

    async def get_current_job(self) -> Optional[dict]:
        if not self._connected:
            return None
        try:
            return await self._db["jobs"].find_one({"status": "running"})
        except Exception as e:
            logger.error(f"get_current_job error: {e}")
            return None

    # ── processed_posts ───────────────────────────────────────────────────────

    async def is_post_processed(self, post_id_or_url: str, target_channel: str) -> bool:
        if not self._connected:
            return False
        try:
            doc = await self._db["processed_posts"].find_one(
                {"post_id": post_id_or_url, "target_channel": target_channel},
                {"_id": 1},
            )
            return doc is not None
        except Exception as e:
            logger.error(f"is_post_processed error: {e}")
            return False

    async def save_processed_post(
        self,
        post_id_or_url: str,
        source_url: str,
        target_channel: str,
        media_type: str,
        status: str,
        telegram_message_id: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> None:
        if not self._connected:
            return
        try:
            doc = {
                "post_id": post_id_or_url,
                "source_url": source_url,
                "target_channel": target_channel,
                "media_type": media_type,
                "status": status,
                "created_at": _now(),
            }
            if telegram_message_id is not None:
                doc["telegram_message_id"] = telegram_message_id
            if error_message:
                doc["error_message"] = error_message
            await self._db["processed_posts"].update_one(
                {"post_id": post_id_or_url, "target_channel": target_channel},
                {"$set": doc},
                upsert=True,
            )
        except Exception as e:
            logger.error(f"save_processed_post error: {e}")

    # ── bot_stats ─────────────────────────────────────────────────────────────

    async def increment_stats(
        self,
        scraped: int = 0,
        sent: int = 0,
        failed: int = 0,
        skipped: int = 0,
        jobs: int = 0,
    ) -> None:
        if not self._connected:
            return
        try:
            inc = {}
            if scraped:
                inc["total_scraped"] = scraped
            if sent:
                inc["total_sent"] = sent
            if failed:
                inc["total_failed"] = failed
            if skipped:
                inc["total_skipped"] = skipped
            if jobs:
                inc["total_jobs"] = jobs
            update: dict = {"$set": {"updated_at": _now(), "last_run_at": _now()}}
            if inc:
                update["$inc"] = inc
            await self._db["bot_stats"].update_one({"_id": "global"}, update, upsert=True)
        except Exception as e:
            logger.error(f"increment_stats error: {e}")

    async def get_stats(self) -> dict:
        if not self._connected:
            return {}
        try:
            doc = await self._db["bot_stats"].find_one({"_id": "global"})
            if not doc:
                return {}
            return {
                "total_scraped": doc.get("total_scraped", 0),
                "total_sent": doc.get("total_sent", 0),
                "total_failed": doc.get("total_failed", 0),
                "total_skipped": doc.get("total_skipped", 0),
                "total_jobs": doc.get("total_jobs", 0),
                "last_run_at": doc.get("last_run_at"),
                "updated_at": doc.get("updated_at"),
            }
        except Exception as e:
            logger.error(f"get_stats error: {e}")
            return {}


mongo = MongoDB()
