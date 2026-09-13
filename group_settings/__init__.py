"""
🏨 DOWNTOWN VILLA — Group Control System
=========================================
Modular group configuration, permissions, sessions, and statistics.

Public API:
    from group_settings import (
        config_manager, permission_manager, session_manager,
        config_cache, button_manager, caption_manager,
        link_manager, validation_manager, statistics_manager,
    )
"""

from group_settings.manager import config_manager, GroupConfigManager, DEFAULT_CONFIG
from group_settings.permissions import permission_manager, PermissionManager
from group_settings.sessions import session_manager, GroupSessionManager
from group_settings.cache import config_cache, ConfigCache
from group_settings.buttons import button_manager, ResultButtonManager
from group_settings.captions import caption_manager, CaptionManager
from group_settings.links import link_manager, GroupLinkManager
from group_settings.validation import validation_manager, GroupValidationManager
from group_settings.statistics import statistics_manager, GroupStatisticsManager

__all__ = [
    "config_manager", "GroupConfigManager", "DEFAULT_CONFIG",
    "permission_manager", "PermissionManager",
    "session_manager", "GroupSessionManager",
    "config_cache", "ConfigCache",
    "button_manager", "ResultButtonManager",
    "caption_manager", "CaptionManager",
    "link_manager", "GroupLinkManager",
    "validation_manager", "GroupValidationManager",
    "statistics_manager", "GroupStatisticsManager",
]
