import logging
from motor.motor_asyncio import AsyncIOMotorClient
from typing import Any, Dict, List
from database.config import DatabaseConfig

logger = logging.getLogger(__name__)

class _PoolEntry:
    def __init__(self, client: AsyncIOMotorClient, db: Any, label: str, index: int):
        self.client = client
        self.db = db
        self.label = label
        self.index = index


class DatabaseManager:
    def __init__(self):
        self._system: List[_PoolEntry] = []
        self._user: List[_PoolEntry] = []
        self._media: List[_PoolEntry] = []
        self._initialized = False
        self._db_enabled = False

    async def initialize(self) -> None:
        if self._initialized:
            return

        try:
            self._system = self._connect_pool(
                DatabaseConfig.get_system_databases(),
                DatabaseConfig.get_system_db_name(),
                "SYSTEM",
            )
            if not self._system:
                logger.warning("No SYSTEM databases configured. Database features disabled.")
                self._initialized = True
                return

            self._user = self._connect_pool(
                DatabaseConfig.get_user_databases(),
                DatabaseConfig.get_user_db_name(),
                "USER",
            ) or self._system

            self._media = self._connect_pool(
                DatabaseConfig.get_media_databases(),
                DatabaseConfig.get_media_db_name(),
                "MEDIA",
            ) or self._user

            self._db_enabled = True
            logger.info(
                f"Databases connected — SYSTEM:{len(self._system)} "
                f"USER:{len(self._user)} MEDIA:{len(self._media)}"
            )
        except Exception as e:
            logger.error(f"Database initialization failed: {e}")
            self._db_enabled = False
        finally:
            self._initialized = True

    def _connect_pool(self, configs: List[Dict[str, str]], db_name: str, tag: str) -> List[_PoolEntry]:
        entries: List[_PoolEntry] = []
        for cfg in configs:
            try:
                client = AsyncIOMotorClient(cfg["uri"])
                db = client[db_name]
                entries.append(_PoolEntry(client, db, cfg["label"], cfg["index"]))
                logger.info(f"{tag} DB #{cfg['index']:02d} → {cfg['label']}")
            except Exception as e:
                logger.error(f"{tag} DB #{cfg.get('index')} failed: {e}")
        return entries

    @property
    def is_db_enabled(self) -> bool:
        return self._db_enabled

    def get_system_entries(self) -> List[_PoolEntry]:
        return self._system

    def get_user_entries(self) -> List[_PoolEntry]:
        return self._user

    def get_media_entries(self) -> List[_PoolEntry]:
        return self._media

    def get_system_db(self):
        return self._system[0].db if self._system else None

    def get_user_db(self):
        return self._user[0].db if self._user else None

    def get_catalog_db(self):
        return self.get_user_db()

    def get_media_db(self, index: int = 0):
        if not self._media:
            return None
        if index < len(self._media):
            return self._media[index].db
        return self._media[0].db

    def get_media_db_count(self) -> int:
        return len(self._media)

    async def close(self) -> None:
        for pool in (self._system, self._user, self._media):
            for entry in pool:
                try:
                    entry.client.close()
                except Exception:
                    pass
        logger.info("All database connections closed.")
