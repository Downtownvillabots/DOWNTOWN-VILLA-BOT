import os
from typing import List, Optional

class DatabaseConfig:
    @staticmethod
    def get_core_uri() -> str:
        return os.getenv("DATABASE_URI", "")

    @staticmethod
    def get_catalog_uri() -> Optional[str]:
        return os.getenv("CATALOG_DATABASE_URI") or os.getenv("DATABASE_URI")

    @staticmethod
    def get_media_uris() -> List[str]:
        uris = []
        multi = os.getenv("MEDIA_DATABASE_URIS")
        if multi:
            uris.extend([u.strip() for u in multi.split(",") if u.strip()])
        i = 1
        while True:
            uri = os.getenv(f"MEDIA_DATABASE_{i}")
            if not uri:
                break
            uris.append(uri.strip())
            i += 1
        if not uris:
            core = DatabaseConfig.get_core_uri()
            if core:
                uris.append(core)
        return uris

    @staticmethod
    def get_core_db_name() -> str:
        return os.getenv("CORE_DATABASE_NAME", os.getenv("DATABASE_NAME", "downtown_villa"))

    @staticmethod
    def get_catalog_db_name() -> str:
        return os.getenv("CATALOG_DATABASE_NAME", "downtown_villa_catalog")

    @staticmethod
    def get_media_db_name() -> str:
        return os.getenv("MEDIA_DATABASE_NAME", "downtown_villa_media")
