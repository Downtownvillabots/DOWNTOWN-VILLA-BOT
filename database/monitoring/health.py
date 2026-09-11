from database import db_registry

class HealthRepository:
    async def get_database_health(self) -> dict:
        health = {}
        core_db = db_registry.get_core_db()
        if core_db:
            try:
                await core_db.command("ping")
                health["core"] = "ok"
            except Exception:
                health["core"] = "error"
        catalog_db = db_registry.get_catalog_db()
        if catalog_db:
            try:
                await catalog_db.command("ping")
                health["catalog"] = "ok"
            except Exception:
                health["catalog"] = "error"
        for i in range(db_registry.get_media_shard_count()):
            db = db_registry.get_media_db(i)
            try:
                await db.command("ping")
                health[f"media_{i}"] = "ok"
            except Exception:
                health[f"media_{i}"] = "error"
        return health
