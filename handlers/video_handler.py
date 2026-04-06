import asyncio
import logging
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Optional

from pyrogram import Client, filters
from pyrogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup as IKM,
    InlineKeyboardButton as IKB,
)

from config import (
    BOT_FOOTER, COOLDOWN_SECONDS, FORCE_SUB_CHANNEL,
    MAX_FILE_SIZE, MAX_QUEUE_PER_USER, QUALITY_PRESETS,
    RESOLUTION_OPTIONS, TEMP_DIR, PROGRESS_EDIT_INTERVAL,
)
from database import db
from utils.helpers import (
    Cooldown, ThrottledEditor, human_duration, human_size,
    human_speed, human_eta, progress_bar, safe_edit,
)
from utils.compressor import compress_video, extract_thumbnail, get_video_info

log = logging.getLogger("vbot.video")

cooldown = Cooldown(COOLDOWN_SECONDS)
cancel_events: dict[int, asyncio.Event] = {}
pending_tasks: dict[int, dict] = {}
active_tasks: dict[int, dict] = {}
task_queue: asyncio.Queue = asyncio.Queue()

H = "━━━━━━━━━━━━━━━━━━━━━━━━"

PENDING_EXPIRE = 10 * 60
NUM_WORKERS = 2
STALL_TIMEOUT = 5 * 60
WATCHDOG_CHECK = 30


def _safe_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)
    name = name.strip('. ')
    if not name:
        name = "video"
    if len(name) > 200:
        ext = name.rsplit('.', 1)[-1] if '.' in name else ''
        name = name[:190] + ('.' + ext if ext else '')
    return name


def _is_video(message: Message) -> bool:
    if message.video:
        return True
    if message.document:
        mime = message.document.mime_type or ""
        name = (message.document.file_name or "").lower()
        if mime.startswith("video/") or any(name.endswith(ext) for ext in (".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv", ".m4v")):
            return True
    if message.animation:
        return True
    return False


def _get_file_info(message: Message) -> Optional[tuple]:
    if message.video:
        v = message.video
        return (v.file_id, v.file_name or f"video_{v.file_unique_id[:8]}.mp4", v.file_size or 0, v.file_unique_id or "",
                v.duration or 0, v.width or 0, v.height or 0)
    if message.document:
        d = message.document
        return (d.file_id, d.file_name or f"doc_{d.file_unique_id[:8]}", d.file_size or 0, d.file_unique_id or "",
                0, 0, 0)
    if message.animation:
        a = message.animation
        return (a.file_id, a.file_name or f"anim_{a.file_unique_id[:8]}.mp4", a.file_size or 0, a.file_unique_id or "",
                a.duration or 0, a.width or 0, a.height or 0)
    return None


def _queue_position() -> int:
    return task_queue.qsize() + len(active_tasks)


def _cleanup_stale_pending():
    now = time.time()
    expired = [uid for uid, t in pending_tasks.items() if now - t.get("created_at", now) > PENDING_EXPIRE]
    for uid in expired:
        pending_tasks.pop(uid, None)
        log.info("Cleaned up stale pending task for uid=%s", uid)


async def _get_force_channel() -> Optional[str]:
    ch = await db.get_setting("force_channel", "")
    return ch.strip() or FORCE_SUB_CHANNEL


async def _get_cooldown() -> int:
    val = await db.get_setting("cooldown", "")
    if val.isdigit():
        return int(val)
    return COOLDOWN_SECONDS


async def _get_daily_limit() -> int:
    val = await db.get_setting("daily_limit", "0")
    return int(val) if val.isdigit() else 0


async def _get_max_size() -> int:
    val = await db.get_setting("max_size_mb", "")
    if val.isdigit():
        return int(val) * 1024 * 1024
    return MAX_FILE_SIZE


async def check_force_sub(client: Client, uid: int) -> bool:
    channel = await _get_force_channel()
    if not channel:
        return True
    try:
        member = await client.get_chat_member(channel, uid)
        if member and member.status.value in ("member", "administrator", "creator"):
            return True
    except Exception:
        pass
    return False


async def _stall_watchdog(cancel_ev: asyncio.Event, last_progress: dict, uid: int, label: str):
    while not cancel_ev.is_set():
        await asyncio.sleep(WATCHDOG_CHECK)
        if cancel_ev.is_set():
            return
        stall_time = time.time() - last_progress["time"]
        if stall_time > STALL_TIMEOUT:
            log.warning("%s stalled for uid=%s (no progress for %.0fs)", label, uid, stall_time)
            cancel_ev.set()
            return


async def queue_worker(client: Client, worker_id: int = 1):
    log.info("Queue worker #%d started", worker_id)
    while True:
        try:
            task = await task_queue.get()
            uid = task["uid"]
            if uid in pending_tasks:
                del pending_tasks[uid]
            active_tasks[uid] = task
            try:
                await process_compression(client, task)
            except Exception as e:
                log.exception("Worker #%d task error for uid=%s: %s", worker_id, uid, e)
            finally:
                active_tasks.pop(uid, None)
                cancel_events.pop(uid, None)
                task_queue.task_done()
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.exception("Worker #%d unexpected error: %s", worker_id, e)
            await asyncio.sleep(1)


async def process_compression(client: Client, task: dict):
    uid = task["uid"]
    chat_id = task["chat_id"]
    file_id = task["file_id"]
    file_name = task["file_name"]
    file_size = task["file_size"]
    quality_key = task["quality"]
    resolution_key = task["resolution"]
    msg_id = task["status_msg_id"]
    task_start = time.time()

    safe_file_name = _safe_filename(file_name)

    quality = QUALITY_PRESETS[quality_key]
    resolution = RESOLUTION_OPTIONS[resolution_key]

    cancel_ev = asyncio.Event()
    last_progress = {"time": time.time(), "bytes": 0}
    cancel_events[uid] = cancel_ev

    cancel_kb = IKM([[IKB("🛑 Cancel", callback_data=f"cancel_{uid}")]])

    editor = ThrottledEditor(client, chat_id, msg_id, interval=PROGRESS_EDIT_INTERVAL)

    dest_dir = TEMP_DIR / str(uuid.uuid4())
    dest_dir.mkdir(parents=True, exist_ok=True)
    input_file = dest_dir / safe_file_name
    safe_stem = safe_file_name.rsplit(".", 1)[0] if "." in safe_file_name else safe_file_name
    output_file = dest_dir / f"{safe_stem}_compressed.mp4"
    thumb_file = dest_dir / "thumb.jpg"

    watchdog_task = None

    try:
        await editor(
            f"📥 <b>Downloading Video...</b>\n"
            f"<code>[{progress_bar(0)}] 0%</code>\n\n"
            f"🎞 <b>File:</b> <code>{file_name[:50]}</code>\n"
            f"📦 <b>Size:</b> {human_size(file_size)}\n"
            f"⏳ <b>Status:</b> Starting download...",
            force=True, reply_markup=cancel_kb,
        )

        start_dl = time.time()

        async def dl_progress(current: int, total: int):
            if cancel_ev.is_set():
                raise asyncio.CancelledError()
            if current > last_progress["bytes"]:
                last_progress["bytes"] = current
                last_progress["time"] = time.time()
            try:
                real_total = total if total > 0 else file_size
                pct = current / real_total * 100 if real_total > 0 else 0
                pct = min(pct, 99.9)
                elapsed = time.time() - start_dl
                speed = current / elapsed if elapsed > 0 else 0
                eta = (real_total - current) / speed if speed > 0 else None
                bar = progress_bar(pct)
                await editor(
                    f"📥 <b>Downloading Video...</b>\n"
                    f"<code>[{bar}] {pct:.1f}%</code>\n\n"
                    f"🎞 <b>File:</b> <code>{file_name[:50]}</code>\n"
                    f"📦 <b>Size:</b> {human_size(current)} / {human_size(real_total)}\n"
                    f"🚀 <b>Speed:</b> {human_speed(speed)}\n"
                    f"⏳ <b>ETA:</b> {human_eta(eta)}\n"
                    f"🔄 <b>Status:</b> Downloading from Telegram",
                    reply_markup=cancel_kb,
                )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.debug("dl_progress error: %s", e)

        last_progress["time"] = time.time()
        last_progress["bytes"] = 0
        watchdog_task = asyncio.create_task(_stall_watchdog(cancel_ev, last_progress, uid, "Download"))

        await client.download_media(
            file_id,
            file_name=str(input_file),
            progress=dl_progress,
        )

        watchdog_task.cancel()
        try:
            await watchdog_task
        except asyncio.CancelledError:
            pass
        watchdog_task = None

        if cancel_ev.is_set():
            raise asyncio.CancelledError()

        if not input_file.exists():
            await editor("❌ <b>Error:</b> Downloaded file not found.", force=True)
            return

        actual_size = input_file.stat().st_size

        await editor(
            f"📥 <b>Download Complete!</b>\n"
            f"<code>[{progress_bar(100)}] 100%</code>\n\n"
            f"🎞 <b>File:</b> <code>{file_name[:50]}</code>\n"
            f"📦 <b>Size:</b> {human_size(actual_size)}\n"
            f"✅ <b>Status:</b> Download complete!",
            force=True, reply_markup=cancel_kb,
        )
        await asyncio.sleep(0.5)

        video_info = await get_video_info(input_file)
        vid_dur = human_duration(video_info.get("duration", 0))
        vid_res = f"{video_info.get('width', '?')}x{video_info.get('height', '?')}"

        await editor(
            f"⚙️ <b>Compressing Video...</b>\n"
            f"<code>[{progress_bar(0)}] 0%</code>\n\n"
            f"🎞 <b>File:</b> <code>{file_name[:50]}</code>\n"
            f"🎛 <b>Mode:</b> {quality['label']} / {resolution_key}\n"
            f"🎥 <b>Video:</b> {vid_res} • {vid_dur}\n"
            f"⏳ <b>ETA:</b> Calculating...\n"
            f"🔄 <b>Status:</b> Compressing with FFmpeg",
            force=True, reply_markup=cancel_kb,
        )

        compress_start = time.time()

        async def compress_progress(pct: float, duration: float):
            last_progress["time"] = time.time()
            elapsed = time.time() - compress_start
            eta_val = (elapsed / pct * (100 - pct)) if pct > 0 else None
            bar = progress_bar(pct)
            await editor(
                f"⚙️ <b>Compressing Video...</b>\n"
                f"<code>[{bar}] {pct:.1f}%</code>\n\n"
                f"🎞 <b>File:</b> <code>{file_name[:50]}</code>\n"
                f"🎛 <b>Mode:</b> {quality['label']} / {resolution_key}\n"
                f"⏱ <b>Elapsed:</b> {human_duration(elapsed)}\n"
                f"⏳ <b>ETA:</b> {human_eta(eta_val)}\n"
                f"🔄 <b>Status:</b> Compressing with FFmpeg",
                reply_markup=cancel_kb,
            )

        last_progress["time"] = time.time()
        watchdog_task = asyncio.create_task(_stall_watchdog(cancel_ev, last_progress, uid, "Compress"))

        success = await compress_video(
            input_path=input_file,
            output_path=output_file,
            crf=quality["crf"],
            preset=quality["preset"],
            resolution=resolution,
            cancel_event=cancel_ev,
            progress_callback=compress_progress,
        )

        watchdog_task.cancel()
        try:
            await watchdog_task
        except asyncio.CancelledError:
            pass
        watchdog_task = None

        if cancel_ev.is_set():
            raise asyncio.CancelledError()

        if not success or not output_file.exists():
            await editor(
                f"❌ <b>Compression Failed</b>\n"
                f"{H}\n\n"
                f"FFmpeg could not compress this video.\n"
                f"The format may not be supported.\n\n"
                f"{H}\n"
                f"{BOT_FOOTER}",
                force=True,
            )
            return

        compressed_size = output_file.stat().st_size
        saved_size = max(actual_size - compressed_size, 0)
        saved_pct = (saved_size / actual_size * 100) if actual_size > 0 else 0

        await editor(
            f"⚙️ <b>Compression Complete!</b>\n"
            f"<code>[{progress_bar(100)}] 100%</code>\n\n"
            f"📦 <b>Original:</b> {human_size(actual_size)}\n"
            f"📉 <b>Compressed:</b> {human_size(compressed_size)}\n"
            f"💾 <b>Saved:</b> {human_size(saved_size)} ({saved_pct:.0f}%)\n"
            f"✅ <b>Status:</b> Compression complete!",
            force=True, reply_markup=cancel_kb,
        )
        await asyncio.sleep(0.5)

        has_thumb = await extract_thumbnail(output_file, thumb_file)

        await editor(
            f"📤 <b>Uploading Compressed Video...</b>\n"
            f"<code>[{progress_bar(0)}] 0%</code>\n\n"
            f"🎞 <b>File:</b> <code>{file_name[:50]}</code>\n"
            f"📉 <b>New Size:</b> {human_size(compressed_size)}\n"
            f"🌐 <b>Status:</b> Starting upload...",
            force=True, reply_markup=cancel_kb,
        )

        start_up = time.time()

        async def up_progress(current: int, total: int):
            if cancel_ev.is_set():
                raise asyncio.CancelledError()
            if current > last_progress["bytes"]:
                last_progress["bytes"] = current
                last_progress["time"] = time.time()
            try:
                pct = current / total * 100 if total else 0
                elapsed = time.time() - start_up
                speed = current / elapsed if elapsed > 0 else 0
                eta = (total - current) / speed if speed > 0 else None
                bar = progress_bar(pct)
                await editor(
                    f"📤 <b>Uploading Compressed Video...</b>\n"
                    f"<code>[{bar}] {pct:.1f}%</code>\n\n"
                    f"🎞 <b>File:</b> <code>{file_name[:50]}</code>\n"
                    f"📉 <b>Size:</b> {human_size(current)} / {human_size(total)}\n"
                    f"🚀 <b>Speed:</b> {human_speed(speed)}\n"
                    f"⏳ <b>ETA:</b> {human_eta(eta)}\n"
                    f"🌐 <b>Status:</b> Uploading to Telegram",
                    reply_markup=cancel_kb,
                )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.debug("up_progress error: %s", e)

        duration_int = int(video_info.get("duration", 0))
        width = video_info.get("width", 0)
        height = video_info.get("height", 0)

        if resolution and height > 0 and width > 0:
            ratio = resolution / height
            width = int(width * ratio)
            height = resolution

        elapsed_total = time.time() - task_start

        caption = (
            f"✅ <b>Compression Complete!</b>\n"
            f"{H}\n\n"
            f"🎞 <b>File:</b> <code>{file_name[:55]}</code>\n"
            f"📦 <b>Original:</b> <code>{human_size(actual_size)}</code>\n"
            f"📉 <b>Compressed:</b> <code>{human_size(compressed_size)}</code>\n"
            f"💾 <b>Saved:</b> <code>{human_size(saved_size)} ({saved_pct:.0f}%)</code>\n"
            f"⏱ <b>Time:</b> <code>{human_duration(elapsed_total)}</code>\n"
            f"🎛 <b>Quality:</b> <code>{quality['label']}</code>\n"
            f"📐 <b>Resolution:</b> <code>{resolution_key}</code>\n\n"
            f"{H}\n"
            f"{BOT_FOOTER}"
        )

        last_progress["time"] = time.time()
        last_progress["bytes"] = 0
        watchdog_task = asyncio.create_task(_stall_watchdog(cancel_ev, last_progress, uid, "Upload"))

        await client.send_video(
            chat_id=chat_id,
            video=str(output_file),
            caption=caption,
            duration=duration_int,
            width=width if width > 0 else None,
            height=height if height > 0 else None,
            thumb=str(thumb_file) if has_thumb else None,
            progress=up_progress,
            reply_to_message_id=task.get("original_msg_id"),
            supports_streaming=True,
        )

        watchdog_task.cancel()
        try:
            await watchdog_task
        except asyncio.CancelledError:
            pass
        watchdog_task = None

        elapsed_total = time.time() - task_start

        try:
            await client.delete_messages(chat_id, msg_id)
        except Exception:
            pass

        await db.record_compression(
            uid, file_name, actual_size, compressed_size,
            saved_size, elapsed_total, quality_key, resolution_key,
        )
        log.info(
            "SUCCESS: %s | %s → %s (saved %s) [%s]",
            file_name, human_size(actual_size), human_size(compressed_size),
            human_size(saved_size), human_duration(elapsed_total),
        )

        try:
            log_ch = await db.get_setting("log_channel", "")
            if log_ch:
                log_chat_id = int(log_ch) if log_ch.lstrip("-").isdigit() else log_ch
                user_name = task.get("user_name") or ""
                display_name = user_name if user_name else str(uid)
                mention = f"<a href='tg://user?id={uid}'>{display_name}</a>"
                log_caption = (
                    f"👤 <b>User:</b> {mention}\n"
                    f"🆔 <b>ID:</b> <code>{uid}</code>\n"
                    f"🎞 <b>File:</b> {file_name[:50]}\n"
                    f"📦 <b>Size:</b> {human_size(actual_size)}\n"
                    f"🎛 <b>Quality:</b> {quality['label']} • {resolution_key}\n"
                    f"📉 <b>Result:</b> {human_size(compressed_size)} ({saved_pct:.0f}% saved)"
                )
                await client.send_video(
                    chat_id=log_chat_id,
                    video=file_id,
                    caption=log_caption,
                    thumb=str(thumb_file) if has_thumb else None,
                    supports_streaming=True,
                )
        except Exception as e:
            log.warning("Failed to send log to channel: %s", e)

    except asyncio.CancelledError:
        stalled = time.time() - last_progress["time"] > STALL_TIMEOUT
        if stalled:
            await editor(
                f"⏰ <b>Task Stalled</b>\n"
                f"{H}\n\n"
                f"No progress for {STALL_TIMEOUT // 60} minutes.\n"
                f"Task auto-cancelled. Please try again.\n\n"
                f"{H}\n"
                f"{BOT_FOOTER}",
                force=True,
            )
            log.info("Task auto-cancelled (stall) for uid=%s", uid)
        else:
            elapsed = time.time() - task_start
            await editor(
                f"🛑 <b>Task Cancelled</b>\n"
                f"{H}\n\n"
                f"You cancelled this compression.\n"
                f"⏱ <b>Time Spent:</b> <code>{human_duration(elapsed)}</code>\n\n"
                f"📤 Send another video whenever you're ready!\n\n"
                f"{H}\n"
                f"{BOT_FOOTER}",
                force=True,
            )
            log.info("Task cancelled by user %s", uid)
    except Exception as e:
        log.exception("Compression task error for uid=%s", uid)
        await editor(
            f"❌ <b>Error Occurred</b>\n"
            f"{H}\n\n"
            f"<code>{str(e)[:300]}</code>\n\n"
            f"Please try again later.\n\n"
            f"{H}\n"
            f"{BOT_FOOTER}",
            force=True,
        )
    finally:
        if watchdog_task and not watchdog_task.done():
            watchdog_task.cancel()
            try:
                await watchdog_task
            except asyncio.CancelledError:
                pass
        cancel_events.pop(uid, None)
        shutil.rmtree(dest_dir, ignore_errors=True)


async def handle_quality_selection(client: Client, callback: CallbackQuery):
    uid = callback.from_user.id
    quality_key = callback.data.replace("quality_", "")
    if quality_key not in QUALITY_PRESETS:
        return

    if uid not in pending_tasks:
        await safe_edit(callback.message, "❌ Session expired. Please send the video again.")
        return

    pending_tasks[uid]["quality"] = quality_key

    kb = IKM([
        [IKB("📺 1080p (Full HD)", callback_data="res_1080p"), IKB("📺 720p (HD)", callback_data="res_720p")],
        [IKB("📺 480p (SD)", callback_data="res_480p"), IKB("📺 360p (Low)", callback_data="res_360p")],
        [IKB("📐 Keep Original", callback_data="res_original")],
    ])
    t = pending_tasks[uid]
    res_info = ""
    if t.get("vid_width") and t.get("vid_height"):
        res_info = f"\n🎥 <b>Current:</b> {t['vid_width']}x{t['vid_height']}"

    await safe_edit(
        callback.message,
        f"📐 <b>Select Resolution</b>\n"
        f"{H}\n\n"
        f"🎞 <b>File:</b> <code>{t['file_name'][:40]}</code>\n"
        f"🎛 <b>Quality:</b> {QUALITY_PRESETS[quality_key]['label']}"
        f"{res_info}\n\n"
        f"Choose output resolution:",
        reply_markup=kb,
    )


async def handle_resolution_selection(client: Client, callback: CallbackQuery):
    uid = callback.from_user.id
    resolution_key = callback.data.replace("res_", "")
    if resolution_key not in RESOLUTION_OPTIONS:
        return

    if uid not in pending_tasks:
        await safe_edit(callback.message, "❌ Session expired. Please send the video again.")
        return

    task_data = pending_tasks[uid]
    task_data["resolution"] = resolution_key

    quality = QUALITY_PRESETS[task_data["quality"]]
    pos = _queue_position() + 1

    cancel_kb = IKM([[IKB("🛑 Cancel", callback_data=f"cancel_{uid}")]])
    await safe_edit(
        callback.message,
        f"⏳ <b>Task Queued</b>  •  Position: <b>#{pos}</b>\n"
        f"{H}\n\n"
        f"🎞 <b>File:</b> <code>{task_data['file_name'][:40]}</code>\n"
        f"📦 <b>Size:</b> {human_size(task_data['file_size'])}\n"
        f"🎛 <b>Quality:</b> {quality['label']}\n"
        f"📐 <b>Resolution:</b> {resolution_key}\n\n"
        f"🔄 Waiting to start...",
        reply_markup=cancel_kb,
    )

    task_data["status_msg_id"] = callback.message.id
    pending_tasks.pop(uid, None)
    await task_queue.put(task_data)


def register_video_handlers(app: Client):

    @app.on_message(filters.command("cancel") & filters.private)
    async def cmd_cancel(client: Client, message: Message):
        uid = message.from_user.id
        ev = cancel_events.get(uid)
        if ev and not ev.is_set():
            ev.set()
            await message.reply("🛑 <b>Cancelling current task...</b>")
        elif uid in pending_tasks:
            del pending_tasks[uid]
            await message.reply("🛑 <b>Pending task removed.</b>")
        else:
            await message.reply("ℹ️ No active task to cancel.")

    @app.on_message((filters.video | filters.document | filters.animation) & filters.private)
    async def on_video(client: Client, message: Message):
        if not _is_video(message):
            return

        uid = message.from_user.id
        user = message.from_user
        chat_id = message.chat.id

        await db.add_user(uid, user.username or "", user.first_name or "")

        if await db.is_banned(uid):
            await message.reply("🚫 You are banned from using this bot.")
            return

        if not await check_force_sub(client, uid):
            channel = await _get_force_channel()
            ch_name = channel.lstrip("@") if channel else ""
            kb = IKM([[IKB("📢 Join Channel", url=f"https://t.me/{ch_name}")]])
            await message.reply("⚠️ Please join our channel first to use this bot.", reply_markup=kb)
            return

        cd_seconds = await _get_cooldown()
        cooldown.seconds = cd_seconds
        wait = cooldown.check(uid)
        if wait is not None:
            await message.reply(f"⏳ Please wait <b>{wait:.0f}s</b> before next task.")
            return

        daily_limit = await _get_daily_limit()
        if daily_limit > 0:
            daily_count = await db.get_daily_count(uid)
            if daily_count >= daily_limit:
                await message.reply(
                    f"🚫 <b>Daily limit reached!</b>\n\n"
                    f"You've used <b>{daily_count}/{daily_limit}</b> compressions today.\n"
                    f"Please try again tomorrow."
                )
                return

        _cleanup_stale_pending()

        from config import ADMIN_IDS
        is_admin = uid in ADMIN_IDS
        if not is_admin:
            queued_count = sum(1 for t in task_queue._queue if t.get("uid") == uid)
            total_tasks = (1 if uid in active_tasks else 0) + queued_count
            if total_tasks >= MAX_QUEUE_PER_USER:
                await message.reply(
                    f"⚠️ <b>Queue Full!</b>\n\n"
                    f"📋 You have <b>{total_tasks}</b> task(s) running/queued.\n"
                    f"📏 Maximum allowed: <b>{MAX_QUEUE_PER_USER}</b>\n\n"
                    f"⏳ Please wait for a task to finish or /cancel first."
                )
                return

        if uid in pending_tasks:
            await message.reply("⚠️ Please select quality/resolution for your previous video first, then send a new one.")
            return

        file_info = _get_file_info(message)
        if not file_info:
            return

        fid, fname, fsize, fhash, fdur, fwidth, fheight = file_info

        max_size = await _get_max_size()
        if fsize > max_size:
            await message.reply(
                f"❌ <b>File too large!</b>\n\n"
                f"📦 <b>Your file:</b> {human_size(fsize)}\n"
                f"📏 <b>Max size:</b> {human_size(max_size)}"
            )
            return

        pending_tasks[uid] = {
            "uid": uid,
            "chat_id": chat_id,
            "file_id": fid,
            "file_name": fname,
            "file_size": fsize,
            "file_hash": fhash,
            "original_msg_id": message.id,
            "quality": None,
            "resolution": None,
            "vid_duration": fdur,
            "vid_width": fwidth,
            "vid_height": fheight,
            "user_name": user.first_name or user.username or "",
            "created_at": time.time(),
        }

        dur_text = ""
        if fdur > 0:
            dur_text = f"\n🎥 <b>Duration:</b> {human_duration(fdur)}  •  <b>Res:</b> {fwidth}x{fheight}"

        kb = IKM([
            [IKB("🟢 Low (Fast)", callback_data="quality_low")],
            [IKB("🟡 Medium (Balanced)", callback_data="quality_medium")],
            [IKB("🔴 High (Best Quality)", callback_data="quality_high")],
        ])

        await message.reply(
            f"🎬 <b>Video Received!</b>\n"
            f"{H}\n\n"
            f"🎞 <b>File:</b> <code>{fname[:50]}</code>\n"
            f"📦 <b>Size:</b> {human_size(fsize)}"
            f"{dur_text}\n\n"
            f"🎛 <b>Select Compression Quality:</b>",
            reply_markup=kb,
        )

    @app.on_message(filters.private & filters.text & ~filters.command(["start", "help", "info", "profile", "statsme", "history", "cancel", "stats", "users", "broadcast", "ban", "unban", "banned", "logs", "settings", "setdaily", "setcooldown", "setchannel", "removechannel", "setmaxsize", "userinfo", "top", "today"]))
    async def on_text(client: Client, message: Message):
        await message.reply(
            f"❓ Send me a <b>video file</b> to compress!\n\n"
            f"Type /help for instructions.\n\n"
            f"{BOT_FOOTER}"
        )
