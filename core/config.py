import os
from os import environ

# ============================
# Bot Connection
# ============================
API_ID = int(environ.get('API_ID', ''))
API_HASH = environ.get('API_HASH', '')
BOT_TOKEN = environ.get('BOT_TOKEN', '')
SESSION = environ.get('SESSION', 'downtown_villa')

# ============================
# Admins
# ============================
ADMINS = [int(admin) if admin.isdigit() else admin for admin in environ.get('ADMINS', '').split()]

# ============================
# Logging
# ============================
LOG_CHANNEL = int(environ.get('LOG_CHANNEL', '-100'))
