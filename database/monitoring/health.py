from database import db_registry

class HealthRepository:
    async def get_database_health(self) -> dict:
        health = {}
        system_db = db_registry.get_system_db()
        if system_db:
            try:
                await system_db.command("ping")
                health["system"] = "ok"
            except Exception:
                health["system"] = "error"
        user_db = db_registry.get_user_db()
        if user_db:
            try:
                await user_db.command("ping")
                health["user"] = "ok"
            except Exception:
                health["user"] = "error"
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
        
