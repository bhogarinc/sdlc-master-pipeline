"""
Notification Bridge Adapter for Legacy-Modern Notification System Integration

Provides adapters for converting between legacy notification formats and modern
TaskFlow Pro notification models. Supports real-time WebSocket bridging.
"""

from typing import Optional, List, Dict, Any, Union
from datetime import datetime
from enum import Enum
import json
import logging

from .base import TwoWayAdapter, AdapterContext, AdaptationError

logger = logging.getLogger(__name__)


class LegacyNotificationType(Enum):
    """Legacy notification type values."""
    EMAIL = "E"
    SMS = "S"
    PUSH = "P"
    IN_APP = "I"


class ModernNotificationType(Enum):
    """Modern notification type values."""
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"
    IN_APP = "in_app"
    WEBSOCKET = "websocket"


class LegacyNotificationPriority(Enum):
    """Legacy priority values (numeric)."""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    URGENT = 4


class ModernNotificationPriority(Enum):
    """Modern priority values."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class LegacyNotification:
    """Legacy notification data structure."""
    
    def __init__(
        self,
        notification_id: str,
        recipient_id: str,
        type: str,
        subject: str,
        message: str,
        priority: int = 2,
        status: str = "pending",
        created_date: Optional[str] = None,
        sent_date: Optional[str] = None,
        read_date: Optional[str] = None,
        action_url: Optional[str] = None,
        action_label: Optional[str] = None,
        metadata: Optional[str] = None,  # JSON string
        template_id: Optional[str] = None
    ):
        self.notification_id = notification_id
        self.recipient_id = recipient_id
        self.type = type
        self.subject = subject
        self.message = message
        self.priority = priority
        self.status = status
        self.created_date = created_date
        self.sent_date = sent_date
        self.read_date = read_date
        self.action_url = action_url
        self.action_label = action_label
        self.metadata = metadata
        self.template_id = template_id


class ModernNotification:
    """Modern notification data structure (TaskFlow Pro)."""
    
    def __init__(
        self,
        id: str,
        user_id: str,
        type: str,
        title: str,
        content: str,
        priority: str = "normal",
        status: str = "pending",
        created_at: Optional[datetime] = None,
        sent_at: Optional[datetime] = None,
        read_at: Optional[datetime] = None,
        action: Optional[Dict[str, str]] = None,
        data: Optional[Dict[str, Any]] = None,
        template_id: Optional[str] = None,
        channel: str = "in_app",
        delivery_attempts: int = 0,
        error_message: Optional[str] = None
    ):
        self.id = id
        self.user_id = user_id
        self.type = type
        self.title = title
        self.content = content
        self.priority = priority
        self.status = status
        self.created_at = created_at
        self.sent_at = sent_at
        self.read_at = read_at
        self.action = action
        self.data = data or {}
        self.template_id = template_id
        self.channel = channel
        self.delivery_attempts = delivery_attempts
        self.error_message = error_message


class NotificationBridgeAdapter(TwoWayAdapter[LegacyNotification, ModernNotification]):
    """
    Bidirectional adapter for notification systems.
    
    Bridges legacy notification system with modern WebSocket-based system.
    Handles type mapping, priority conversion, and metadata transformation.
    """
    
    # Type mapping
    TYPE_TO_MODERN = {
        "E": "email",
        "S": "sms",
        "P": "push",
        "I": "in_app"
    }
    
    TYPE_TO_LEGACY = {v: k for k, v in TYPE_TO_MODERN.items()}
    
    # Priority mapping
    PRIORITY_TO_MODERN = {
        1: "low",
        2: "normal",
        3: "high",
        4: "urgent"
    }
    
    PRIORITY_TO_LEGACY = {v: k for k, v in PRIORITY_TO_MODERN.items()}
    
    # Status mapping
    STATUS_TO_MODERN = {
        "pending": "pending",
        "sent": "sent",
        "delivered": "delivered",
        "read": "read",
        "failed": "failed",
        "cancelled": "cancelled"
    }
    
    def __init__(self, context: Optional[AdapterContext] = None):
        super().__init__(context)
        self._date_format = "%Y-%m-%d %H:%M:%S"
        self._websocket_enabled = True
    
    def to_modern(self, legacy_data: LegacyNotification) -> ModernNotification:
        """Convert legacy notification to modern format."""
        try:
            # Parse dates
            created_at = self._parse_date(legacy_data.created_date) or datetime.utcnow()
            sent_at = self._parse_date(legacy_data.sent_date)
            read_at = self._parse_date(legacy_data.read_date)
            
            # Convert type
            type_val = self.TYPE_TO_MODERN.get(legacy_data.type, "in_app")
            
            # Convert priority
            priority = self.PRIORITY_TO_MODERN.get(legacy_data.priority, "normal")
            
            # Parse metadata
            data = self._parse_metadata(legacy_data.metadata)
            
            # Build action
            action = None
            if legacy_data.action_url:
                action = {
                    "url": legacy_data.action_url,
                    "label": legacy_data.action_label or "View"
                }
            
            return ModernNotification(
                id=legacy_data.notification_id,
                user_id=legacy_data.recipient_id,
                type=type_val,
                title=legacy_data.subject,
                content=legacy_data.message,
                priority=priority,
                status=legacy_data.status,
                created_at=created_at,
                sent_at=sent_at,
                read_at=read_at,
                action=action,
                data=data,
                template_id=legacy_data.template_id,
                channel=type_val
            )
            
        except Exception as e:
            logger.error(f"Failed to adapt legacy notification {legacy_data.notification_id}: {str(e)}")
            raise AdaptationError(
                f"Notification adaptation failed: {str(e)}",
                legacy_data,
                self.context
            )
    
    def to_legacy(self, modern_data: ModernNotification) -> LegacyNotification:
        """Convert modern notification to legacy format."""
        try:
            # Convert type
            type_val = self.TYPE_TO_LEGACY.get(modern_data.type, "I")
            
            # Convert priority
            priority = self.PRIORITY_TO_LEGACY.get(modern_data.priority, 2)
            
            # Format dates
            created_date = self._format_date(modern_data.created_at)
            sent_date = self._format_date(modern_data.sent_at)
            read_date = self._format_date(modern_data.read_at)
            
            # Serialize metadata
            metadata = json.dumps(modern_data.data) if modern_data.data else None
            
            # Extract action
            action_url = None
            action_label = None
            if modern_data.action:
                action_url = modern_data.action.get("url")
                action_label = modern_data.action.get("label")
            
            return LegacyNotification(
                notification_id=modern_data.id,
                recipient_id=modern_data.user_id,
                type=type_val,
                subject=modern_data.title,
                message=modern_data.content,
                priority=priority,
                status=modern_data.status,
                created_date=created_date,
                sent_date=sent_date,
                read_date=read_date,
                action_url=action_url,
                action_label=action_label,
                metadata=metadata,
                template_id=modern_data.template_id
            )
            
        except Exception as e:
            logger.error(f"Failed to convert modern notification {modern_data.id} to legacy: {str(e)}")
            raise AdaptationError(
                f"Notification conversion failed: {str(e)}",
                modern_data,
                self.context
            )
    
    def _parse_date(self, date_str: Optional[str]) -> Optional[datetime]:
        """Parse date string to datetime."""
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str, self._date_format)
        except ValueError:
            logger.warning(f"Could not parse date: {date_str}")
            return None
    
    def _format_date(self, dt: Optional[datetime]) -> Optional[str]:
        """Format datetime to string."""
        if not dt:
            return None
        return dt.strftime(self._date_format)
    
    def _parse_metadata(self, metadata_str: Optional[str]) -> Dict[str, Any]:
        """Parse JSON metadata string."""
        if not metadata_str:
            return {}
        try:
            return json.loads(metadata_str)
        except json.JSONDecodeError:
            logger.warning(f"Could not parse metadata JSON: {metadata_str}")
            return {"raw_metadata": metadata_str}


class WebSocketNotificationBridge:
    """
    Bridge for real-time notification delivery via WebSocket.
    
    Connects legacy notification events to modern WebSocket system.
    """
    
    def __init__(self, adapter: Optional[NotificationBridgeAdapter] = None):
        self.adapter = adapter or NotificationBridgeAdapter()
        self._websocket_connections: Dict[str, Any] = {}  # user_id -> connection
        self._event_handlers: Dict[str, List[callable]] = {}
    
    def register_connection(self, user_id: str, connection: Any):
        """Register a WebSocket connection for a user."""
        self._websocket_connections[user_id] = connection
        logger.info(f"Registered WebSocket connection for user {user_id}")
    
    def unregister_connection(self, user_id: str):
        """Unregister a WebSocket connection."""
        if user_id in self._websocket_connections:
            del self._websocket_connections[user_id]
            logger.info(f"Unregistered WebSocket connection for user {user_id}")
    
    def bridge_notification(self, legacy_notification: LegacyNotification) -> bool:
        """
        Bridge a legacy notification to WebSocket.
        
        Args:
            legacy_notification: Notification from legacy system
            
        Returns:
            True if successfully bridged, False otherwise
        """
        try:
            # Convert to modern format
            modern_notification = self.adapter.to_modern(legacy_notification)
            
            # Get user connection
            user_id = modern_notification.user_id
            connection = self._websocket_connections.get(user_id)
            
            if not connection:
                logger.warning(f"No WebSocket connection for user {user_id}")
                return False
            
            # Build WebSocket message
            ws_message = {
                "type": "notification",
                "data": {
                    "id": modern_notification.id,
                    "title": modern_notification.title,
                    "content": modern_notification.content,
                    "priority": modern_notification.priority,
                    "action": modern_notification.action,
                    "timestamp": modern_notification.created_at.isoformat() if modern_notification.created_at else None
                }
            }
            
            # Send via WebSocket
            self._send_ws_message(connection, ws_message)
            
            # Trigger event handlers
            self._trigger_event("notification_sent", {
                "notification_id": modern_notification.id,
                "user_id": user_id,
                "channel": "websocket"
            })
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to bridge notification: {str(e)}")
            return False
    
    def on_event(self, event_type: str, handler: callable):
        """Register an event handler."""
        if event_type not in self._event_handlers:
            self._event_handlers[event_type] = []
        self._event_handlers[event_type].append(handler)
    
    def _trigger_event(self, event_type: str, data: Dict[str, Any]):
        """Trigger event handlers."""
        handlers = self._event_handlers.get(event_type, [])
        for handler in handlers:
            try:
                handler(data)
            except Exception as e:
                logger.error(f"Event handler error: {str(e)}")
    
    def _send_ws_message(self, connection: Any, message: Dict[str, Any]):
        """Send message via WebSocket connection."""
        # This would integrate with actual WebSocket implementation
        # For now, we assume connection has a send method
        if hasattr(connection, 'send'):
            connection.send(json.dumps(message))
        elif hasattr(connection, 'send_text'):
            connection.send_text(json.dumps(message))
        else:
            raise AdaptationError("WebSocket connection has no send method")


class NotificationBatchBridge:
    """
    Bridge for batch notification processing.
    
    Handles bulk migration and bridging of notifications.
    """
    
    def __init__(self, adapter: Optional[NotificationBridgeAdapter] = None):
        self.adapter = adapter or NotificationBridgeAdapter()
        self.ws_bridge = WebSocketNotificationBridge(self.adapter)
        self.results = {
            "success": [],
            "failed": [],
            "skipped": []
        }
    
    def bridge_batch(
        self,
        legacy_notifications: List[LegacyNotification],
        use_websocket: bool = True
    ) -> Dict[str, Any]:
        """
        Bridge a batch of notifications.
        
        Args:
            legacy_notifications: List of legacy notifications
            use_websocket: Whether to send via WebSocket
            
        Returns:
            Processing results
        """
        for notification in legacy_notifications:
            try:
                if use_websocket:
                    success = self.ws_bridge.bridge_notification(notification)
                    if success:
                        self.results["success"].append(notification.notification_id)
                    else:
                        self.results["skipped"].append(notification.notification_id)
                else:
                    # Just convert and store
                    modern = self.adapter.to_modern(notification)
                    self.results["success"].append(notification.notification_id)
                    
            except AdaptationError as e:
                self.results["failed"].append({
                    "id": notification.notification_id,
                    "error": str(e)
                })
        
        return self.get_summary()
    
    def get_summary(self) -> Dict[str, int]:
        """Get batch processing summary."""
        return {
            "total": sum(len(v) for v in self.results.values()),
            "successful": len(self.results["success"]),
            "failed": len(self.results["failed"]),
            "skipped": len(self.results["skipped"])
        }
