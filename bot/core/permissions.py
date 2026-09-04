"""
Permissions system.

Provides utilities to check if a user is owner, admin, or sudo.
This will be used by future plugins to restrict commands.
"""

from typing import Union

from bot.config import Config


class Permissions:
    """Static permission checker."""

    @staticmethod
    def is_owner(user_id: Union[int, str]) -> bool:
        """Check if user is an owner."""
        return int(user_id) in Config.OWNER_IDS

    @staticmethod
    def is_admin(user_id: Union[int, str]) -> bool:
        """Check if user is an admin."""
        return int(user_id) in Config.ADMIN_IDS

    @staticmethod
    def is_sudo(user_id: Union[int, str]) -> bool:
        """Check if user is a sudo."""
        return int(user_id) in Config.SUDO_IDS

    @staticmethod
    def is_privileged(user_id: Union[int, str]) -> bool:
        """Check if user has any elevated rights."""
        uid = int(user_id)
        return (
            uid in Config.OWNER_IDS
            or uid in Config.ADMIN_IDS
            or uid in Config.SUDO_IDS
        )
