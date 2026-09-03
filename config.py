# ============================================================
# config.py – Pure Engine Configuration
# ONLY Telegram credentials are required.
# STORAGE_URI is optional – used only when features need it later.
# ============================================================

from os import environ

# ============================
# Bot Credentials (REQUIRED)
# ============================
API_ID = int(environ.get("API_ID", ""))
API_HASH = environ.get("API_HASH", "")
BOT_TOKEN = environ.get("BOT_TOKEN", "")
SESSION = environ.get("SESSION", "downtownvilla_bot")
BOT_NAME = environ.get("BOT_NAME", "DOWNTOWN VILLA")
BOT_LINK = environ.get("BOT_LINK", "https://t.me/DownTownVillaBot")

# ============================
# Computer Storage (OPTIONAL – for future features)
# This will be used later when you add database-dependent features.
# Set it in Render as COMPUTER_STORAGE (or any name you prefer).
# ============================
COMPUTER_STORAGE = environ.get("COMPUTER_STORAGE", "")  # optional, not used by engine
STORAGE_NAME = environ.get("STORAGE_NAME", "downtownvilla_storage")  # optional

# ============================
# Admin (OPTIONAL – for future)
# ============================
OWNER_IDS = [int(x) for x in environ.get("OWNER_IDS", "").split() if x.isdigit()]
ADMINS = OWNER_IDS

# ============================
# Validation – only credentials required
# ============================
def validate_config():
    missing = []
    if not BOT_TOKEN:
        missing.append("BOT_TOKEN")
    if not API_ID or not API_HASH:
        missing.append("API_ID/API_HASH")
    if missing:
        raise ValueError("Missing: " + ", ".join(missing))
