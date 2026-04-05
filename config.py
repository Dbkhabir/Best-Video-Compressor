import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        print(f"FATAL: Missing required env var: {key}", file=sys.stderr)
        sys.exit(1)
    return val


BOT_TOKEN = os.getenv("VBOT_TOKEN") or os.getenv("BOT_TOKEN") or _require("BOT_TOKEN")
API_ID = int(os.getenv("VBOT_API_ID") or os.getenv("API_ID") or os.getenv("TELEGRAM_API_ID") or _require("API_ID"))
API_HASH = os.getenv("VBOT_API_HASH") or os.getenv("API_HASH") or os.getenv("TELEGRAM_API_HASH") or _require("API_HASH")

DB_PATH = Path(__file__).parent / "bot.db"

ADMIN_IDS: list[int] = []
_raw = os.getenv("VBOT_ADMIN_IDS") or os.getenv("ADMIN_IDS", "")
if _raw.strip():
    ADMIN_IDS = [int(x.strip()) for x in _raw.split(",") if x.strip().isdigit()]

FORCE_SUB_CHANNEL = os.getenv("FORCE_SUB_CHANNEL", "").strip() or None
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID", "").strip() or None

BOT_VERSION = os.getenv("BOT_VERSION", "1.0.0")
MAX_QUEUE_PER_USER = int(os.getenv("MAX_QUEUE_PER_USER", "3"))
COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", "5"))

TEMP_DIR = Path("/tmp/vcompressor")
WORKDIR = Path(__file__).parent
LOG_FILE = WORKDIR / "bot.log"

EDIT_INTERVAL = 2.0
PROGRESS_EDIT_INTERVAL = 1.5

QUALITY_PRESETS = {
    "low": {"crf": "32", "preset": "ultrafast", "label": "🟢 Low (Fast)"},
    "medium": {"crf": "28", "preset": "medium", "label": "🟡 Medium"},
    "high": {"crf": "23", "preset": "slow", "label": "🔴 High (Best)"},
}

RESOLUTION_OPTIONS = {
    "1080p": 1080,
    "720p": 720,
    "480p": 480,
    "360p": 360,
    "original": None,
}

MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", str(2 * 1024 * 1024 * 1024)))

BOT_USERNAME = os.getenv("BOT_USERNAME", "BestVideoCompressorBot")
BOT_FOOTER = f"⚡ @{BOT_USERNAME}"
BOT_NAME = "Video Compressor Bot"
