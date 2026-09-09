import os

class DatabaseConfig:
    @staticmethod
    def get_database_uri() -> str:
        return os.getenv("DATABASE_URI", "")

    @staticmethod
    def get_database_name() -> str:
        return os.getenv("DATABASE_NAME", "downtown_villa")
