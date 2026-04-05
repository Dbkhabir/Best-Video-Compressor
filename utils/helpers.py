import asyncio
import logging
import time
from typing import Optional

_log = logging.getLogger("vbot.editor")


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


class ThrottledEditor:
    def __init__(self, client, chat_id: int, msg_id: int, interval: float = 1.5):
        self.client = client
        self.cid = chat_id
        self.mid = msg_id
        self._interval = interval
        self._last_t = 0.0
        self._last_txt = ""

    async def __call__(self, text: str, force: bool = False, reply_markup=None):
        if text == self._last_txt:
            return
        now = time.time()
        if not force and now - self._last_t < self._interval:
            return
        try:
            await self.client.edit_message_text(
                self.cid, self.mid, text,
                reply_markup=reply_markup,
            )
            self._last_t = time.time()
            self._last_txt = text
        except Exception as e:
            err_str = f"{type(e).__name__}: {e}"
            if "FloodWait" in err_str or "FLOOD_WAIT" in err_str:
                wait_time = getattr(e, "value", 3)
                self._last_t = time.time() + wait_time
                _log.debug("FloodWait %ds, pausing edits", wait_time)
            elif "MESSAGE_NOT_MODIFIED" in err_str:
                self._last_txt = text
            else:
                self._last_t = time.time()
                _log.warning("Edit failed: %s", err_str)
