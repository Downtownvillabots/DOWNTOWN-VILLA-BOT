"""
Helper functions for common tasks:
 - Human‑readable file size.
 - Caption rendering with placeholders.
"""

import re
from typing import Dict, Optional


def human_readable_size(size_bytes: int) -> str:
    """Convert bytes to a human readable string."""
    if size_bytes == 0:
        return "0 B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(min(len(size_name) - 1, (size_bytes.bit_length() - 1) // 10))
    p = 1024 ** i
    s = size_bytes / p
    return f"{s:.2f} {size_name[i]}"


def render_caption(template: str, **kwargs) -> str:
    """
    Replace placeholders like {name} or {file_size} in a caption template.
    Example:
        render_caption("Hello {name}, here is {file_size}", name="Alice", file_size="1.2 MB")
    """
    # Cache compiled regex for performance
    _placeholder_re = re.compile(r"\{(\w+)\}")

    def repl(match):
        key = match.group(1)
        return str(kwargs.get(key, match.group(0)))

    return _placeholder_re.sub(repl, template)
