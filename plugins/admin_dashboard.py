# plugins/admin_dashboard.py
"""
🏨 DOWNTOWN VILLA — ULTIMATE DATABASE CONTROL CENTER
====================================================
Complete live MongoDB control center inside Telegram.
- Admin only
- Real MongoDB statistics (dbStats, collStats, buildInfo, ping, listCollections)
- Live auto-refresh with bounded background task
- Multi-confirmation destructive actions
- Secret redaction, audit logging, caching
Single-file implementation.
"""
import asyncio
import logging
import re
import time
from collections import deque
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from pyrogram import Client, filters
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from core.config import ADMINS
from database import db_registry

logger = logging.getLogger(__name__)

# ============================ CONSTANTS ============================
IST = timezone(timedelta(hours=5, minutes=30))
BAR_FULL = "█"
BAR_EMPTY = "░"
BAR_WIDTH = 20
MAX_LATENCY_HISTORY = 30

CACHE_TTL = 10                # seconds
LIVE_REFRESH_DEFAULT = 10     # seconds
LIVE_REFRESH_OPTIONS = [5, 10, 15, 30, 60]
RECENT_DOC_LIMITS = [5, 10, 20]
COLLECTIONS_PAGE_SIZE = 25

SENSITIVE_KEY_PATTERN = re.compile(
    r"(token|password|secret|api[_-]?key|api[_-]?hash|session|uri|database_uri|dsn|auth)",
    re.IGNORECASE,
)
CONN_STRING_PATTERN = re.compile(r"mongodb(\+srv)?://[^\s'\"]+", re.IGNORECASE)


# ============================ HELPERS ============================
def format_bytes(size: Optional[int]) -> str:
    if not size:
        return "0 B"
    try:
        s = float(size)
    except (TypeError, ValueError):
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    i = 0
    while s >= 1024 and i < len(units) - 1:
        s /= 1024.0
        i += 1
    return f"{s:.2f} {units[i]}"


def format_int(n: Optional[int]) -> str:
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return "0"


def progress_bar(percent: float, width: int = BAR_WIDTH) -> str:
    try:
        pct = max(0.0, min(100.0, float(percent)))
    except (TypeError, ValueError):
        pct = 0.0
    filled = int(round(width * pct / 100.0))
    filled = max(0, min(width, filled))
    return BAR_FULL * filled + BAR_EMPTY * (width - filled)


def capacity_emoji(percent: float) -> str:
    try:
        p = float(percent)
    except (TypeError, ValueError):
        return "🟢"
    if p >= 95:
        return "🔴"
    if p >= 85:
        return "🟠"
    if p >= 70:
        return "🟡"
    return "🟢"


def now_ist() -> str:
    return datetime.now(IST).strftime("%I:%M:%S %p IST")


def escape(s: Any) -> str:
    if s is None:
        return ""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if SENSITIVE_KEY_PATTERN.search(str(k)):
                out[k] = "🔐 [REDACTED]"
            else:
                out[k] = redact(v)
        return out
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return CONN_STRING_PATTERN.sub("mongodb://[REDACTED]", value)
    return value


def summarize_doc(doc: Dict[str, Any], max_fields: int = 15, max_val_len: int = 120) -> str:
    safe = redact(doc)
    lines = []
    for i, (k, v) in enumerate(safe.items()):
        if i >= max_fields:
            lines.append("… (more fields truncated)")
            break
        val = str(v)
        if len(val) > max_val_len:
            val = val[: max_val_len - 1] + "…"
        lines.append(f"  <b>{escape(k)}</b>: <code>{escape(val)}</code>")
    return "\n".join(lines)


def is_admin(user_id: int) -> bool:
    try:
        return int(user_id) in [int(a) for a in ADMINS if str(a).lstrip("-").isdigit()]
    except Exception:
        return False


# ============================ CACHE ============================
class TTLCache:
    def __init__(self, ttl: int = CACHE_TTL):
        self._ttl = ttl
        self._data: Dict[str, Tuple[float, Any]] = {}

    def get(self, key: str) -> Optional[Any]:
        entry = self._data.get(key)
        if not entry:
            return None
        ts, value = entry
        if time.time() - ts > self._ttl:
            self._data.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._data[key] = (time.time(), value)

    def invalidate(self, key: Optional[str] = None) -> None:
        if key is None:
            self._data.clear()
        else:
            self._data.pop(key, None)

    async def get_or_set(self, key: str, factory) -> Any:
        cached = self.get(key)
        if cached is not None:
            return cached
        value = await factory()
        self.set(key, value)
        return value


cache = TTLCache()


# ============================ AUDIT LOG ============================
class DatabaseAuditLogger:
    """In-memory audit log + optional channel message. Never logs secrets."""
    def __init__(self, max_entries: int = 200):
        self._entries: deque = deque(maxlen=max_entries)

    async def log(self, admin_id: int, action: str, database: str = "-",
                  collection: str = "-", result: str = "-", extra: str = "") -> None:
        entry = {
            "ts": now_ist(),
            "admin": admin_id,
            "action": action,
            "database": database,
            "collection": collection,
            "result": result,
            "extra": extra,
        }
        self._entries.append(entry)
        logger.info(f"[AUDIT] admin={admin_id} action={action} db={database} "
                    f"coll={collection} result={result} {extra}")

    def recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        return list(self._entries)[-limit:][::-1]


audit = DatabaseAuditLogger()


# ============================ LATENCY HISTORY ============================
class LatencyHistory:
    def __init__(self, maxlen: int = MAX_LATENCY_HISTORY):
        self._data: Dict[str, deque] = {}
        self._maxlen = maxlen

    def record(self, key: str, ms: Optional[float]) -> None:
        if ms is None:
            return
        if key not in self._data:
            self._data[key] = deque(maxlen=self._maxlen)
        self._data[key].append(round(ms, 1))

    def stats(self, key: str) -> Dict[str, Any]:
        d = list(self._data.get(key, []))
        if not d:
            return {"current": None, "avg": None, "min": None, "max": None, "recent": []}
        return {
            "current": d[-1],
            "avg": round(sum(d) / len(d), 1),
            "min": min(d),
            "max": max(d),
            "recent": d[-10:],
        }


latency_history = LatencyHistory()


# ============================ ERROR MONITOR ============================
class DatabaseErrorMonitor:
    def __init__(self, maxlen: int = 50):
        self._errors: deque = deque(maxlen=maxlen)

    def record(self, source: str, error: str) -> None:
        safe = CONN_STRING_PATTERN.sub("mongodb://[REDACTED]", str(error))
        self._errors.append({
            "ts": now_ist(),
            "source": source,
            "error": safe[:300],
        })

    def recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        return list(self._errors)[-limit:][::-1]


error_monitor = DatabaseErrorMonitor()


# ============================ MONGO DIAGNOSTICS ============================
class MongoDiagnostics:
    @staticmethod
    async def ping(db) -> Optional[float]:
        try:
            t0 = time.time()
            await db.command("ping")
            return (time.time() - t0) * 1000.0
        except Exception as e:
            error_monitor.record("ping", str(e))
            return None

    @staticmethod
    async def db_stats(db) -> Optional[Dict[str, Any]]:
        try:
            return await db.command("dbStats")
        except Exception as e:
            error_monitor.record("dbStats", str(e))
            return None

    @staticmethod
    async def list_collections(db) -> List[str]:
        try:
            return sorted(await db.list_collection_names())
        except Exception as e:
            error_monitor.record("listCollections", str(e))
            return []

    @staticmethod
    async def build_info(db) -> Optional[str]:
        try:
            info = await db.command("buildInfo")
            return info.get("version")
        except Exception:
            return None

    @staticmethod
    async def coll_stats(db, coll: str) -> Optional[Dict[str, Any]]:
        try:
            return await db.command("collStats", coll)
        except Exception as e:
            error_monitor.record(f"collStats:{coll}", str(e))
            return None

    @staticmethod
    async def list_indexes(db, coll: str) -> List[Dict[str, Any]]:
        try:
            cursor = db[coll].list_indexes()
            items = []
            async for idx in cursor:
                items.append(idx)
            return items
        except Exception as e:
            error_monitor.record(f"listIndexes:{coll}", str(e))
            return []

    @staticmethod
    async def sample_documents(db, coll: str, limit: int = 5) -> List[Dict[str, Any]]:
        try:
            cursor = db[coll].find({}).limit(limit)
            return await cursor.to_list(length=limit)
        except Exception as e:
            error_monitor.record(f"sample:{coll}", str(e))
            return []


# ============================ STATS MANAGER ============================
class DatabaseStatsManager:
    def get_all_dbs(self) -> List[Dict[str, Any]]:
        dbs: List[Dict[str, Any]] = []
        seen_ids = set()

        system_db = db_registry.get_system_db()
        if system_db is not None:
            dbs.append({"label": "SYSTEM", "db": system_db, "name": "downtown_villa_system"})
            seen_ids.add(id(system_db))

        user_db = db_registry.get_user_db()
        if user_db is not None and id(user_db) not in seen_ids:
            dbs.append({"label": "USER", "db": user_db, "name": "downtown_villa_user"})
            seen_ids.add(id(user_db))

        media_count = db_registry.get_media_shard_count()
        for i in range(media_count):
            mdb = db_registry.get_media_db(i)
            if mdb is None or id(mdb) in seen_ids:
                continue
            dbs.append({"label": f"MEDIA_{i + 1}", "db": mdb, "name": "downtown_villa_media"})
            seen_ids.add(id(mdb))

        for i, d in enumerate(dbs, 1):
            d["index"] = i
        return dbs

    def get_db_by_index(self, idx: int) -> Optional[Dict[str, Any]]:
        for d in self.get_all_dbs():
            if d["index"] == idx:
                return d
        return None

    async def get_full_stats(self, force: bool = False) -> Dict[str, Any]:
        if not force:
            cached = cache.get("full_stats")
            if cached is not None:
                return cached
        dbs = self.get_all_dbs()
        results = await asyncio.gather(
            *[self._gather_db_stats(e) for e in dbs],
            return_exceptions=False,
        )
        totals = self._compute_totals(results)
        data = {
            "databases": results,
            "totals": totals,
            "updated": now_ist(),
            "db_count": len(results),
        }
        cache.set("full_stats", data)
        return data

    async def _gather_db_stats(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        db = entry["db"]
        out: Dict[str, Any] = {
            "index": entry["index"],
            "label": entry["label"],
            "name": entry["name"],
            "online": False,
            "ping_ms": None,
            "version": None,
            "collections": 0,
            "objects": 0,
            "data_size": 0,
            "storage_size": 0,
            "index_size": 0,
            "avg_obj_size": 0,
            "collection_names": [],
        }
        ping = await MongoDiagnostics.ping(db)
        if ping is None:
            return out
        out["online"] = True
        out["ping_ms"] = round(ping, 1)
        latency_history.record(entry["label"], ping)

        stats = await MongoDiagnostics.db_stats(db)
        if stats:
            out["collections"] = stats.get("collections", 0)
            out["objects"] = stats.get("objects", 0)
            out["data_size"] = stats.get("dataSize", 0)
            out["storage_size"] = stats.get("storageSize", 0)
            out["index_size"] = stats.get("indexSize", 0)
            out["avg_obj_size"] = stats.get("avgObjSize", 0) or 0
        out["collection_names"] = await MongoDiagnostics.list_collections(db)
        out["version"] = await MongoDiagnostics.build_info(db)
        return out

    def _compute_totals(self, dbs: List[Dict[str, Any]]) -> Dict[str, int]:
        t = {"objects": 0, "data_size": 0, "storage_size": 0, "index_size": 0, "collections": 0}
        for d in dbs:
            if not d["online"]:
                continue
            t["objects"] += d["objects"]
            t["data_size"] += d["data_size"]
            t["storage_size"] += d["storage_size"]
            t["index_size"] += d["index_size"]
            t["collections"] += d["collections"]
        return t

    async def get_media_only(self) -> Dict[str, Any]:
        cached = cache.get("media_only")
        if cached is not None:
            return cached
        dbs = [d for d in self.get_all_dbs() if d["label"].startswith("MEDIA_")]
        results = await asyncio.gather(*[self._gather_db_stats(e) for e in dbs]) if dbs else []
        total_files = sum(r["objects"] for r in results)
        total_storage = sum(r["storage_size"] for r in results)
        total_data = sum(r["data_size"] for r in results)
        data = {
            "shards": results,
            "total_files": total_files,
            "total_storage": total_storage,
            "total_data": total_data,
        }
        cache.set("media_only", data)
        return data

    async def get_user_db_stats(self) -> Dict[str, Any]:
        cached = cache.get("user_db")
        if cached is not None:
            return cached
        user_db = db_registry.get_user_db()
        if user_db is None:
            return {"available": False}
        dbs = await MongoDiagnostics.db_stats(user_db)
        names = await MongoDiagnostics.list_collections(user_db)
        counts: Dict[str, int] = {}
        for name in names:
            try:
                counts[name] = await user_db[name].estimated_document_count()
            except Exception:
                counts[name] = 0
        data = {
            "available": True,
            "name": "downtown_villa_user",
            "objects": (dbs or {}).get("objects", 0),
            "data_size": (dbs or {}).get("dataSize", 0),
            "storage_size": (dbs or {}).get("storageSize", 0),
            "index_size": (dbs or {}).get("indexSize", 0),
            "collections": names,
            "counts": counts,
        }
        cache.set("user_db", data)
        return data


stats_manager = DatabaseStatsManager()


# ============================ DUPLICATE MANAGER ============================
class DuplicateManager:
    async def scan(self, db, collection_name: str, key: str = "file_id") -> Dict[str, Any]:
        if db is None:
            return {"ok": False, "reason": "No database"}
        coll = db[collection_name]
        try:
            pipeline = [
                {"$match": {key: {"$exists": True, "$ne": None}}},
                {"$group": {"_id": f"${key}", "count": {"$sum": 1}}},
                {"$match": {"count": {"$gt": 1}}},
                {"$count": "duplicate_groups"},
            ]
            result = await coll.aggregate(pipeline).to_list(length=1)
            dup_groups = result[0]["duplicate_groups"] if result else 0
            return {"ok": True, "duplicate_groups": dup_groups, "key": key}
        except Exception as e:
            error_monitor.record("duplicate_scan", str(e))
            return {"ok": False, "reason": str(e)}


duplicate_manager = DuplicateManager()


# ============================ CONFIRMATION MANAGER ============================
class ConfirmationManager:
    """Tracks multi-step destructive confirmations per (admin, action)."""
    def __init__(self, ttl: int = 120):
        self._pending: Dict[str, Dict[str, Any]] = {}
        self._ttl = ttl

    def _key(self, admin_id: int, token: str) -> str:
        return f"{admin_id}:{token}"

    def start(self, admin_id: int, token: str, payload: Dict[str, Any]) -> None:
        self._pending[self._key(admin_id, token)] = {
            "step": 1,
            "payload": payload,
            "expires": time.time() + self._ttl,
        }

    def advance(self, admin_id: int, token: str) -> Optional[Dict[str, Any]]:
        k = self._key(admin_id, token)
        entry = self._pending.get(k)
        if not entry:
            return None
        if time.time() > entry["expires"]:
            self._pending.pop(k, None)
            return None
        entry["step"] += 1
        entry["expires"] = time.time() + self._ttl
        return entry

    def get(self, admin_id: int, token: str) -> Optional[Dict[str, Any]]:
        k = self._key(admin_id, token)
        entry = self._pending.get(k)
        if not entry:
            return None
        if time.time() > entry["expires"]:
            self._pending.pop(k, None)
            return None
        return entry

    def cancel(self, admin_id: int, token: str) -> None:
        self._pending.pop(self._key(admin_id, token), None)

    def cleanup(self) -> None:
        now = time.time()
        for k in list(self._pending.keys()):
            if self._pending[k]["expires"] < now:
                self._pending.pop(k, None)


confirmations = ConfirmationManager()


# ============================ LIVE REFRESH MANAGER ============================
class LiveRefreshManager:
    """One shared background task per admin message, cancellable."""
    def __init__(self):
        self._tasks: Dict[int, asyncio.Task] = {}
        self._state: Dict[int, Dict[str, Any]] = {}

    def is_live(self, chat_id: int) -> bool:
        return chat_id in self._tasks and not self._tasks[chat_id].done()

    def interval(self, chat_id: int) -> int:
        return self._state.get(chat_id, {}).get("interval", LIVE_REFRESH_DEFAULT)

    async def start(self, client: Client, chat_id: int, message_id: int, view: str,
                    extra: Optional[Dict[str, Any]] = None) -> None:
        await self.stop(chat_id)
        self._state[chat_id] = {"interval": self.interval(chat_id), "view": view,
                                "extra": extra or {}, "message_id": message_id}
        self._tasks[chat_id] = asyncio.create_task(
            self._loop(client, chat_id, message_id, view, extra or {})
        )

    async def stop(self, chat_id: int) -> None:
        task = self._tasks.pop(chat_id, None)
        self._state.pop(chat_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except Exception:
                pass

    def set_interval(self, chat_id: int, interval: int) -> None:
        if chat_id in self._state:
            self._state[chat_id]["interval"] = interval
        else:
            self._state[chat_id] = {"interval": interval}

    async def _loop(self, client: Client, chat_id: int, message_id: int, view: str,
                    extra: Dict[str, Any]) -> None:
        try:
            while True:
                interval = self.interval(chat_id)
                await asyncio.sleep(interval)
                try:
                    data = await stats_manager.get_full_stats(force=True)
                    text, kb = render_view(view, data, extra)
                    try:
                        await client.edit_message_text(
                            chat_id=chat_id,
                            message_id=message_id,
                            text=text,
                            reply_markup=kb,
                            parse_mode="html",
                            disable_web_page_preview=True,
                        )
                    except Exception:
                        pass
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    error_monitor.record("live_refresh", str(e))
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.warning(f"Live refresh loop error: {e}")


live_refresh = LiveRefreshManager()


# ============================ VIEW RENDERERS ============================
def render_main(data: Dict[str, Any]) -> Tuple[str, InlineKeyboardMarkup]:
    lines = [
        "🏨 <b>DOWNTOWN VILLA</b>",
        "💾 <b>DATABASE CONTROL CENTER</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"🗄️ Databases: <b>{data['db_count']}</b>",
        f"🔄 Updated: <code>{data['updated']}</code>",
        "",
    ]
    for db in data["databases"]:
        lines.append(render_db_block(db))
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    t = data["totals"]
    lines.extend([
        "📊 <b>ALL DATABASES TOTAL</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📦 Files: <code>{format_int(t['objects'])}</code>",
        f"💾 Storage: <code>{format_bytes(t['storage_size'])}</code>",
        f"📄 Data: <code>{format_bytes(t['data_size'])}</code>",
        f"🧩 Indexes: <code>{format_bytes(t['index_size'])}</code>",
        f"🗂️ Collections: <code>{format_int(t['collections'])}</code>",
        "",
        "🟢 SYSTEM HEALTHY" if all(d["online"] for d in data["databases"]) and data["databases"]
        else "🔴 SOME DATABASES OFFLINE",
    ])
    return "\n".join(lines), main_keyboard(data)


def render_db_block(db: Dict[str, Any]) -> str:
    status = "🟢" if db["online"] else "🔴"
    ping = f"{db['ping_ms']}ms" if db["ping_ms"] is not None else "—"
    return (
        f"{status} <b>DATABASE {db['index']:02d} — {db['label']}</b>\n"
        f"🏷️ Name: <code>{escape(db['name'])}</code>\n"
        f"⏱️ Ping: <code>{ping}</code>\n"
        f"📦 Documents: <code>{format_int(db['objects'])}</code>\n"
        f"💾 Storage: <code>{format_bytes(db['storage_size'])}</code>\n"
        f"📄 Data: <code>{format_bytes(db['data_size'])}</code>\n"
        f"🧩 Indexes: <code>{format_bytes(db['index_size'])}</code>\n"
        f"🗂️ Collections: <code>{format_int(db['collections'])}</code>"
    )


def render_db_detail(db: Dict[str, Any], db_extra: Optional[Dict[str, Any]] = None) -> Tuple[str, InlineKeyboardMarkup]:
    status = "🟢 ONLINE" if db["online"] else "🔴 OFFLINE"
    ping = f"{db['ping_ms']}ms" if db["ping_ms"] is not None else "—"
    version = db["version"] or "—"
    lines = [
        f"🗄️ <b>DATABASE {db['index']:02d} — {db['label']}</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🏷️ Name: <code>{escape(db['name'])}</code>",
        f"📡 Status: {status}",
        f"⏱️ Ping: <code>{ping}</code>",
        f"🍃 MongoDB: <code>{escape(version)}</code>",
        "",
        f"📦 Documents: <code>{format_int(db['objects'])}</code>",
        f"🗂️ Collections: <code>{format_int(db['collections'])}</code>",
        f"📄 Data: <code>{format_bytes(db['data_size'])}</code>",
        f"💾 Storage: <code>{format_bytes(db['storage_size'])}</code>",
        f"🧩 Indexes: <code>{format_bytes(db['index_size'])}</code>",
        f"📐 Avg Object: <code>{format_bytes(int(db['avg_obj_size'] or 0))}</code>",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "COLLECTIONS",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    names = db["collection_names"]
    if not names:
        lines.append("⚪ No collections.")
    else:
        for n in names[:30]:
            lines.append(f"• <code>{escape(n)}</code>")
        if len(names) > 30:
            lines.append(f"… and {len(names) - 30} more")
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🧱 Collections", callback_data=f"db_colls:{db['index']}:1"),
            InlineKeyboardButton("🔄 Refresh", callback_data=f"db_detail:{db['index']}"),
        ],
        [
            InlineKeyboardButton("◀️ Back", callback_data="db_main"),
            InlineKeyboardButton("🏠 Home", callback_data="db_main"),
        ],
    ])
    return "\n".join(lines), kb


def render_collections(idx: int, db: Dict[str, Any], page: int) -> Tuple[str, InlineKeyboardMarkup]:
    names = db["collection_names"]
    total = len(names)
    total_pages = max(1, (total + COLLECTIONS_PAGE_SIZE - 1) // COLLECTIONS_PAGE_SIZE)
    page = max(1, min(page, total_pages))
    start = (page - 1) * COLLECTIONS_PAGE_SIZE
    end = start + COLLECTIONS_PAGE_SIZE
    slice_ = names[start:end]
    lines = [
        f"🧱 <b>COLLECTIONS — DB {idx:02d} ({escape(db['label'])})</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"Total: <code>{total}</code>  Page: <code>{page}/{total_pages}</code>",
        "",
    ]
    if not slice_:
        lines.append("⚪ No collections.")
    for i, n in enumerate(slice_, start=start + 1):
        lines.append(f"{i}. <code>{escape(n)}</code>")
    rows = []
    for n in slice_:
        rows.append([InlineKeyboardButton(f"📄 {n[:40]}", callback_data=f"db_coll:{idx}:{n}")])
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"db_colls:{idx}:{page - 1}"))
    nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"db_colls:{idx}:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([
        InlineKeyboardButton("◀️ Back", callback_data=f"db_detail:{idx}"),
        InlineKeyboardButton("🏠 Home", callback_data="db_main"),
    ])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def render_collection_detail(idx: int, coll_name: str) -> Tuple[str, InlineKeyboardMarkup]:
    entry = stats_manager.get_db_by_index(idx)
    if not entry:
        return "❌ Database not found.", back_keyboard()
    db = entry["db"]
    stats = await MongoDiagnostics.coll_stats(db, coll_name)
    lines = [
        f"🧱 <b>COLLECTION</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📚 Name: <code>{escape(coll_name)}</code>",
    ]
    if stats:
        lines.extend([
            f"📦 Documents: <code>{format_int(stats.get('count', 0))}</code>",
            f"📄 Data: <code>{format_bytes(stats.get('size', 0))}</code>",
            f"💾 Storage: <code>{format_bytes(stats.get('storageSize', 0))}</code>",
            f"🧩 Indexes: <code>{format_bytes(stats.get('totalIndexSize', 0))}</code>",
            f"📐 Avg Object: <code>{format_bytes(int(stats.get('avgObjSize', 0) or 0))}</code>",
            f"🗂️ Indexes: <code>{len(stats.get('indexSizes', {}) or {})}</code>",
        ])
    else:
        lines.append("⚪ Statistics unavailable.")
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📄 Recent Docs", callback_data=f"db_recent:{idx}:{coll_name}"),
            InlineKeyboardButton("🔑 Indexes", callback_data=f"db_idx:{idx}:{coll_name}"),
        ],
        [
            InlineKeyboardButton("🔄 Refresh", callback_data=f"db_coll:{idx}:{coll_name}"),
            InlineKeyboardButton("◀️ Back", callback_data=f"db_colls:{idx}:1"),
        ],
        [
            InlineKeyboardButton("🏠 Home", callback_data="db_main"),
        ],
    ])
    return "\n".join(lines), kb


async def render_recent(idx: int, coll_name: str, limit: int = 5) -> Tuple[str, InlineKeyboardMarkup]:
    entry = stats_manager.get_db_by_index(idx)
    if not entry:
        return "❌ Database not found.", back_keyboard()
    db = entry["db"]
    docs = await MongoDiagnostics.sample_documents(db, coll_name, limit=limit)
    lines = [
        f"📄 <b>RECENT DOCUMENTS — {escape(coll_name)}</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"Limit: <code>{limit}</code>  Returned: <code>{len(docs)}</code>",
        "",
    ]
    if not docs:
        lines.append("⚪ No documents.")
    for i, doc in enumerate(docs, 1):
        lines.append(f"<b>Document {i}</b>")
        lines.append(summarize_doc(doc))
        lines.append("")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Limit {n}", callback_data=f"db_recent:{idx}:{coll_name}:{n}")
         for n in RECENT_DOC_LIMITS],
        [
            InlineKeyboardButton("🔄 Refresh", callback_data=f"db_recent:{idx}:{coll_name}:{limit}"),
            InlineKeyboardButton("◀️ Back", callback_data=f"db_coll:{idx}:{coll_name}"),
        ],
    ])
    return "\n".join(lines), kb


async def render_indexes(idx: int, coll_name: str) -> Tuple[str, InlineKeyboardMarkup]:
    entry = stats_manager.get_db_by_index(idx)
    if not entry:
        return "❌ Database not found.", back_keyboard()
    db = entry["db"]
    indexes = await MongoDiagnostics.list_indexes(db, coll_name)
    lines = [
        f"🔑 <b>INDEXES — {escape(coll_name)}</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    if not indexes:
        lines.append("⚪ No indexes found.")
    for i, idx_doc in enumerate(indexes, 1):
        safe = redact(idx_doc)
        lines.append(f"<b>{i}. {escape(safe.get('name', '?'))}</b>")
        lines.append(f"  Keys: <code>{escape(safe.get('key', {}))}</code>")
        if safe.get("unique"):
            lines.append("  Unique: ✅")
        if safe.get("sparse"):
            lines.append("  Sparse: ✅")
        if "expireAfterSeconds" in safe:
            lines.append(f"  TTL: <code>{safe['expireAfterSeconds']}s</code>")
        lines.append("")
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Refresh", callback_data=f"db_idx:{idx}:{coll_name}"),
            InlineKeyboardButton("◀️ Back", callback_data=f"db_coll:{idx}:{coll_name}"),
        ],
    ])
    return "\n".join(lines), kb


async def render_health(data: Dict[str, Any]) -> Tuple[str, InlineKeyboardMarkup]:
    lines = [
        "❤️ <b>DATABASE HEALTH</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    healthy = 0
    total = len(data["databases"])
    for db in data["databases"]:
        if db["online"]:
            healthy += 1
            lines.append(f"🟢 <b>{db['label']}</b> ({db['index']:02d}) — <code>{db['ping_ms']}ms</code>")
        else:
            lines.append(f"🔴 <b>{db['label']}</b> ({db['index']:02d}) — OFFLINE")
    lines.append("")
    if total == 0:
        lines.append("⚪ No databases configured.")
    elif healthy == total:
        lines.append("🟢 <b>ALL DATABASES HEALTHY</b>")
    elif healthy == 0:
        lines.append("🔴 <b>ALL DATABASES DOWN</b>")
    else:
        lines.append(f"🟡 <b>PARTIAL — {healthy}/{total} HEALTHY</b>")
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Refresh", callback_data="db_health"),
            InlineKeyboardButton("🏠 Home", callback_data="db_main"),
        ],
    ])
    return "\n".join(lines), kb


async def render_performance(data: Dict[str, Any]) -> Tuple[str, InlineKeyboardMarkup]:
    lines = [
        "📈 <b>DATABASE PERFORMANCE</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    for db in data["databases"]:
        key = db["label"]
        st = latency_history.stats(key)
        cur = st["current"] if st["current"] is not None else "—"
        avg = st["avg"] if st["avg"] is not None else "—"
        mn = st["min"] if st["min"] is not None else "—"
        mx = st["max"] if st["max"] is not None else "—"
        lines.append(f"<b>{key}</b>")
        lines.append(f"  Current: <code>{cur}ms</code>  Avg: <code>{avg}ms</code>")
        lines.append(f"  Min: <code>{mn}ms</code>  Max: <code>{mx}ms</code>")
        if st["recent"]:
            lines.append(f"  Recent: <code>{' '.join(str(x) for x in st['recent'])}</code>")
        lines.append("")
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Refresh", callback_data="db_perf"),
            InlineKeyboardButton("🏠 Home", callback_data="db_main"),
        ],
    ])
    return "\n".join(lines), kb


async def render_distribution(data: Dict[str, Any]) -> Tuple[str, InlineKeyboardMarkup]:
    lines = [
        "📊 <b>DATABASE DISTRIBUTION</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    media = [d for d in data["databases"] if d["label"].startswith("MEDIA_")]
    total_files = sum(d["objects"] for d in media) or 1
    for d in media:
        pct = (d["objects"] / total_files) * 100
        bar = progress_bar(pct, 18)
        lines.append(f"{d['label']} {bar} {d['objects']:,} files ({pct:.1f}%)")
    if not media:
        lines.append("⚪ No media shards configured.")
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Refresh", callback_data="db_dist"),
            InlineKeyboardButton("🏠 Home", callback_data="db_main"),
        ],
    ])
    return "\n".join(lines), kb


async def render_media(data: Dict[str, Any]) -> Tuple[str, InlineKeyboardMarkup]:
    md = await stats_manager.get_media_only()
    lines = [
        "📁 <b>MEDIA DATABASE</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    if not md["shards"]:
        lines.append("⚪ No media shards configured.")
    for shard in md["shards"]:
        status = "🟢" if shard["online"] else "🔴"
        lines.append(f"{status} <b>{shard['label']}</b>")
        lines.append(f"  📦 Files: <code>{format_int(shard['objects'])}</code>")
        lines.append(f"  💾 Storage: <code>{format_bytes(shard['storage_size'])}</code>")
        lines.append("")
    lines.extend([
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "📊 <b>TOTAL MEDIA</b>",
        f"📦 Files: <code>{format_int(md['total_files'])}</code>",
        f"💾 Storage: <code>{format_bytes(md['total_storage'])}</code>",
    ])
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Refresh", callback_data="db_media"),
            InlineKeyboardButton("🏠 Home", callback_data="db_main"),
        ],
    ])
    return "\n".join(lines), kb


async def render_user_db() -> Tuple[str, InlineKeyboardMarkup]:
    ud = await stats_manager.get_user_db_stats()
    if not ud.get("available"):
        return "⚪ User database not available.", back_keyboard()
    lines = [
        "👥 <b>USER DATABASE</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🏷️ Name: <code>{escape(ud['name'])}</code>",
        f"📦 Documents: <code>{format_int(ud['objects'])}</code>",
        f"💾 Storage: <code>{format_bytes(ud['storage_size'])}</code>",
        f"📄 Data: <code>{format_bytes(ud['data_size'])}</code>",
        f"🧩 Indexes: <code>{format_bytes(ud['index_size'])}</code>",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "COLLECTION COUNTS",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    for name in ud["collections"]:
        lines.append(f"• <code>{escape(name)}</code>: {format_int(ud['counts'].get(name, 0))}")
    if not ud["collections"]:
        lines.append("⚪ No collections.")
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Refresh", callback_data="db_user"),
            InlineKeyboardButton("🏠 Home", callback_data="db_main"),
        ],
    ])
    return "\n".join(lines), kb


async def render_errors() -> Tuple[str, InlineKeyboardMarkup]:
    errs = error_monitor.recent(20)
    lines = [
        "🚨 <b>DATABASE ERRORS</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    if not errs:
        lines.append("🟢 No recent errors.")
    for e in errs:
        lines.append(f"⏱️ <code>{e['ts']}</code>")
        lines.append(f"📍 <b>{escape(e['source'])}</b>")
        lines.append(f"<code>{escape(e['error'])}</code>")
        lines.append("")
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Refresh", callback_data="db_errors"),
            InlineKeyboardButton("🏠 Home", callback_data="db_main"),
        ],
    ])
    return "\n".join(lines), kb


async def render_audit() -> Tuple[str, InlineKeyboardMarkup]:
    entries = audit.recent(20)
    lines = [
        "🛡 <b>AUDIT LOG</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    if not entries:
        lines.append("⚪ No audit entries.")
    for e in entries:
        lines.append(f"⏱️ <code>{e['ts']}</code>")
        lines.append(
            f"👤 <code>{e['admin']}</code> • <b>{escape(e['action'])}</b>"
        )
        lines.append(
            f"🗄️ <code>{escape(e['database'])}</code> / <code>{escape(e['collection'])}</code>"
        )
        lines.append(f"✅ Result: <code>{escape(e['result'])}</code>")
        if e["extra"]:
            lines.append(f"ℹ️ {escape(e['extra'])}")
        lines.append("")
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Refresh", callback_data="db_audit"),
            InlineKeyboardButton("🏠 Home", callback_data="db_main"),
        ],
    ])
    return "\n".join(lines), kb


async def render_config(data: Dict[str, Any]) -> Tuple[str, InlineKeyboardMarkup]:
    lines = [
        "🧪 <b>DATABASE CONFIGURATION</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    for d in data["databases"]:
        lines.append(f"{'🟢' if d['online'] else '🔴'} {d['label']}: "
                     f"{'CONFIGURED' if d['online'] else 'OFFLINE'}")
    lines.append("")
    lines.append(f"🔄 Live refresh: <code>{LIVE_REFRESH_DEFAULT}s</code> default")
    lines.append(f"💾 Cache TTL: <code>{CACHE_TTL}s</code>")
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Refresh", callback_data="db_config"),
            InlineKeyboardButton("🏠 Home", callback_data="db_main"),
        ],
    ])
    return "\n".join(lines), kb


async def render_duplicates() -> Tuple[str, InlineKeyboardMarkup]:
    data = await stats_manager.get_full_stats()
    media = [d for d in data["databases"] if d["label"].startswith("MEDIA_")]
    lines = [
        "♻️ <b>DUPLICATE SCAN</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "Scanning <code>file_id</code> duplicates per shard…",
        "",
    ]
    total_dupes = 0
    for d in media:
        entry = stats_manager.get_db_by_index(d["index"])
        coll_name = None
        for name in d["collection_names"]:
            if "file" in name.lower() or "media" in name.lower():
                coll_name = name
                break
        if not coll_name and d["collection_names"]:
            coll_name = d["collection_names"][0]
        if not coll_name:
            lines.append(f"⚪ {d['label']}: no collection")
            continue
        result = await duplicate_manager.scan(entry["db"], coll_name, "file_id")
        if result.get("ok"):
            dupes = result.get("duplicate_groups", 0)
            total_dupes += dupes
            lines.append(f"🔍 {d['label']} / <code>{escape(coll_name)}</code>")
            lines.append(f"   Duplicate groups: <code>{format_int(dupes)}</code>")
        else:
            lines.append(f"🔴 {d['label']}: {escape(result.get('reason'))}")
    lines.append("")
    lines.append(f"📊 <b>Total duplicate groups: {format_int(total_dupes)}</b>")
    lines.append("")
    lines.append("⚠️ Read-only. Removal requires multi-step confirmation.")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚠️ Duplicate Removal", callback_data="db_duprem")],
        [
            InlineKeyboardButton("🔄 Rescan", callback_data="db_dups"),
            InlineKeyboardButton("🏠 Home", callback_data="db_main"),
        ],
    ])
    return "\n".join(lines), kb


# ============================ KEYBOARDS ============================
def main_keyboard(data: Dict[str, Any]) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    dbs = data["databases"]
    pair: List[InlineKeyboardButton] = []
    for db in dbs:
        emoji = "🟢" if db["online"] else "🔴"
        label = f"{emoji} DB{db['index']:02d} {db['label']}"
        pair.append(InlineKeyboardButton(label, callback_data=f"db_detail:{db['index']}"))
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)

    rows.append([
        InlineKeyboardButton("📊 DISTRIBUTION", callback_data="db_dist"),
        InlineKeyboardButton("❤️ HEALTH", callback_data="db_health"),
    ])
    rows.append([
        InlineKeyboardButton("📈 PERF", callback_data="db_perf"),
        InlineKeyboardButton("📁 MEDIA", callback_data="db_media"),
    ])
    rows.append([
        InlineKeyboardButton("👥 USER DB", callback_data="db_user"),
        InlineKeyboardButton("♻️ DUPLICATES", callback_data="db_dups"),
    ])
    rows.append([
        InlineKeyboardButton("🚨 ERRORS", callback_data="db_errors"),
        InlineKeyboardButton("🛡 AUDIT", callback_data="db_audit"),
    ])
    rows.append([
        InlineKeyboardButton("🧪 CONFIG", callback_data="db_config"),
        InlineKeyboardButton("🧹 MAINTENANCE", callback_data="db_maint"),
    ])
    rows.append([
        InlineKeyboardButton("🔄 REFRESH", callback_data="db_refresh"),
        InlineKeyboardButton("🟢 LIVE", callback_data="db_live"),
    ])
    return InlineKeyboardMarkup(rows)


def back_keyboard(target: str = "db_main") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️ Back", callback_data=target),
        InlineKeyboardButton("🏠 Home", callback_data="db_main"),
    ]])


def confirm_keyboard(token: str, step: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚠️ CONTINUE", callback_data=f"db_confirm:{token}"),
            InlineKeyboardButton("❌ CANCEL", callback_data=f"db_cancel:{token}"),
        ],
    ])


def final_confirm_keyboard(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("☢️ YES, PERMANENTLY DELETE", callback_data=f"db_confirm:{token}")],
        [InlineKeyboardButton("❌ CANCEL", callback_data=f"db_cancel:{token}")],
    ])


# ============================ VIEW ROUTER ============================
def render_view(view: str, data: Dict[str, Any], extra: Dict[str, Any]) -> Tuple[str, InlineKeyboardMarkup]:
    """Synchronous render for live refresh. Falls back if needed."""
    try:
        if view == "main":
            return render_main(data)
        if view == "health":
            return asyncio.get_event_loop().run_until_complete(render_health(data)) if False else render_health_sync(data)
        if view == "perf":
            return render_perf_sync(data)
        if view == "dist":
            return render_dist_sync(data)
        if view == "config":
            return render_config_sync(data)
        return render_main(data)
    except Exception as e:
        logger.warning(f"render_view fallback: {e}")
        return render_main(data)


def render_health_sync(data: Dict[str, Any]) -> Tuple[str, InlineKeyboardMarkup]:
    lines = ["❤️ <b>DATABASE HEALTH</b>", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"]
    healthy = 0
    total = len(data["databases"])
    for db in data["databases"]:
        if db["online"]:
            healthy += 1
            lines.append(f"🟢 <b>{db['label']}</b> ({db['index']:02d}) — <code>{db['ping_ms']}ms</code>")
        else:
            lines.append(f"🔴 <b>{db['label']}</b> ({db['index']:02d}) — OFFLINE")
    lines.append("")
    if total and healthy == total:
        lines.append("🟢 <b>ALL DATABASES HEALTHY</b>")
    elif total and healthy == 0:
        lines.append("🔴 <b>ALL DATABASES DOWN</b>")
    else:
        lines.append(f"🟡 <b>{healthy}/{total} HEALTHY</b>")
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 Refresh", callback_data="db_health"),
        InlineKeyboardButton("🏠 Home", callback_data="db_main"),
    ]])
    return "\n".join(lines), kb


def render_perf_sync(data: Dict[str, Any]) -> Tuple[str, InlineKeyboardMarkup]:
    lines = ["📈 <b>DATABASE PERFORMANCE</b>", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"]
    for db in data["databases"]:
        key = db["label"]
        st = latency_history.stats(key)
        cur = st["current"] if st["current"] is not None else "—"
        avg = st["avg"] if st["avg"] is not None else "—"
        mn = st["min"] if st["min"] is not None else "—"
        mx = st["max"] if st["max"] is not None else "—"
        lines.append(f"<b>{key}</b>")
        lines.append(f"  Cur: <code>{cur}ms</code>  Avg: <code>{avg}ms</code>  Min: <code>{mn}ms</code>  Max: <code>{mx}ms</code>")
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 Refresh", callback_data="db_perf"),
        InlineKeyboardButton("🏠 Home", callback_data="db_main"),
    ]])
    return "\n".join(lines), kb


def render_dist_sync(data: Dict[str, Any]) -> Tuple[str, InlineKeyboardMarkup]:
    lines = ["📊 <b>DATABASE DISTRIBUTION</b>", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"]
    media = [d for d in data["databases"] if d["label"].startswith("MEDIA_")]
    total_files = sum(d["objects"] for d in media) or 1
    for d in media:
        pct = (d["objects"] / total_files) * 100
        bar = progress_bar(pct, 18)
        lines.append(f"{d['label']} {bar} {d['objects']:,} ({pct:.1f}%)")
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 Refresh", callback_data="db_dist"),
        InlineKeyboardButton("🏠 Home", callback_data="db_main"),
    ]])
    return "\n".join(lines), kb


def render_config_sync(data: Dict[str, Any]) -> Tuple[str, InlineKeyboardMarkup]:
    lines = ["🧪 <b>DATABASE CONFIGURATION</b>", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"]
    for d in data["databases"]:
        lines.append(f"{'🟢' if d['online'] else '🔴'} {d['label']}")
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 Refresh", callback_data="db_config"),
        InlineKeyboardButton("🏠 Home", callback_data="db_main"),
    ]])
    return "\n".join(lines), kb


# ============================ HANDLERS ============================
@Client.on_message(filters.command("database") & filters.private)
async def cmd_database(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        await message.reply_text("⛔ Unauthorized.")
        return
    msg = await message.reply_text("🔄 Loading database control center...")
    try:
        data = await stats_manager.get_full_stats(force=True)
    except Exception as e:
        logger.exception("cmd_database failed")
        await msg.edit_text(f"🔴 Failed: <code>{escape(e)}</code>", parse_mode="html")
        return
    text, kb = render_main(data)
    try:
        await msg.edit_text(text, reply_markup=kb, parse_mode="html",
                            disable_web_page_preview=True)
    except Exception as e:
        logger.warning(f"edit_text failed: {e}")


@Client.on_callback_query(filters.regex(r"^db_main$"))
async def cb_main(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ Unauthorized", show_alert=True); return
    await live_refresh.stop(q.message.chat.id)
    data = await stats_manager.get_full_stats(force=True)
    text, kb = render_main(data)
    try:
        await q.message.edit_text(text, reply_markup=kb, parse_mode="html",
                                  disable_web_page_preview=True)
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^db_refresh$"))
async def cb_refresh(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ Unauthorized", show_alert=True); return
    cache.invalidate()
    data = await stats_manager.get_full_stats(force=True)
    text, kb = render_main(data)
    try:
        await q.message.edit_text(text, reply_markup=kb, parse_mode="html",
                                  disable_web_page_preview=True)
    except Exception:
        pass
    await q.answer("🔄 Refreshed")


@Client.on_callback_query(filters.regex(r"^db_detail:(\d+)$"))
async def cb_detail(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ Unauthorized", show_alert=True); return
    idx = int(q.matches[0].group(1))
    data = await stats_manager.get_full_stats()
    db = next((d for d in data["databases"] if d["index"] == idx), None)
    if not db:
        await q.answer("Not found", show_alert=True); return
    text, kb = render_db_detail(db)
    try:
        await q.message.edit_text(text, reply_markup=kb, parse_mode="html",
                                  disable_web_page_preview=True)
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^db_colls:(\d+):(\d+)$"))
async def cb_colls(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ Unauthorized", show_alert=True); return
    idx = int(q.matches[0].group(1))
    page = int(q.matches[0].group(2))
    data = await stats_manager.get_full_stats()
    db = next((d for d in data["databases"] if d["index"] == idx), None)
    if not db:
        await q.answer("Not found", show_alert=True); return
    text, kb = render_collections(idx, db, page)
    try:
        await q.message.edit_text(text, reply_markup=kb, parse_mode="html",
                                  disable_web_page_preview=True)
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^db_coll:(\d+):(.+)$"))
async def cb_coll(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ Unauthorized", show_alert=True); return
    idx = int(q.matches[0].group(1))
    coll = q.matches[0].group(2)
    text, kb = await render_collection_detail(idx, coll)
    try:
        await q.message.edit_text(text, reply_markup=kb, parse_mode="html",
                                  disable_web_page_preview=True)
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^db_recent:(\d+):([^:]+)(?::(\d+))?$"))
async def cb_recent(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ Unauthorized", show_alert=True); return
    idx = int(q.matches[0].group(1))
    coll = q.matches[0].group(2)
    limit_str = q.matches[0].group(3)
    limit = int(limit_str) if limit_str else 5
    text, kb = await render_recent(idx, coll, limit)
    try:
        await q.message.edit_text(text, reply_markup=kb, parse_mode="html",
                                  disable_web_page_preview=True)
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^db_idx:(\d+):(.+)$"))
async def cb_idx(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ Unauthorized", show_alert=True); return
    idx = int(q.matches[0].group(1))
    coll = q.matches[0].group(2)
    text, kb = await render_indexes(idx, coll)
    try:
        await q.message.edit_text(text, reply_markup=kb, parse_mode="html",
                                  disable_web_page_preview=True)
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^db_health$"))
async def cb_health(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ Unauthorized", show_alert=True); return
    data = await stats_manager.get_full_stats(force=True)
    text, kb = await render_health(data)
    try:
        await q.message.edit_text(text, reply_markup=kb, parse_mode="html",
                                  disable_web_page_preview=True)
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^db_perf$"))
async def cb_perf(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ Unauthorized", show_alert=True); return
    data = await stats_manager.get_full_stats()
    text, kb = await render_performance(data)
    try:
        await q.message.edit_text(text, reply_markup=kb, parse_mode="html",
                                  disable_web_page_preview=True)
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^db_dist$"))
async def cb_dist(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ Unauthorized", show_alert=True); return
    data = await stats_manager.get_full_stats()
    text, kb = await render_distribution(data)
    try:
        await q.message.edit_text(text, reply_markup=kb, parse_mode="html",
                                  disable_web_page_preview=True)
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^db_media$"))
async def cb_media(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ Unauthorized", show_alert=True); return
    data = await stats_manager.get_full_stats()
    text, kb = await render_media(data)
    try:
        await q.message.edit_text(text, reply_markup=kb, parse_mode="html",
                                  disable_web_page_preview=True)
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^db_user$"))
async def cb_user(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ Unauthorized", show_alert=True); return
    text, kb = await render_user_db()
    try:
        await q.message.edit_text(text, reply_markup=kb, parse_mode="html",
                                  disable_web_page_preview=True)
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^db_errors$"))
async def cb_errors(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ Unauthorized", show_alert=True); return
    text, kb = await render_errors()
    try:
        await q.message.edit_text(text, reply_markup=kb, parse_mode="html",
                                  disable_web_page_preview=True)
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^db_audit$"))
async def cb_audit(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ Unauthorized", show_alert=True); return
    text, kb = await render_audit()
    try:
        await q.message.edit_text(text, reply_markup=kb, parse_mode="html",
                                  disable_web_page_preview=True)
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^db_config$"))
async def cb_config(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ Unauthorized", show_alert=True); return
    data = await stats_manager.get_full_stats()
    text, kb = await render_config(data)
    try:
        await q.message.edit_text(text, reply_markup=kb, parse_mode="html",
                                  disable_web_page_preview=True)
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^db_dups$"))
async def cb_dups(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ Unauthorized", show_alert=True); return
    await q.answer("Scanning...")
    text, kb = await render_duplicates()
    try:
        await q.message.edit_text(text, reply_markup=kb, parse_mode="html",
                                  disable_web_page_preview=True)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^db_duprem$"))
async def cb_duprem(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ Unauthorized", show_alert=True); return
    token = f"duprem:{int(time.time())}"
    confirmations.start(q.from_user.id, token, {"action": "duplicate_removal"})
    text = (
        "⚠️ <b>DUPLICATE REMOVAL</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "This action may delete database records.\n\n"
        "Continue?"
    )
    try:
        await q.message.edit_text(text, reply_markup=confirm_keyboard(token, 1),
                                  parse_mode="html")
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^db_confirm:(.+)$"))
async def cb_confirm(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ Unauthorized", show_alert=True); return
    token = q.matches[0].group(1)
    entry = confirmations.get(q.from_user.id, token)
    if not entry:
        await q.answer("⏱️ Expired or invalid.", show_alert=True); return
    step = entry["step"]
    if step < 3:
        confirmations.advance(q.from_user.id, token)
        if step == 1:
            text = (
                "🚨 <b>FINAL WARNING</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "This can permanently delete database records.\n"
                "This cannot be safely undone.\n\n"
                "Continue?"
            )
            kb = confirm_keyboard(token, 2)
        else:
            text = (
                "☢️ <b>PERMANENT DELETION</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "Click the confirmation button below to execute.\n"
                "This is irreversible."
            )
            kb = final_confirm_keyboard(token)
        try:
            await q.message.edit_text(text, reply_markup=kb, parse_mode="html")
        except Exception:
            pass
        await q.answer()
        return

    # Step 3 reached: execute
    confirmations.cancel(q.from_user.id, token)
    payload = entry["payload"]
    action = payload.get("action")
    if action == "duplicate_removal":
        await audit.log(q.from_user.id, "duplicate_removal", result="REQUESTED",
                        extra="Not executed — safe mode")
        text = (
            "⚠️ <b>DUPLICATE REMOVAL — SAFE MODE</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Removal is disabled in this build to prevent data loss.\n"
            "Scan results are read-only.\n\n"
            "Contact the developer to enable dangerous operations."
        )
        try:
            await q.message.edit_text(text, reply_markup=back_keyboard("db_dups"),
                                      parse_mode="html")
        except Exception:
            pass
        await q.answer()
        return


@Client.on_callback_query(filters.regex(r"^db_cancel:(.+)$"))
async def cb_cancel(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ Unauthorized", show_alert=True); return
    token = q.matches[0].group(1)
    confirmations.cancel(q.from_user.id, token)
    try:
        await q.message.edit_text("❌ Cancelled.", reply_markup=back_keyboard("db_main"))
    except Exception:
        pass
    await q.answer("Cancelled")


@Client.on_callback_query(filters.regex(r"^db_maint$"))
async def cb_maint(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ Unauthorized", show_alert=True); return
    text = (
        "🧹 <b>DATABASE MAINTENANCE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Safe tools only. Destructive operations are not exposed here."
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Refresh Stats", callback_data="db_refresh"),
            InlineKeyboardButton("🧹 Clear Cache", callback_data="db_clearcache"),
        ],
        [
            InlineKeyboardButton("♻️ Duplicate Scan", callback_data="db_dups"),
            InlineKeyboardButton("❤️ Health", callback_data="db_health"),
        ],
        [
            InlineKeyboardButton("🏠 Home", callback_data="db_main"),
        ],
    ])
    try:
        await q.message.edit_text(text, reply_markup=kb, parse_mode="html")
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^db_clearcache$"))
async def cb_clearcache(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ Unauthorized", show_alert=True); return
    cache.invalidate()
    await q.answer("🧹 Cache cleared", show_alert=True)


@Client.on_callback_query(filters.regex(r"^db_live$"))
async def cb_live(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ Unauthorized", show_alert=True); return
    chat_id = q.message.chat.id
    if live_refresh.is_live(chat_id):
        await live_refresh.stop(chat_id)
        await q.answer("🔴 Live monitoring OFF", show_alert=True)
        return
    rows = [
        [InlineKeyboardButton(f"{n}s", callback_data=f"db_livego:{n}")
         for n in LIVE_REFRESH_OPTIONS],
        [InlineKeyboardButton("❌ Cancel", callback_data="db_main")],
    ]
    try:
        await q.message.edit_text(
            "🟢 <b>LIVE MONITORING</b>\nChoose refresh interval:",
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode="html",
        )
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^db_livego:(\d+)$"))
async def cb_livego(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ Unauthorized", show_alert=True); return
    interval = int(q.matches[0].group(1))
    chat_id = q.message.chat.id
    live_refresh.set_interval(chat_id, interval)
    await live_refresh.start(client, chat_id, q.message.id, "main", {})
    await q.answer(f"🟢 Live ON — every {interval}s", show_alert=True)
    try:
        data = await stats_manager.get_full_stats(force=True)
        text, kb = render_main(data)
        await q.message.edit_text(text, reply_markup=kb, parse_mode="html",
                                  disable_web_page_preview=True)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^noop$"))
async def cb_noop(client: Client, q: CallbackQuery):
    await q.answer()


# ============================ CLEANUP TASK ============================
async def _cleanup_loop():
    while True:
        try:
            confirmations.cleanup()
        except Exception:
            pass
        await asyncio.sleep(60)


@Client.on_message(filters.command("database_cleanup") & filters.private)
async def cmd_cleanup(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        await message.reply_text("⛔ Unauthorized."); return
    await live_refresh.stop(message.chat.id)
    await message.reply_text("🧹 Live monitor stopped for this chat.")
