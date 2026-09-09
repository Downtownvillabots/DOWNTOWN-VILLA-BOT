import os
import re
from typing import Dict, List, Optional, Tuple

class DatabaseConfig:
    """Reads and validates database environment variables."""

    @staticmethod
    def _get_matching_env_vars(prefix: str) -> List[tuple[int, str]]:
        """Return sorted list of (index, value) for env vars like PREFIX_1, PREFIX_2, ..."""
        pattern = re.compile(rf"^{prefix}_(\d+)$")
        found = []
        for key, value in os.environ.items():
            match = pattern.match(key)
            if match:
                index = int(match.group(1))
                found.append((index, value))
        found.sort(key=lambda x: x[0])
        return found

    @staticmethod
    def get_system_databases() -> Dict[int, str]:
        return dict(DatabaseConfig._get_matching_env_vars("SYSTEM_DATABASE"))

    @staticmethod
    def get_user_databases() -> Dict[int, str]:
        return dict(DatabaseConfig._get_matching_env_vars("USER_DATABASE"))

    @staticmethod
    def get_media_databases() -> Dict[int, str]:
        return dict(DatabaseConfig._get_matching_env_vars("DATABASE"))

    @staticmethod
    def get_database_name(category: str, index: int, fallback: str) -> str:
        """Get the database name for a given category and index."""
        env_name = f"{category}_{index}_NAME"
        name = os.getenv(env_name)
        if name:
            return name
        # Try to extract from URI (if it has a database name)
        uris = {
            "SYSTEM": DatabaseConfig.get_system_databases(),
            "USER": DatabaseConfig.get_user_databases(),
            "DATABASE": DatabaseConfig.get_media_databases()
        }.get(category, {})
        uri = uris.get(index)
        if uri:
            # Parse database name from URI
            # Format: mongodb://user:pass@host:port/dbname?...
            parts = uri.split('/')
            if len(parts) >= 4:
                db_part = parts[3].split('?')[0]
                if db_part:
                    return db_part
        # Fallback
        return f"{fallback}_{index}"

    @staticmethod
    def get_media_threshold_mb() -> Optional[int]:
        raw = os.getenv("MEDIA_DB_THRESHOLD_MB")
        if raw:
            try:
                return int(raw)
            except ValueError:
                pass
        return None
