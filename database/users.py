# ============================================================
# database/users.py – User, Group, Premium, Verification & Settings
# Uses the primary user DB (get_user_db())
# ============================================================

import logging
import time
from datetime import datetime
from typing import Optional, List, Dict, Any

from motor.motor_asyncio import AsyncIOMotorDatabase, AsyncIOMotorCollection

from database.connection import get_user_db
from config import (
    DATABASE_NAME,
    PM_SEARCH,
    AUTO_FFILTER,
    BUTTON_MODE,
    EMOJI_MODE,
    STREAM_MODE,
    PREMIUM_STREAM_MODE,
    CUSTOM_FILE_CAPTION,
    IS_VERIFY,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ============================================================
# Collections
# ============================================================
def _db() -> AsyncIOMotorDatabase:
    return get_user_db()

def _users_col() -> AsyncIOMotorCollection:
    return _db()["users"]

def _groups_col() -> AsyncIOMotorCollection:
    return _db()["groups"]

def _premium_col() -> AsyncIOMotorCollection:
    return _db()["uersz"]

def _settings_col() -> AsyncIOMotorCollection:
    return _db()["bot_settings"]

def _misc_col() -> AsyncIOMotorCollection:
    return _db()["misc"]

def _verify_col() -> AsyncIOMotorCollection:
    return _db()["verify_id"]

def _codes_col() -> AsyncIOMotorCollection:
    return _db()["codes"]

def _filename_col() -> AsyncIOMotorCollection:
    return _db()["filename"]

def _movie_updates_col() -> AsyncIOMotorCollection:
    return _db()["movie_updates"]

def _connections_col() -> AsyncIOMotorCollection:
    return _db()["connection"]

def _requests_col() -> AsyncIOMotorCollection:
    return _db()["requests"]

# ============================================================
# User Management
# ============================================================
async def add_user(user_id: int, first_name: str, last_name: str = "", username: str = None):
    try:
        data = {
            "_id": user_id,
            "first_name": first_name,
            "last_name": last_name,
            "username": username,
            "date": datetime.utcnow(),
        }
        await _users_col().update_one({"_id": user_id}, {"$set": data}, upsert=True)
        logger.info(f"[USER] Added/Updated user {user_id} ({first_name})")
    except Exception as e:
        logger.error(f"[USER] Failed to add user {user_id}: {e}")

async def is_user_exist(user_id: int) -> bool:
    try:
        return (await _users_col().find_one({"_id": user_id})) is not None
    except Exception as e:
        logger.error(f"[USER] Error checking existence for {user_id}: {e}")
        return False

async def delete_user(user_id: int):
    try:
        await _users_col().delete_one({"_id": user_id})
        logger.info(f"[USER] Deleted user {user_id}")
    except Exception as e:
        logger.error(f"[USER] Failed to delete user {user_id}: {e}")

async def get_all_users() -> List[Dict]:
    try:
        return [user async for user in _users_col().find()]
    except Exception as e:
        logger.error(f"[USER] Failed to fetch users: {e}")
        return []

async def get_user(user_id: int) -> Optional[Dict]:
    try:
        return await _users_col().find_one({"_id": user_id})
    except Exception as e:
        logger.error(f"[USER] Failed to get user {user_id}: {e}")
        return None

# ============================================================
# Group Management
# ============================================================
async def add_group(group_id: int, title: str, username: str = None):
    try:
        data = {
            "_id": group_id,
            "title": title,
            "username": username,
            "date": datetime.utcnow(),
        }
        await _groups_col().update_one({"_id": group_id}, {"$set": data}, upsert=True)
        logger.info(f"[GROUP] Added/Updated group {group_id} ({title})")
    except Exception as e:
        logger.error(f"[GROUP] Failed to add group {group_id}: {e}")

async def is_group_exist(group_id: int) -> bool:
    try:
        return (await _groups_col().find_one({"_id": group_id})) is not None
    except Exception as e:
        logger.error(f"[GROUP] Error checking existence for {group_id}: {e}")
        return False

async def delete_group(group_id: int):
    try:
        await _groups_col().delete_one({"_id": group_id})
        logger.info(f"[GROUP] Deleted group {group_id}")
    except Exception as e:
        logger.error(f"[GROUP] Failed to delete group {group_id}: {e}")

async def get_all_groups() -> List[Dict]:
    try:
        return [group async for group in _groups_col().find()]
    except Exception as e:
        logger.error(f"[GROUP] Failed to fetch groups: {e}")
        return []

# ============================================================
# Premium Management
# ============================================================
async def add_premium(user_id: int, expiry: datetime):
    try:
        await _premium_col().update_one(
            {"_id": user_id},
            {"$set": {"expiry_time": expiry}},
            upsert=True,
        )
        logger.info(f"[PREMIUM] Added premium for {user_id} until {expiry}")
    except Exception as e:
        logger.error(f"[PREMIUM] Failed to add premium for {user_id}: {e}")

async def remove_premium(user_id: int):
    try:
        await _premium_col().delete_one({"_id": user_id})
        logger.info(f"[PREMIUM] Removed premium for {user_id}")
    except Exception as e:
        logger.error(f"[PREMIUM] Failed to remove premium for {user_id}: {e}")

async def is_premium(user_id: int) -> bool:
    try:
        doc = await _premium_col().find_one({"_id": user_id})
        if doc and doc.get("expiry_time") and doc["expiry_time"] > datetime.utcnow():
            return True
        return False
    except Exception as e:
        logger.error(f"[PREMIUM] Error checking premium for {user_id}: {e}")
        return False

async def get_premium_users() -> List[Dict]:
    try:
        return [doc async for doc in _premium_col().find({"expiry_time": {"$gt": datetime.utcnow()}})]
    except Exception as e:
        logger.error(f"[PREMIUM] Failed to fetch premium users: {e}")
        return []

async def check_expired_premium():
    try:
        await _premium_col().delete_many({"expiry_time": {"$lte": datetime.utcnow()}})
        logger.info("[PREMIUM] Cleaned expired premium users")
    except Exception as e:
        logger.error(f"[PREMIUM] Failed to clean expired premium: {e}")

# ============================================================
# Verification System
# ============================================================
async def set_verify_status(user_id: int, stage: int):
    try:
        await _verify_col().update_one(
            {"_id": user_id},
            {"$set": {"stage": stage, "timestamp": time.time()}},
            upsert=True,
        )
        logger.info(f"[VERIFY] Set verification stage {stage} for user {user_id}")
    except Exception as e:
        logger.error(f"[VERIFY] Failed to set verification for {user_id}: {e}")

async def get_verify_status(user_id: int) -> Optional[Dict]:
    try:
        return await _verify_col().find_one({"_id": user_id})
    except Exception as e:
        logger.error(f"[VERIFY] Failed to get verification for {user_id}: {e}")
        return None

async def reset_verification(user_id: int):
    try:
        await _verify_col().delete_one({"_id": user_id})
        logger.info(f"[VERIFY] Reset verification for user {user_id}")
    except Exception as e:
        logger.error(f"[VERIFY] Failed to reset verification for {user_id}: {e}")

# ============================================================
# Settings (Global & Group)
# ============================================================
async def get_settings(group_id: int) -> Dict:
    try:
        settings = await _settings_col().find_one({"_id": group_id})
        if not settings:
            settings = {}
        defaults = {
            "imdb": True,
            "spell_check": True,
            "max_btn": False,
            "auto_delete": True,
            "protection": False,
            "pm_search": PM_SEARCH,
            "auto_filter": AUTO_FFILTER,
            "button_mode": BUTTON_MODE,
            "emoji_mode": EMOJI_MODE,
            "stream_mode": STREAM_MODE,
            "premium_stream": PREMIUM_STREAM_MODE,
            "caption": CUSTOM_FILE_CAPTION,
        }
        defaults.update(settings)
        return defaults
    except Exception as e:
        logger.error(f"[SETTINGS] Failed to get settings for {group_id}: {e}")
        return {}

async def save_group_settings(group_id: int, key: str, value: Any):
    try:
        await _settings_col().update_one(
            {"_id": group_id},
            {"$set": {key: value}},
            upsert=True,
        )
        logger.info(f"[SETTINGS] Saved {key}={value} for group {group_id}")
    except Exception as e:
        logger.error(f"[SETTINGS] Failed to save setting for {group_id}: {e}")

async def reset_group_settings(group_id: int):
    try:
        await _settings_col().delete_one({"_id": group_id})
        logger.info(f"[SETTINGS] Reset settings for group {group_id}")
    except Exception as e:
        logger.error(f"[SETTINGS] Failed to reset settings for {group_id}: {e}")

# ============================================================
# Banned / Connections / Misc
# ============================================================
async def get_banned() -> tuple:
    try:
        banned_users = []
        banned_chats = []
        async for doc in _misc_col().find({"type": "banned_user"}):
            banned_users.append(doc["user_id"])
        async for doc in _misc_col().find({"type": "banned_chat"}):
            banned_chats.append(doc["chat_id"])
        return banned_users, banned_chats
    except Exception as e:
        logger.error(f"[MISC] Failed to get banned lists: {e}")
        return [], []

async def set_banned_user(user_id: int, ban: bool = True):
    try:
        if ban:
            await _misc_col().update_one(
                {"type": "banned_user", "user_id": user_id},
                {"$set": {"user_id": user_id}},
                upsert=True,
            )
        else:
            await _misc_col().delete_one({"type": "banned_user", "user_id": user_id})
        logger.info(f"[MISC] Set banned user {user_id}: {ban}")
    except Exception as e:
        logger.error(f"[MISC] Failed to update banned user {user_id}: {e}")

async def set_banned_chat(chat_id: int, ban: bool = True):
    try:
        if ban:
            await _misc_col().update_one(
                {"type": "banned_chat", "chat_id": chat_id},
                {"$set": {"chat_id": chat_id}},
                upsert=True,
            )
        else:
            await _misc_col().delete_one({"type": "banned_chat", "chat_id": chat_id})
        logger.info(f"[MISC] Set banned chat {chat_id}: {ban}")
    except Exception as e:
        logger.error(f"[MISC] Failed to update banned chat {chat_id}: {e}")

async def add_connection(chat_id: int, user_id: int):
    try:
        await _connections_col().update_one(
            {"user_id": user_id, "chat_id": chat_id},
            {"$set": {"chat_id": chat_id}},
            upsert=True,
        )
        logger.info(f"[CONNECTION] Added connection {chat_id} for user {user_id}")
    except Exception as e:
        logger.error(f"[CONNECTION] Failed to add connection {chat_id} for user {user_id}: {e}")

async def remove_connection(chat_id: int, user_id: int):
    try:
        await _connections_col().delete_one({"user_id": user_id, "chat_id": chat_id})
        logger.info(f"[CONNECTION] Removed connection {chat_id} for user {user_id}")
    except Exception as e:
        logger.error(f"[CONNECTION] Failed to remove connection {chat_id} for user {user_id}: {e}")

# ============================================================
# Additional (if needed) – you can add more methods from old file
# ============================================================