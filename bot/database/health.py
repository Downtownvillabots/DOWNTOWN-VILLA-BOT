"""
Health monitoring.

Periodically checks the status of all databases.
Uses MongoDB's ping command to determine connectivity.
"""

import asyncio
import logging
from datetime import datetime

from bot.database.manager import DatabaseManager
from bot.database.registry import DatabaseRegistry

logger = logging.getLogger("database.health")

class HealthMonitor:
    """Monitors database health and updates registry status."""

    def __init__(self, manager: DatabaseManager, registry: DatabaseRegistry, interval: int = 60):
        self.manager = manager
        self.registry = registry
        self.interval = interval
        self._task = None
        self._running = False

    async def _check_one(self, key: str):
        """Ping a single database to check if it's reachable."""
        info = self.registry.get_info(key)
        if not info:
            return
        db = self.manager.get_registered_database(key)
        if db is None:
            info.status = "🔴 OFFLINE"
            logger.warning("Database '%s' not registered, marking offline.", key)
            return
        try:
            await db.command("ping")
            info.status = "🟢 ONLINE"
            logger.debug("Database '%s' is online.", key)
        except Exception as e:
            info.status = "🔴 OFFLINE"
            logger.error("Database '%s' ping failed: %s", key, e)

    async def check_all(self):
        """Check all databases in parallel."""
        keys = [info.key for info in self.registry.get_all()]
        await asyncio.gather(*[self._check_one(k) for k in keys])

    async def _loop(self):
        """Background loop that runs every interval."""
        self._running = True
        while self._running:
            await self.check_all()
            await asyncio.sleep(self.interval)

    async def start(self):
        """Start the background monitoring task."""
        self._task = asyncio.create_task(self._loop())
        logger.info("Health monitor started (interval %ds).", self.interval)

    async def stop(self):
        """Stop the monitor."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Health monitor stopped.")
