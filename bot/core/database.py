"""
Database layer.

Lazy connection: only connects if STORAGE_URI is set.
Uses Motor for async MongoDB – ready for future features.
Provides connection pooling via Motor's default pool.
"""

from typing import Optional

from bot.config import Config


class Database:
    """Async database wrapper."""

    def __init__(self) -> None:
        self._client = None
        self._db = None
        self._enabled = False

    async def connect(self) -> None:
        """Establish connection if URI is provided."""
        if not Config.STORAGE_URI:
            self._enabled = False
            return

        from motor.motor_asyncio import AsyncIOMotorClient

        self._client = AsyncIOMotorClient(Config.STORAGE_URI)
        # You can specify a database name, e.g. from the URI path.
        self._db = self._client.get_default_database()
        self._enabled = True

    async def close(self) -> None:
        """Close the connection if open."""
        if self._client:
            self._client.close()
            self._client = None
            self._db = None
            self._enabled = False

    @property
    def is_connected(self) -> bool:
        return self._enabled

    @property
    def db(self):
        """Return the database object, or None if not enabled."""
        return self._db if self._enabled else None


# Singleton instance
database = Database()
