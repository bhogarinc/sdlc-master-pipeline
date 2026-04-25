"""
Event Bridge for Legacy-Modern Event System Integration

Connects legacy event system with modern event-driven architecture.
Supports event transformation, routing, and async processing.
"""

from typing import Dict, Any, Optional, List, Callable, Union
from datetime import datetime
from enum import Enum
from dataclasses import dataclass, asdict
import json
import logging
from abc import ABC, abstractmethod
import asyncio

logger = logging.getLogger(__name__)


class EventType(Enum):
    """Standardized event types."""
    TASK_CREATED = "task.created"
    TASK_UPDATED = "task.updated"
    TASK_DELETED = "task.deleted"
    TASK_ASSIGNED = "task.assigned"
    TASK_COMPLETED = "task.completed"
    USER_CREATED = "user.created"
    USER_UPDATED = "user.updated"
    USER_LOGIN = "user.login"
    NOTIFICATION_SENT = "notification.sent"
    NOTIFICATION_READ = "notification.read"
    TEAM_MEMBER_ADDED = "team.member_added"
    TEAM_MEMBER_REMOVED = "team.member_removed"


class LegacyEventType(Enum):
    """Legacy event type codes."""
    T_CREATE = "TC"
    T_UPDATE = "TU"
    T_DELETE = "TD"
    T_ASSIGN = "TA"
    T_COMPLETE = "TCOMP"
    U_CREATE = "UC"
    U_UPDATE = "UU"
    U_LOGIN = "UL"
    N_SEND = "NS"
    N_READ = "NR"


@dataclass
class LegacyEvent:
    """Legacy event structure."""
    event_id: str
    event_type: str
    entity_id: str
    entity_type: str
    timestamp: str
    user_id: Optional[str] = None
    data: Optional[str] = None  # JSON string
    metadata: Optional[str] = None


@dataclass
class ModernEvent:
    """Modern event structure (CloudEvents compatible)."""
    specversion: str = "1.0"
    type: str = ""
    source: str = ""
    id: str = ""
    time: Optional[str] = None
    datacontenttype: str = "application/json"
    data: Optional[Dict[str, Any]] = None
    extensions: Optional[Dict[str, Any]] = None


class EventTransformer:
    """
    Transforms events between legacy and modern formats.
    
    Handles format conversion, field mapping, and enrichment.
    """
    
    # Event type mapping
    TYPE_MAPPING = {
        "TC": "task.created",
        "TU": "task.updated",
        "TD": "task.deleted",
        "TA": "task.assigned",
        "TCOMP": "task.completed",
        "UC": "user.created",
        "UU": "user.updated",
        "UL": "user.login",
        "NS": "notification.sent",
        "NR": "notification.read"
    }
    
    REVERSE_TYPE_MAPPING = {v: k for k, v in TYPE_MAPPING.items()}
    
    def __init__(self, source: str = "legacy-system"):
        self.source = source
    
    def to_modern(self, legacy_event: LegacyEvent) -> ModernEvent:
        """
        Transform legacy event to CloudEvents format.
        
        Args:
            legacy_event: Legacy event structure
            
        Returns:
            Modern CloudEvent structure
        """
        # Map event type
        event_type = self.TYPE_MAPPING.get(
            legacy_event.event_type,
            f"legacy.{legacy_event.event_type.lower()}"
        )
        
        # Parse data
        data = self._parse_data(legacy_event.data)
        
        # Parse metadata
        extensions = self._parse_metadata(legacy_event.metadata)
        
        # Parse timestamp
        timestamp = self._parse_timestamp(legacy_event.timestamp)
        
        return ModernEvent(
            type=event_type,
            source=self.source,
            id=legacy_event.event_id,
            time=timestamp,
            data={
                "entity_id": legacy_event.entity_id,
                "entity_type": legacy_event.entity_type,
                "user_id": legacy_event.user_id,
                **data
            },
            extensions=extensions
        )
    
    def to_legacy(self, modern_event: ModernEvent) -> LegacyEvent:
        """
        Transform modern event to legacy format.
        
        Args:
            modern_event: Modern CloudEvent structure
            
        Returns:
            Legacy event structure
        """
        # Reverse map event type
        legacy_type = self.REVERSE_TYPE_MAPPING.get(
            modern_event.type,
            modern_event.type.split(".")[-1].upper()[:5]
        )
        
        # Extract data
        data = modern_event.data or {}
        entity_id = data.get("entity_id", "")
        entity_type = data.get("entity_type", "")
        user_id = data.get("user_id")
        
        # Remove extracted fields from data
        event_data = {k: v for k, v in data.items() 
                     if k not in ("entity_id", "entity_type", "user_id")}
        
        return LegacyEvent(
            event_id=modern_event.id,
            event_type=legacy_type,
            entity_id=entity_id,
            entity_type=entity_type,
            timestamp=modern_event.time or datetime.utcnow().isoformat(),
            user_id=user_id,
            data=json.dumps(event_data) if event_data else None,
            metadata=json.dumps(modern_event.extensions) if modern_event.extensions else None
        )
    
    def _parse_data(self, data_str: Optional[str]) -> Dict[str, Any]:
        """Parse event data from JSON string."""
        if not data_str:
            return {}
        try:
            return json.loads(data_str)
        except json.JSONDecodeError:
            logger.warning(f"Could not parse event data: {data_str}")
            return {"raw_data": data_str}
    
    def _parse_metadata(self, metadata_str: Optional[str]) -> Dict[str, Any]:
        """Parse event metadata from JSON string."""
        if not metadata_str:
            return {}
        try:
            return json.loads(metadata_str)
        except json.JSONDecodeError:
            return {}
    
    def _parse_timestamp(self, timestamp_str: str) -> str:
        """Parse and normalize timestamp."""
        try:
            # Try parsing various formats
            for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"]:
                try:
                    dt = datetime.strptime(timestamp_str, fmt)
                    return dt.isoformat() + "Z"
                except ValueError:
                    continue
            return timestamp_str
        except Exception:
            return datetime.utcnow().isoformat() + "Z"


class EventHandler(ABC):
    """Abstract base class for event handlers."""
    
    @abstractmethod
    async def handle(self, event: ModernEvent) -> bool:
        """Handle an event."""
        pass
    
    @abstractmethod
    def supports(self, event_type: str) -> bool:
        """Check if handler supports event type."""
        pass


class LegacyEventBridge:
    """
    Bridge connecting legacy event system to modern event bus.
    
    Features:
    - Event transformation
    - Async event processing
    - Event routing
    - Dead letter queue for failed events
    """
    
    def __init__(
        self,
        transformer: Optional[EventTransformer] = None,
        async_mode: bool = True
    ):
        self.transformer = transformer or EventTransformer()
        self.async_mode = async_mode
        self._handlers: Dict[str, List[EventHandler]] = {}
        self._middleware: List[Callable] = []
        self._dead_letter_queue: List[Dict[str, Any]] = []
        self._event_count = 0
        self._failed_count = 0
    
    def register_handler(self, event_type: str, handler: EventHandler):
        """Register an event handler for a specific event type."""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)
        logger.info(f"Registered handler for event type: {event_type}")
    
    def register_middleware(self, middleware: Callable):
        """Register middleware for event processing."""
        self._middleware.append(middleware)
    
    async def bridge_event(self, legacy_event: LegacyEvent) -> bool:
        """
        Bridge a legacy event to the modern event system.
        
        Args:
            legacy_event: Event from legacy system
            
        Returns:
            True if successfully processed
        """
        try:
            # Transform to modern format
            modern_event = self.transformer.to_modern(legacy_event)
            
            # Apply middleware
            for middleware in self._middleware:
                modern_event = await middleware(modern_event)
                if modern_event is None:
                    logger.debug(f"Event filtered by middleware: {legacy_event.event_id}")
                    return True
            
            # Process event
            if self.async_mode:
                asyncio.create_task(self._process_event(modern_event))
            else:
                await self._process_event(modern_event)
            
            self._event_count += 1
            return True
            
        except Exception as e:
            logger.error(f"Failed to bridge event {legacy_event.event_id}: {e}")
            self._dead_letter_queue.append({
                "event": legacy_event,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            })
            self._failed_count += 1
            return False
    
    async def _process_event(self, event: ModernEvent):
        """Process a modern event through registered handlers."""
        handlers = self._handlers.get(event.type, [])
        
        # Also check wildcard handlers
        wildcard_handlers = self._handlers.get("*", [])
        all_handlers = handlers + wildcard_handlers
        
        for handler in all_handlers:
            try:
                if handler.supports(event.type):
                    success = await handler.handle(event)
                    if not success:
                        logger.warning(f"Handler failed for event {event.id}")
            except Exception as e:
                logger.error(f"Handler error for event {event.id}: {e}")
    
    def get_stats(self) -> Dict[str, int]:
        """Get bridge statistics."""
        return {
            "total_events": self._event_count,
            "failed_events": self._failed_count,
            "dead_letter_queue_size": len(self._dead_letter_queue)
        }
    
    def get_dead_letter_queue(self) -> List[Dict[str, Any]]:
        """Get failed events for reprocessing."""
        return self._dead_letter_queue.copy()
    
    def clear_dead_letter_queue(self):
        """Clear the dead letter queue."""
        self._dead_letter_queue.clear()


class WebSocketEventPublisher:
    """
    Publishes events to WebSocket connections.
    
    Enables real-time event streaming to clients.
    """
    
    def __init__(self):
        self._connections: Dict[str, Any] = {}  # user_id -> connection
        self._subscriptions: Dict[str, List[str]] = {}  # user_id -> [event_types]
    
    def subscribe(self, user_id: str, event_types: List[str]):
        """Subscribe a user to specific event types."""
        if user_id not in self._subscriptions:
            self._subscriptions[user_id] = []
        self._subscriptions[user_id].extend(event_types)
    
    def unsubscribe(self, user_id: str, event_types: Optional[List[str]] = None):
        """Unsubscribe a user from events."""
        if event_types is None:
            self._subscriptions.pop(user_id, None)
        elif user_id in self._subscriptions:
            self._subscriptions[user_id] = [
                et for et in self._subscriptions[user_id]
                if et not in event_types
            ]
    
    def register_connection(self, user_id: str, connection: Any):
        """Register a WebSocket connection."""
        self._connections[user_id] = connection
    
    async def publish(self, event: ModernEvent):
        """Publish event to subscribed connections."""
        message = json.dumps({
            "type": event.type,
            "data": event.data,
            "timestamp": event.time
        })
        
        for user_id, event_types in self._subscriptions.items():
            if event.type in event_types or "*" in event_types:
                connection = self._connections.get(user_id)
                if connection:
                    try:
                        if hasattr(connection, 'send'):
                            await connection.send(message)
                        elif hasattr(connection, 'send_text'):
                            await connection.send_text(message)
                    except Exception as e:
                        logger.error(f"Failed to send to user {user_id}: {e}")


class EventReplayHandler:
    """
    Handles replay of events for recovery or audit purposes.
    """
    
    def __init__(self, bridge: LegacyEventBridge):
        self.bridge = bridge
        self._event_store: List[LegacyEvent] = []
    
    def store_event(self, event: LegacyEvent):
        """Store event for potential replay."""
        self._event_store.append(event)
    
    async def replay_events(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        event_types: Optional[List[str]] = None
    ) -> int:
        """
        Replay stored events.
        
        Args:
            start_time: Only replay events after this time
            end_time: Only replay events before this time
            event_types: Only replay specific event types
            
        Returns:
            Number of events replayed
        """
        replayed = 0
        
        for event in self._event_store:
            event_time = datetime.fromisoformat(event.timestamp.replace('Z', '+00:00'))
            
            # Filter by time
            if start_time and event_time < start_time:
                continue
            if end_time and event_time > end_time:
                continue
            
            # Filter by type
            if event_types and event.event_type not in event_types:
                continue
            
            # Replay
            await self.bridge.bridge_event(event)
            replayed += 1
        
        return replayed
