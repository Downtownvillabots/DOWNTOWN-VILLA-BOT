import os
from typing import List, Dict

class DatabaseConfig:
    # ---------- Dynamic list readers ----------
    @staticmethod
    def _read_list(prefix: str, name_prefix: str) -> List[Dict[str, str]]:
        items: List[Dict[str, str]] = []
        i = 1
        while True:
            uri = os.getenv(f"{prefix}_{i:02d}") or os.getenv(f"{prefix}_{i}")
            if not uri:
                break
            name = (
                os.getenv(f"{name_prefix}_{i:02d}")
                or os.getenv(f"{name_prefix}_{i}")
                or f"{prefix}-{i:02d}"
            )
            items.append({"uri": uri.strip(), "label": name.strip(), "index": i})
            i += 1
        return items

    # ---------- SYSTEM ----------
    @staticmethod
    def get_system_databases() -> List[Dict[str, str]]:
        items = DatabaseConfig._read_list("SYSTEM_DATABASE", "SYSTEM_DATABASE_NAME")
        if items:
            return items
        legacy = os.getenv("DATABASE_URI", "")
        if legacy:
            return [{
                "uri": legacy.strip(),
                "label": os.getenv("SYSTEM_DATABASE_NAME_01", "SYSTEM-01"),
                "index": 1,
            }]
        return []

    # ---------- USER ----------
    @staticmethod
    def get_user_databases() -> List[Dict[str, str]]:
        items = DatabaseConfig._read_list("USER_DATABASE", "USER_DATABASE_NAME")
        if items:
            return items
        sysdbs = DatabaseConfig.get_system_databases()
        if sysdbs:
            return [{
                "uri": sysdbs[0]["uri"],
                "label": "USERS-01",
                "index": 1,
            }]
        return []

    # ---------- MEDIA ----------
    @staticmethod
    def get_media_databases() -> List[Dict[str, str]]:
        items = DatabaseConfig._read_list("MEDIA_DATABASE", "MEDIA_DATABASE_NAME")
        if items:
            return items
        userdbs = DatabaseConfig.get_user_databases()
        if userdbs:
            return [{
                "uri": userdbs[0]["uri"],
                "label": "MEDIA-01",
                "index": 1,
            }]
        return []

    # ---------- Database names inside MongoDB ----------
    @staticmethod
    def get_system_db_name() -> str:
        return os.getenv("SYSTEM_DATABASE_DB", "downtown_villa_system")

    @staticmethod
    def get_user_db_name() -> str:
        return os.getenv("USER_DATABASE_DB", "downtown_villa_user")

    @staticmethod
    def get_media_db_name() -> str:
        return os.getenv("MEDIA_DATABASE_DB", "downtown_villa_media")
