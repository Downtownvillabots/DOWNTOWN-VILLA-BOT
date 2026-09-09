import os
import logging

logger = logging.getLogger(__name__)

class DatabaseConfig:
    @staticmethod
    def get_database_uri() -> str:
        uri = os.getenv("DATABASE_URI", "")
        # Debug: log whether URI is set and its length (mask password)
        if uri:
            # Mask password for safe logging
            safe_uri = uri.split("@")[-1] if "@" in uri else uri
            logger.info(f"DATABASE_URI is set (length {len(uri)}). Host part: {safe_uri}")
        else:
            logger.warning("DATABASE_URI is empty or not set.")
        return uri

    @staticmethod
    def get_database_name() -> str:
        return os.getenv("DATABASE_NAME", "downtown_villa")
