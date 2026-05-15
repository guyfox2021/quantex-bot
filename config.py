import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_TELEGRAM_ID = os.getenv("OWNER_TELEGRAM_ID", "")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set in .env")
if not OWNER_TELEGRAM_ID:
    raise ValueError("OWNER_TELEGRAM_ID is not set in .env")

try:
    OWNER_TELEGRAM_ID = int(OWNER_TELEGRAM_ID)
except ValueError:
    raise ValueError("OWNER_TELEGRAM_ID must be an integer")

CHECK_INTERVAL_MINUTES = int(os.getenv("CHECK_INTERVAL_MINUTES", "5"))
GOOGLE_SHEETS_ENABLED = os.getenv("GOOGLE_SHEETS_ENABLED", "0") == "1"
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")
DASHBOARD_HOST = os.getenv("DASHBOARD_HOST", "0.0.0.0")
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8010"))
DASHBOARD_TOKEN = os.getenv("DASHBOARD_TOKEN", "")
DASHBOARD_PUBLIC_URL = os.getenv("DASHBOARD_PUBLIC_URL", "")

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
DATABASE_PATH = str(DATA_DIR / "bot.db")
