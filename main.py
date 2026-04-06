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
MAX_LOG_SIZE = 10 * 1024 * 1024


def _rotate_log():
    try:
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > MAX_LOG_SIZE:
            backup = LOG_FILE.with_suffix(".log.old")
            if backup.exists():
                backup.unlink()
            LOG_FILE.rename(backup)
            log.info("Log file rotated (was >%d MB)", MAX_LOG_SIZE // (1024 * 1024))
    except Exception as e:
        log.warning("Log rotation failed: %s", e)


def _clean_session_files():
    session_file = WORKDIR / "video_compressor_bot.session"
    journal = WORKDIR / "video_compressor_bot.session-journal"
    for f in [journal]:
        if f.exists():
            try:
                f.unlink()
                log.info("Cleaned stale session journal: %s", f.name)
            except Exception as e:
                log.warning("Could not clean %s: %s", f.name, e)


async def temp_cleanup_worker():
    log.info("Temp cleanup worker started (interval=%ds, max_age=%ds)", TEMP_CLEANUP_INTERVAL, TEMP_MAX_AGE)
    while True:
        try:
            await asyncio.sleep(TEMP_CLEANUP_INTERVAL)
            if not TEMP_DIR.exists():
                continue
            now = time.time()
            cleaned = 0
            total_freed = 0
            for item in TEMP_DIR.iterdir():
                if item.is_dir():
                    try:
                        age = now - item.stat().st_mtime
                        if age > TEMP_MAX_AGE:
                            dir_size = sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
                            shutil.rmtree(item, ignore_errors=True)
                            cleaned += 1
                            total_freed += dir_size
                    except Exception:
                        pass
            if cleaned > 0:
                log.info("Temp cleanup: removed %d old folders, freed %s", cleaned, human_size(total_freed))
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.warning("Temp cleanup error: %s", e)


async def main():
    _rotate_log()
    _clean_session_files()

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
    from handlers.video_handler import register_video_handlers, queue_worker, NUM_WORKERS

    register_user_handlers(app)
    register_admin_handlers(app)
    register_admin_callbacks(app)
    register_admin_input_handler(app)
    register_video_handlers(app)

    log.info("Starting Pyrogram client...")
    try:
        await app.start()
    except Exception as e:
        err_str = str(e).lower()
        if "database" in err_str or "locked" in err_str or "corrupt" in err_str:
            log.warning("Session file may be corrupted, removing and retrying...")
            session_file = WORKDIR / "video_compressor_bot.session"
            if session_file.exists():
                session_file.unlink()
            await app.start()
        else:
            raise

    me = await app.get_me()
    log.info("Bot ready: @%s (id=%d)", me.username, me.id)

    worker_tasks = [asyncio.create_task(queue_worker(app, i + 1)) for i in range(NUM_WORKERS)]
    cleanup_task = asyncio.create_task(temp_cleanup_worker())

    stats = await db.global_stats()
    print(
        f"\n{'━' * 50}\n"
        f"  🎬  {BOT_NAME} v1.0\n"
        f"  Bot      : @{me.username}\n"
        f"  Mode     : Pyrogram MTProto\n"
        f"  Workers  : {NUM_WORKERS}\n"
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
        for wt in worker_tasks:
            wt.cancel()
        cleanup_task.cancel()
        for wt in worker_tasks:
            try:
                await wt
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
