import asyncio
import logging
import shutil
import time
from pathlib import Path

import psutil
from pyrogram import Client, ContinuePropagation, filters
from pyrogram.types import Message, CallbackQuery
from pyrogram.types import InlineKeyboardMarkup as IKM, InlineKeyboardButton as IKB

from config import ADMIN_IDS, BOT_FOOTER, BOT_VERSION, LOG_FILE, TEMP_DIR
from database import db
from utils.helpers import human_size, human_duration, safe_edit

log = logging.getLogger("vbot.admin")
_bot_start_time = time.time()

H = "━━━━━━━━━━━━━━━━━━━━━━━━"

admin_input_state: dict[int, str] = {}


def _admin_filter():
    return filters.user(ADMIN_IDS) & filters.private if ADMIN_IDS else filters.user([0])


def _settings_keyboard():
    return IKM([
        [IKB("📊 Daily Limit", callback_data="adm_daily"), IKB("⏱ Cooldown", callback_data="adm_cooldown")],
        [IKB("📢 Force Channel", callback_data="adm_force_ch"), IKB("📋 Log Channel", callback_data="adm_log_ch")],
        [IKB("📏 Max File Size", callback_data="adm_maxsize"), IKB("🧹 Clean Temp", callback_data="adm_clean")],
        [IKB("📊 Stats", callback_data="adm_stats"), IKB("🏆 Top Users", callback_data="adm_top")],
        [IKB("📅 Today", callback_data="adm_today"), IKB("👥 Users", callback_data="adm_users")],
        [IKB("🚫 Banned List", callback_data="adm_banned"), IKB("📄 Logs", callback_data="adm_logs")],
        [IKB("❌ Close", callback_data="adm_close")],
    ])


async def _settings_text():
    all_s = await db.all_settings()
    daily = all_s.get("daily_limit", "0")
    cd = all_s.get("cooldown", "5")
    force_ch = all_s.get("force_channel", "")
    log_ch = all_s.get("log_channel", "")
    ms = all_s.get("max_size_mb", "2048")

    daily_d = f"{daily}/day" if daily != "0" else "Unlimited"
    force_d = f"@{force_ch.lstrip('@')}" if force_ch else "Not set"
    log_d = f"{log_ch}" if log_ch else "Not set"

    return (
        f"⚙️ <b>Bot Settings Panel</b>\n"
        f"{H}\n\n"
        f"📊 <b>Daily Limit:</b> <code>{daily_d}</code>\n"
        f"⏱ <b>Cooldown:</b> <code>{cd}s</code>\n"
        f"📢 <b>Force Channel:</b> <code>{force_d}</code>\n"
        f"📋 <b>Log Channel:</b> <code>{log_d}</code>\n"
        f"📏 <b>Max File Size:</b> <code>{ms} MB</code>\n\n"
        f"👇 Tap a button to change settings\n\n"
        f"{H}\n"
        f"{BOT_FOOTER}"
    )


def register_admin_handlers(app: Client):

    @app.on_message(filters.command("settings") & _admin_filter())
    async def admin_settings_cmd(client: Client, message: Message):
        admin_input_state.pop(message.from_user.id, None)
        text = await _settings_text()
        await message.reply(text, reply_markup=_settings_keyboard())

    @app.on_message(filters.command("stats") & _admin_filter())
    async def admin_stats(client: Client, message: Message):
        uptime = human_duration(time.time() - _bot_start_time)
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        stats = await db.global_stats()
        today = await db.today_stats()

        await message.reply(
            f"🛠 <b>Admin Dashboard</b>\n"
            f"{H}\n\n"
            f"📊 <b>All-Time</b>\n"
            f"  ● 👥 <b>Users:</b> <code>{stats['users']:,}</code>\n"
            f"  ● 🎬 <b>Compressed:</b> <code>{stats['compressions']:,}</code>\n"
            f"  ● 💾 <b>Saved:</b> <code>{human_size(stats['total_saved'])}</code>\n\n"
            f"📅 <b>Today</b>\n"
            f"  ● 🎬 <b>Compressed:</b> <code>{today['count']:,}</code>\n"
            f"  ● 💾 <b>Saved:</b> <code>{human_size(today['saved'])}</code>\n\n"
            f"🤖 <b>Bot</b>\n"
            f"  ● ⏱ <b>Uptime:</b> <code>{uptime}</code>\n"
            f"  ● 🏷 <b>Version:</b> <code>{BOT_VERSION}</code>\n\n"
            f"💻 <b>Server</b>\n"
            f"  ● <b>CPU:</b> <code>{cpu}%</code>\n"
            f"  ● <b>RAM:</b> <code>{mem.percent}%</code> ({human_size(mem.used)})\n"
            f"  ● <b>Disk:</b> <code>{disk.percent}%</code> ({human_size(disk.used)})\n\n"
            f"{H}\n{BOT_FOOTER}",
        )

    @app.on_message(filters.command(["ban"]) & _admin_filter())
    async def admin_ban(client: Client, message: Message):
        args = message.text.split(None, 1)
        if len(args) < 2:
            await message.reply("Usage: /ban <code>&lt;user_id&gt;</code>")
            return
        try:
            target = int(args[1].strip())
        except ValueError:
            await message.reply("Usage: /ban <code>&lt;user_id&gt;</code>")
            return
        await db.ban_user(target)
        await message.reply(f"🚫 User <code>{target}</code> has been <b>banned</b>.")

    @app.on_message(filters.command(["unban"]) & _admin_filter())
    async def admin_unban(client: Client, message: Message):
        args = message.text.split(None, 1)
        if len(args) < 2:
            await message.reply("Usage: /unban <code>&lt;user_id&gt;</code>")
            return
        try:
            target = int(args[1].strip())
        except ValueError:
            await message.reply("Usage: /unban <code>&lt;user_id&gt;</code>")
            return
        await db.unban_user(target)
        await message.reply(f"✅ User <code>{target}</code> has been <b>unbanned</b>.")

    @app.on_message(filters.command("userinfo") & _admin_filter())
    async def admin_userinfo(client: Client, message: Message):
        args = message.text.split(None, 1)
        if len(args) < 2:
            await message.reply("Usage: /userinfo <code>&lt;user_id&gt;</code>")
            return
        try:
            target = int(args[1].strip())
        except ValueError:
            await message.reply("Usage: /userinfo <code>&lt;user_id&gt;</code>")
            return
        user = await db.get_user(target)
        if not user:
            await message.reply(f"❌ User <code>{target}</code> not found.")
            return
        daily = await db.get_daily_count(target)
        banned_str = "🚫 Yes" if user.get("banned") else "✅ No"
        await message.reply(
            f"👤 <b>User Info</b>\n{H}\n\n"
            f"🆔 <b>ID:</b> <code>{user['user_id']}</code>\n"
            f"👤 <b>Username:</b> @{user.get('username') or '—'}\n"
            f"📝 <b>Name:</b> {user.get('first_name') or '—'}\n"
            f"📅 <b>Joined:</b> <code>{(user.get('join_date') or '')[:10]}</code>\n"
            f"🕐 <b>Last Active:</b> <code>{(user.get('last_used') or '')[:10]}</code>\n\n"
            f"📊 <b>Stats</b>\n"
            f"  ● 🎬 <b>Total:</b> <code>{user.get('total_compressed', 0):,}</code>\n"
            f"  ● 💾 <b>Saved:</b> <code>{human_size(user.get('total_saved_size', 0))}</code>\n"
            f"  ● 📅 <b>Today:</b> <code>{daily}</code>\n"
            f"  ● 🚫 <b>Banned:</b> {banned_str}\n\n"
            f"{H}\n{BOT_FOOTER}",
        )

    @app.on_message(filters.command("broadcast") & _admin_filter())
    async def admin_broadcast(client: Client, message: Message):
        text = message.text.split(None, 1)
        if len(text) < 2:
            await message.reply("Usage: /broadcast <code>Your message</code>")
            return
        broadcast_text = text[1]
        ids = await db.all_user_ids()
        status = await message.reply(f"📢 Broadcasting to {len(ids)} users...")
        sent, failed = 0, 0
        for uid in ids:
            try:
                await client.send_message(uid, broadcast_text)
                sent += 1
            except Exception:
                failed += 1
            await asyncio.sleep(0.05)
        await status.edit_text(
            f"📢 <b>Broadcast Complete</b>\n{H}\n\n"
            f"  ✅ <b>Sent:</b> {sent}\n"
            f"  ❌ <b>Failed:</b> {failed}\n\n{H}\n{BOT_FOOTER}",
        )


def register_admin_callbacks(app: Client):

    async def _handle_admin_callback(client: Client, callback: CallbackQuery):
        uid = callback.from_user.id
        if uid not in ADMIN_IDS:
            await callback.answer("⛔ Admin only.", show_alert=True)
            return
        data = callback.data
        try:
            await _process_admin_callback(client, callback, uid, data)
        except Exception as e:
            log.warning("Admin callback error (%s): %s", data, e)
            try:
                await callback.answer(f"❌ Error: {str(e)[:100]}", show_alert=True)
            except Exception:
                pass

    async def _process_admin_callback(client: Client, callback: CallbackQuery, uid: int, data: str):

        if data == "adm_close":
            await callback.answer()
            admin_input_state.pop(uid, None)
            await callback.message.delete()
            return

        if data == "adm_back":
            await callback.answer()
            admin_input_state.pop(uid, None)
            text = await _settings_text()
            await safe_edit(callback.message, text, reply_markup=_settings_keyboard())
            return

        back_kb = IKM([[IKB("🔙 Back to Panel", callback_data="adm_back")]])

        if data == "adm_daily":
            await callback.answer()
            cur = await db.get_setting("daily_limit", "0")
            cur_d = f"{cur}/day" if cur != "0" else "Unlimited"
            admin_input_state[uid] = "daily_limit"
            await safe_edit(
                callback.message,
                f"📊 <b>Daily Limit</b>\n{H}\n\n"
                f"<b>Current:</b> <code>{cur_d}</code>\n\n"
                f"Send a number to set the daily limit.\n"
                f"Send <code>0</code> to disable.\n\n"
                f"Example: <code>10</code> = 10 videos/day",
                reply_markup=back_kb,
            )

        elif data == "adm_cooldown":
            await callback.answer()
            cur = await db.get_setting("cooldown", "5")
            admin_input_state[uid] = "cooldown"
            await safe_edit(
                callback.message,
                f"⏱ <b>Cooldown</b>\n{H}\n\n"
                f"<b>Current:</b> <code>{cur}s</code>\n\n"
                f"Send seconds between tasks.\n"
                f"Send <code>0</code> to disable.\n\n"
                f"Example: <code>30</code> = 30 seconds gap",
                reply_markup=back_kb,
            )

        elif data == "adm_force_ch":
            await callback.answer()
            cur = await db.get_setting("force_channel", "")
            cur_d = f"@{cur.lstrip('@')}" if cur else "Not set"
            admin_input_state[uid] = "force_channel"
            await safe_edit(
                callback.message,
                f"📢 <b>Force Subscribe Channel</b>\n{H}\n\n"
                f"<b>Current:</b> <code>{cur_d}</code>\n\n"
                f"Send channel username or ID.\n"
                f"Send <code>off</code> to remove.\n\n"
                f"Example: <code>@MyChannel</code>",
                reply_markup=back_kb,
            )

        elif data == "adm_log_ch":
            await callback.answer()
            cur = await db.get_setting("log_channel", "")
            cur_d = cur if cur else "Not set"
            admin_input_state[uid] = "log_channel"
            await safe_edit(
                callback.message,
                f"📋 <b>Log Channel</b>\n{H}\n\n"
                f"<b>Current:</b> <code>{cur_d}</code>\n\n"
                f"Send channel ID (e.g. <code>-1001234567890</code>)\n"
                f"or username (e.g. <code>@MyLogChannel</code>).\n"
                f"Send <code>off</code> to remove.\n\n"
                f"Bot must be admin in the channel.",
                reply_markup=back_kb,
            )

        elif data == "adm_maxsize":
            await callback.answer()
            cur = await db.get_setting("max_size_mb", "2048")
            admin_input_state[uid] = "max_size_mb"
            await safe_edit(
                callback.message,
                f"📏 <b>Max File Size</b>\n{H}\n\n"
                f"<b>Current:</b> <code>{cur} MB</code>\n\n"
                f"Send max file size in MB.\n\n"
                f"Example: <code>500</code> = 500 MB",
                reply_markup=back_kb,
            )

        elif data == "adm_clean":
            await callback.answer("🧹 Cleaning...")
            count = 0
            if TEMP_DIR.exists():
                for d in TEMP_DIR.iterdir():
                    if d.is_dir():
                        try:
                            shutil.rmtree(d)
                            count += 1
                        except Exception:
                            pass
            await safe_edit(
                callback.message,
                f"🧹 <b>Temp Cleanup Done</b>\n{H}\n\n"
                f"  ● Deleted <b>{count}</b> temp folders.\n\n{H}\n{BOT_FOOTER}",
                reply_markup=IKM([[IKB("🔙 Back to Panel", callback_data="adm_back")]]),
            )

        elif data == "adm_stats":
            await callback.answer()
            uptime = human_duration(time.time() - _bot_start_time)
            cpu = psutil.cpu_percent(interval=0.5)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            stats = await db.global_stats()
            today = await db.today_stats()
            await safe_edit(
                callback.message,
                f"🛠 <b>Admin Dashboard</b>\n{H}\n\n"
                f"📊 <b>All-Time</b>\n"
                f"  ● 👥 <b>Users:</b> <code>{stats['users']:,}</code>\n"
                f"  ● 🎬 <b>Compressed:</b> <code>{stats['compressions']:,}</code>\n"
                f"  ● 💾 <b>Saved:</b> <code>{human_size(stats['total_saved'])}</code>\n\n"
                f"📅 <b>Today</b>\n"
                f"  ● 🎬 <code>{today['count']:,}</code> compressions\n"
                f"  ● 💾 <code>{human_size(today['saved'])}</code> saved\n\n"
                f"💻 <b>Server</b>\n"
                f"  ● <b>CPU:</b> <code>{cpu}%</code> • <b>RAM:</b> <code>{mem.percent}%</code>\n"
                f"  ● <b>Disk:</b> <code>{disk.percent}%</code>\n"
                f"  ● ⏱ Uptime: <code>{uptime}</code>\n\n"
                f"{H}\n{BOT_FOOTER}",
                reply_markup=IKM([[IKB("🔙 Back to Panel", callback_data="adm_back")]]),
            )

        elif data == "adm_top":
            await callback.answer()
            users = await db.top_users(10)
            if not users:
                await safe_edit(
                    callback.message,
                    "📭 No users yet.",
                    reply_markup=IKM([[IKB("🔙 Back", callback_data="adm_back")]]),
                )
                return
            lines = [f"🏆 <b>Top Users</b>\n{H}\n"]
            medals = ["🥇", "🥈", "🥉"]
            for i, u in enumerate(users, 1):
                medal = medals[i - 1] if i <= 3 else f"<b>{i}.</b>"
                name = u.get("first_name") or u.get("username") or str(u["user_id"])
                lines.append(
                    f"\n{medal} <b>{name}</b>\n"
                    f"  🎬 {u.get('total_compressed', 0):,} • 💾 {human_size(u.get('total_saved_size', 0))}"
                )
            lines.append(f"\n\n{H}\n{BOT_FOOTER}")
            await safe_edit(
                callback.message,
                "\n".join(lines),
                reply_markup=IKM([[IKB("🔙 Back", callback_data="adm_back")]]),
            )

        elif data == "adm_today":
            await callback.answer()
            today = await db.today_stats()
            await safe_edit(
                callback.message,
                f"📅 <b>Today's Stats</b>\n{H}\n\n"
                f"  ● 🎬 <b>Compressions:</b> <code>{today['count']:,}</code>\n"
                f"  ● 💾 <b>Space Saved:</b> <code>{human_size(today['saved'])}</code>\n\n"
                f"{H}\n{BOT_FOOTER}",
                reply_markup=IKM([[IKB("🔙 Back", callback_data="adm_back")]]),
            )

        elif data == "adm_users":
            await callback.answer()
            total = await db.total_users()
            await safe_edit(
                callback.message,
                f"👥 <b>Total Users:</b> <code>{total:,}</code>",
                reply_markup=IKM([[IKB("🔙 Back", callback_data="adm_back")]]),
            )

        elif data == "adm_banned":
            await callback.answer()
            blist = await db.banned_list()
            if not blist:
                await safe_edit(
                    callback.message,
                    "✅ No banned users.",
                    reply_markup=IKM([[IKB("🔙 Back", callback_data="adm_back")]]),
                )
                return
            lines = [f"🚫 <b>Banned Users</b>\n{H}\n"]
            for u in blist[:20]:
                lines.append(f"  ● <code>{u['user_id']}</code> — {u.get('first_name') or u.get('username') or '?'}")
            lines.append(f"\n\n{H}\n{BOT_FOOTER}")
            await safe_edit(
                callback.message,
                "\n".join(lines),
                reply_markup=IKM([[IKB("🔙 Back", callback_data="adm_back")]]),
            )

        elif data == "adm_logs":
            await callback.answer()
            if not LOG_FILE.exists():
                await safe_edit(
                    callback.message,
                    "📄 No log file found.",
                    reply_markup=IKM([[IKB("🔙 Back", callback_data="adm_back")]]),
                )
                return
            try:
                content = LOG_FILE.read_text("utf-8")
                last_lines = "\n".join(content.splitlines()[-25:])
                await safe_edit(
                    callback.message,
                    f"📄 <b>Recent Logs</b>\n\n<pre>{last_lines[:3500]}</pre>",
                    reply_markup=IKM([[IKB("🔙 Back", callback_data="adm_back")]]),
                )
            except Exception as e:
                await safe_edit(
                    callback.message,
                    f"❌ Error: {e}",
                    reply_markup=IKM([[IKB("🔙 Back", callback_data="adm_back")]]),
                )

    for prefix in ["adm_daily", "adm_cooldown", "adm_force_ch", "adm_log_ch",
                    "adm_maxsize", "adm_clean", "adm_stats", "adm_top",
                    "adm_today", "adm_users", "adm_banned", "adm_logs",
                    "adm_close", "adm_back"]:
        app.on_callback_query(filters.regex(f"^{prefix}$") & filters.user(ADMIN_IDS))(
            _handle_admin_callback
        )


def register_admin_input_handler(app: Client):

    @app.on_message(filters.text & filters.private & _admin_filter())
    async def admin_input_capture(client: Client, message: Message):
        uid = message.from_user.id
        state = admin_input_state.get(uid)
        if not state:
            raise ContinuePropagation

        text = message.text.strip()
        if text.startswith("/"):
            admin_input_state.pop(uid, None)
            raise ContinuePropagation

        try:
            await _process_admin_input(message, uid, state, text)
        except Exception as e:
            log.warning("Admin input error (%s): %s", state, e)
            try:
                await message.reply(f"❌ Error: {str(e)[:200]}")
            except Exception:
                pass

    async def _process_admin_input(message: Message, uid: int, state: str, text: str):
        admin_input_state.pop(uid, None)
        result_msg = ""

        if state == "daily_limit":
            if not text.isdigit():
                result_msg = "❌ Invalid number. Setting unchanged."
            else:
                val = int(text)
                await db.set_setting("daily_limit", str(val))
                label = f"{val}/day" if val > 0 else "Unlimited"
                result_msg = f"✅ Daily limit set to: {label}"

        elif state == "cooldown":
            if not text.isdigit():
                result_msg = "❌ Invalid number. Setting unchanged."
            else:
                val = max(0, int(text))
                await db.set_setting("cooldown", str(val))
                label = f"{val}s" if val > 0 else "Disabled"
                result_msg = f"✅ Cooldown set to: {label}"

        elif state == "force_channel":
            if text.lower() in ("off", "none", "remove", "0"):
                await db.del_setting("force_channel")
                result_msg = "✅ Force channel removed."
            else:
                await db.set_setting("force_channel", text)
                result_msg = f"✅ Force channel set to: {text}"

        elif state == "log_channel":
            if text.lower() in ("off", "none", "remove", "0"):
                await db.del_setting("log_channel")
                result_msg = "✅ Log channel removed."
            else:
                await db.set_setting("log_channel", text)
                result_msg = f"✅ Log channel set to: {text}"

        elif state == "max_size_mb":
            if not text.isdigit():
                result_msg = "❌ Invalid number. Setting unchanged."
            else:
                val = max(1, int(text))
                await db.set_setting("max_size_mb", str(val))
                result_msg = f"✅ Max file size set to: {val} MB"

        if result_msg:
            await message.reply(result_msg)
        settings_text = await _settings_text()
        await message.reply(settings_text, reply_markup=_settings_keyboard())
