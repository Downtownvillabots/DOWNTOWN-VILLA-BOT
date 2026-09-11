from database.connection import DatabaseManager
from database.registry import DatabaseRegistry

db_manager = DatabaseManager()
db_registry = DatabaseRegistry(db_manager)
