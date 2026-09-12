# plugins/admin_dashboard.py
"""
🏨 DOWNTOWN VILLA — ULTIMATE DATABASE CONTROL CENTER
Fully hierarchical, dynamic, real-data MongoDB dashboard inside Telegram.
"""
import asyncio
import logging
import re
import time
from collections import deque
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from core.config import ADMINS
from database import db_registry

logger = logging.getLogger(__name__)

# ─────────────────────────── CONSTANTS ───────────────────────────
IST = timezone(timedelta(hours=5, minutes=30))
BAR_FULL = "█"
BAR_EMPTY = "░"
BAR_WIDTH = 20
CACHE_TTL = 10
LIVE_DEFAULT = 15
LIVE_OPTIONS = [10, 15, 30, 60]
RECENT_LIMITS = [5, 10, 20]
COLL_PAGE_SIZE = 25
MAX_LATENCY_HISTORY = 30

SENSITIVE_KEY = re.compile(
    r"(token|password|secret|api[_-]?key|api[_-]?hash|session|uri|database_uri|dsn|auth)",
    re.IGNORECASE,
)
MONGO_URI_PAT = re.compile(r"mongodb(\+srv)?://[^\s'\"]+", re.IGNORECASE)


# ─────────────────────────── HELPERS ───────────────────────────
def fmt_bytes(size: Optional[int]) -> str:
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


def fmt_int(n: Optional[int]) -> str:
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return "0"


def bar(percent: float, width: int = BAR_WIDTH) -> str:
    try:
        p = max(0.0, min(100.0, float(percent)))
    except (TypeError, ValueError):
        p = 0.0
    filled = int(round(width * p / 100.0))
    filled = max(0, min(width, filled))
    return BAR_FULL * filled + BAR_EMPTY * (width - filled)


def status_emoji(percent: float) -> str:
    try:
        p = float(percent)
    except (TypeError, ValueError):
        return "⚪"
    if p >= 100:
        return "🔴"
    if p >= 90:
        return "🔴"
    if p >= 75:
        return "🟠"
    if p >= 60:
        return "🟡"
    return "🟢"


def now_ist() -> str:
    return datetime.now(IST).strftime("%I:%M:%S %p IST")


def esc(s: Any) -> str:
    if s is None:
        return ""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def redact(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: ("🔐 [REDACTED]" if SENSITIVE_KEY.search(str(k)) else redact(val))
                for k, val in v.items()}
    if isinstance(v, list):
        return [redact(x) for x in v]
    if isinstance(v, str):
        return MONGO_URI_PAT.sub("mongodb://[REDACTED]", v)
    return v


def summarize_doc(doc: Dict[str, Any], max_fields: int = 12, max_len: int = 100) -> str:
    safe = redact(doc)
    out = []
    for i, (k, v) in enumerate(safe.items()):
        if i >= max_fields:
            out.append("  <i>… truncated</i>")
            break
        sval = str(v)
        if len(sval) > max_len:
            sval = sval[: max_len - 1] + "…"
        out.append(f"  <b>{esc(k)}</b>: <code>{esc(sval)}</code>")
    return "\n".join(out)


def is_admin(uid: int) -> bool:
    try:
        return int(uid) in [int(a) for a in ADMINS if str(a).lstrip("-").isdigit()]
    except Exception:
        return False


# ─────────────────────────── CACHE ───────────────────────────
class _Cache:
    def __init__(self, ttl: int = CACHE_TTL):
        self.ttl = ttl
        self._d: Dict[str, Tuple[float, Any]] = {}

    def get(self, k: str):
        e = self._d.get(k)
        if not e:
            return None
        if time.time() - e[0] > self.ttl:
            self._d.pop(k, None)
            return None
        return e[1]

    def set(self, k: str, v: Any) -> None:
        self._d[k] = (time.time(), v)

    def invalidate(self, k: Optional[str] = None) -> None:
        if k is None:
            self._d.clear()
        else:
            self._d.pop(k, None)


cache = _Cache()


# ─────────────────────────── ERROR MONITOR ───────────────────────────
class _ErrorMonitor:
    def __init__(self, maxlen: int = 50):
        self._q: deque = deque(maxlen=maxlen)

    def record(self, src: str, err: str) -> None:
        safe = MONGO_URI_PAT.sub("mongodb://[REDACTED]", str(err))
        self._q.append({"ts": now_ist(), "src": src, "err": safe[:280]})

    def recent(self, n: int = 20) -> List[Dict[str, Any]]:
        return list(self._q)[-n:][::-1]


errors = _ErrorMonitor()


# ─────────────────────────── LATENCY ───────────────────────────
class _Latency:
    def __init__(self, maxlen: int = MAX_LATENCY_HISTORY):
        self._d: Dict[str, deque] = {}
        self._m = maxlen

    def record(self, key: str, ms: Optional[float]) -> None:
        if ms is None:
            return
        self._d.setdefault(key, deque(maxlen=self._m)).append(round(ms, 1))

    def stats(self, key: str) -> Dict[str, Any]:
        d = list(self._d.get(key, []))
        if not d:
            return {"cur": None, "avg": None, "min": None, "max": None}
        return {"cur": d[-1], "avg": round(sum(d) / len(d), 1), "min": min(d), "max": max(d)}


latency = _Latency()


# ─────────────────────────── AUDIT ───────────────────────────
class _Audit:
    def __init__(self, maxlen: int = 200):
        self._q: deque = deque(maxlen=maxlen)

    def log(self, admin: int, action: str, target: str = "-", result: str = "-", extra: str = ""):
        self._q.append({
            "ts": now_ist(), "admin": admin, "action": action,
            "target": target, "result": result, "extra": extra,
        })
        logger.info(f"[AUDIT] admin={admin} action={action} target={target} result={result} {extra}")

    def recent(self, n: int = 20) -> List[Dict[str, Any]]:
        return list(self._q)[-n:][::-1]


audit = _Audit()


# ─────────────────────────── MONGO DIAGNOSTICS ───────────────────────────
class Diagnostics:
    @staticmethod
    async def ping(db) -> Optional[float]:
        try:
            t0 = time.time()
            await db.command("ping")
            return (time.time() - t0) * 1000.0
        except Exception as e:
            errors.record("ping", str(e))
            return None

    @staticmethod
    async def db_stats(db) -> Optional[Dict[str, Any]]:
        try:
            return await db.command("dbStats")
        except Exception as e:
            errors.record("dbStats", str(e))
            return None

    @staticmethod
    async def coll_stats(db, name: str) -> Optional[Dict[str, Any]]:
        try:
            return await db.command("collStats", name)
        except Exception as e:
            errors.record(f"collStats:{name}", str(e))
            return None

    @staticmethod
    async def list_collections(db) -> List[str]:
        try:
            return sorted(await db.list_collection_names())
        except Exception as e:
            errors.record("listCollections", str(e))
            return []

    @staticmethod
    async def build_version(db) -> Optional[str]:
        try:
            return (await db.command("buildInfo")).get("version")
        except Exception:
            return None

    @staticmethod
    async def list_indexes(db, coll: str) -> List[Dict[str, Any]]:
        try:
            out = []
            async for idx in db[coll].list_indexes():
                out.append(idx)
            return out
        except Exception as e:
            errors.record(f"listIndexes:{coll}", str(e))
            return []

    @staticmethod
    async def sample(db, coll: str, limit: int = 5) -> List[Dict[str, Any]]:
        try:
            return await db[coll].find({}).limit(limit).to_list(length=limit)
        except Exception as e:
            errors.record(f"sample:{coll}", str(e))
            return []

    @staticmethod
    async def estimate_count(db, coll: str) -> int:
        try:
            return await db[coll].estimated_document_count()
        except Exception:
            return 0


# ─────────────────────────── STATS MANAGER ───────────────────────────
class StatsManager:
    def _entries(self, cat: str) -> List:
        if cat == "system":
            return db_registry.system_entries()
        if cat == "user":
            return db_registry.user_entries()
        if cat == "media":
            return db_registry.media_entries()
        return []

    async def db_info(self, cat: str, index: int) -> Optional[Dict[str, Any]]:
        for e in self._entries(cat):
            if e.index == index:
                info = await self._gather(cat, e)
                return info
        return None

    async def category(self, cat: str) -> Dict[str, Any]:
        key = f"cat:{cat}"
        cached = cache.get(key)
        if cached:
            return cached
        entries = self._entries(cat)
        results = await asyncio.gather(*[self._gather(cat, e) for e in entries])
        totals = self._totals(results)
        data = {"items": results, "totals": totals, "updated": now_ist(),
                "count": len(results), "category": cat}
        cache.set(key, data)
        return data

    async def overall(self) -> Dict[str, Any]:
        cached = cache.get("overall")
        if cached:
            return cached
        s = await self.category("system")
        u = await self.category("user")
        m = await self.category("media")
        overall_totals = self._merge_totals([s["totals"], u["totals"], m["totals"]])
        data = {
            "system": s, "user": u, "media": m,
            "totals": overall_totals,
            "count": s["count"] + u["count"] + m["count"],
            "updated": now_ist(),
        }
        cache.set("overall", data)
        return data

    async def _gather(self, cat: str, entry) -> Dict[str, Any]:
        db = entry.db
        out = {
            "cat": cat, "index": entry.index, "label": entry.label,
            "online": False, "ping_ms": None, "version": None,
            "collections": 0, "objects": 0,
            "data_size": 0, "storage_size": 0, "index_size": 0,
            "avg_obj": 0, "collection_names": [],
        }
        p = await Diagnostics.ping(db)
        if p is None:
            return out
        out["online"] = True
        out["ping_ms"] = round(p, 1)
        latency.record(f"{cat}:{entry.label}", p)

        st = await Diagnostics.db_stats(db)
        if st:
            out["collections"] = st.get("collections", 0)
            out["objects"] = st.get("objects", 0)
            out["data_size"] = st.get("dataSize", 0)
            out["storage_size"] = st.get("storageSize", 0)
            out["index_size"] = st.get("indexSize", 0)
            out["avg_obj"] = st.get("avgObjSize", 0) or 0
        out["collection_names"] = await Diagnostics.list_collections(db)
        out["version"] = await Diagnostics.build_version(db)
        return out

    def _totals(self, items: List[Dict[str, Any]]) -> Dict[str, int]:
        t = {"objects": 0, "data_size": 0, "storage_size": 0, "index_size": 0, "collections": 0}
        for i in items:
            if not i["online"]:
                continue
            t["objects"] += i["objects"]
            t["data_size"] += i["data_size"]
            t["storage_size"] += i["storage_size"]
            t["index_size"] += i["index_size"]
            t["collections"] += i["collections"]
        return t

    def _merge_totals(self, totals: List[Dict[str, int]]) -> Dict[str, int]:
        m = {"objects": 0, "data_size": 0, "storage_size": 0, "index_size": 0, "collections": 0}
        for t in totals:
            for k in m:
                m[k] += t.get(k, 0)
        return m


stats = StatsManager()


# ─────────────────────────── LIVE MONITOR ───────────────────────────
class LiveMonitor:
    def __init__(self):
        self._tasks: Dict[int, asyncio.Task] = {}
        self._state: Dict[int, Dict[str, Any]] = {}

    def is_live(self, chat_id: int) -> bool:
        t = self._tasks.get(chat_id)
        return t is not None and not t.done()

    def interval(self, chat_id: int) -> int:
        return self._state.get(chat_id, {}).get("interval", LIVE_DEFAULT)

    async def start(self, client: Client, chat_id: int, msg_id: int, view: str, extra: Dict):
        await self.stop(chat_id)
        self._state[chat_id] = {"interval": self.interval(chat_id), "view": view, "extra": extra or {}}
        self._tasks[chat_id] = asyncio.create_task(self._loop(client, chat_id, msg_id, view, extra or {}))

    async def stop(self, chat_id: int):
        t = self._tasks.pop(chat_id, None)
        self._state.pop(chat_id, None)
        if t and not t.done():
            t.cancel()
            try:
                await t
            except Exception:
                pass

    async def _loop(self, client: Client, chat_id: int, msg_id: int, view: str, extra: Dict):
        try:
            while True:
                await asyncio.sleep(self.interval(chat_id))
                cache.invalidate()
                try:
                    text, kb = await build_view(view, extra)
                    await client.edit_message_text(
                        chat_id=chat_id, message_id=msg_id,
                        text=text, reply_markup=kb,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    pass
        except asyncio.CancelledError:
            return


live = LiveMonitor()


# ─────────────────────────── CONFIRMATION ───────────────────────────
class Confirmations:
    def __init__(self, ttl: int = 180):
        self._p: Dict[str, Dict[str, Any]] = {}
        self._ttl = ttl

    def _k(self, uid: int, tok: str) -> str:
        return f"{uid}:{tok}"

    def start(self, uid: int, tok: str, payload: Dict):
        self._p[self._k(uid, tok)] = {"step": 1, "payload": payload, "exp": time.time() + self._ttl}

    def get(self, uid: int, tok: str) -> Optional[Dict]:
        e = self._p.get(self._k(uid, tok))
        if not e:
            return None
        if time.time() > e["exp"]:
            self._p.pop(self._k(uid, tok), None)
            return None
        return e

    def advance(self, uid: int, tok: str) -> Optional[Dict]:
        e = self.get(uid, tok)
        if not e:
            return None
        e["step"] += 1
        e["exp"] = time.time() + self._ttl
        return e

    def cancel(self, uid: int, tok: str):
        self._p.pop(self._k(uid, tok), None)

    def cleanup(self):
        now = time.time()
        for k in list(self._p.keys()):
            if self._p[k]["exp"] < now:
                self._p.pop(k, None)


confirms = Confirmations()


# ─────────────────────────── DUPLICATE SCAN ───────────────────────────
async def duplicate_scan(cat: str, index: int, key: str = "file_id") -> Dict[str, Any]:
    info = await stats.db_info(cat, index)
    if not info or not info["online"]:
        return {"ok": False, "reason": "DB offline"}
    entry = None
    for e in (db_registry.system_entries() if cat == "system"
              else db_registry.user_entries() if cat == "user"
              else db_registry.media_entries()):
        if e.index == index:
            entry = e
            break
    if not entry:
        return {"ok": False, "reason": "Entry missing"}
    db = entry.db
    total_dupes = 0
    per_coll = []
    for name in info["collection_names"]:
        try:
            pipeline = [
                {"$match": {key: {"$exists": True, "$ne": None}}},
                {"$group": {"_id": f"${key}", "n": {"$sum": 1}}},
                {"$match": {"n": {"$gt": 1}}},
                {"$count": "g"},
            ]
            r = await db[name].aggregate(pipeline).to_list(length=1)
            g = r[0]["g"] if r else 0
            if g:
                per_coll.append({"name": name, "dupes": g})
                total_dupes += g
        except Exception as e:
            errors.record(f"dup:{name}", str(e))
        return {"ok": True, "total": total_dupes, "per_collection": per_coll}


# ─────────────────────────── VIEW BUILDERS ───────────────────────────
def _status(cat: str, items: List[Dict[str, Any]]) -> str:
    if not items:
        return "⚪ NO DATABASES"
    up = sum(1 for i in items if i["online"])
    if up == len(items):
        return "🟢 HEALTHY"
    if up == 0:
        return "🔴 OFFLINE"
    return f"🟡 {up}/{len(items)} ONLINE"


def _db_block(cat: str, d: Dict[str, Any]) -> str:
    status = "🟢" if d["online"] else "🔴"
    ping = f"{d['ping_ms']}ms" if d["ping_ms"] is not None else "—"
    title = f"{cat.upper()} DATABASE {d['index']:02d}"
    return "\n".join([
        f"{status} <b>{title}</b>",
        f"🏷️ CLUSTER: <code>{esc(d['label'])}</code>",
        f"⏱️ PING: <code>{ping}</code>",
        f"📦 DOCUMENTS: <code>{fmt_int(d['objects'])}</code>",
        f"💾 STORAGE: <code>{fmt_bytes(d['storage_size'])}</code>",
        f"📄 DATA: <code>{fmt_bytes(d['data_size'])}</code>",
        f"🧩 INDEXES: <code>{fmt_bytes(d['index_size'])}</code>",
        f"🗂️ COLLECTIONS: <code>{fmt_int(d['collections'])}</code>",
    ])


def _totals_block(t: Dict[str, int]) -> str:
    return "\n".join([
        "📊 <b>ALL DATABASES TOTAL</b>",
        f"📦 DOCUMENTS: <code>{fmt_int(t['objects'])}</code>",
        f"💾 STORAGE: <code>{fmt_bytes(t['storage_size'])}</code>",
        f"📄 DATA: <code>{fmt_bytes(t['data_size'])}</code>",
        f"🧩 INDEXES: <code>{fmt_bytes(t['index_size'])}</code>",
        f"🗂️ COLLECTIONS: <code>{fmt_int(t['collections'])}</code>",
    ])


def _progress_block(percent: float, label: str) -> str:
    return "\n".join([
        f"📊 <b>{label}</b>",
        f"{status_emoji(percent)} {percent:.1f}% USED",
        f"<code>{bar(percent)}</code>",
    ])


# ─────────────────────────── MAIN SCREEN ───────────────────────────
def kb_main(data: Dict[str, Any]) -> InlineKeyboardMarkup:
    s = data["system"]; u = data["user"]; m = data["media"]
    rows = [
        [InlineKeyboardButton("🖥️ SYSTEM DATABASES", callback_data="db_cat:system")],
        [InlineKeyboardButton("👥 USER DATABASES", callback_data="db_cat:user")],
        [InlineKeyboardButton("🎬 MEDIA DATABASES", callback_data="db_cat:media")],
        [InlineKeyboardButton("📊 OVERALL", callback_data="db_cat:overall")],
        [
            InlineKeyboardButton("❤️ HEALTH", callback_data="db_health:overall"),
            InlineKeyboardButton("⚡ PERFORMANCE", callback_data="db_perf:overall"),
        ],
        [
            InlineKeyboardButton("🧹 DUPLICATES", callback_data="db_dups:media:1"),
            InlineKeyboardButton("🧩 INDEXES", callback_data="db_colls:media:1:1"),
        ],
        [
            InlineKeyboardButton("📋 ACTIVITY LOG", callback_data="db_audit"),
            InlineKeyboardButton("🚨 ERRORS", callback_data="db_errors"),
        ],
        [
            InlineKeyboardButton("📡 LIVE MONITOR", callback_data="db_live"),
            InlineKeyboardButton("🔄 REFRESH", callback_data="db_refresh"),
        ],
        [InlineKeyboardButton("❌ CLOSE", callback_data="db_close")],
    ]
    return InlineKeyboardMarkup(rows)


async def view_main() -> Tuple[str, InlineKeyboardMarkup]:
    data = await stats.overall()
    s, u, m = data["system"], data["user"], data["media"]
    lines = [
        "🏨 <b>DOWNTOWN VILLA</b>",
        "💾 <b>DATABASE CONTROL CENTER</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🔄 UPDATED: <code>{data['updated']}</code>",
        "",
        f"🖥️ SYSTEM DATABASES: <b>{s['count']}</b>",
        f"👥 USER DATABASES: <b>{u['count']}</b>",
        f"🎬 MEDIA DATABASES: <b>{m['count']}</b>",
        f"🗄️ TOTAL: <b>{data['count']}</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        _totals_block(data["totals"]),
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🖥️ SYSTEM STATUS: {_status('system', s['items'])}",
        f"👥 USER STATUS: {_status('user', u['items'])}",
        f"🎬 MEDIA STATUS: {_status('media', m['items'])}",
        "",
        "📡 LIVE MONITORING: 🟢 READY",
        f"🕐 LAST UPDATE: {data['updated']}",
    ]
    return "\n".join(lines), kb_main(data)


# ─────────────────────────── CATEGORY SCREEN ───────────────────────────
def kb_category(cat: str, data: Dict[str, Any]) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    pair: List[InlineKeyboardButton] = []
    for item in data["items"]:
        emoji = "🟢" if item["online"] else "🔴"
        label = f"{emoji} {cat.upper()} DB {item['index']:02d}"
        pair.append(InlineKeyboardButton(label, callback_data=f"db_db:{cat}:{item['index']}"))
        if len(pair) == 2:
            rows.append(pair); pair = []
    if pair:
        rows.append(pair)
    rows.append([InlineKeyboardButton(f"📊 ALL {cat.upper()} DATABASES",
                                      callback_data=f"db_catall:{cat}")])
    if cat != "overall":
        rows.append([
            InlineKeyboardButton("❤️ HEALTH", callback_data=f"db_health:{cat}"),
            InlineKeyboardButton("⚡ PERFORMANCE", callback_data=f"db_perf:{cat}"),
        ])
    rows.append([
        InlineKeyboardButton("🔄 REFRESH", callback_data=f"db_cat:{cat}"),
        InlineKeyboardButton("◀️ BACK", callback_data="db_main"),
    ])
    return InlineKeyboardMarkup(rows)


async def view_category(cat: str) -> Tuple[str, InlineKeyboardMarkup]:
    if cat == "overall":
        return await view_main()
    data = await stats.category(cat)
    title = {
        "system": "🖥️ SYSTEM DATABASE CONTROL",
        "user": "👥 USER DATABASE CONTROL",
        "media": "🎬 MEDIA DATABASE CONTROL",
    }.get(cat, "DATABASE CONTROL")
    lines = [
        f"🏨 <b>DOWNTOWN VILLA</b>",
        f"<b>{title}</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📊 <b>{data['count']} CONFIGURED</b>",
        f"🔄 UPDATED: <code>{data['updated']}</code>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    if not data["items"]:
        lines.append("⚪ NO DATABASES IN THIS CATEGORY.")
    for item in data["items"]:
        lines.append(_db_block(cat, item))
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(_totals_block(data["totals"]))
    return "\n".join(lines), kb_category(cat, data)


# ─────────────────────────── INDIVIDUAL DB SCREEN ───────────────────────────
def kb_db(cat: str, index: int, db: Dict[str, Any]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🧱 COLLECTIONS", callback_data=f"db_colls:{cat}:{index}:1"),
            InlineKeyboardButton("📊 STATISTICS", callback_data=f"db_stats:{cat}:{index}"),
        ],
        [
            InlineKeyboardButton("🔍 SEARCH", callback_data=f"db_search:{cat}:{index}"),
            InlineKeyboardButton("🧹 DUPLICATES", callback_data=f"db_dups:{cat}:{index}"),
        ],
        [
            InlineKeyboardButton("🧩 INDEXES", callback_data=f"db_colls:{cat}:{index}:1"),
            InlineKeyboardButton("🗑️ CLEAR DATA", callback_data=f"db_clear:{cat}:{index}"),
        ],
        [
            InlineKeyboardButton("❤️ HEALTH", callback_data=f"db_health:{cat}"),
            InlineKeyboardButton("⚡ PERFORMANCE", callback_data=f"db_perf:{cat}"),
        ],
        [
            InlineKeyboardButton("🔄 REFRESH", callback_data=f"db_db:{cat}:{index}"),
            InlineKeyboardButton("◀️ BACK", callback_data=f"db_cat:{cat}"),
        ],
    ])


async def view_db(cat: str, index: int) -> Tuple[str, InlineKeyboardMarkup]:
    info = await stats.db_info(cat, index)
    if not info:
        return "❌ DATABASE NOT FOUND.", InlineKeyboardMarkup([[
            InlineKeyboardButton("◀️ BACK", callback_data=f"db_cat:{cat}")
        ]])
    status = "🟢 ONLINE" if info["online"] else "🔴 OFFLINE"
    ping = f"{info['ping_ms']}ms" if info["ping_ms"] is not None else "—"
    ver = info["version"] or "—"
    lines = [
        f"🏨 <b>DOWNTOWN VILLA</b>",
        f"🗄️ <b>{cat.upper()} DATABASE {info['index']:02d}</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🏷️ CLUSTER: <code>{esc(info['label'])}</code>",
        f"📡 STATUS: {status}",
        f"⏱️ PING: <code>{ping}</code>",
        f"🍃 MONGODB: <code>{esc(ver)}</code>",
        "",
        f"📦 DOCUMENTS: <code>{fmt_int(info['objects'])}</code>",
        f"🗂️ COLLECTIONS: <code>{fmt_int(info['collections'])}</code>",
        f"📄 DATA: <code>{fmt_bytes(info['data_size'])}</code>",
        f"💾 STORAGE: <code>{fmt_bytes(info['storage_size'])}</code>",
        f"🧩 INDEXES: <code>{fmt_bytes(info['index_size'])}</code>",
        f"📐 AVG OBJECT: <code>{fmt_bytes(int(info['avg_obj'] or 0))}</code>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "📚 <b>COLLECTIONS</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    names = info["collection_names"]
    if not names:
        lines.append("⚪ NO COLLECTIONS.")
    else:
        for i, n in enumerate(names[:25], 1):
            lines.append(f"{i}. <code>{esc(n)}</code>")
        if len(names) > 25:
            lines.append(f"… +{len(names) - 25} MORE")
    return "\n".join(lines), kb_db(cat, index, info)


# ─────────────────────────── COLLECTIONS EXPLORER ───────────────────────────
def kb_colls(cat: str, index: int, page: int, total_pages: int, names: List[str]) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    for n in names[:COLL_PAGE_SIZE]:
        rows.append([InlineKeyboardButton(f"📁 {n[:45]}",
                                           callback_data=f"db_coll:{cat}:{index}:{n}")])
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("◀️ PREVIOUS",
                                         callback_data=f"db_colls:{cat}:{index}:{page-1}"))
    nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="db_noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("NEXT ▶️",
                                         callback_data=f"db_colls:{cat}:{index}:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([
        InlineKeyboardButton("◀️ BACK", callback_data=f"db_db:{cat}:{index}"),
        InlineKeyboardButton("🏠 HOME", callback_data="db_main"),
    ])
    return InlineKeyboardMarkup(rows)


async def view_colls(cat: str, index: int, page: int) -> Tuple[str, InlineKeyboardMarkup]:
    info = await stats.db_info(cat, index)
    if not info:
        return "❌ DB NOT FOUND.", InlineKeyboardMarkup([[
            InlineKeyboardButton("◀️ BACK", callback_data=f"db_cat:{cat}")]])
    names = info["collection_names"]
    total = len(names)
    tp = max(1, (total + COLL_PAGE_SIZE - 1) // COLL_PAGE_SIZE)
    page = max(1, min(page, tp))
    start = (page - 1) * COLL_PAGE_SIZE
    slice_ = names[start:start + COLL_PAGE_SIZE]
    lines = [
        f"🏨 <b>DOWNTOWN VILLA</b>",
        f"🧱 <b>COLLECTIONS — {cat.upper()} DB {index:02d}</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"TOTAL: <code>{total}</code>  PAGE: <code>{page}/{tp}</code>",
        "",
    ]
    for i, n in enumerate(slice_, start=start + 1):
        lines.append(f"{i}. <code>{esc(n)}</code>")
    return "\n".join(lines), kb_colls(cat, index, page, tp, slice_)


# ─────────────────────────── COLLECTION DETAIL ───────────────────────────
def kb_coll(cat: str, index: int, name: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📄 RECENT DOCS",
                                  callback_data=f"db_recent:{cat}:{index}:{name}:5"),
            InlineKeyboardButton("🔑 INDEXES", callback_data=f"db_idx:{cat}:{index}:{name}"),
        ],
        [
            InlineKeyboardButton("🧹 FIND DUPLICATES",
                                  callback_data=f"db_dup_coll:{cat}:{index}:{name}"),
            InlineKeyboardButton("🗑️ CLEAR COLLECTION",
                                  callback_data=f"db_clear_coll:{cat}:{index}:{name}"),
        ],
        [
            InlineKeyboardButton("🔄 REFRESH", callback_data=f"db_coll:{cat}:{index}:{name}"),
            InlineKeyboardButton("◀️ BACK", callback_data=f"db_colls:{cat}:{index}:1"),
        ],
    ])


async def view_coll(cat: str, index: int, name: str) -> Tuple[str, InlineKeyboardMarkup]:
    info = await stats.db_info(cat, index)
    if not info:
        return "❌ DB NOT FOUND.", InlineKeyboardMarkup([[
            InlineKeyboardButton("◀️ BACK", callback_data=f"db_cat:{cat}")]])
    entry = None
    for e in (db_registry.system_entries() if cat == "system"
              else db_registry.user_entries() if cat == "user"
              else db_registry.media_entries()):
        if e.index == index:
            entry = e; break
    if not entry:
        return "❌ DB ENTRY MISSING.", InlineKeyboardMarkup([[
            InlineKeyboardButton("◀️ BACK", callback_data=f"db_cat:{cat}")]])
    st = await Diagnostics.coll_stats(entry.db, name)
    lines = [
        "🏨 <b>DOWNTOWN VILLA</b>",
        f"🧱 <b>COLLECTION</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📚 NAME: <code>{esc(name)}</code>",
        f"🗄️ DATABASE: {cat.upper()} {index:02d} ({esc(entry.label)})",
    ]
    if st:
        lines += [
            f"📦 DOCUMENTS: <code>{fmt_int(st.get('count', 0))}</code>",
            f"📄 DATA: <code>{fmt_bytes(st.get('size', 0))}</code>",
            f"💾 STORAGE: <code>{fmt_bytes(st.get('storageSize', 0))}</code>",
            f"🧩 INDEX SIZE: <code>{fmt_bytes(st.get('totalIndexSize', 0))}</code>",
            f"📐 AVG OBJECT: <code>{fmt_bytes(int(st.get('avgObjSize', 0) or 0))}</code>",
            f"🔑 INDEXES: <code>{len(st.get('indexSizes', {}) or {})}</code>",
        ]
    else:
        lines.append("⚪ STATISTICS UNAVAILABLE.")
    return "\n".join(lines), kb_coll(cat, index, name)


# ─────────────────────────── RECENT DOCS ───────────────────────────
async def view_recent(cat: str, index: int, name: str, limit: int) -> Tuple[str, InlineKeyboardMarkup]:
    entry = None
    for e in (db_registry.system_entries() if cat == "system"
              else db_registry.user_entries() if cat == "user"
              else db_registry.media_entries()):
        if e.index == index:
            entry = e; break
    if not entry:
        return "❌ DB NOT FOUND.", InlineKeyboardMarkup([[
            InlineKeyboardButton("◀️ BACK", callback_data=f"db_cat:{cat}")]])
    docs = await Diagnostics.sample(entry.db, name, limit)
    lines = [
        "🏨 <b>DOWNTOWN VILLA</b>",
        f"📄 <b>RECENT DOCUMENTS — {esc(name)}</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"LIMIT: <code>{limit}</code>  RETURNED: <code>{len(docs)}</code>",
        "",
    ]
    if not docs:
        lines.append("⚪ NO DOCUMENTS.")
    for i, d in enumerate(docs, 1):
        lines.append(f"<b>DOCUMENT {i}</b>")
        lines.append(summarize_doc(d))
        lines.append("")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"LIMIT {n}",
                               callback_data=f"db_recent:{cat}:{index}:{name}:{n}")
         for n in RECENT_LIMITS],
        [
            InlineKeyboardButton("🔄 REFRESH",
                                  callback_data=f"db_recent:{cat}:{index}:{name}:{limit}"),
            InlineKeyboardButton("◀️ BACK", callback_data=f"db_coll:{cat}:{index}:{name}"),
        ],
    ])
    return "\n".join(lines), kb


# ─────────────────────────── INDEXES ───────────────────────────
async def view_indexes(cat: str, index: int, name: str) -> Tuple[str, InlineKeyboardMarkup]:
    entry = None
    for e in (db_registry.system_entries() if cat == "system"
              else db_registry.user_entries() if cat == "user"
              else db_registry.media_entries()):
        if e.index == index:
            entry = e; break
    if not entry:
        return "❌ DB NOT FOUND.", InlineKeyboardMarkup([[
            InlineKeyboardButton("◀️ BACK", callback_data=f"db_cat:{cat}")]])
    idxs = await Diagnostics.list_indexes(entry.db, name)
    lines = [
        "🏨 <b>DOWNTOWN VILLA</b>",
        f"🔑 <b>INDEXES — {esc(name)}</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    if not idxs:
        lines.append("⚪ NO INDEXES.")
    for i, ix in enumerate(idxs, 1):
        safe = redact(ix)
        lines.append(f"<b>{i}. {esc(safe.get('name', '?'))}</b>")
        lines.append(f"  KEYS: <code>{esc(safe.get('key', {}))}</code>")
        if safe.get("unique"):
            lines.append("  UNIQUE: ✅")
        if safe.get("sparse"):
            lines.append("  SPARSE: ✅")
        if "expireAfterSeconds" in safe:
            lines.append(f"  TTL: <code>{safe['expireAfterSeconds']}s</code>")
        lines.append("")
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 REFRESH", callback_data=f"db_idx:{cat}:{index}:{name}"),
            InlineKeyboardButton("◀️ BACK", callback_data=f"db_coll:{cat}:{index}:{name}"),
        ],
    ])
    return "\n".join(lines), kb


# ─────────────────────────── HEALTH ───────────────────────────
async def view_health(cat: str) -> Tuple[str, InlineKeyboardMarkup]:
    if cat == "overall":
        data = await stats.overall()
        categories = [("system", data["system"]), ("user", data["user"]), ("media", data["media"])]
    else:
        c = await stats.category(cat)
        categories = [(cat, c)]
    lines = [
        "🏨 <b>DOWNTOWN VILLA</b>",
        "❤️ <b>DATABASE HEALTH</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    all_ok = True
    for name, cat_data in categories:
        up = sum(1 for i in cat_data["items"] if i["online"])
        total = len(cat_data["items"])
        if up != total or total == 0:
            all_ok = False
        lines.append(f"<b>{name.upper()}</b>: {_status(name, cat_data['items'])}")
        for i in cat_data["items"]:
            if i["online"]:
                lines.append(f"  🟢 {i['label']} — <code>{i['ping_ms']}ms</code>")
            else:
                lines.append(f"  🔴 {i['label']} — OFFLINE")
    lines.append("")
    lines.append("🟢 <b>ALL HEALTHY</b>" if all_ok else "🟡 <b>WARNINGS PRESENT</b>")
    back = "db_main" if cat == "overall" else f"db_cat:{cat}"
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 REFRESH", callback_data=f"db_health:{cat}"),
        InlineKeyboardButton("◀️ BACK", callback_data=back),
    ]])
    return "\n".join(lines), kb


# ─────────────────────────── PERFORMANCE ───────────────────────────
async def view_perf(cat: str) -> Tuple[str, InlineKeyboardMarkup]:
    if cat == "overall":
        data = await stats.overall()
        cats = [("system", data["system"]), ("user", data["user"]), ("media", data["media"])]
    else:
        c = await stats.category(cat)
        cats = [(cat, c)]
    lines = [
        "🏨 <b>DOWNTOWN VILLA</b>",
        "⚡ <b>DATABASE PERFORMANCE</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    for name, cd in cats:
        for i in cd["items"]:
            key = f"{name}:{i['label']}"
            st = latency.stats(key)
            cur = st["cur"] if st["cur"] is not None else "—"
            avg = st["avg"] if st["avg"] is not None else "—"
            mn = st["min"] if st["min"] is not None else "—"
            mx = st["max"] if st["max"] is not None else "—"
            lines.append(f"<b>{name.upper()} {i['label']}</b>")
            lines.append(f"  CUR: <code>{cur}ms</code>  AVG: <code>{avg}ms</code>")
            lines.append(f"  MIN: <code>{mn}ms</code>  MAX: <code>{mx}ms</code>")
            lines.append("")
    back = "db_main" if cat == "overall" else f"db_cat:{cat}"
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 REFRESH", callback_data=f"db_perf:{cat}"),
        InlineKeyboardButton("◀️ BACK", callback_data=back),
    ]])
    return "\n".join(lines), kb


# ─────────────────────────── DUPLICATES ───────────────────────────
def kb_dups(cat: str, index: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 START SCAN", callback_data=f"db_dup_scan:{cat}:{index}")],
        [
            InlineKeyboardButton("📊 VIEW LAST SCAN", callback_data=f"db_dup_last:{cat}:{index}"),
            InlineKeyboardButton("🗑️ REMOVE DUPLICATES", callback_data=f"db_dup_remove:{cat}:{index}"),
        ],
        [
            InlineKeyboardButton("🔄 REFRESH", callback_data=f"db_dups:{cat}:{index}"),
            InlineKeyboardButton("◀️ BACK", callback_data=f"db_db:{cat}:{index}"),
        ],
    ])


async def view_dups(cat: str, index: int) -> Tuple[str, InlineKeyboardMarkup]:
    info = await stats.db_info(cat, index)
    if not info:
        return "❌ DB NOT FOUND.", InlineKeyboardMarkup([[
            InlineKeyboardButton("◀️ BACK", callback_data="db_main")]])
    lines = [
        "🏨 <b>DOWNTOWN VILLA</b>",
        "🧹 <b>DUPLICATE CONTROL CENTER</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🗄️ TARGET: {cat.upper()} DB {index:02d} ({esc(info['label'])})",
        f"📦 TOTAL RECORDS: <code>{fmt_int(info['objects'])}</code>",
        "🔍 SCAN STATUS: <b>READY</b>",
        "",
        "PRESS <b>START SCAN</b> TO SCAN FOR DUPLICATES ON KEY <code>file_id</code>.",
        "",
        "⚠️ SCAN IS READ-ONLY. REMOVAL REQUIRES 3-STAGE CONFIRMATION.",
    ]
    return "\n".join(lines), kb_dups(cat, index)


async def view_dup_scan(cat: str, index: int) -> Tuple[str, InlineKeyboardMarkup]:
    result = await duplicate_scan(cat, index, "file_id")
    info = await stats.db_info(cat, index)
    lines = [
        "🏨 <b>DOWNTOWN VILLA</b>",
        "🧹 <b>DUPLICATE SCAN RESULT</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🗄️ TARGET: {cat.upper()} DB {index:02d}",
    ]
    if not result.get("ok"):
        lines.append(f"🔴 SCAN FAILED: {esc(result.get('reason'))}")
        return "\n".join(lines), kb_dups(cat, index)
    lines.append(f"📦 DOCUMENTS SCANNED: <code>{fmt_int(info['objects'])}</code>")
    lines.append(f"🧹 DUPLICATE GROUPS: <code>{fmt_int(result['total'])}</code>")
    lines.append("")
    if result["per_collection"]:
        lines.append("<b>PER COLLECTION:</b>")
        for pc in result["per_collection"][:20]:
            lines.append(f"• <code>{esc(pc['name'])}</code>: {fmt_int(pc['dupes'])}")
    else:
        lines.append("🟢 NO DUPLICATES FOUND.")
    return "\n".join(lines), kb_dups(cat, index)


# ─────────────────────────── ACTIVITY ───────────────────────────
async def view_audit() -> Tuple[str, InlineKeyboardMarkup]:
    entries = audit.recent(30)
    lines = [
        "🏨 <b>DOWNTOWN VILLA</b>",
        "📋 <b>ACTIVITY LOG</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    if not entries:
        lines.append("⚪ NO ACTIVITY.")
    for e in entries:
        lines.append(f"⏱️ <code>{e['ts']}</code>")
        lines.append(f"👤 <code>{e['admin']}</code> → <b>{esc(e['action'])}</b>")
        lines.append(f"🎯 TARGET: <code>{esc(e['target'])}</code>")
        lines.append(f"✅ RESULT: <code>{esc(e['result'])}</code>")
        lines.append("")
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 REFRESH", callback_data="db_audit"),
        InlineKeyboardButton("◀️ BACK", callback_data="db_main"),
    ]])
    return "\n".join(lines), kb


async def view_errors() -> Tuple[str, InlineKeyboardMarkup]:
    errs = errors.recent(20)
    lines = [
        "🏨 <b>DOWNTOWN VILLA</b>",
        "🚨 <b>DATABASE ERRORS</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    if not errs:
        lines.append("🟢 NO RECENT ERRORS.")
    for e in errs:
        lines.append(f"⏱️ <code>{e['ts']}</code>")
        lines.append(f"📍 <b>{esc(e['src'])}</b>")
        lines.append(f"<code>{esc(e['err'])}</code>")
        lines.append("")
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 REFRESH", callback_data="db_errors"),
        InlineKeyboardButton("◀️ BACK", callback_data="db_main"),
    ]])
    return "\n".join(lines), kb


# ─────────────────────────── CATEGORY TOTAL VIEW ───────────────────────────
async def view_cat_all(cat: str) -> Tuple[str, InlineKeyboardMarkup]:
    data = await stats.category(cat)
    lines = [
        f"🏨 <b>DOWNTOWN VILLA</b>",
        f"📊 <b>ALL {cat.upper()} DATABASES</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        _totals_block(data["totals"]),
        "",
    ]
    for item in data["items"]:
        lines.append(_db_block(cat, item))
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 REFRESH", callback_data=f"db_catall:{cat}"),
        InlineKeyboardButton("◀️ BACK", callback_data=f"db_cat:{cat}"),
    ]])
    return "\n".join(lines), kb


# ─────────────────────────── CLEAR DATA (DANGER ZONE) ───────────────────────────
def kb_clear(cat: str, index: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑️ CLEAR THIS DATABASE",
                               callback_data=f"db_clear_db:{cat}:{index}")],
        [
            InlineKeyboardButton("◀️ BACK", callback_data=f"db_db:{cat}:{index}"),
            InlineKeyboardButton("❌ CANCEL", callback_data="db_main"),
        ],
    ])


async def view_clear(cat: str, index: int) -> Tuple[str, InlineKeyboardMarkup]:
    info = await stats.db_info(cat, index)
    if not info:
        return "❌ DB NOT FOUND.", InlineKeyboardMarkup([[
            InlineKeyboardButton("◀️ BACK", callback_data="db_main")]])
    lines = [
        "🏨 <b>DOWNTOWN VILLA</b>",
        "☢️ <b>DANGER ZONE — CLEAR DATA</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🎯 TARGET: {cat.upper()} DB {index:02d}",
        f"📚 CLUSTER: <code>{esc(info['label'])}</code>",
        f"📦 DOCUMENTS: <code>{fmt_int(info['objects'])}</code>",
        f"💾 STORAGE: <code>{fmt_bytes(info['storage_size'])}</code>",
        "",
        "⚠️ <b>THIS WILL REMOVE ALL DOCUMENTS IN ALL COLLECTIONS.</b>",
        "⚠️ <b>THIS CANNOT BE UNDONE.</b>",
        "",
        "MULTI-STAGE CONFIRMATION REQUIRED.",
    ]
    return "\n".join(lines), kb_clear(cat, index)


async def do_clear_db(cat: str, index: int) -> Tuple[str, InlineKeyboardMarkup]:
    entry = None
    for e in (db_registry.system_entries() if cat == "system"
              else db_registry.user_entries() if cat == "user"
              else db_registry.media_entries()):
        if e.index == index:
            entry = e; break
    if not entry:
        return "❌ DB NOT FOUND.", InlineKeyboardMarkup([[
            InlineKeyboardButton("◀️ BACK", callback_data="db_main")]])
    deleted = 0
    for name in await Diagnostics.list_collections(entry.db):
        try:
            r = await entry.db[name].delete_many({})
            deleted += r.deleted_count
        except Exception as e:
            errors.record(f"clear:{name}", str(e))
    cache.invalidate()
    audit.log(0, "clear_database", target=f"{cat}:{index}", result=f"deleted={deleted}")
    lines = [
        "🏨 <b>DOWNTOWN VILLA</b>",
        "🟢 <b>OPERATION COMPLETE</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🎯 TARGET: {cat.upper()} DB {index:02d}",
        f"🗑️ DOCUMENTS REMOVED: <code>{fmt_int(deleted)}</code>",
        f"⏱️ TIME: <code>{now_ist()}</code>",
        "📊 STATISTICS REFRESHED: 🟢 YES",
    ]
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("📊 VIEW DATABASE",
                               callback_data=f"db_db:{cat}:{index}"),
        InlineKeyboardButton("◀️ BACK", callback_data="db_main"),
    ]])
    return "\n".join(lines), kb


# ─────────────────────────── VIEW ROUTER ───────────────────────────
async def build_view(view: str, extra: Dict[str, Any]) -> Tuple[str, InlineKeyboardMarkup]:
    try:
        if view == "main":
            return await view_main()
        if view == "category":
            return await view_category(extra["cat"])
        if view == "db":
            return await view_db(extra["cat"], extra["index"])
        if view == "colls":
            return await view_colls(extra["cat"], extra["index"], extra.get("page", 1))
        if view == "coll":
            return await view_coll(extra["cat"], extra["index"], extra["name"])
        if view == "recent":
            return await view_recent(extra["cat"], extra["index"], extra["name"], extra.get("limit", 5))
        if view == "indexes":
            return await view_indexes(extra["cat"], extra["index"], extra["name"])
        if view == "health":
            return await view_health(extra["cat"])
        if view == "perf":
            return await view_perf(extra["cat"])
        if view == "audit":
            return await view_audit()
        if view == "errors":
            return await view_errors()
        if view == "catall":
            return await view_cat_all(extra["cat"])
        return await view_main()
    except Exception as e:
        logger.exception(f"build_view({view}) failed")
        return f"🔴 RENDER FAILED: <code>{esc(e)}</code>", InlineKeyboardMarkup([[
            InlineKeyboardButton("🏠 HOME", callback_data="db_main")]])


# ─────────────────────────── HANDLERS ───────────────────────────
@Client.on_message(filters.command("database") & filters.private)
async def cmd_database(client: Client, msg: Message):
    if not is_admin(msg.from_user.id):
        await msg.reply_text("⛔ UNAUTHORIZED.")
        return
    m = await msg.reply_text("🔄 LOADING DATABASE CONTROL CENTER...")
    text, kb = await build_view("main", {})
    try:
        await m.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                          disable_web_page_preview=True)
    except Exception as e:
        logger.warning(f"edit failed: {e}")


@Client.on_callback_query(filters.regex(r"^db_main$"))
async def cb_main(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ UNAUTHORIZED", show_alert=True); return
    await live.stop(q.message.chat.id)
    text, kb = await build_view("main", {})
    try:
        await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True)
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^db_refresh$"))
async def cb_refresh(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ UNAUTHORIZED", show_alert=True); return
    cache.invalidate()
    text, kb = await build_view("main", {})
    try:
        await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True)
    except Exception:
        pass
    await q.answer("🔄 REFRESHED")


@Client.on_callback_query(filters.regex(r"^db_cat:(system|user|media|overall)$"))
async def cb_cat(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ UNAUTHORIZED", show_alert=True); return
    cat = q.matches[0].group(1)
    text, kb = await build_view("category", {"cat": cat})
    try:
        await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True)
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^db_catall:(system|user|media)$"))
async def cb_catall(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ UNAUTHORIZED", show_alert=True); return
    cat = q.matches[0].group(1)
    text, kb = await build_view("catall", {"cat": cat})
    try:
        await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True)
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^db_db:(system|user|media):(\d+)$"))
async def cb_db(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ UNAUTHORIZED", show_alert=True); return
    cat = q.matches[0].group(1); idx = int(q.matches[0].group(2))
    text, kb = await build_view("db", {"cat": cat, "index": idx})
    try:
        await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True)
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^db_colls:(system|user|media):(\d+):(\d+)$"))
async def cb_colls(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ UNAUTHORIZED", show_alert=True); return
    cat = q.matches[0].group(1); idx = int(q.matches[0].group(2)); page = int(q.matches[0].group(3))
    text, kb = await build_view("colls", {"cat": cat, "index": idx, "page": page})
    try:
        await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True)
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^db_coll:(system|user|media):(\d+):(.+)$"))
async def cb_coll(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ UNAUTHORIZED", show_alert=True); return
    cat = q.matches[0].group(1); idx = int(q.matches[0].group(2)); name = q.matches[0].group(3)
    text, kb = await build_view("coll", {"cat": cat, "index": idx, "name": name})
    try:
        await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True)
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^db_recent:(system|user|media):(\d+):([^:]+):(\d+)$"))
async def cb_recent(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ UNAUTHORIZED", show_alert=True); return
    cat = q.matches[0].group(1); idx = int(q.matches[0].group(2))
    name = q.matches[0].group(3); lim = int(q.matches[0].group(4))
    text, kb = await build_view("recent", {"cat": cat, "index": idx, "name": name, "limit": lim})
    try:
        await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True)
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^db_idx:(system|user|media):(\d+):(.+)$"))
async def cb_idx(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ UNAUTHORIZED", show_alert=True); return
    cat = q.matches[0].group(1); idx = int(q.matches[0].group(2)); name = q.matches[0].group(3)
    text, kb = await build_view("indexes", {"cat": cat, "index": idx, "name": name})
    try:
        await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True)
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^db_health:(system|user|media|overall)$"))
async def cb_health(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ UNAUTHORIZED", show_alert=True); return
    cat = q.matches[0].group(1)
    text, kb = await build_view("health", {"cat": cat})
    try:
        await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True)
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^db_perf:(system|user|media|overall)$"))
async def cb_perf(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ UNAUTHORIZED", show_alert=True); return
    cat = q.matches[0].group(1)
    text, kb = await build_view("perf", {"cat": cat})
    try:
        await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True)
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^db_audit$"))
async def cb_audit(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ UNAUTHORIZED", show_alert=True); return
    text, kb = await build_view("audit", {})
    try:
        await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True)
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^db_errors$"))
async def cb_errors(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ UNAUTHORIZED", show_alert=True); return
    text, kb = await build_view("errors", {})
    try:
        await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True)
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^db_dups:(system|user|media):(\d+)$"))
async def cb_dups(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ UNAUTHORIZED", show_alert=True); return
    cat = q.matches[0].group(1); idx = int(q.matches[0].group(2))
    text, kb = await view_dups(cat, idx)
    try:
        await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True)
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^db_dup_scan:(system|user|media):(\d+)$"))
async def cb_dup_scan(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ UNAUTHORIZED", show_alert=True); return
    cat = q.matches[0].group(1); idx = int(q.matches[0].group(2))
    await q.answer("🔍 SCANNING...")
    text, kb = await view_dup_scan(cat, idx)
    try:
        await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^db_dup_last:(system|user|media):(\d+)$"))
async def cb_dup_last(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ UNAUTHORIZED", show_alert=True); return
    await q.answer("USE START SCAN TO RUN A FRESH SCAN.", show_alert=True)


@Client.on_callback_query(filters.regex(r"^db_dup_remove:(system|user|media):(\d+)$"))
async def cb_dup_remove(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ UNAUTHORIZED", show_alert=True); return
    cat = q.matches[0].group(1); idx = int(q.matches[0].group(2))
    tok = f"dup:{cat}:{idx}:{int(time.time())}"
    confirms.start(q.from_user.id, tok, {"action": "dup_remove", "cat": cat, "index": idx})
    text = (
        "⚠️ <b>DUPLICATE REMOVAL — STEP 1/3</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 TARGET: {cat.upper()} DB {idx:02d}\n\n"
        "THIS MAY DELETE DATABASE RECORDS.\n\n"
        "CONTINUE?"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚠️ CONTINUE", callback_data=f"db_confirm:{tok}")],
        [InlineKeyboardButton("❌ CANCEL", callback_data=f"db_cancel:{tok}")],
    ])
    try:
        await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^db_clear:(system|user|media):(\d+)$"))
async def cb_clear(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ UNAUTHORIZED", show_alert=True); return
    cat = q.matches[0].group(1); idx = int(q.matches[0].group(2))
    text, kb = await view_clear(cat, idx)
    try:
        await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True)
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^db_clear_db:(system|user|media):(\d+)$"))
async def cb_clear_db(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ UNAUTHORIZED", show_alert=True); return
    cat = q.matches[0].group(1); idx = int(q.matches[0].group(2))
    tok = f"clear:{cat}:{idx}:{int(time.time())}"
    confirms.start(q.from_user.id, tok, {"action": "clear_db", "cat": cat, "index": idx})
    text = (
        "⚠️ <b>STEP 1/3 — CLEAR DATABASE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 {cat.upper()} DB {idx:02d}\n\n"
        "ALL DOCUMENTS WILL BE REMOVED.\n\n"
        "CONTINUE?"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚠️ CONTINUE", callback_data=f"db_confirm:{tok}")],
        [InlineKeyboardButton("❌ CANCEL", callback_data=f"db_cancel:{tok}")],
    ])
    try:
        await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^db_confirm:(.+)$"))
async def cb_confirm(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ UNAUTHORIZED", show_alert=True); return
    tok = q.matches[0].group(1)
    entry = confirms.get(q.from_user.id, tok)
    if not entry:
        await q.answer("⏱️ EXPIRED OR INVALID.", show_alert=True); return
    step = entry["step"]
    if step < 3:
        confirms.advance(q.from_user.id, tok)
        if step == 1:
            text = (
                "🚨 <b>STEP 2/3 — FINAL WARNING</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "THIS CANNOT BE UNDONE.\n\n"
                "CONTINUE?"
            )
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🚨 CONTINUE", callback_data=f"db_confirm:{tok}")],
                [InlineKeyboardButton("❌ CANCEL", callback_data=f"db_cancel:{tok}")],
            ])
        else:
            text = (
                "☢️ <b>STEP 3/3 — PERMANENT DELETION</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "CLICK BELOW TO EXECUTE."
            )
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("☢️ YES, PERMANENTLY DELETE", callback_data=f"db_confirm:{tok}")],
                [InlineKeyboardButton("❌ CANCEL", callback_data=f"db_cancel:{tok}")],
            ])
        try:
            await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        await q.answer()
        return

    # Step 3 → execute
    confirms.cancel(q.from_user.id, tok)
    payload = entry["payload"]
    action = payload.get("action")
    if action == "clear_db":
        cat = payload["cat"]; idx = payload["index"]
        text, kb = await do_clear_db(cat, idx)
        try:
            await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                      disable_web_page_preview=True)
        except Exception:
            pass
        await q.answer("✅ DONE")
    elif action == "dup_remove":
        audit.log(q.from_user.id, "duplicate_removal_safe_mode",
                  target=f"{payload['cat']}:{payload['index']}",
                  result="DISABLED_SAFE_MODE")
        text = (
            "⚠️ <b>DUPLICATE REMOVAL — SAFE MODE</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "REMOVAL IS DISABLED TO PREVENT DATA LOSS.\n"
            "SCAN RESULTS REMAIN READ-ONLY."
        )
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("◀️ BACK", callback_data="db_main")]])
        try:
            await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        await q.answer("SAFE MODE")


@Client.on_callback_query(filters.regex(r"^db_cancel:(.+)$"))
async def cb_cancel(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ UNAUTHORIZED", show_alert=True); return
    tok = q.matches[0].group(1)
    confirms.cancel(q.from_user.id, tok)
    try:
        await q.message.edit_text(
            "❌ CANCELLED.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 HOME", callback_data="db_main")]]),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass
    await q.answer("CANCELLED")


@Client.on_callback_query(filters.regex(r"^db_live$"))
async def cb_live(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ UNAUTHORIZED", show_alert=True); return
    chat_id = q.message.chat.id
    if live.is_live(chat_id):
        await live.stop(chat_id)
        await q.answer("🔴 LIVE MONITOR OFF", show_alert=True)
        return
    rows = [
        [InlineKeyboardButton(f"{n}s", callback_data=f"db_livego:{n}") for n in LIVE_OPTIONS],
        [InlineKeyboardButton("❌ CANCEL", callback_data="db_main")],
    ]
    try:
        await q.message.edit_text(
            "🟢 <b>LIVE MONITOR</b>\nCHOOSE REFRESH INTERVAL:",
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^db_livego:(\d+)$"))
async def cb_livego(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ UNAUTHORIZED", show_alert=True); return
    interval = int(q.matches[0].group(1))
    chat_id = q.message.chat.id
    await live.start(client, chat_id, q.message.id, "main", {})
    live._state[chat_id]["interval"] = interval
    await q.answer(f"🟢 LIVE ON — EVERY {interval}s", show_alert=True)
    try:
        text, kb = await build_view("main", {})
        await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^db_close$"))
async def cb_close(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔ UNAUTHORIZED", show_alert=True); return
    await live.stop(q.message.chat.id)
    try:
        await q.message.delete()
    except Exception:
        pass
    await q.answer("CLOSED")


@Client.on_callback_query(filters.regex(r"^db_noop$"))
async def cb_noop(client: Client, q: CallbackQuery):
    await q.answer()


# ─────────────────────────── CLEANUP LOOP ───────────────────────────
async def _confirm_cleanup():
    while True:
        try:
            confirms.cleanup()
        except Exception:
            pass
        await asyncio.sleep(60)


@Client.on_message(filters.command("database_cleanup") & filters.private)
async def cmd_cleanup(client: Client, msg: Message):
    if not is_admin(msg.from_user.id):
        await msg.reply_text("⛔ UNAUTHORIZED."); return
    await live.stop(msg.chat.id)
    await msg.reply_text("🧹 LIVE MONITOR STOPPED FOR THIS CHAT.")
