# plugins/admin_dashboard.py
"""
🏨 DOWNTOWN VILLA — ULTIMATE DATABASE CONTROL CENTER (FANCY EDITION)
Beautiful typography + colorful progress bars. Real MongoDB data only.
"""
import asyncio, logging, re, time
from collections import deque
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from core.config import ADMINS
from database import db_registry

logger = logging.getLogger(__name__)

# ═══════════════════════ FANCY FONTS ═══════════════════════
_M_BOLD = {
    **{chr(ord('A') + i): "𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭"[i] for i in range(26)},
    **{chr(ord('a') + i): "𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇"[i] for i in range(26)},
    **{chr(ord('0') + i): "𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵"[i] for i in range(10)},
}
_M_SC = {
    'a':'ᴀ','b':'ʙ','c':'ᴄ','d':'ᴅ','e':'ᴇ','f':'ꜰ','g':'ɢ','h':'ʜ','i':'ɪ',
    'j':'ᴊ','k':'ᴋ','l':'ʟ','m':'ᴍ','n':'ɴ','o':'ᴏ','p':'ᴘ','q':'ǫ','r':'ʀ',
    's':'ꜱ','t':'ᴛ','u':'ᴜ','v':'ᴠ','w':'ᴡ','x':'x','y':'ʏ','z':'ᴢ',
    'A':'ᴀ','B':'ʙ','C':'ᴄ','D':'ᴅ','E':'ᴇ','F':'ꜰ','G':'ɢ','H':'ʜ','I':'ɪ',
    'J':'ᴊ','K':'ᴋ','L':'ʟ','M':'ᴍ','N':'ɴ','O':'ᴏ','P':'ᴘ','Q':'ǫ','R':'ʀ',
    'S':'ꜱ','T':'ᴛ','U':'ᴜ','V':'ᴠ','W':'ᴡ','X':'x','Y':'ʏ','Z':'ᴢ',
}
_M_MONO = {
    **{chr(ord('A') + i): "𝙰𝙱𝙲𝙳𝙴𝙵𝙶𝙷𝙸𝙹𝙺𝙻𝙼𝙽𝙾𝙿𝚀𝚁𝚂𝚃𝚄𝚅𝚆𝚇𝚈𝚉"[i] for i in range(26)},
    **{chr(ord('a') + i): "𝚊𝚋𝚌𝚍𝚎𝚏𝚐𝚑𝚒𝚓𝚔𝚕𝚖𝚗𝚘𝚙𝚚𝚛𝚜𝚝𝚞𝚟𝚠𝚡𝚢𝚣"[i] for i in range(26)},
    **{chr(ord('0') + i): "𝟶𝟷𝟸𝟹𝟺𝟻𝟼𝟽𝟾𝟿"[i] for i in range(10)},
}

def fb(s: str) -> str:  # 𝗕𝗼𝗹𝗱 𝘀𝗮𝗻𝘀
    return "".join(_M_BOLD.get(c, c) for c in s)

def sc(s: str) -> str:  # ꜱᴍᴀʟʟ ᴄᴀᴘꜱ
    return "".join(_M_SC.get(c, c) for c in s)

def fm(s: str) -> str:  # 𝙼𝚘𝚗𝚘𝚜𝚙𝚊𝚌𝚎
    return "".join(_M_MONO.get(c, c) for c in s)

# ═══════════════════════ CONSTANTS ═══════════════════════
IST = timezone(timedelta(hours=5, minutes=30))
BAR_W = 18
CACHE_TTL = 10
LIVE_DEFAULT = 15
LIVE_OPTIONS = [10, 15, 30, 60]
RECENT_LIMITS = [5, 10, 20]
COLL_PAGE = 25
MAX_LAT = 30

DIV = "━" * 26
DIV_S = "┄" * 26
TICK = "▰"
EMPTY = "▱"

SENSITIVE = re.compile(
    r"(token|password|secret|api[_-]?key|api[_-]?hash|session|uri|database_uri|dsn|auth)",
    re.IGNORECASE,
)
URI_PAT = re.compile(r"mongodb(\+srv)?://[^\s'\"]+", re.IGNORECASE)

# ═══════════════════════ HELPERS ═══════════════════════
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

def pct(part: float, whole: float) -> float:
    try:
        if not whole:
            return 0.0
        return max(0.0, min(100.0, (float(part) / float(whole)) * 100.0))
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0

def pbar(p: float, w: int = BAR_W) -> str:
    """Fancy progress bar with tick/empty blocks."""
    try:
        p = max(0.0, min(100.0, float(p)))
    except (TypeError, ValueError):
        p = 0.0
    filled = int(round(w * p / 100.0))
    filled = max(0, min(w, filled))
    return TICK * filled + EMPTY * (w - filled)

def pcolor(p: float) -> str:
    """Colour emoji for progress state."""
    try:
        p = float(p)
    except (TypeError, ValueError):
        return "⚪"
    if p >= 100: return "🔴"
    if p >= 90:  return "🔴"
    if p >= 75:  return "🟠"
    if p >= 60:  return "🟡"
    return "🟢"

def progress_line(label: str, p: float, w: int = BAR_W) -> str:
    """One-line colorful progress with label."""
    return f"{pcolor(p)} <b>{sc(label)}</b> · <code>{p:.1f}%</code>\n<code>{pbar(p, w)}</code>"

def now_ist() -> str:
    return datetime.now(IST).strftime("%I:%M:%S %p IST")

def esc(s: Any) -> str:
    if s is None:
        return ""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def redact(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: ("🔐 [REDACTED]" if SENSITIVE.search(str(k)) else redact(val))
                for k, val in v.items()}
    if isinstance(v, list):
        return [redact(x) for x in v]
    if isinstance(v, str):
        return URI_PAT.sub("mongodb://[REDACTED]", v)
    return v

def summarize_doc(doc: Dict[str, Any], maxf: int = 12, maxl: int = 100) -> str:
    safe = redact(doc)
    out = []
    for i, (k, v) in enumerate(safe.items()):
        if i >= maxf:
            out.append("  <i>… ᴛʀᴜɴᴄᴀᴛᴇᴅ</i>")
            break
        sval = str(v)
        if len(sval) > maxl:
            sval = sval[: maxl - 1] + "…"
        out.append(f"  <b>{esc(k)}</b> : <code>{esc(sval)}</code>")
    return "\n".join(out)

def is_admin(uid: int) -> bool:
    try:
        return int(uid) in [int(a) for a in ADMINS if str(a).lstrip("-").isdigit()]
    except Exception:
        return False

# ═══════════════════════ CACHE ═══════════════════════
class _Cache:
    def __init__(self, ttl: int = CACHE_TTL):
        self.ttl = ttl
        self._d: Dict[str, Tuple[float, Any]] = {}
    def get(self, k: str):
        e = self._d.get(k)
        if not e: return None
        if time.time() - e[0] > self.ttl:
            self._d.pop(k, None); return None
        return e[1]
    def set(self, k: str, v: Any): self._d[k] = (time.time(), v)
    def invalidate(self, k: Optional[str] = None):
        if k is None: self._d.clear()
        else: self._d.pop(k, None)

cache = _Cache()

# ═══════════════════════ ERROR MONITOR ═══════════════════════
class _Errors:
    def __init__(self, maxlen: int = 50):
        self._q: deque = deque(maxlen=maxlen)
    def record(self, src: str, err: str):
        safe = URI_PAT.sub("mongodb://[REDACTED]", str(err))
        self._q.append({"ts": now_ist(), "src": src, "err": safe[:280]})
    def recent(self, n: int = 20) -> List[Dict[str, Any]]:
        return list(self._q)[-n:][::-1]

errors = _Errors()

# ═══════════════════════ LATENCY ═══════════════════════
class _Latency:
    def __init__(self, maxlen: int = MAX_LAT):
        self._d: Dict[str, deque] = {}
        self._m = maxlen
    def record(self, key: str, ms: Optional[float]):
        if ms is None: return
        self._d.setdefault(key, deque(maxlen=self._m)).append(round(ms, 1))
    def stats(self, key: str) -> Dict[str, Any]:
        d = list(self._d.get(key, []))
        if not d:
            return {"cur": None, "avg": None, "min": None, "max": None}
        return {"cur": d[-1], "avg": round(sum(d) / len(d), 1), "min": min(d), "max": max(d)}

latency = _Latency()

# ═══════════════════════ AUDIT ═══════════════════════
class _Audit:
    def __init__(self, maxlen: int = 200):
        self._q: deque = deque(maxlen=maxlen)
    def log(self, admin: int, action: str, target: str = "-", result: str = "-", extra: str = ""):
        self._q.append({"ts": now_ist(), "admin": admin, "action": action,
                        "target": target, "result": result, "extra": extra})
        logger.info(f"[AUDIT] admin={admin} action={action} target={target} result={result}")
    def recent(self, n: int = 20) -> List[Dict[str, Any]]:
        return list(self._q)[-n:][::-1]

audit = _Audit()

# ═══════════════════════ DIAGNOSTICS ═══════════════════════
class Diagnostics:
    @staticmethod
    async def ping(db) -> Optional[float]:
        try:
            t0 = time.time()
            await db.command("ping")
            return (time.time() - t0) * 1000.0
        except Exception as e:
            errors.record("ping", str(e)); return None

    @staticmethod
    async def db_stats(db) -> Optional[Dict[str, Any]]:
        try:
            return await db.command("dbStats")
        except Exception as e:
            errors.record("dbStats", str(e)); return None

    @staticmethod
    async def coll_stats(db, name: str) -> Optional[Dict[str, Any]]:
        try:
            return await db.command("collStats", name)
        except Exception as e:
            errors.record(f"collStats:{name}", str(e)); return None

    @staticmethod
    async def list_collections(db) -> List[str]:
        try:
            return sorted(await db.list_collection_names())
        except Exception as e:
            errors.record("listCollections", str(e)); return []

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
            async for ix in db[coll].list_indexes():
                out.append(ix)
            return out
        except Exception as e:
            errors.record(f"listIndexes:{coll}", str(e)); return []

    @staticmethod
    async def sample(db, coll: str, limit: int = 5) -> List[Dict[str, Any]]:
        try:
            return await db[coll].find({}).limit(limit).to_list(length=limit)
        except Exception as e:
            errors.record(f"sample:{coll}", str(e)); return []

# ═══════════════════════ STATS MANAGER ═══════════════════════
class StatsManager:
    def _entries(self, cat: str) -> List:
        return {
            "system": db_registry.system_entries,
            "user": db_registry.user_entries,
            "media": db_registry.media_entries,
        }.get(cat, lambda: [])()
    
    def _find_entry(self, cat: str, index: int):
        for e in self._entries(cat):
            if e.index == index:
                return e
        return None

    async def db_info(self, cat: str, index: int) -> Optional[Dict[str, Any]]:
        e = self._find_entry(cat, index)
        if not e: return None
        return await self._gather(cat, e)

    async def category(self, cat: str) -> Dict[str, Any]:
        key = f"cat:{cat}"
        cached = cache.get(key)
        if cached: return cached
        entries = self._entries(cat)
        results = await asyncio.gather(*[self._gather(cat, e) for e in entries])
        totals = self._totals(results)
        data = {"items": results, "totals": totals, "updated": now_ist(),
                "count": len(results), "category": cat}
        cache.set(key, data)
        return data

    async def overall(self) -> Dict[str, Any]:
        cached = cache.get("overall")
        if cached: return cached
        s, u, m = await asyncio.gather(
            self.category("system"), self.category("user"), self.category("media")
        )
        overall_totals = self._merge([s["totals"], u["totals"], m["totals"]])
        data = {"system": s, "user": u, "media": m, "totals": overall_totals,
                "count": s["count"] + u["count"] + m["count"], "updated": now_ist()}
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
        if p is None: return out
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
            if not i["online"]: continue
            t["objects"] += i["objects"]; t["data_size"] += i["data_size"]
            t["storage_size"] += i["storage_size"]; t["index_size"] += i["index_size"]
            t["collections"] += i["collections"]
        return t

    def _merge(self, totals: List[Dict[str, int]]) -> Dict[str, int]:
        m = {"objects": 0, "data_size": 0, "storage_size": 0, "index_size": 0, "collections": 0}
        for t in totals:
            for k in m: m[k] += t.get(k, 0)
        return m

stats = StatsManager()

# ═══════════════════════ LIVE MONITOR ═══════════════════════
class LiveMonitor:
    def __init__(self):
        self._tasks: Dict[int, asyncio.Task] = {}
        self._state: Dict[int, Dict[str, Any]] = {}
    def is_live(self, chat_id: int) -> bool:
        t = self._tasks.get(chat_id)
        return t is not None and not t.done()
    def interval(self, chat_id: int) -> int:
        return self._state.get(chat_id, {}).get("interval", LIVE_DEFAULT)
    async def start(self, client, chat_id, msg_id, view, extra):
        await self.stop(chat_id)
        self._state[chat_id] = {"interval": self.interval(chat_id), "view": view, "extra": extra}
        self._tasks[chat_id] = asyncio.create_task(self._loop(client, chat_id, msg_id, view, extra))
    async def stop(self, chat_id):
        t = self._tasks.pop(chat_id, None); self._state.pop(chat_id, None)
        if t and not t.done():
            t.cancel()
            try: await t
            except Exception: pass
    async def _loop(self, client, chat_id, msg_id, view, extra):
        try:
            while True:
                await asyncio.sleep(self.interval(chat_id))
                cache.invalidate()
                try:
                    text, kb = await build_view(view, extra)
                    await client.edit_message_text(
                        chat_id=chat_id, message_id=msg_id, text=text, reply_markup=kb,
                        parse_mode=ParseMode.HTML, disable_web_page_preview=True)
                except asyncio.CancelledError: raise
                except Exception: pass
        except asyncio.CancelledError: return

live = LiveMonitor()

# ═══════════════════════ CONFIRMATIONS ═══════════════════════
class Confirmations:
    def __init__(self, ttl: int = 180):
        self._p: Dict[str, Dict[str, Any]] = {}
        self._ttl = ttl
    def _k(self, uid, tok): return f"{uid}:{tok}"
    def start(self, uid, tok, payload):
        self._p[self._k(uid, tok)] = {"step": 1, "payload": payload, "exp": time.time() + self._ttl}
    def get(self, uid, tok):
        e = self._p.get(self._k(uid, tok))
        if not e: return None
        if time.time() > e["exp"]:
            self._p.pop(self._k(uid, tok), None); return None
        return e
    def advance(self, uid, tok):
        e = self.get(uid, tok)
        if not e: return None
        e["step"] += 1; e["exp"] = time.time() + self._ttl
        return e
    def cancel(self, uid, tok): self._p.pop(self._k(uid, tok), None)
    def cleanup(self):
        now = time.time()
        for k in list(self._p.keys()):
            if self._p[k]["exp"] < now: self._p.pop(k, None)

confirms = Confirmations()

# ═══════════════════════ DUPLICATE SCAN ═══════════════════════
async def duplicate_scan(cat: str, index: int, key: str = "file_id") -> Dict[str, Any]:
    info = await stats.db_info(cat, index)
    if not info or not info["online"]:
        return {"ok": False, "reason": "DB offline"}
    entry = stats._find_entry(cat, index)
    if not entry:
        return {"ok": False, "reason": "Entry missing"}
    db = entry.db
    total = 0; per_coll = []
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
                total += g
        except Exception as e:
            errors.record(f"dup:{name}", str(e))
    return {"ok": True, "total": total, "per_collection": per_coll}

# ═══════════════════════ VIEW BUILDERS ═══════════════════════
def _header() -> str:
    return f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>\n💾 <b>{fb('DATABASE CONTROL CENTER')}</b>\n{DIV}"

def _status(cat: str, items: List[Dict[str, Any]]) -> str:
    if not items: return "⚪ ɴᴏ ᴅᴀᴛᴀʙᴀꜱᴇꜱ"
    up = sum(1 for i in items if i["online"])
    if up == len(items): return "🟢 ʜᴇᴀʟᴛʜʏ"
    if up == 0: return "🔴 ᴏꜰꜰʟɪɴᴇ"
    return f"🟡 {up}/{len(items)} ᴏɴʟɪɴᴇ"

def _db_block(cat: str, d: Dict[str, Any], share_pct: Optional[float] = None) -> str:
    status = "🟢" if d["online"] else "🔴"
    ping = f"{d['ping_ms']}ms" if d["ping_ms"] is not None else "—"
    lines = [
        f"{status} <b>{fb(cat.upper() + ' DATABASE ' + f'{d['index']:02d}')}</b>",
        DIV_S,
        f"🏷️ {sc('cluster')} · <code>{esc(d['label'])}</code>",
        f"⏱️ {sc('ping')} · <code>{ping}</code>",
        f"📦 {sc('documents')} · <code>{fmt_int(d['objects'])}</code>",
        f"💾 {sc('storage')} · <code>{fmt_bytes(d['storage_size'])}</code>",
        f"📄 {sc('data')} · <code>{fmt_bytes(d['data_size'])}</code>",
        f"🧩 {sc('indexes')} · <code>{fmt_bytes(d['index_size'])}</code>",
        f"🗂️ {sc('collections')} · <code>{fmt_int(d['collections'])}</code>",
    ]
    if share_pct is not None:
        lines.append("")
        lines.append(progress_line("share of category", share_pct))
    return "\n".join(lines)

def _totals_block(t: Dict[str, int]) -> str:
    return "\n".join([
        f"📊 <b>{fb('ALL DATABASES TOTAL')}</b>",
        DIV_S,
        f"📦 {sc('documents')} · <code>{fmt_int(t['objects'])}</code>",
        f"💾 {sc('storage')} · <code>{fmt_bytes(t['storage_size'])}</code>",
        f"📄 {sc('data')} · <code>{fmt_bytes(t['data_size'])}</code>",
        f"🧩 {sc('indexes')} · <code>{fmt_bytes(t['index_size'])}</code>",
        f"🗂️ {sc('collections')} · <code>{fmt_int(t['collections'])}</code>",
    ])

# ──────────── MAIN SCREEN ────────────
def kb_main(data):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🖥️ SYSTEM DATABASES", callback_data="db_cat:system")],
        [InlineKeyboardButton("👥 USER DATABASES", callback_data="db_cat:user")],
        [InlineKeyboardButton("🎬 MEDIA DATABASES", callback_data="db_cat:media")],
        [InlineKeyboardButton("📊 OVERALL", callback_data="db_cat:overall")],
        [InlineKeyboardButton("❤️ HEALTH", callback_data="db_health:overall"),
         InlineKeyboardButton("⚡ PERFORMANCE", callback_data="db_perf:overall")],
        [InlineKeyboardButton("🧹 DUPLICATES", callback_data="db_dups:media:1"),
         InlineKeyboardButton("🧩 INDEXES", callback_data="db_colls:media:1:1")],
        [InlineKeyboardButton("📋 ACTIVITY LOG", callback_data="db_audit"),
         InlineKeyboardButton("🚨 ERRORS", callback_data="db_errors")],
        [InlineKeyboardButton("📡 LIVE MONITOR", callback_data="db_live"),
         InlineKeyboardButton("🔄 REFRESH", callback_data="db_refresh")],
        [InlineKeyboardButton("❌ CLOSE", callback_data="db_close")],
    ])

async def view_main():
    data = await stats.overall()
    s, u, m = data["system"], data["user"], data["media"]
    tot = data["totals"]
    # category shares by documents
    total_docs = max(1, s["totals"]["objects"] + u["totals"]["objects"] + m["totals"]["objects"])
    sp = pct(s["totals"]["objects"], total_docs)
    up = pct(u["totals"]["objects"], total_docs)
    mp = pct(m["totals"]["objects"], total_docs)
    lines = [
        _header(), "",
        f"🕐 {sc('updated')} · <code>{data['updated']}</code>",
        "",
        f"<b>{fb('DATABASE CATEGORIES')}</b>",
        f"🖥️ {sc('system')} · <b>{s['count']}</b> ᴅᴀᴛᴀʙᴀꜱᴇꜱ",
        f"👥 {sc('user')} · <b>{u['count']}</b> ᴅᴀᴛᴀʙᴀꜱᴇꜱ",
        f"🎬 {sc('media')} · <b>{m['count']}</b> ᴅᴀᴛᴀʙᴀꜱᴇꜱ",
        f"🗄️ {sc('total')} · <b>{data['count']}</b> ᴅᴀᴛᴀʙᴀꜱᴇꜱ",
        "",
        f"<b>{fb('DOCUMENT DISTRIBUTION')}</b>",
        progress_line("system", sp),
        progress_line("user", up),
        progress_line("media", mp),
        "",
        DIV, _totals_block(tot), DIV,
        "",
        f"<b>{fb('SYSTEM STATUS')}</b>",
        f"🖥️ {sc('system')} · {_status('system', s['items'])}",
        f"👥 {sc('user')} · {_status('user', u['items'])}",
        f"🎬 {sc('media')} · {_status('media', m['items'])}",
        "",
        DIV_S,
        f"📡 {sc('live monitoring')} · 🟢 ʀᴇᴀᴅʏ",
    ]
    return "\n".join(lines), kb_main(data)

# ──────────── CATEGORY SCREEN ────────────
def kb_category(cat, data):
    rows = []; pair = []
    for item in data["items"]:
        emoji = "🟢" if item["online"] else "🔴"
        label = f"{emoji} {cat.upper()} DB {item['index']:02d}"
        pair.append(InlineKeyboardButton(label, callback_data=f"db_db:{cat}:{item['index']}"))
        if len(pair) == 2:
            rows.append(pair); pair = []
    if pair: rows.append(pair)
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

async def view_category(cat):
    if cat == "overall":
        return await view_main()
    data = await stats.category(cat)
    titles = {
        "system": ("🖥️", "SYSTEM DATABASE CONTROL"),
        "user":   ("👥", "USER DATABASE CONTROL"),
        "media":  ("🎬", "MEDIA DATABASE CONTROL"),
    }
    icon, t = titles.get(cat, ("🗄️", "DATABASE CONTROL"))
    total_docs = max(1, data["totals"]["objects"])
    lines = [
        _header(), "",
        f"{icon} <b>{fb(t)}</b>",
        DIV, "",
        f"📊 <b>{data['count']} CONFIGURED</b>",
        f"🕐 <code>{data['updated']}</code>",
        "",
    ]
    for item in data["items"]:
        share = pct(item["objects"], total_docs)
        lines.append(_db_block(cat, item, share_pct=share))
        lines.append("")
        lines.append(DIV)
        lines.append("")
    lines.append(_totals_block(data["totals"]))
    return "\n".join(lines), kb_category(cat, data)

# ──────────── INDIVIDUAL DB ────────────
def kb_db(cat, index):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧱 COLLECTIONS", callback_data=f"db_colls:{cat}:{index}:1"),
         InlineKeyboardButton("📊 STATISTICS", callback_data=f"db_stats:{cat}:{index}")],
        [InlineKeyboardButton("🔍 SEARCH", callback_data=f"db_search:{cat}:{index}"),
         InlineKeyboardButton("🧹 DUPLICATES", callback_data=f"db_dups:{cat}:{index}")],
        [InlineKeyboardButton("🧩 INDEXES", callback_data=f"db_colls:{cat}:{index}:1"),
         InlineKeyboardButton("🗑️ CLEAR DATA", callback_data=f"db_clear:{cat}:{index}")],
        [InlineKeyboardButton("❤️ HEALTH", callback_data=f"db_health:{cat}"),
         InlineKeyboardButton("⚡ PERFORMANCE", callback_data=f"db_perf:{cat}")],
        [InlineKeyboardButton("🔄 REFRESH", callback_data=f"db_db:{cat}:{index}"),
         InlineKeyboardButton("◀️ BACK", callback_data=f"db_cat:{cat}")],
    ])

async def view_db(cat, index):
    info = await stats.db_info(cat, index)
    if not info:
        return "❌ ᴅᴀᴛᴀʙᴀꜱᴇ ɴᴏᴛ ꜰᴏᴜɴᴅ.", InlineKeyboardMarkup([[
            InlineKeyboardButton("◀️ BACK", callback_data=f"db_cat:{cat}")]])
    status = "🟢 ᴏɴʟɪɴᴇ" if info["online"] else "🔴 ᴏꜰꜰʟɪɴᴇ"
    ping = f"{info['ping_ms']}ms" if info["ping_ms"] is not None else "—"
    ver = info["version"] or "—"
    # index overhead vs data size
    overhead = pct(info["index_size"], max(1, info["data_size"]))
    # storage efficiency: data / storage
    eff = pct(info["data_size"], max(1, info["storage_size"]))
    lines = [
        _header(), "",
        f"🗄️ <b>{fb(cat.upper() + ' DATABASE ' + f'{info['index']:02d}')}</b>",
        DIV, "",
        f"🏷️ {sc('cluster')} · <code>{esc(info['label'])}</code>",
        f"📡 {sc('status')} · {status}",
        f"⏱️ {sc('ping')} · <code>{ping}</code>",
        f"🍃 {sc('mongodb')} · <code>{esc(ver)}</code>",
        "",
        f"📦 {sc('documents')} · <code>{fmt_int(info['objects'])}</code>",
        f"🗂️ {sc('collections')} · <code>{fmt_int(info['collections'])}</code>",
        f"📄 {sc('data')} · <code>{fmt_bytes(info['data_size'])}</code>",
        f"💾 {sc('storage')} · <code>{fmt_bytes(info['storage_size'])}</code>",
        f"🧩 {sc('indexes')} · <code>{fmt_bytes(info['index_size'])}</code>",
        f"📐 {sc('avg object')} · <code>{fmt_bytes(int(info['avg_obj'] or 0))}</code>",
        "",
        f"<b>{fb('PERFORMANCE METRICS')}</b>",
        progress_line("index overhead", overhead),
        progress_line("storage efficiency", eff),
        "",
        DIV,
        f"📚 <b>{fb('COLLECTIONS')}</b>",
        DIV,
    ]
    names = info["collection_names"]
    if not names:
        lines.append("⚪ ɴᴏ ᴄᴏʟʟᴇᴄᴛɪᴏɴꜱ.")
    else:
        for i, n in enumerate(names[:25], 1):
            lines.append(f"  <b>{i:02d}.</b> <code>{esc(n)}</code>")
        if len(names) > 25:
            lines.append(f"  <i>… +{len(names) - 25} ᴍᴏʀᴇ</i>")
    return "\n".join(lines), kb_db(cat, index)

# ──────────── COLLECTIONS ────────────
def kb_colls(cat, index, page, total_pages, names):
    rows = [[InlineKeyboardButton(f"📁 {n[:42]}", callback_data=f"db_coll:{cat}:{index}:{n}")]
            for n in names[:COLL_PAGE]]
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("◀️ PREV", callback_data=f"db_colls:{cat}:{index}:{page-1}"))
    nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="db_noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("NEXT ▶️", callback_data=f"db_colls:{cat}:{index}:{page+1}"))
    if nav: rows.append(nav)
    rows.append([
        InlineKeyboardButton("◀️ BACK", callback_data=f"db_db:{cat}:{index}"),
        InlineKeyboardButton("🏠 HOME", callback_data="db_main"),
    ])
    return InlineKeyboardMarkup(rows)

async def view_colls(cat, index, page):
    info = await stats.db_info(cat, index)
    if not info:
        return "❌ ᴅʙ ɴᴏᴛ ꜰᴏᴜɴᴅ.", InlineKeyboardMarkup([[
            InlineKeyboardButton("◀️ BACK", callback_data=f"db_cat:{cat}")]])
    names = info["collection_names"]
    total = len(names)
    tp = max(1, (total + COLL_PAGE - 1) // COLL_PAGE)
    page = max(1, min(page, tp))
    start = (page - 1) * COLL_PAGE
    slice_ = names[start:start + COLL_PAGE]
    lines = [
        _header(), "",
        f"🧱 <b>{fb(f'COLLECTIONS — {cat.upper()} DB {index:02d}')}</b>",
        DIV, "",
        f"📊 ᴛᴏᴛᴀʟ · <code>{total}</code>",
        f"📄 ᴘᴀɢᴇ · <code>{page}/{tp}</code>",
        "",
    ]
    for i, n in enumerate(slice_, start=start + 1):
        lines.append(f"  <b>{i:02d}.</b> <code>{esc(n)}</code>")
    return "\n".join(lines), kb_colls(cat, index, page, tp, slice_)

# ──────────── COLLECTION DETAIL ────────────
def kb_coll(cat, index, name):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 RECENT DOCS",
                                callback_data=f"db_recent:{cat}:{index}:{name}:5"),
         InlineKeyboardButton("🔑 INDEXES", callback_data=f"db_idx:{cat}:{index}:{name}")],
        [InlineKeyboardButton("🧹 FIND DUPLICATES",
                                callback_data=f"db_dup_coll:{cat}:{index}:{name}"),
         InlineKeyboardButton("🗑️ CLEAR COLLECTION",
                                callback_data=f"db_clear_coll:{cat}:{index}:{name}")],
        [InlineKeyboardButton("🔄 REFRESH", callback_data=f"db_coll:{cat}:{index}:{name}"),
         InlineKeyboardButton("◀️ BACK", callback_data=f"db_colls:{cat}:{index}:1")],
    ])

async def view_coll(cat, index, name):
    entry = stats._find_entry(cat, index)
    if not entry:
        return "❌ ᴅʙ ɴᴏᴛ ꜰᴏᴜɴᴅ.", InlineKeyboardMarkup([[
            InlineKeyboardButton("◀️ BACK", callback_data=f"db_cat:{cat}")]])
    st = await Diagnostics.coll_stats(entry.db, name)
    lines = [
        _header(), "",
        f"🧱 <b>{fb('COLLECTION')}</b>",
        DIV, "",
        f"📚 {sc('name')} · <code>{esc(name)}</code>",
        f"🗄️ {sc('database')} · {cat.upper()} {index:02d} ({esc(entry.label)})",
        "",
    ]
    if st:
        data_sz = st.get("size", 0) or 0
        stor_sz = st.get("storageSize", 0) or 0
        idx_sz = st.get("totalIndexSize", 0) or 0
        eff = pct(data_sz, max(1, stor_sz))
        oh = pct(idx_sz, max(1, data_sz))
        lines += [
            f"📦 {sc('documents')} · <code>{fmt_int(st.get('count', 0))}</code>",
            f"📄 {sc('data')} · <code>{fmt_bytes(data_sz)}</code>",
            f"💾 {sc('storage')} · <code>{fmt_bytes(stor_sz)}</code>",
            f"🧩 {sc('index size')} · <code>{fmt_bytes(idx_sz)}</code>",
            f"📐 {sc('avg object')} · <code>{fmt_bytes(int(st.get('avgObjSize', 0) or 0))}</code>",
            f"🔑 {sc('indexes')} · <code>{len(st.get('indexSizes', {}) or {})}</code>",
            "",
            f"<b>{fb('METRICS')}</b>",
            progress_line("storage efficiency", eff),
            progress_line("index overhead", oh),
        ]
    else:
        lines.append("⚪ ꜱᴛᴀᴛɪꜱᴛɪᴄꜱ ᴜɴᴀᴠᴀɪʟᴀʙʟᴇ.")
    return "\n".join(lines), kb_coll(cat, index, name)

# ──────────── RECENT DOCS ────────────
async def view_recent(cat, index, name, limit):
    entry = stats._find_entry(cat, index)
    if not entry:
        return "❌ ᴅʙ ɴᴏᴛ ꜰᴏᴜɴᴅ.", InlineKeyboardMarkup([[
            InlineKeyboardButton("◀️ BACK", callback_data=f"db_cat:{cat}")]])
    docs = await Diagnostics.sample(entry.db, name, limit)
    lines = [
        _header(), "",
        f"📄 <b>{fb('RECENT DOCUMENTS')}</b>",
        f"📚 <code>{esc(name)}</code>",
        DIV, "",
        f"🔢 ʟɪᴍɪᴛ · <code>{limit}</code>",
        f"📊 ʀᴇᴛᴜʀɴᴇᴅ · <code>{len(docs)}</code>",
        "",
    ]
    if not docs:
        lines.append("⚪ ɴᴏ ᴅᴏᴄᴜᴍᴇɴᴛꜱ.")
    for i, d in enumerate(docs, 1):
        lines.append(f"<b>{fb(f'DOCUMENT {i:02d}')}</b>")
        lines.append(summarize_doc(d))
        lines.append("")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"LIMIT {n}", callback_data=f"db_recent:{cat}:{index}:{name}:{n}")
         for n in RECENT_LIMITS],
        [InlineKeyboardButton("🔄 REFRESH",
                                callback_data=f"db_recent:{cat}:{index}:{name}:{limit}"),
         InlineKeyboardButton("◀️ BACK", callback_data=f"db_coll:{cat}:{index}:{name}")],
    ])
    return "\n".join(lines), kb

# ──────────── INDEXES ────────────
async def view_indexes(cat, index, name):
    entry = stats._find_entry(cat, index)
    if not entry:
        return "❌ ᴅʙ ɴᴏᴛ ꜰᴏᴜɴᴅ.", InlineKeyboardMarkup([[
            InlineKeyboardButton("◀️ BACK", callback_data=f"db_cat:{cat}")]])
    idxs = await Diagnostics.list_indexes(entry.db, name)
    lines = [
        _header(), "",
        f"🔑 <b>{fb('INDEXES')}</b>",
        f"📚 <code>{esc(name)}</code>",
        DIV, "",
        f"🔢 ᴛᴏᴛᴀʟ · <code>{len(idxs)}</code>",
        "",
    ]
    if not idxs:
        lines.append("⚪ ɴᴏ ɪɴᴅᴇxᴇꜱ.")
    for i, ix in enumerate(idxs, 1):
        safe = redact(ix)
        lines.append(f"<b>{i:02d}. {esc(safe.get('name', '?'))}</b>")
        lines.append(f"  🔑 ᴋᴇʏꜱ · <code>{esc(safe.get('key', {}))}</code>")
        if safe.get("unique"): lines.append("  ✅ ᴜɴɪQᴜᴇ")
        if safe.get("sparse"): lines.append("  ✅ ꜱᴘᴀʀꜱᴇ")
        if "expireAfterSeconds" in safe:
            lines.append(f"  ⏱️ ᴛᴛʟ · <code>{safe['expireAfterSeconds']}s</code>")
        lines.append("")
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 REFRESH", callback_data=f"db_idx:{cat}:{index}:{name}"),
        InlineKeyboardButton("◀️ BACK", callback_data=f"db_coll:{cat}:{index}:{name}"),
    ]])
    return "\n".join(lines), kb

# ──────────── HEALTH ────────────
async def view_health(cat):
    if cat == "overall":
        data = await stats.overall()
        groups = [("system", data["system"]), ("user", data["user"]), ("media", data["media"])]
    else:
        c = await stats.category(cat)
        groups = [(cat, c)]
    lines = [_header(), "", f"❤️ <b>{fb('DATABASE HEALTH')}</b>", DIV, ""]
    all_ok = True
    for name, cd in groups:
        lines.append(f"<b>{name.upper()}</b> · {_status(name, cd['items'])}")
        for i in cd["items"]:
            if i["online"]:
                lines.append(f"  🟢 <code>{esc(i['label'])}</code> · <code>{i['ping_ms']}ms</code>")
            else:
                lines.append(f"  🔴 <code>{esc(i['label'])}</code> · ᴏꜰꜰʟɪɴᴇ")
                all_ok = False
        lines.append("")
    lines.append(DIV)
    lines.append("🟢 <b>ALL HEALTHY</b>" if all_ok else "🟡 <b>WARNINGS PRESENT</b>")
    back = "db_main" if cat == "overall" else f"db_cat:{cat}"
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 REFRESH", callback_data=f"db_health:{cat}"),
        InlineKeyboardButton("◀️ BACK", callback_data=back),
    ]])
    return "\n".join(lines), kb

# ──────────── PERFORMANCE ────────────
async def view_perf(cat):
    if cat == "overall":
        data = await stats.overall()
        groups = [("system", data["system"]), ("user", data["user"]), ("media", data["media"])]
    else:
        c = await stats.category(cat)
        groups = [(cat, c)]
    lines = [_header(), "", f"⚡ <b>{fb('DATABASE PERFORMANCE')}</b>", DIV, ""]
    for name, cd in groups:
        for i in cd["items"]:
            st = latency.stats(f"{name}:{i['label']}")
            cur = st["cur"] if st["cur"] is not None else "—"
            avg = st["avg"] if st["avg"] is not None else "—"
            mn = st["min"] if st["min"] is not None else "—"
            mx = st["max"] if st["max"] is not None else "—"
            lines.append(f"<b>{name.upper()} · {esc(i['label'])}</b>")
            lines.append(f"  ᴄᴜʀ · <code>{cur}ms</code>   ᴀᴠɢ · <code>{avg}ms</code>")
            lines.append(f"  ᴍɪɴ · <code>{mn}ms</code>   ᴍᴀx · <code>{mx}ms</code>")
            # latency bar (relative to 200ms max)
            if isinstance(st["cur"], (int, float)):
                lat_pct = min(100.0, st["cur"] / 2.0)  # 200ms = 100%
                lines.append(f"  {pcolor(lat_pct)} <code>{pbar(lat_pct, 16)}</code>")
            lines.append("")
    back = "db_main" if cat == "overall" else f"db_cat:{cat}"
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 REFRESH", callback_data=f"db_perf:{cat}"),
        InlineKeyboardButton("◀️ BACK", callback_data=back),
    ]])
    return "\n".join(lines), kb

# ──────────── AUDIT ────────────
async def view_audit():
    entries = audit.recent(30)
    lines = [_header(), "", f"📋 <b>{fb('ACTIVITY LOG')}</b>", DIV, ""]
    if not entries:
        lines.append("⚪ ɴᴏ ᴀᴄᴛɪᴠɪᴛʏ.")
    for e in entries:
        lines.append(f"⏱️ <code>{e['ts']}</code>")
        lines.append(f"👤 <code>{e['admin']}</code> · <b>{esc(e['action'])}</b>")
        lines.append(f"🎯 <code>{esc(e['target'])}</code>")
        lines.append(f"✅ <code>{esc(e['result'])}</code>")
        lines.append("")
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 REFRESH", callback_data="db_audit"),
        InlineKeyboardButton("◀️ BACK", callback_data="db_main"),
    ]])
    return "\n".join(lines), kb

# ──────────── ERRORS ────────────
async def view_errors():
    errs = errors.recent(20)
    lines = [_header(), "", f"🚨 <b>{fb('DATABASE ERRORS')}</b>", DIV, ""]
    if not errs:
        lines.append("🟢 ɴᴏ ʀᴇᴄᴇɴᴛ ᴇʀʀᴏʀꜱ.")
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

# ──────────── CATEGORY ALL ────────────
async def view_cat_all(cat):
    data = await stats.category(cat)
    total_docs = max(1, data["totals"]["objects"])
    lines = [_header(), "",
             f"📊 <b>{fb(f'ALL {cat.upper()} DATABASES')}</b>",
             DIV, "", _totals_block(data["totals"]), "", DIV, ""]
    for item in data["items"]:
        share = pct(item["objects"], total_docs)
        lines.append(_db_block(cat, item, share_pct=share))
        lines.append("")
        lines.append(DIV)
        lines.append("")
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 REFRESH", callback_data=f"db_catall:{cat}"),
        InlineKeyboardButton("◀️ BACK", callback_data=f"db_cat:{cat}"),
    ]])
    return "\n".join(lines), kb

# ──────────── DUPLICATES ────────────
def kb_dups(cat, index):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 START SCAN", callback_data=f"db_dup_scan:{cat}:{index}")],
        [InlineKeyboardButton("🗑️ REMOVE DUPLICATES", callback_data=f"db_dup_remove:{cat}:{index}")],
        [InlineKeyboardButton("🔄 REFRESH", callback_data=f"db_dups:{cat}:{index}"),
         InlineKeyboardButton("◀️ BACK", callback_data=f"db_db:{cat}:{index}")],
    ])

async def view_dups(cat, index):
    info = await stats.db_info(cat, index)
    if not info:
        return "❌ ᴅʙ ɴᴏᴛ ꜰᴏᴜɴᴅ.", InlineKeyboardMarkup([[
            InlineKeyboardButton("◀️ BACK", callback_data="db_main")]])
    lines = [
        _header(), "",
        f"🧹 <b>{fb('DUPLICATE CONTROL CENTER')}</b>",
        DIV, "",
        f"🗄️ ᴛᴀʀɢᴇᴛ · {cat.upper()} ᴅʙ {index:02d}",
        f"🏷️ ᴄʟᴜꜱᴛᴇʀ · <code>{esc(info['label'])}</code>",
        f"📦 ᴛᴏᴛᴀʟ ʀᴇᴄᴏʀᴅꜱ · <code>{fmt_int(info['objects'])}</code>",
        "",
        DIV_S,
        "🔍 ꜱᴄᴀɴ ꜱᴛᴀᴛᴜꜱ · <b>ʀᴇᴀᴅʏ</b>",
        DIV_S,
        "",
        "ᴘʀᴇꜱꜱ <b>START SCAN</b> ᴛᴏ ꜱᴄᴀɴ ꜰᴏʀ ᴅᴜᴘʟɪᴄᴀᴛᴇꜱ ᴏɴ ᴋᴇʏ <code>file_id</code>.",
        "",
        "⚠️ ꜱᴄᴀɴ ɪꜱ ʀᴇᴀᴅ-ᴏɴʟʏ. ʀᴇᴍᴏᴠᴀʟ ʀᴇQᴜɪʀᴇꜱ 3-ꜱᴛᴀɢᴇ ᴄᴏɴꜰɪʀᴍᴀᴛɪᴏɴ.",
    ]
    return "\n".join(lines), kb_dups(cat, index)

async def view_dup_scan(cat, index):
    result = await duplicate_scan(cat, index, "file_id")
    info = await stats.db_info(cat, index)
    lines = [
        _header(), "",
        f"🧹 <b>{fb('DUPLICATE SCAN RESULT')}</b>",
        DIV, "",
        f"🗄️ ᴛᴀʀɢᴇᴛ · {cat.upper()} ᴅʙ {index:02d}",
    ]
    if not result.get("ok"):
        lines.append(f"🔴 ꜱᴄᴀɴ ꜰᴀɪʟᴇᴅ · {esc(result.get('reason'))}")
        return "\n".join(lines), kb_dups(cat, index)
    total_docs = max(1, info["objects"])
    scanned = total_docs  # simplified
    lines.append(f"📦 ꜱᴄᴀɴɴᴇᴅ · <code>{fmt_int(scanned)}</code>")
    lines.append(f"🧹 ᴅᴜᴘʟɪᴄᴀᴛᴇ ɢʀᴏᴜᴘꜱ · <code>{fmt_int(result['total'])}</code>")
    lines.append("")
    if result["per_collection"]:
        lines.append(f"<b>{fb('PER COLLECTION')}</b>")
        for pc in result["per_collection"][:20]:
            lines.append(f"• <code>{esc(pc['name'])}</code> · <b>{fmt_int(pc['dupes'])}</b>")
    else:
        lines.append("🟢 ɴᴏ ᴅᴜᴘʟɪᴄᴀᴛᴇꜱ ꜰᴏᴜɴᴅ.")
    return "\n".join(lines), kb_dups(cat, index)

# ──────────── CLEAR DATA ────────────
async def view_clear(cat, index):
    info = await stats.db_info(cat, index)
    if not info:
        return "❌ ᴅʙ ɴᴏᴛ ꜰᴏᴜɴᴅ.", InlineKeyboardMarkup([[
            InlineKeyboardButton("◀️ BACK", callback_data="db_main")]])
    lines = [
        _header(), "",
        "☢️ <b>" + fb("DANGER ZONE — CLEAR DATA") + "</b>",
        DIV, "",
        f"🎯 ᴛᴀʀɢᴇᴛ · {cat.upper()} ᴅʙ {index:02d}",
        f"🏷️ ᴄʟᴜꜱᴛᴇʀ · <code>{esc(info['label'])}</code>",
        f"📦 ᴅᴏᴄᴜᴍᴇɴᴛꜱ · <code>{fmt_int(info['objects'])}</code>",
        f"💾 ꜱᴛᴏʀᴀɢᴇ · <code>{fmt_bytes(info['storage_size'])}</code>",
        "",
        DIV,
        "⚠️ <b>ᴛʜɪꜱ ᴡɪʟʟ ʀᴇᴍᴏᴠᴇ ᴀʟʟ ᴅᴏᴄᴜᴍᴇɴᴛꜱ ɪɴ ᴀʟʟ ᴄᴏʟʟᴇᴄᴛɪᴏɴꜱ.</b>",
        "⚠️ <b>ᴛʜɪꜱ ᴄᴀɴɴᴏᴛ ʙᴇ ᴜɴᴅᴏɴᴇ.</b>",
        DIV,
        "",
        "ᴍᴜʟᴛɪ-ꜱᴛᴀɢᴇ ᴄᴏɴꜰɪʀᴍᴀᴛɪᴏɴ ʀᴇQᴜɪʀᴇᴅ.",
    ]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑️ CLEAR THIS DATABASE", callback_data=f"db_clear_db:{cat}:{index}")],
        [InlineKeyboardButton("◀️ BACK", callback_data=f"db_db:{cat}:{index}"),
         InlineKeyboardButton("❌ CANCEL", callback_data="db_main")],
    ])
    return "\n".join(lines), kb

async def do_clear_db(cat, index):
    entry = stats._find_entry(cat, index)
    if not entry:
        return "❌ ᴅʙ ɴᴏᴛ ꜰᴏᴜɴᴅ.", InlineKeyboardMarkup([[
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
        _header(), "",
        "🟢 <b>" + fb("OPERATION COMPLETE") + "</b>",
        DIV, "",
        f"🎯 ᴛᴀʀɢᴇᴛ · {cat.upper()} ᴅʙ {index:02d}",
        f"🗑️ ᴅᴏᴄᴜᴍᴇɴᴛꜱ ʀᴇᴍᴏᴠᴇᴅ · <code>{fmt_int(deleted)}</code>",
        f"⏱️ ᴛɪᴍᴇ · <code>{now_ist()}</code>",
        "📊 ꜱᴛᴀᴛɪꜱᴛɪᴄꜱ ʀᴇꜰʀᴇꜱʜᴇᴅ · 🟢 ʏᴇꜱ",
    ]
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("📊 VIEW DATABASE", callback_data=f"db_db:{cat}:{index}"),
        InlineKeyboardButton("◀️ BACK", callback_data="db_main"),
    ]])
    return "\n".join(lines), kb

# ═══════════════════════ VIEW ROUTER ═══════════════════════
async def build_view(view: str, extra: Dict[str, Any]):
    try:
        if view == "main": return await view_main()
        if view == "category": return await view_category(extra["cat"])
        if view == "db": return await view_db(extra["cat"], extra["index"])
        if view == "colls": return await view_colls(extra["cat"], extra["index"], extra.get("page", 1))
        if view == "coll": return await view_coll(extra["cat"], extra["index"], extra["name"])
        if view == "recent": return await view_recent(extra["cat"], extra["index"], extra["name"], extra.get("limit", 5))
        if view == "indexes": return await view_indexes(extra["cat"], extra["index"], extra["name"])
        if view == "health": return await view_health(extra["cat"])
        if view == "perf": return await view_perf(extra["cat"])
        if view == "audit": return await view_audit()
        if view == "errors": return await view_errors()
        if view == "catall": return await view_cat_all(extra["cat"])
        return await view_main()
    except Exception as e:
        logger.exception(f"build_view({view}) failed")
        return f"🔴 ʀᴇɴᴅᴇʀ ꜰᴀɪʟᴇᴅ: <code>{esc(e)}</code>", InlineKeyboardMarkup([[
            InlineKeyboardButton("🏠 HOME", callback_data="db_main")]])

# ═══════════════════════ HANDLERS ═══════════════════════
@Client.on_message(filters.command("database") & filters.private)
async def cmd_database(client: Client, msg: Message):
    if not is_admin(msg.from_user.id):
        await msg.reply_text("⛔ ᴜɴᴀᴜᴛʜᴏʀɪᴢᴇᴅ."); return
    m = await msg.reply_text("🔄 ʟᴏᴀᴅɪɴɢ ᴅᴀᴛᴀʙᴀꜱᴇ ᴄᴏɴᴛʀᴏʟ ᴄᴇɴᴛᴇʀ...")
    text, kb = await build_view("main", {})
    try:
        await m.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                          disable_web_page_preview=True)
    except Exception as e:
        logger.warning(f"edit failed: {e}")

@Client.on_callback_query(filters.regex(r"^db_main$"))
async def cb_main(client, q):
    if not is_admin(q.from_user.id): await q.answer("⛔", show_alert=True); return
    await live.stop(q.message.chat.id)
    text, kb = await build_view("main", {})
    try: await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                    disable_web_page_preview=True)
    except Exception: pass
    await q.answer()

@Client.on_callback_query(filters.regex(r"^db_refresh$"))
async def cb_refresh(client, q):
    if not is_admin(q.from_user.id): await q.answer("⛔", show_alert=True); return
    cache.invalidate()
    text, kb = await build_view("main", {})
    try: await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                    disable_web_page_preview=True)
    except Exception: pass
    await q.answer("🔄 ʀᴇꜰʀᴇꜱʜᴇᴅ")

@Client.on_callback_query(filters.regex(r"^db_cat:(system|user|media|overall)$"))
async def cb_cat(client, q):
    if not is_admin(q.from_user.id): await q.answer("⛔", show_alert=True); return
    cat = q.matches[0].group(1)
    text, kb = await build_view("category", {"cat": cat})
    try: await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                    disable_web_page_preview=True)
    except Exception: pass
    await q.answer()

@Client.on_callback_query(filters.regex(r"^db_catall:(system|user|media)$"))
async def cb_catall(client, q):
    if not is_admin(q.from_user.id): await q.answer("⛔", show_alert=True); return
    cat = q.matches[0].group(1)
    text, kb = await build_view("catall", {"cat": cat})
    try: await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                    disable_web_page_preview=True)
    except Exception: pass
    await q.answer()

@Client.on_callback_query(filters.regex(r"^db_db:(system|user|media):(\d+)$"))
async def cb_db(client, q):
    if not is_admin(q.from_user.id): await q.answer("⛔", show_alert=True); return
    cat = q.matches[0].group(1); idx = int(q.matches[0].group(2))
    text, kb = await build_view("db", {"cat": cat, "index": idx})
    try: await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                    disable_web_page_preview=True)
    except Exception: pass
    await q.answer()

@Client.on_callback_query(filters.regex(r"^db_colls:(system|user|media):(\d+):(\d+)$"))
async def cb_colls(client, q):
    if not is_admin(q.from_user.id): await q.answer("⛔", show_alert=True); return
    cat = q.matches[0].group(1); idx = int(q.matches[0].group(2)); page = int(q.matches[0].group(3))
    text, kb = await build_view("colls", {"cat": cat, "index": idx, "page": page})
    try: await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                    disable_web_page_preview=True)
    except Exception: pass
    await q.answer()

@Client.on_callback_query(filters.regex(r"^db_coll:(system|user|media):(\d+):(.+)$"))
async def cb_coll(client, q):
    if not is_admin(q.from_user.id): await q.answer("⛔", show_alert=True); return
    cat = q.matches[0].group(1); idx = int(q.matches[0].group(2)); name = q.matches[0].group(3)
    text, kb = await build_view("coll", {"cat": cat, "index": idx, "name": name})
    try: await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                    disable_web_page_preview=True)
    except Exception: pass
    await q.answer()

@Client.on_callback_query(filters.regex(r"^db_recent:(system|user|media):(\d+):([^:]+):(\d+)$"))
async def cb_recent(client, q):
    if not is_admin(q.from_user.id): await q.answer("⛔", show_alert=True); return
    cat = q.matches[0].group(1); idx = int(q.matches[0].group(2))
    name = q.matches[0].group(3); lim = int(q.matches[0].group(4))
    text, kb = await build_view("recent", {"cat": cat, "index": idx, "name": name, "limit": lim})
    try: await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                    disable_web_page_preview=True)
    except Exception: pass
    await q.answer()

@Client.on_callback_query(filters.regex(r"^db_idx:(system|user|media):(\d+):(.+)$"))
async def cb_idx(client, q):
    if not is_admin(q.from_user.id): await q.answer("⛔", show_alert=True); return
    cat = q.matches[0].group(1); idx = int(q.matches[0].group(2)); name = q.matches[0].group(3)
    text, kb = await build_view("indexes", {"cat": cat, "index": idx, "name": name})
    try: await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                    disable_web_page_preview=True)
    except Exception: pass
    await q.answer()

@Client.on_callback_query(filters.regex(r"^db_health:(system|user|media|overall)$"))
async def cb_health(client, q):
    if not is_admin(q.from_user.id): await q.answer("⛔", show_alert=True); return
    cat = q.matches[0].group(1)
    text, kb = await build_view("health", {"cat": cat})
    try: await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                    disable_web_page_preview=True)
    except Exception: pass
    await q.answer()

@Client.on_callback_query(filters.regex(r"^db_perf:(system|user|media|overall)$"))
async def cb_perf(client, q):
    if not is_admin(q.from_user.id): await q.answer("⛔", show_alert=True); return
    cat = q.matches[0].group(1)
    text, kb = await build_view("perf", {"cat": cat})
    try: await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                    disable_web_page_preview=True)
    except Exception: pass
    await q.answer()

@Client.on_callback_query(filters.regex(r"^db_audit$"))
async def cb_audit(client, q):
    if not is_admin(q.from_user.id): await q.answer("⛔", show_alert=True); return
    text, kb = await build_view("audit", {})
    try: await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                    disable_web_page_preview=True)
    except Exception: pass
    await q.answer()

@Client.on_callback_query(filters.regex(r"^db_errors$"))
async def cb_errors(client, q):
    if not is_admin(q.from_user.id): await q.answer("⛔", show_alert=True); return
    text, kb = await build_view("errors", {})
    try: await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                    disable_web_page_preview=True)
    except Exception: pass
    await q.answer()

@Client.on_callback_query(filters.regex(r"^db_dups:(system|user|media):(\d+)$"))
async def cb_dups(client, q):
    if not is_admin(q.from_user.id): await q.answer("⛔", show_alert=True); return
    cat = q.matches[0].group(1); idx = int(q.matches[0].group(2))
    text, kb = await view_dups(cat, idx)
    try: await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                    disable_web_page_preview=True)
    except Exception: pass
    await q.answer()

@Client.on_callback_query(filters.regex(r"^db_dup_scan:(system|user|media):(\d+)$"))
async def cb_dup_scan(client, q):
    if not is_admin(q.from_user.id): await q.answer("⛔", show_alert=True); return
    cat = q.matches[0].group(1); idx = int(q.matches[0].group(2))
    await q.answer("🔍 ꜱᴄᴀɴɴɪɴɢ...")
    text, kb = await view_dup_scan(cat, idx)
    try: await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                    disable_web_page_preview=True)
    except Exception: pass

@Client.on_callback_query(filters.regex(r"^db_dup_remove:(system|user|media):(\d+)$"))
async def cb_dup_remove(client, q):
    if not is_admin(q.from_user.id): await q.answer("⛔", show_alert=True); return
    cat = q.matches[0].group(1); idx = int(q.matches[0].group(2))
    tok = f"dup:{cat}:{idx}:{int(time.time())}"
    confirms.start(q.from_user.id, tok, {"action": "dup_remove", "cat": cat, "index": idx})
    text = (
        "⚠️ <b>" + fb("DUPLICATE REMOVAL — STEP 1/3") + "</b>\n"
        f"{DIV}\n\n"
        f"🎯 ᴛᴀʀɢᴇᴛ · {cat.upper()} ᴅʙ {idx:02d}\n\n"
        "ᴛʜɪꜱ ᴍᴀʏ ᴅᴇʟᴇᴛᴇ ᴅᴀᴛᴀʙᴀꜱᴇ ʀᴇᴄᴏʀᴅꜱ.\n\n"
        "ᴄᴏɴᴛɪɴᴜᴇ?"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚠️ CONTINUE", callback_data=f"db_confirm:{tok}")],
        [InlineKeyboardButton("❌ CANCEL", callback_data=f"db_cancel:{tok}")],
    ])
    try: await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception: pass
    await q.answer()

@Client.on_callback_query(filters.regex(r"^db_clear:(system|user|media):(\d+)$"))
async def cb_clear(client, q):
    if not is_admin(q.from_user.id): await q.answer("⛔", show_alert=True); return
    cat = q.matches[0].group(1); idx = int(q.matches[0].group(2))
    text, kb = await view_clear(cat, idx)
    try: await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                    disable_web_page_preview=True)
    except Exception: pass
    await q.answer()

@Client.on_callback_query(filters.regex(r"^db_clear_db:(system|user|media):(\d+)$"))
async def cb_clear_db(client, q):
    if not is_admin(q.from_user.id): await q.answer("⛔", show_alert=True); return
    cat = q.matches[0].group(1); idx = int(q.matches[0].group(2))
    tok = f"clear:{cat}:{idx}:{int(time.time())}"
    confirms.start(q.from_user.id, tok, {"action": "clear_db", "cat": cat, "index": idx})
    text = (
        "⚠️ <b>" + fb("STEP 1/3 — CLEAR DATABASE") + "</b>\n"
        f"{DIV}\n\n"
        f"🎯 {cat.upper()} ᴅʙ {idx:02d}\n\n"
        "ᴀʟʟ ᴅᴏᴄᴜᴍᴇɴᴛꜱ ᴡɪʟʟ ʙᴇ ʀᴇᴍᴏᴠᴇᴅ.\n\n"
        "ᴄᴏɴᴛɪɴᴜᴇ?"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚠️ CONTINUE", callback_data=f"db_confirm:{tok}")],
        [InlineKeyboardButton("❌ CANCEL", callback_data=f"db_cancel:{tok}")],
    ])
    try: await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception: pass
    await q.answer()

@Client.on_callback_query(filters.regex(r"^db_confirm:(.+)$"))
async def cb_confirm(client, q):
    if not is_admin(q.from_user.id): await q.answer("⛔", show_alert=True); return
    tok = q.matches[0].group(1)
    entry = confirms.get(q.from_user.id, tok)
    if not entry: await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True); return
    step = entry["step"]
    if step < 3:
        confirms.advance(q.from_user.id, tok)
        if step == 1:
            text = (
                "🚨 <b>" + fb("STEP 2/3 — FINAL WARNING") + "</b>\n"
                f"{DIV}\n\n"
                "ᴛʜɪꜱ ᴄᴀɴɴᴏᴛ ʙᴇ ᴜɴᴅᴏɴᴇ.\n\n"
                "ᴄᴏɴᴛɪɴᴜᴇ?"
            )
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🚨 CONTINUE", callback_data=f"db_confirm:{tok}")],
                [InlineKeyboardButton("❌ CANCEL", callback_data=f"db_cancel:{tok}")],
            ])
        else:
            text = (
                "☢️ <b>" + fb("STEP 3/3 — PERMANENT DELETION") + "</b>\n"
                f"{DIV}\n\n"
                "ᴄʟɪᴄᴋ ʙᴇʟᴏᴡ ᴛᴏ ᴇxᴇᴄᴜᴛᴇ."
            )
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("☢️ YES, PERMANENTLY DELETE", callback_data=f"db_confirm:{tok}")],
                [InlineKeyboardButton("❌ CANCEL", callback_data=f"db_cancel:{tok}")],
            ])
        try: await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        except Exception: pass
        await q.answer()
        return
    confirms.cancel(q.from_user.id, tok)
    payload = entry["payload"]; action = payload.get("action")
    if action == "clear_db":
        text, kb = await do_clear_db(payload["cat"], payload["index"])
        try: await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                        disable_web_page_preview=True)
        except Exception: pass
        await q.answer("✅ ᴅᴏɴᴇ")
    elif action == "dup_remove":
        audit.log(q.from_user.id, "duplicate_removal_safe_mode",
                  target=f"{payload['cat']}:{payload['index']}", result="SAFE_MODE")
        text = (
            "⚠️ <b>" + fb("DUPLICATE REMOVAL — SAFE MODE") + "</b>\n"
            f"{DIV}\n\n"
            "ʀᴇᴍᴏᴠᴀʟ ɪꜱ ᴅɪꜱᴀʙʟᴇᴅ ᴛᴏ ᴘʀᴇᴠᴇɴᴛ ᴅᴀᴛᴀ ʟᴏꜱꜱ."
        )
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("◀️ BACK", callback_data="db_main")]])
        try: await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        except Exception: pass
        await q.answer("ꜱᴀꜰᴇ ᴍᴏᴅᴇ")

@Client.on_callback_query(filters.regex(r"^db_cancel:(.+)$"))
async def cb_cancel(client, q):
    if not is_admin(q.from_user.id): await q.answer("⛔", show_alert=True); return
    tok = q.matches[0].group(1)
    confirms.cancel(q.from_user.id, tok)
    try:
        await q.message.edit_text("❌ ᴄᴀɴᴄᴇʟʟᴇᴅ.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 HOME", callback_data="db_main")]]),
            parse_mode=ParseMode.HTML)
    except Exception: pass
    await q.answer("ᴄᴀɴᴄᴇʟʟᴇᴅ")

@Client.on_callback_query(filters.regex(r"^db_live$"))
async def cb_live(client, q):
    if not is_admin(q.from_user.id): await q.answer("⛔", show_alert=True); return
    chat_id = q.message.chat.id
    if live.is_live(chat_id):
        await live.stop(chat_id)
        await q.answer("🔴 ʟɪᴠᴇ ᴍᴏɴɪᴛᴏʀ ᴏꜰꜰ", show_alert=True); return
    rows = [[InlineKeyboardButton(f"{n}s", callback_data=f"db_livego:{n}") for n in LIVE_OPTIONS],
            [InlineKeyboardButton("❌ CANCEL", callback_data="db_main")]]
    try:
        await q.message.edit_text(
            "🟢 <b>" + fb("LIVE MONITOR") + "</b>\nᴄʜᴏᴏꜱᴇ ʀᴇꜰʀᴇꜱʜ ɪɴᴛᴇʀᴠᴀʟ:",
            reply_markup=InlineKeyboardMarkup(rows), parse_mode=ParseMode.HTML)
    except Exception: pass
    await q.answer()

@Client.on_callback_query(filters.regex(r"^db_livego:(\d+)$"))
async def cb_livego(client, q):
    if not is_admin(q.from_user.id): await q.answer("⛔", show_alert=True); return
    interval = int(q.matches[0].group(1))
    chat_id = q.message.chat.id
    await live.start(client, chat_id, q.message.id, "main", {})
    live._state[chat_id]["interval"] = interval
    await q.answer(f"🟢 ʟɪᴠᴇ ᴏɴ · {interval}ꜱ", show_alert=True)
    try:
        text, kb = await build_view("main", {})
        await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                    disable_web_page_preview=True)
    except Exception: pass

@Client.on_callback_query(filters.regex(r"^db_close$"))
async def cb_close(client, q):
    if not is_admin(q.from_user.id): await q.answer("⛔", show_alert=True); return
    await live.stop(q.message.chat.id)
    try: await q.message.delete()
    except Exception: pass
    await q.answer("ᴄʟᴏꜱᴇᴅ")

@Client.on_callback_query(filters.regex(r"^db_noop$"))
async def cb_noop(client, q): await q.answer()

# ═══════════════════════ CLEANUP ═══════════════════════
async def _confirm_cleanup():
    while True:
        try: confirms.cleanup()
        except Exception: pass
        await asyncio.sleep(60)

@Client.on_message(filters.command("database_cleanup") & filters.private)
async def cmd_cleanup(client, msg):
    if not is_admin(msg.from_user.id):
        await msg.reply_text("⛔ ᴜɴᴀᴜᴛʜᴏʀɪᴢᴇᴅ."); return
    await live.stop(msg.chat.id)
    await msg.reply_text("🧹 ʟɪᴠᴇ ᴍᴏɴɪᴛᴏʀ ꜱᴛᴏᴘᴘᴇᴅ ꜰᴏʀ ᴛʜɪꜱ ᴄʜᴀᴛ.")
