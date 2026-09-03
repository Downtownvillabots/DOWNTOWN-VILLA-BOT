# ============================================================
# config.py – Central Configuration for DOWNTOWN VILLA BOT
# All environment variables are read here. Every plugin imports from this.
# ============================================================

import re
from os import environ, getenv
from Script import script

# ============================
# Configuration Version
# ============================
CONFIG_VERSION = "2.0"

# ============================
# Utility Functions
# ============================
id_pattern = re.compile(r'^.\d+$')

def is_enabled(value, default):
    if value is None:
        return default
    value = str(value).strip().lower()
    if value in ["true", "yes", "1", "enable", "y"]:
        return True
    elif value in ["false", "no", "0", "disable", "n"]:
        return False
    else:
        return default

# ============================
# Debug Mode
# ============================
DEBUG_MODE = is_enabled(environ.get("DEBUG_MODE", "False"), False)

# ============================
# Timezone
# ============================
TIMEZONE = environ.get("TIMEZONE", "Asia/Kolkata")

# ============================
# Bot Information
# ============================
BOT_NAME = environ.get('BOT_NAME', 'DOWNTOWN VILLA')
BOT_LINK = environ.get('BOT_LINK', 'https://t.me/DownTownVillaBot')
BRAND_NAME = environ.get('BRAND_NAME', 'DOWNTOWN VILLA')
BRAND_LOGO = environ.get('BRAND_LOGO', 'https://example.com/logo.png')

SESSION = environ.get('SESSION', 'down_town_villa_search')
API_ID = int(environ.get('API_ID', ''))
API_HASH = environ.get('API_HASH', '')
BOT_TOKEN = environ.get('BOT_TOKEN', "")

# ============================
# Admin Permissions (multi-level)
# ============================
OWNER_IDS = [int(x) if x.isdigit() else x for x in environ.get('OWNER_IDS', '').split()]
ADMIN_IDS = [int(x) if x.isdigit() else x for x in environ.get('ADMIN_IDS', '').split()]
SUDO_IDS  = [int(x) if x.isdigit() else x for x in environ.get('SUDO_IDS', '').split()]
ADMINS = list(set(OWNER_IDS + ADMIN_IDS + SUDO_IDS))

def has_permission(user_id, level="admin"):
    if user_id in OWNER_IDS:
        return True
    if level in ("owner", "admin", "sudo"):
        return user_id in ADMIN_IDS or user_id in SUDO_IDS
    return user_id in ADMINS

# ============================
# Channel Groups
# ============================
STORAGE_CHANNELS = [int(c) if c.isdigit() else c for c in environ.get('STORAGE_CHANNELS', '').split()]
SEARCH_CHANNELS = [int(c) if c.isdigit() else c for c in environ.get('SEARCH_CHANNELS', '').split()]
LOG_CHANNELS     = [int(c) if c.isdigit() else c for c in environ.get('LOG_CHANNELS', '').split()]
# Backward compatibility: singular LOG_CHANNEL (first entry if exists)
LOG_CHANNEL = LOG_CHANNELS[0] if LOG_CHANNELS else None
BROADCAST_CHANNELS = [int(c) if c.isdigit() else c for c in environ.get('BROADCAST_CHANNELS', '').split()]
FORCE_SUB_CHANNELS = [int(c) if c.isdigit() else c for c in environ.get('FORCE_SUB_CHANNELS', '').split()]
UPDATE_CHANNELS  = [int(c) if c.isdigit() else c for c in environ.get('UPDATE_CHANNELS', '').split()]
CHANNELS = STORAGE_CHANNELS + SEARCH_CHANNELS + UPDATE_CHANNELS

# ============================
# Logging Configuration
# ============================
LOG_LEVEL = environ.get('LOG_LEVEL', 'INFO').upper()
LOG_SYSTEM_CHANNEL = int(environ.get('LOG_SYSTEM_CHANNEL', '-100')) or None
LOG_ERROR_CHANNEL = int(environ.get('LOG_ERROR_CHANNEL', '-100')) or None
LOG_ADMIN_CHANNEL = int(environ.get('LOG_ADMIN_CHANNEL', '-100')) or None
LOG_BROADCAST_CHANNEL = int(environ.get('LOG_BROADCAST_CHANNEL', '-100')) or None
LOG_VERIFICATION_CHANNEL = int(environ.get('LOG_VERIFICATION_CHANNEL', '-100')) or None
LOG_DATABASE_CHANNEL = int(environ.get('LOG_DATABASE_CHANNEL', '-100')) or None

# ============================
# Feature Flags
# ============================
AUTO_FILTER_ENABLED = is_enabled(environ.get('AUTO_FILTER_ENABLED', 'True'), True)
BROADCAST_ENABLED = is_enabled(environ.get('BROADCAST_ENABLED', 'True'), True)
SUPERBROADCAST_ENABLED = is_enabled(environ.get('SUPERBROADCAST_ENABLED', 'True'), True)
PREMIUM_ENABLED = is_enabled(environ.get('PREMIUM_ENABLED', 'True'), True)
VERIFICATION_ENABLED = is_enabled(environ.get('VERIFICATION_ENABLED', 'True'), True)
STREAM_ENABLED = is_enabled(environ.get('STREAM_ENABLED', 'True'), True)
ADMIN_PANEL_ENABLED = is_enabled(environ.get('ADMIN_PANEL_ENABLED', 'True'), True)
TMDB_ENABLED = is_enabled(environ.get('TMDB_ENABLED', 'True'), True)
MAINTENANCE_ENABLED = is_enabled(environ.get('MAINTENANCE_ENABLED', 'False'), False)

# ============================
# MongoDB – Unlimited DB Support
# ============================
DATABASE_NAME = environ.get('DATABASE_NAME', "Cluster0")
COLLECTION_NAME = environ.get('COLLECTION_NAME', 'downtown_villa_files')

_uri_1 = environ.get('DATABASE_URI', '')
_uri_2 = environ.get('DATABASE_URI_1', _uri_1)
_uri_3 = environ.get('DATABASE_URI_2', _uri_2)
_uri_4 = environ.get('DATABASE_URI_3', _uri_3)
_uri_5 = environ.get('DATABASE_URI_4', _uri_4)
_uri_6 = environ.get('DATABASE_URI_5', _uri_5)
_uri_7 = environ.get('DATABASE_URI_6', _uri_6)
_uri_8 = environ.get('DATABASE_URI_7', _uri_7)
_uri_9 = environ.get('DATABASE_URI_8', _uri_8)
_uri_10 = environ.get('DATABASE_URI_9', _uri_9)

_ALL_URIS = [_uri_1, _uri_2, _uri_3, _uri_4, _uri_5, _uri_6, _uri_7, _uri_8, _uri_9, _uri_10]
_DB_URIS = []
_seen = set()
for uri in _ALL_URIS:
    if uri and uri not in _seen:
        _DB_URIS.append(uri)
        _seen.add(uri)

if not _DB_URIS:
    _DB_URIS = ['mongodb://localhost:27017']

DATABASE_URI = _DB_URIS[0]
MULTIPLE_DB = len(_DB_URIS) > 1 or is_enabled(environ.get('MULTIPLE_DB', "False"), False)
DATABASE_URIS = _DB_URIS
MEDIA_DATABASE_URIS = DATABASE_URIS[1:] if len(DATABASE_URIS) > 1 else DATABASE_URIS

# Legacy aliases
DATABASE_URI2 = _DB_URIS[1] if len(_DB_URIS) > 1 else DATABASE_URI
DATABASE_URI3 = _DB_URIS[2] if len(_DB_URIS) > 2 else DATABASE_URI2

# Database Health
DB_CONNECTION_TIMEOUT = int(environ.get('DB_CONNECTION_TIMEOUT', '5000'))
DB_RETRY_COUNT = int(environ.get('DB_RETRY_COUNT', '3'))
DB_HEALTH_CHECK_INTERVAL = int(environ.get('DB_HEALTH_CHECK_INTERVAL', '60'))
DB_OPERATION_TIMEOUT = int(environ.get('DB_OPERATION_TIMEOUT', '10'))
DB_AUTO_RECONNECT = is_enabled(environ.get('DB_AUTO_RECONNECT', 'True'), True)

# ============================
# Broadcast Settings
# ============================
BROADCAST_MAX_CONCURRENT = int(environ.get('BROADCAST_MAX_CONCURRENT', '3'))
BROADCAST_RETRY_COUNT = int(environ.get('BROADCAST_RETRY_COUNT', '3'))
BROADCAST_FLOOD_WAIT_MODE = environ.get('BROADCAST_FLOOD_WAIT_MODE', 'wait')
BROADCAST_DELAY = int(environ.get('BROADCAST_DELAY', '1'))
BROADCAST_BATCH_SIZE = int(environ.get('BROADCAST_BATCH_SIZE', '100'))
BROADCAST_PROGRESS_INTERVAL = int(environ.get('BROADCAST_PROGRESS_INTERVAL', '5'))

# ============================
# Auto-Delete Configuration
# ============================
AUTO_DELETE_ENABLED = is_enabled(environ.get('AUTO_DELETE_ENABLED', 'True'), True)
DELETE_TIME = int(environ.get('DELETE_TIME', '300'))
DELETE_WARNING = environ.get('DELETE_WARNING', "⚠️ This file will be automatically deleted after {} seconds.")
DELETE_WARNING_ENABLED = is_enabled(environ.get('DELETE_WARNING_ENABLED', 'True'), True)

# ============================
# File / Search Configuration
# ============================
MAX_SEARCH_RESULTS = int(environ.get('MAX_SEARCH_RESULTS', '10'))
MAX_BUTTONS_PER_PAGE = int(environ.get('MAX_BUTTONS_PER_PAGE', '10'))
PAGINATION_SIZE = int(environ.get('PAGINATION_SIZE', '10'))
SEARCH_CACHE_DURATION = int(environ.get('SEARCH_CACHE_DURATION', '60'))
MAX_INDEXED_FILE_SIZE = int(environ.get('MAX_INDEXED_FILE_SIZE', '0'))
SUPPORTED_MEDIA_TYPES = environ.get('SUPPORTED_MEDIA_TYPES', 'video,audio,document').split(',')

# ============================
# Session / Temporary Storage
# ============================
SESSION_TIMEOUT = int(environ.get('SESSION_TIMEOUT', '1800'))
BROADCAST_SESSION_TIMEOUT = int(environ.get('BROADCAST_SESSION_TIMEOUT', '3600'))
CALLBACK_EXPIRATION = int(environ.get('CALLBACK_EXPIRATION', '1800'))

# ============================
# Verification Settings
# ============================
IS_VERIFY = is_enabled(environ.get('IS_VERIFY', 'False'), False)
TWO_VERIFY_GAP = int(environ.get('TWO_VERIFY_GAP', "1200"))
THREE_VERIFY_GAP = int(environ.get('THREE_VERIFY_GAP', "54000"))
TUTORIAL = environ.get("TUTORIAL", "https://t.me/DownTownVilla")
TUTORIAL_2 = environ.get("TUTORIAL_2", "https://t.me/DownTownVilla")
TUTORIAL_3 = environ.get("TUTORIAL_3", "https://t.me/DownTownVilla")
LOG_VR_CHANNEL = int(environ.get('LOG_VR_CHANNEL', '-100'))
VERIFY_IMG = environ.get("VERIFY_IMG", "https://telegra.ph/file/9ecc5d6e4df5b83424896.jpg")

# ============================
# Shortener Settings
# ============================
SHORTENER_API = environ.get("SHORTENER_API", "")
SHORTENER_WEBSITE = environ.get("SHORTENER_WEBSITE", "")
SHORTENER_API2 = environ.get("SHORTENER_API2", "")
SHORTENER_WEBSITE2 = environ.get("SHORTENER_WEBSITE2", "")
SHORTENER_API3 = environ.get("SHORTENER_API3", "")
SHORTENER_WEBSITE3 = environ.get("SHORTENER_WEBSITE3", "")

# ============================
# Premium Settings
# ============================
PREMIUM_LOGS = int(environ.get('PREMIUM_LOGS', '-100'))
QR_CODE = environ.get('QR_CODE', 'https://graph.org/file/e419f801841c2ee3db0fc.jpg')
OWNER_UPI_ID = environ.get('OWNER_UPI_ID', 'not_set')
STAR_PREMIUM_PLANS = {10: "7day", 20: "15day", 40: "1month", 55: "45day", 75: "60day"}

# ============================
# IMDb / TMDB Settings
# ============================
IMDB = is_enabled(environ.get('IMDB', 'True'), False)
TMDB_API_KEY = environ.get('TMDB_API_KEY', '')
TMDB_POSTER = is_enabled(environ.get('TMDB_POSTER', 'True'), True)
LANDSCAPE_POSTER = is_enabled(environ.get('LANDSCAPE_POSTER', 'True'), True)
IMDB_TEMPLATE = environ.get("IMDB_TEMPLATE", "<b>{title} ({year})</b>\n{rating} / 10")

# ============================
# Misc Settings
# ============================
PM_SEARCH = is_enabled(environ.get('PM_SEARCH', "True"), True)
AUTO_FFILTER = is_enabled(environ.get('AUTO_FFILTER', "True"), True)
SPELL_CHECK_REPLY = is_enabled(environ.get("SPELL_CHECK_REPLY", "True"), True)
MELCOW_NEW_USERS = is_enabled(environ.get('MELCOW_NEW_USERS', "False"), False)
PROTECT_CONTENT = is_enabled(environ.get('PROTECT_CONTENT', "False"), False)
EMOJI_MODE = is_enabled(environ.get('EMOJI_MODE', "True"), True)
BUTTON_MODE = is_enabled(environ.get('BUTTON_MODE', "False"), False)
STREAM_MODE = is_enabled(environ.get('STREAM_MODE', "True"), True)
PREMIUM_STREAM_MODE = is_enabled(environ.get('PREMIUM_STREAM_MODE', "False"), False)
ULTRA_FAST_MODE = is_enabled(environ.get('ULTRA_FAST_MODE', "False"), True)
CUSTOM_FILE_CAPTION = environ.get("CUSTOM_FILE_CAPTION", "<b>{file_name}</b>")
MAX_B_TN = environ.get("MAX_B_TN", "5")

# ============================
# Maintenance Settings
# ============================
MAINTENANCE = is_enabled(environ.get('MAINTENANCE', "False"), False)
MAINTENANCE_MESSAGE = environ.get('MAINTENANCE_MESSAGE', "🚧 Service under maintenance. Please try again later.")
MAINTENANCE_ALLOW_ADMINS = is_enabled(environ.get('MAINTENANCE_ALLOW_ADMINS', "True"), True)

# ============================
# Server & Web
# ============================
ON_HEROKU = 'DYNO' in environ
APP_NAME = environ.get('APP_NAME', None) if ON_HEROKU else None
BIND_ADDRESS = getenv('WEB_SERVER_BIND_ADDRESS', '0.0.0.0')
FQDN = (
    environ.get('FQDN', BIND_ADDRESS)
    if not ON_HEROKU or environ.get('FQDN')
    else f"{APP_NAME}.herokuapp.com"
)
FQDN = re.sub(r'^https?://', '', str(FQDN)).rstrip('/')
NO_PORT = is_enabled(environ.get('NO_PORT'), False)
HAS_SSL = is_enabled(getenv('HAS_SSL'), True)
PORT = int(environ.get("PORT", "8080"))

if HAS_SSL:
    URL = f"https://{FQDN}/"
else:
    URL = f"http://{FQDN}/" if NO_PORT else f"http://{FQDN}:{PORT}/"

SLEEP_THRESHOLD = int(environ.get('SLEEP_THRESHOLD', '60'))
WORKERS = int(environ.get('WORKERS', '4'))
SESSION_NAME = str(environ.get('SESSION_NAME', 'downTownVillaBot'))
PING_INTERVAL = int(environ.get("PING_INTERVAL", "298"))

# ============================
# Environment Validation
# ============================
def validate_config():
    errors = []
    if not BOT_TOKEN:
        errors.append("BOT_TOKEN is missing")
    if not API_ID or not API_HASH:
        errors.append("API_ID / API_HASH are missing")
    if not DATABASE_URI:
        errors.append("DATABASE_URI is missing")
    if not OWNER_IDS and not ADMINS:
        errors.append("At least one OWNER_IDS or ADMINS must be set")
    if errors:
        raise ValueError("Configuration error: " + ", ".join(errors))

validate_config()
