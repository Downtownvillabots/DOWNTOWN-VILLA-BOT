# database/config.py
import os
from typing import List, Optional

class DatabaseConfig:
    # ---------- System (Core) ----------
    @staticmethod
    def get_system_uri() -> str:
        return os.getenv("SYSTEM_DATABASE_01", "")

    @staticmethod
    def get_system_db_name() -> str:
        return os.getenv("SYSTEM_DATABASE_NAME", "downtown_villa_system")

    # ---------- User ----------
    @staticmethod
    def get_user_uri() -> Optional[str]:
        return os.getenv("USER_DATABASE_01") or DatabaseConfig.get_system_uri()

    @staticmethod
    def get_user_db_name() -> str:
        return os.getenv("USER_DATABASE_NAME", "downtown_villa_user")

    # ---------- Catalog (optional) ----------
    @staticmethod
    def get_catalog_uri() -> Optional[str]:
        return os.getenv("CATALOG_DATABASE_01") or DatabaseConfig.get_user_uri()

    @staticmethod
    def get_catalog_db_name() -> str:
        return os.getenv("CATALOG_DATABASE_NAME", "downtown_villa_catalog")

    # ---------- Media Pool ----------
    @staticmethod
    def get_media_uris() -> List[str]:
        uris = []
        multi = os.getenv("MEDIA_DATABASE_URIS")
        if multi:
            uris.extend([u.strip() for u in multi.split(",") if u.strip()])
        i = 1
        while True:
            uri = os.getenv(f"MEDIA_DATABASE_{i:02d}") or os.getenv(f"MEDIA_DATABASE_{i}")
            if not uri:
                break
            uris.append(uri.strip())
            i += 1
        if not uris:
            fallback = DatabaseConfig.get_user_uri()
            if fallback:
                uris.append(fallback)
        return uris

    @staticmethod
    def get_media_db_name() -> str:
        return os.getenv("MEDIA_DATABASE_NAME", "downtown_villa_media")
