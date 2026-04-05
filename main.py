#!/usr/bin/env python3
"""
Video Compressor Bot — Entry Point
Pyrogram MTProto for large file support
"""

import asyncio
import logging
import shutil
import signal
import sys
import time
from pathlib import Path

from pyrogram import Client

from config import API_HASH, API_ID, BOT_TOKEN, LOG_FILE, TEMP_DIR, WORKDIR, BOT_NAME
from database import db
from utils.helpers import human_size

logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(LOG_FILE), encoding="utf-8"),
    ],
)
logging.getLogger("pyrogram").setLevel(logging.WARNING)
log = logging.getLogger("vbot")

TEMP_CLEANUP_INTERVAL = 3600
TEMP_MAX_AGE = 3600


async def temp_cleanup_worker():
    log.info("Temp cleanup worker started (interval=%ds, max_age=%ds)", TEMP_CLEANUP_INTERVAL, TEMP_MAX_AGE)
    while True:
        try:
            await asyncio.sleep(TEMP_CLEANUP_INTERVAL)
            if not TEMP_DIR.exists():
                continue
            now = time.time()
            cleaned = 0
            for item in TEMP_DIR.iterdir():
                if item.is_dir():
                    try:
                        age = now - item.stat().st_mtime
                        if age > TEMP_MAX_AGE:
                            shutil.rmtree(item, ignore_errors=True)
                            cleaned += 1
                    except Exception:
                        pass
            if cleaned > 0:
                log.info("Temp cleanup: removed %d old folders", cleaned)
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.warning("Temp cleanup error: %s", e)


async def main():
    TEMP_DIR.mkdir(parents=True, exist_ok=True)

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        log.critical("FFmpeg/FFprobe not found! Install FFmpeg first.")
        sys.exit(1)
    log.info("FFmpeg found: %s", shutil.which("ffmpeg"))

    log.info("Connecting to database...")
    await db.connect()
    log.info("Database connected")

    app = Client(
        "video_compressor_bot",
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=BOT_TOKEN,
        workdir=str(WORKDIR),
    )

    from handlers.user_handlers import register_user_handlers
    from handlers.admin_handlers import register_admin_handlers, register_admin_callbacks, register_admin_input_handler
    from handlers.video_handler import register_video_handlers, queue_worker

    register_user_handlers(app)
    register_admin_handlers(app)
    register_admin_callbacks(app)
    register_admin_input_handler(app)
    register_video_handlers(app)

    log.info("Starting Pyrogram client...")
    await app.start()
    me = await app.get_me()
    log.info("Bot ready: @%s (id=%d)", me.username, me.id)

    worker_task = asyncio.create_task(queue_worker(app))
    cleanup_task = asyncio.create_task(temp_cleanup_worker())

    stats = await db.global_stats()
    print(
        f"\n{'━' * 50}\n"
        f"  🎬  {BOT_NAME} v1.0\n"
        f"  Bot      : @{me.username}\n"
        f"  Mode     : Pyrogram MTProto\n"
        f"  Users    : {stats['users']:,}\n"
        f"  Compressed: {stats['compressions']:,}\n"
        f"  Saved    : {human_size(stats['total_saved'])}\n"
        f"{'━' * 50}\n",
        flush=True,
    )

    stop_event = asyncio.Event()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, lambda: stop_event.set())
        except NotImplementedError:
            signal.signal(sig, lambda s, f: stop_event.set())

    try:
        await stop_event.wait()
    finally:
        log.info("Shutting down...")
        worker_task.cancel()
        cleanup_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
        await app.stop()
        await db.close()
        log.info("Bot stopped gracefully.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot stopped.")
