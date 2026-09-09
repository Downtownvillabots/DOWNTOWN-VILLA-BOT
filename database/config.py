import os
import re
from typing import Dict, List, Optional

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
        found.sort(key=lambda x: x[0])  # sort by index
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
    def get_media_threshold_mb() -> Optional[int]:
        raw = os.getenv("MEDIA_DB_THRESHOLD_MB")
        if raw:
            try:
                return int(raw)
            except ValueError:
                pass
        return None  # default later
