import logging
import time

import psutil
from pyrogram import Client, ContinuePropagation, filters
from pyrogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup as IKM,
    InlineKeyboardButton as IKB,
)

from config import (
    BOT_FOOTER, BOT_NAME, BOT_VERSION, BOT_USERNAME,
    COOLDOWN_SECONDS, FORCE_SUB_CHANNEL,
)
from database import db
from utils.helpers import human_size, human_duration, short_name, Cooldown, safe_edit

log = logging.getLogger("vbot.user")
cooldown = Cooldown(COOLDOWN_SECONDS)
_bot_start_time = time.time()

H = "━━━━━━━━━━━━━━━━━━━━━━━━"


def register_user_handlers(app: Client):

    @app.on_message(filters.command("start") & filters.private)
    async def cmd_start(client: Client, message: Message):
        user = message.from_user
        await db.add_user(user.id, user.username or "", user.first_name or "")
        kb = IKM([
            [IKB("📚 Help", callback_data="help"), IKB("🖥 Bot Info", callback_data="info")],
            [IKB("👤 My Profile", callback_data="profile"), IKB("🗂 History", callback_data="history")],
        ])
        await message.reply(
            f"🎬 <b>{BOT_NAME}</b>\n"
            f"{H}\n\n"
            f"Hey, <b>{short_name(user)}</b>! 👋\n\n"
            f"I can <b>compress your videos</b> and send them\n"
            f"back — smaller, faster, and ready to share!\n\n"
            f"🎞 <b>Supported Formats</b>\n"
            f"  ● MP4 • MKV • AVI • MOV • WebM\n"
            f"  ● Video documents & animations\n"
            f"  ● Large files up to <b>2GB+</b> via MTProto\n\n"
            f"✨ <b>Key Features</b>\n"
            f"  ● 🎛 Quality presets (Low / Medium / High)\n"
            f"  ● 📐 Resolution pick (360p → 1080p)\n"
            f"  ● 📊 Live progress tracking\n"
            f"  ● 🗂 Compression history & stats\n"
            f"  ● ⚡ Smart queue system\n\n"
            f"📤 <b>Send me a video to get started!</b>\n\n"
            f"{H}\n"
            f"{BOT_FOOTER}",
            reply_markup=kb,
        )

    @app.on_message(filters.command("help") & filters.private)
    async def cmd_help(client: Client, message: Message):
        kb = IKM([[IKB("🏠 Back to Menu", callback_data="start")]])
        await message.reply(
            f"📚 <b>Help & Guide</b>\n"
            f"{H}\n\n"
            f"📖 <b>How It Works</b>\n"
            f"  1️⃣  Send any video file\n"
            f"  2️⃣  Pick compression quality\n"
            f"  3️⃣  Choose output resolution\n"
            f"  4️⃣  Wait while I compress it\n"
            f"  5️⃣  Get your compressed video!\n\n"
            f"🤖 <b>Available Commands</b>\n"
            f"  /start  — Main menu\n"
            f"  /help   — This guide\n"
            f"  /info   — Bot & server info\n"
            f"  /profile — Your stats\n"
            f"  /history — Past compressions\n"
            f"  /cancel  — Stop current task\n\n"
            f"🎛 <b>Quality Presets</b>\n"
            f"  🟢 <b>Low</b> — Fastest, smallest size\n"
            f"  🟡 <b>Medium</b> — Balanced quality & size\n"
            f"  🔴 <b>High</b> — Best quality, larger file\n\n"
            f"📐 <b>Resolution Options</b>\n"
            f"  1080p │ 720p │ 480p │ 360p │ Original\n\n"
            f"{H}\n"
            f"{BOT_FOOTER}",
            reply_markup=kb,
        )

    @app.on_message(filters.command("info") & filters.private)
    async def cmd_info(client: Client, message: Message):
        uptime = human_duration(time.time() - _bot_start_time)
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        stats = await db.global_stats()

        await message.reply(
            f"🖥 <b>Bot Information</b>\n"
            f"{H}\n\n"
            f"🤖 <b>Version:</b> <code>{BOT_VERSION}</code>\n"
            f"⏱ <b>Uptime:</b> <code>{uptime}</code>\n\n"
            f"💻 <b>Server</b>\n"
            f"  ● <b>CPU:</b> <code>{cpu}%</code>\n"
            f"  ● <b>RAM:</b> <code>{mem.percent}%</code> ({human_size(mem.used)} / {human_size(mem.total)})\n"
            f"  ● <b>Disk:</b> <code>{disk.percent}%</code> ({human_size(disk.used)} / {human_size(disk.total)})\n\n"
            f"📊 <b>Statistics</b>\n"
            f"  ● 👥 <b>Users:</b> <code>{stats['users']:,}</code>\n"
            f"  ● 🎬 <b>Compressed:</b> <code>{stats['compressions']:,}</code>\n"
            f"  ● 💾 <b>Space Saved:</b> <code>{human_size(stats['total_saved'])}</code>\n\n"
            f"{H}\n"
            f"{BOT_FOOTER}",
        )

    @app.on_message(filters.command(["profile", "statsme"]) & filters.private)
    async def cmd_profile(client: Client, message: Message):
        uid = message.from_user.id
        user = await db.get_user(uid)
        if not user:
            await message.reply("❌ Profile not found. Send /start first.")
            return
        daily = await db.get_daily_count(uid)
        daily_limit = int(await db.get_setting("daily_limit", "0"))
        limit_text = f"{daily}/{daily_limit}" if daily_limit > 0 else f"{daily}/∞"
        kb = IKM([
            [IKB("🗂 History", callback_data="history"), IKB("🏠 Menu", callback_data="start")],
        ])
        await message.reply(
            f"👤 <b>Your Profile</b>\n"
            f"{H}\n\n"
            f"🆔 <b>User ID:</b> <code>{user['user_id']}</code>\n"
            f"👤 <b>Username:</b> @{user.get('username') or '—'}\n"
            f"📝 <b>Name:</b> {user.get('first_name') or '—'}\n"
            f"📅 <b>Joined:</b> <code>{(user.get('join_date') or '')[:10]}</code>\n\n"
            f"📊 <b>Your Stats</b>\n"
            f"  ● 🎬 <b>Total:</b> <code>{user.get('total_compressed', 0):,}</code> videos\n"
            f"  ● 💾 <b>Space Saved:</b> <code>{human_size(user.get('total_saved_size', 0))}</code>\n"
            f"  ● 📅 <b>Today:</b> <code>{limit_text}</code>\n"
            f"  ● 🕐 <b>Last Active:</b> <code>{(user.get('last_used') or '')[:10]}</code>\n\n"
            f"{H}\n"
            f"{BOT_FOOTER}",
            reply_markup=kb,
        )

    @app.on_message(filters.command("history") & filters.private)
    async def cmd_history(client: Client, message: Message):
        uid = message.from_user.id
        h = await db.get_history(uid)
        if not h:
            await message.reply("📭 No compression history yet.\nSend a video to get started!")
            return
        lines = [
            f"🗂 <b>Compression History</b>\n"
            f"{H}\n"
        ]
        for i, e in enumerate(h, 1):
            saved_pct = 0
            orig = e.get('original_size', 0)
            comp = e.get('compressed_size', 0)
            if orig > 0:
                saved_pct = ((orig - comp) / orig) * 100
            lines.append(
                f"\n<b>{i}.</b> 🎞 <code>{(e.get('file_name') or '?')[:35]}</code>\n"
                f"  📦 {human_size(orig)} → {human_size(comp)} (<b>{saved_pct:.0f}%</b> saved)\n"
                f"  ⏱ {human_duration(e.get('time_taken', 0))}  •  📅 {(e.get('timestamp') or '')[:10]}"
            )
        lines.append(f"\n\n{H}\n{BOT_FOOTER}")
        kb = IKM([[IKB("🏠 Menu", callback_data="start")]])
        await message.reply("\n".join(lines), reply_markup=kb)

    @app.on_callback_query()
    async def on_callback(client: Client, callback: CallbackQuery):
        data = callback.data
        uid = callback.from_user.id

        if data == "start":
            await callback.answer()
            user = callback.from_user
            await db.add_user(user.id, user.username or "", user.first_name or "")
            kb = IKM([
                [IKB("📚 Help", callback_data="help"), IKB("🖥 Bot Info", callback_data="info")],
                [IKB("👤 My Profile", callback_data="profile"), IKB("🗂 History", callback_data="history")],
            ])
            await safe_edit(
                callback.message,
                f"🎬 <b>{BOT_NAME}</b>\n"
                f"{H}\n\n"
                f"Hey, <b>{short_name(user)}</b>! 👋\n\n"
                f"Send me any <b>video</b> and I'll compress it\n"
                f"and send it back — smaller and faster!\n\n"
                f"📤 <b>Send a video to get started!</b>\n\n"
                f"{H}\n"
                f"{BOT_FOOTER}",
                reply_markup=kb,
            )
        elif data == "help":
            await callback.answer()
            kb = IKM([[IKB("🏠 Back to Menu", callback_data="start")]])
            await safe_edit(
                callback.message,
                f"📚 <b>Help & Guide</b>\n"
                f"{H}\n\n"
                f"📖 <b>How It Works</b>\n"
                f"  1️⃣  Send any video file\n"
                f"  2️⃣  Pick quality & resolution\n"
                f"  3️⃣  Wait for compression\n"
                f"  4️⃣  Get your compressed video!\n\n"
                f"{H}\n"
                f"{BOT_FOOTER}",
                reply_markup=kb,
            )
        elif data == "info":
            await callback.answer()
            uptime = human_duration(time.time() - _bot_start_time)
            stats = await db.global_stats()
            cpu = psutil.cpu_percent(interval=0.5)
            mem = psutil.virtual_memory()
            await safe_edit(
                callback.message,
                f"🖥 <b>Bot Information</b>\n"
                f"{H}\n\n"
                f"🤖 <b>Version:</b> <code>{BOT_VERSION}</code>\n"
                f"⏱ <b>Uptime:</b> <code>{uptime}</code>\n"
                f"💻 <b>CPU:</b> <code>{cpu}%</code> • <b>RAM:</b> <code>{mem.percent}%</code>\n\n"
                f"📊 <b>Statistics</b>\n"
                f"  ● 👥 <b>Users:</b> <code>{stats['users']:,}</code>\n"
                f"  ● 🎬 <b>Compressed:</b> <code>{stats['compressions']:,}</code>\n"
                f"  ● 💾 <b>Saved:</b> <code>{human_size(stats['total_saved'])}</code>\n\n"
                f"{H}\n"
                f"{BOT_FOOTER}",
                reply_markup=IKM([[IKB("🏠 Menu", callback_data="start")]]),
            )
        elif data == "profile":
            await callback.answer()
            user_data = await db.get_user(uid)
            if not user_data:
                await safe_edit(callback.message, "❌ Profile not found. Send /start first.")
                return
            daily = await db.get_daily_count(uid)
            daily_limit = int(await db.get_setting("daily_limit", "0"))
            limit_text = f"{daily}/{daily_limit}" if daily_limit > 0 else f"{daily}/∞"
            await safe_edit(
                callback.message,
                f"👤 <b>Your Profile</b>\n"
                f"{H}\n\n"
                f"🆔 <b>User ID:</b> <code>{user_data['user_id']}</code>\n"
                f"📝 <b>Name:</b> {user_data.get('first_name') or '—'}\n"
                f"🎬 <b>Compressed:</b> <code>{user_data.get('total_compressed', 0):,}</code> videos\n"
                f"💾 <b>Space Saved:</b> <code>{human_size(user_data.get('total_saved_size', 0))}</code>\n"
                f"📅 <b>Today:</b> <code>{limit_text}</code>\n\n"
                f"{H}\n"
                f"{BOT_FOOTER}",
                reply_markup=IKM([
                    [IKB("🗂 History", callback_data="history"), IKB("🏠 Menu", callback_data="start")],
                ]),
            )
        elif data == "history":
            await callback.answer()
            h = await db.get_history(uid)
            if not h:
                await safe_edit(
                    callback.message,
                    "📭 No history yet. Send a video to start!",
                    reply_markup=IKM([[IKB("🏠 Menu", callback_data="start")]]),
                )
                return
            lines = [
                f"🗂 <b>History</b>\n"
                f"{H}\n"
            ]
            for i, e in enumerate(h[:5], 1):
                saved_pct = 0
                orig = e.get('original_size', 0)
                comp = e.get('compressed_size', 0)
                if orig > 0:
                    saved_pct = ((orig - comp) / orig) * 100
                lines.append(
                    f"\n<b>{i}.</b> 🎞 <code>{(e.get('file_name') or '?')[:30]}</code>\n"
                    f"  📦 {human_size(orig)} → {human_size(comp)} (<b>{saved_pct:.0f}%</b> saved)"
                )
            lines.append(f"\n\n{H}\n{BOT_FOOTER}")
            await safe_edit(
                callback.message,
                "\n".join(lines),
                reply_markup=IKM([[IKB("🏠 Menu", callback_data="start")]]),
            )
        elif data.startswith("cancel_"):
            await callback.answer("🛑 Cancelling...")
            from handlers.video_handler import cancel_events
            try:
                target_uid = int(data.split("_")[1])
                if target_uid == uid:
                    ev = cancel_events.get(uid)
                    if ev and not ev.is_set():
                        ev.set()
            except (ValueError, IndexError):
                pass
        elif data.startswith("quality_"):
            await callback.answer()
            from handlers.video_handler import handle_quality_selection
            await handle_quality_selection(client, callback)
        elif data.startswith("res_"):
            await callback.answer()
            from handlers.video_handler import handle_resolution_selection
            await handle_resolution_selection(client, callback)
        else:
            raise ContinuePropagation
