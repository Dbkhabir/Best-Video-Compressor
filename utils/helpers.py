import asyncio
import logging
import time
from typing import Optional

_log = logging.getLogger("vbot.editor")

_global_edit_tracker = {
    "count": 0,
    "window_start": 0.0,
    "blocked_until": 0.0,
}
GLOBAL_MAX_EDITS_PER_MIN = 25
GLOBAL_WINDOW = 60


def _check_global_rate() -> bool:
    now = time.time()
    t = _global_edit_tracker
    if now < t["blocked_until"]:
        return False
    if now - t["window_start"] > GLOBAL_WINDOW:
        t["count"] = 0
        t["window_start"] = now
    if t["count"] >= GLOBAL_MAX_EDITS_PER_MIN:
        return False
    t["count"] += 1
    return True


def _apply_global_backoff(seconds: float):
    _global_edit_tracker["blocked_until"] = time.time() + seconds
    _log.warning("Global edit backoff for %.0fs", seconds)


def human_size(b: int) -> str:
    if b < 0:
        b = 0
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"


def human_speed(bps: float) -> str:
    if bps <= 0:
        return "—"
    return human_size(int(bps)) + "/s"


def human_eta(secs: Optional[float]) -> str:
    if not secs or secs <= 0:
        return "—"
    secs = int(secs)
    if secs < 60:
        return f"{secs}s"
    m, s = divmod(secs, 60)
    if m < 60:
        return f"{m:02d}m {s:02d}s"
    h, m = divmod(m, 60)
    return f"{h:02d}h {m:02d}m"


def human_duration(secs: float) -> str:
    secs = int(secs)
    if secs < 60:
        return f"{secs}s"
    m, s = divmod(secs, 60)
    if m < 60:
        return f"{m:02d}m {s:02d}s"
    h, m = divmod(m, 60)
    return f"{h:02d}h {m:02d}m {s:02d}s"


def progress_bar(pct: float, width: int = 14) -> str:
    filled = int(width * pct / 100)
    return "█" * filled + "░" * (width - filled)


def short_name(user) -> str:
    first = getattr(user, "first_name", "") or ""
    last = getattr(user, "last_name", "") or ""
    name = f"{first} {last}".strip()
    return name or str(getattr(user, "id", "?"))


class Cooldown:
    def __init__(self, seconds: int):
        self._last: dict[int, float] = {}
        self._cd = seconds

    @property
    def seconds(self):
        return self._cd

    @seconds.setter
    def seconds(self, val: int):
        self._cd = val

    def check(self, uid: int) -> Optional[float]:
        now = time.time()
        remaining = self._cd - (now - self._last.get(uid, 0.0))
        if remaining > 0:
            return remaining
        self._last[uid] = now
        return None

    def cleanup(self, max_age: int = 3600):
        now = time.time()
        expired = [uid for uid, ts in self._last.items() if now - ts > max_age]
        for uid in expired:
            del self._last[uid]


def _handle_flood(e) -> float:
    wait_time = getattr(e, "value", 5)
    if isinstance(wait_time, int) and wait_time > 0:
        _apply_global_backoff(min(wait_time, 60))
        return wait_time
    _apply_global_backoff(10)
    return 10


async def safe_edit(message, text: str, reply_markup=None):
    try:
        await message.edit_text(text, reply_markup=reply_markup)
        return True
    except Exception as e:
        err_str = f"{type(e).__name__}: {e}"
        if "FloodWait" in err_str or "FLOOD_WAIT" in err_str:
            wait = _handle_flood(e)
            _log.warning("FloodWait %ds on safe_edit, skipping", wait)
            if wait <= 3:
                await asyncio.sleep(wait)
                try:
                    await message.edit_text(text, reply_markup=reply_markup)
                    return True
                except Exception:
                    pass
        elif "MESSAGE_NOT_MODIFIED" in err_str:
            pass
        elif "MESSAGE_ID_INVALID" in err_str:
            _log.warning("Message deleted, cannot edit")
        else:
            _log.warning("safe_edit failed: %s", err_str)
        return False


async def safe_reply(message, text: str, reply_markup=None):
    try:
        return await message.reply(text, reply_markup=reply_markup)
    except Exception as e:
        err_str = f"{type(e).__name__}: {e}"
        if "FloodWait" in err_str or "FLOOD_WAIT" in err_str:
            wait = _handle_flood(e)
            _log.warning("FloodWait %ds on safe_reply, skipping", wait)
            if wait <= 3:
                await asyncio.sleep(wait)
                try:
                    return await message.reply(text, reply_markup=reply_markup)
                except Exception:
                    pass
        else:
            _log.warning("safe_reply failed: %s", err_str)
        return None


class ThrottledEditor:
    BASE_INTERVAL = 3.0
    MAX_INTERVAL = 15.0

    def __init__(self, client, chat_id: int, msg_id: int, interval: float = 3.0):
        self.client = client
        self.cid = chat_id
        self.mid = msg_id
        self._interval = max(interval, self.BASE_INTERVAL)
        self._last_t = 0.0
        self._last_txt = ""
        self._dead = False
        self._flood_hits = 0

    async def __call__(self, text: str, force: bool = False, reply_markup=None):
        if self._dead:
            return
        if text == self._last_txt:
            return
        now = time.time()
        if not force and now - self._last_t < self._interval:
            return
        if not force and not _check_global_rate():
            return
        try:
            await self.client.edit_message_text(
                self.cid, self.mid, text,
                reply_markup=reply_markup,
            )
            self._last_t = time.time()
            self._last_txt = text
            if self._flood_hits > 0 and self._interval > self.BASE_INTERVAL:
                self._interval = max(self._interval - 0.5, self.BASE_INTERVAL)
        except Exception as e:
            err_str = f"{type(e).__name__}: {e}"
            if "FloodWait" in err_str or "FLOOD_WAIT" in err_str:
                wait_time = _handle_flood(e)
                self._flood_hits += 1
                self._interval = min(self._interval * 2, self.MAX_INTERVAL)
                self._last_t = time.time() + min(wait_time, 30)
                _log.warning(
                    "FloodWait %ds (hit #%d), interval now %.1fs",
                    wait_time, self._flood_hits, self._interval,
                )
            elif "MESSAGE_NOT_MODIFIED" in err_str:
                self._last_txt = text
            elif "MESSAGE_ID_INVALID" in err_str or "message to edit not found" in err_str.lower():
                _log.warning("Message was deleted, editor disabled")
                self._dead = True
            else:
                self._last_t = time.time()
                _log.warning("Edit failed: %s", err_str)
