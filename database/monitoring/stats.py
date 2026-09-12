from database import db_registry

class StatsRepository:
    async def get_user_count(self) -> int:
        db = db_registry.get_user_db()
        return await db["users"].estimated_document_count()

    async def get_group_count(self) -> int:
        db = db_registry.get_user_db()
        return await db["groups"].estimated_document_count()

    async def get_media_count(self) -> int:
        total = 0
        for i in range(db_registry.get_media_shard_count()):
            db = db_registry.get_media_db(i)
            total += await db["media_files"].estimated_document_count()
        return total
