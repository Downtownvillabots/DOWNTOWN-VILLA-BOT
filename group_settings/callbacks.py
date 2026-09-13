"""
Callback constants + safe parser.
Every callback is `gs:<namespace>:<action>:<token_or_extra>`.
Never exceeds 64 bytes.
"""
from typing import Optional, Tuple


class NS:
    MAIN = "main"
    CONTENT = "content"
    SEARCH = "search"
    BUTTONS = "buttons"
    CAPTIONS = "captions"
    LINKS = "links"
    METADATA = "metadata"
    FSUB = "fsub"
    VERIFY = "verify"
    SECURITY = "security"
    WELCOME = "welcome"
    AUTODEL = "autodel"
    REQ = "req"
    STATS = "stats"
    RESET = "reset"
    OWNER = "owner"
    ADD = "add"
    VIEW = "view"


def make(ns: str, action: str, extra: str = "") -> str:
    """Build a callback string."""
    parts = ["gs", ns, action]
    if extra:
        parts.append(extra)
    out = ":".join(parts)
    if len(out.encode("utf-8")) > 64:
        # Trim extra if too long
        out = out[:64]
    return out


def parse(data: str) -> Optional[Tuple[str, str, str]]:
    """Return (namespace, action, extra) or None."""
    if not data or not data.startswith("gs:"):
        return None
    parts = data.split(":", 3)
    if len(parts) < 3:
        return None
    ns = parts[1]
    action = parts[2]
    extra = parts[3] if len(parts) > 3 else ""
    return ns, action, extra
