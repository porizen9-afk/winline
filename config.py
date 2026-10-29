import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = int(os.getenv("OWNER_ID") or "0")
STATICGRAM_API = os.getenv("STATICGRAM_API", "https://api.staticgram.top").rstrip("/")
WEBAPP_URL = os.getenv("WEBAPP_URL", "")
DB_PATH = os.getenv("DB_PATH", "data/app.db")
RELAYER_JSON = os.getenv("RELAYER_JSON", "data/relayer_gifts.json")
WITHDRAW_STEP = int(os.getenv("WITHDRAW_STEP", "25"))
DAILY_WITHDRAW_CAP = int(os.getenv("DAILY_WITHDRAW_CAP", "50000"))
MIN_BET = float(os.getenv("MIN_BET", "0.1"))
MAX_BET = float(os.getenv("MAX_BET", "50000"))
MINES_HOUSE = float(os.getenv("MINES_HOUSE", "1.45"))
DEV_USER_ID = os.getenv("DEV_USER_ID")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x.isdigit()]
