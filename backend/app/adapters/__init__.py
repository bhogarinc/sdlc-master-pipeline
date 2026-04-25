"""
TaskFlow Pro - Legacy Adapter Module

This module provides adapter and facade layers for integrating legacy systems
with the modern TaskFlow Pro application.

Components:
- Adapters: Convert between legacy and modern interfaces
- Anti-Corruption Layers: Prevent legacy concepts from leaking
- Data Mappers: Transform data between formats
- Event Bridges: Connect legacy events to modern event system
- Auth Bridge: Unify authentication mechanisms
"""

from .base import Adapter, BaseAdapter, TwoWayAdapter
from .task_adapter import LegacyTaskAdapter, ModernTaskAdapter
from .user_adapter import LegacyUserAdapter, UserMigrationAdapter
from .notification_adapter import NotificationBridgeAdapter
from .auth_bridge import AuthenticationBridge, LegacyAuthAdapter, ModernAuthAdapter
from .data_mappers import (
    TaskDataMapper,
    UserDataMapper,
    NotificationDataMapper,
    TeamDataMapper
)
from .event_bridge import LegacyEventBridge, EventTransformer
from .anti_corruption import (
    TaskDomainACL,
    UserDomainACL,
    NotificationACL,
    LegacyContextIsolator
)
from .api_compatibility import (
    LegacyAPICompatibilityLayer,
    VersionedAPIRouter,
    ResponseTransformer
)

__version__ = "1.0.0"
__all__ = [
    # Base Classes
    "Adapter",
    "BaseAdapter",
    "TwoWayAdapter",
    # Task Adapters
    "LegacyTaskAdapter",
    "ModernTaskAdapter",
    # User Adapters
    "LegacyUserAdapter",
    "UserMigrationAdapter",
    # Notification Adapters
    "NotificationBridgeAdapter",
    # Auth Bridge
    "AuthenticationBridge",
    "LegacyAuthAdapter",
    "ModernAuthAdapter",
    # Data Mappers
    "TaskDataMapper",
    "UserDataMapper",
    "NotificationDataMapper",
    "TeamDataMapper",
    # Event Bridge
    "LegacyEventBridge",
    "EventTransformer",
    # Anti-Corruption Layers
    "TaskDomainACL",
    "UserDomainACL",
    "NotificationACL",
    "LegacyContextIsolator",
    # API Compatibility
    "LegacyAPICompatibilityLayer",
    "VersionedAPIRouter",
    "ResponseTransformer",
]
