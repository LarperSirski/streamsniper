"""Application configuration. Secrets are read from the local .env file."""
import logging
from datetime import datetime
from pathlib import Path
import os
import sys
from uuid import uuid4

from dotenv import load_dotenv

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR))
APP_ICON_PATH = RESOURCE_DIR / "ui" / "StreamSniper.ico"

APP_DATA_DIR = Path(
    os.getenv("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
).expanduser() / "StreamSniper"
APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_PATH = APP_DATA_DIR / ".env"
load_dotenv(CONFIG_PATH if CONFIG_PATH.exists() else BASE_DIR / ".env")

_data_dir = Path(
    os.getenv("DATA_DIR") or str(Path.home() / "Videos" / "StreamSniper")
).expanduser()
DATA_DIR = _data_dir if _data_dir.is_absolute() else BASE_DIR / _data_dir
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = APP_DATA_DIR / "youtube_guard.db"
LOG_DIR = APP_DATA_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def create_session_log_path():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return LOG_DIR / f"session_{timestamp}_{uuid4().hex[:8]}.log"


LOG_PATH = create_session_log_path()
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "90"))
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK", "").strip()
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".ts", ".m4v"}


def configure_logging():
    logging.basicConfig(
        filename=LOG_PATH,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )
