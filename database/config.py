import os

class DatabaseConfig:
    """Simple database configuration using a single URI and name."""

    @staticmethod
    def get_database_uri() -> str:
        """Return the main database URI."""
        return os.getenv("DATABASE_URI", "")

    @staticmethod
    def get_database_name() -> str:
        """Return the main database name (default: downtown_villa)."""
        return os.getenv("DATABASE_NAME", "downtown_villa")
