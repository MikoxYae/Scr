import os
import asyncio
from dotenv import load_dotenv
from pyrogram import Client, idle

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "8603042415:AAGjOKwH8uDaLG5AWjP-CTh0hQ6qHGTJ_2Y")
API_ID    = int(os.getenv("API_ID",  "32947515"))
API_HASH  = os.getenv("API_HASH",    "cc73af06049861e86e404ddd1fc6da35")

app = Client("scraper_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)


async def _async_run():
    from app import handlers  # noqa: F401 — registers all handlers
    from app.utils.logger import logger
    from app.db import mongo

    await mongo.connect()
    if mongo.is_connected():
        logger.info("MongoDB: connected")
    else:
        logger.info("MongoDB: disabled (bot running normally without it)")

    logger.info("Bot chal raha hai... Ctrl+C se band karo")
    async with app:
        await idle()

    await mongo.disconnect()


def run():
    asyncio.run(_async_run())
