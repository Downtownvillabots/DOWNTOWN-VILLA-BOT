"""
Central database manager.

Responsible for:
- Creating and reusing AsyncIOMotorClient instances.
- Connection pooling (Motor does this internally).
- Timeouts and retries.
- Automatic reconnection attempts.
- Safe logging (no credentials).
"""

import asyncio
import logging
from typing import Dict, Optional, List, Any

from bot.database.exceptions import DatabaseConnectionError

logger = logging.getLogger("database.manager")

# Default database name if not specified in URI
DEFAULT_DB_NAME = "DOWNTOWN VILLA DATABASE"

class DatabaseManager:
    """
    Manages all MongoDB connections.
    Each database URI gets its own client, but we reuse them.
    """

    def __init__(self) -> None:
        self._clients: Dict[str, Any] = {}      # uri_hash -> client
        self._databases: Dict[str, Any] = {}    # db_key -> client/db object
        self._lock = asyncio.Lock()             # prevent race conditions

    async def initialize(self):
        """Prepare the manager for use."""
        logger.debug("DatabaseManager initialized.")

    def _get_client(self, uri: str):
        """Get or create a Motor client for the given URI."""
        uri_hash = hash(uri)
        if uri_hash not in self._clients:
            from motor.motor_asyncio import AsyncIOMotorClient
            logger.debug("Creating new Motor client for URI hash %s", uri_hash)
            client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000)
            self._clients[uri_hash] = client
        return self._clients[uri_hash]

    async def get_database(self, uri: str, db_name: Optional[str] = None):
        """
        Returns a MotorDatabase object.
        If db_name is None, it tries to use the one from the URI.
        If that fails, it uses DEFAULT_DB_NAME.
        """
        client = self._get_client(uri)
        if db_name is None:
            try:
                db = client.get_default_database()
            except Exception:
                # No db name in URI – use fallback
                db = client[DEFAULT_DB_NAME]
                logger.warning("No database name in URI. Using default '%s'.", DEFAULT_DB_NAME)
        else:
            db = client[db_name]
        return db

    async def register_database(self, db_key: str, uri: str, db_name: Optional[str] = None):
        """
        Register a database in the internal map so we can retrieve it later.
        """
        async with self._lock:
            if db_key not in self._databases:
                db = await self.get_database(uri, db_name)
                self._databases[db_key] = db
                logger.info("Registered database key '%s'", db_key)
            else:
                logger.debug("Database key '%s' already registered", db_key)

    async def unregister_database(self, db_key: str):
        """Remove a database from the map."""
        async with self._lock:
            if db_key in self._databases:
                del self._databases[db_key]
                logger.info("Unregistered database key '%s'", db_key)

    def get_registered_database(self, db_key: str):
        """Return a previously registered database object, or None."""
        return self._databases.get(db_key)

    async def close_all(self):
        """Close all clients (used on shutdown)."""
        for client in self._clients.values():
            client.close()
        self._clients.clear()
        self._databases.clear()
        logger.info("All database clients closed.")
