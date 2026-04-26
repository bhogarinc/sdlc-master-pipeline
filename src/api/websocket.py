"""WebSocket support for real-time notifications."""
import json
import logging
from typing import Dict, List, Set
from uuid import UUID

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status
from jose import JWTError, jwt

from src.config.settings import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()
settings = get_settings()


class ConnectionManager:
    """Manages WebSocket connections for real-time notifications."""
    
    def __init__(self):
        # user_id -> set of WebSocket connections
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        # team_id -> set of user_ids
        self.team_subscriptions: Dict[str, Set[str]] = {}
    
    async def connect(self, websocket: WebSocket, user_id: str) -> None:
        """Accept connection and register user."""
        await websocket.accept()
        
        if user_id not in self.active_connections:
            self.active_connections[user_id] = set()
        self.active_connections[user_id].add(websocket)
        
        logger.info(f"WebSocket connected for user {user_id}")
    
    def disconnect(self, websocket: WebSocket, user_id: str) -> None:
        """Remove connection."""
        if user_id in self.active_connections:
            self.active_connections[user_id].discard(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
        
        # Clean up team subscriptions
        for team_id, users in self.team_subscriptions.items():
            users.discard(user_id)
        
        logger.info(f"WebSocket disconnected for user {user_id}")
    
    def subscribe_to_team(self, user_id: str, team_id: str) -> None:
        """Subscribe user to team notifications."""
        if team_id not in self.team_subscriptions:
            self.team_subscriptions[team_id] = set()
        self.team_subscriptions[team_id].add(user_id)
        logger.debug(f"User {user_id} subscribed to team {team_id}")
    
    def unsubscribe_from_team(self, user_id: str, team_id: str) -> None:
        """Unsubscribe user from team notifications."""
        if team_id in self.team_subscriptions:
            self.team_subscriptions[team_id].discard(user_id)
    
    async def send_to_user(self, user_id: str, message: dict) -> None:
        """Send message to specific user."""
        if user_id not in self.active_connections:
            return
        
        disconnected = set()
        for connection in self.active_connections[user_id]:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error sending to user {user_id}: {e}")
                disconnected.add(connection)
        
        # Clean up dead connections
        for conn in disconnected:
            self.active_connections[user_id].discard(conn)
    
    async def send_to_team(self, team_id: str, message: dict, exclude_user: str = None) -> None:
        """Send message to all team members."""
        if team_id not in self.team_subscriptions:
            return
        
        for user_id in self.team_subscriptions[team_id]:
            if user_id != exclude_user:
                await self.send_to_user(user_id, message)
    
    async def broadcast(self, message: dict) -> None:
        """Broadcast message to all connected users."""
        for user_id in list(self.active_connections.keys()):
            await self.send_to_user(user_id, message)
    
    def get_user_count(self) -> int:
        """Get total number of connected users."""
        return len(self.active_connections)
    
    def get_connection_count(self) -> int:
        """Get total number of active connections."""
        return sum(len(conns) for conns in self.active_connections.values())


# Global connection manager instance
manager = ConnectionManager()


class NotificationType:
    """Notification types."""
    TASK_CREATED = "task_created"
    TASK_UPDATED = "task_updated"
    TASK_ASSIGNED = "task_assigned"
    TASK_COMPLETED = "task_completed"
    TASK_COMMENT = "task_comment"
    TEAM_INVITE = "team_invite"
    MEMBER_JOINED = "member_joined"
    MENTION = "mention"
    SYSTEM = "system"


def create_notification(
    notification_type: str,
    title: str,
    message: str,
    data: dict = None,
    team_id: str = None,
    task_id: str = None
) -> dict:
    """Create standardized notification payload."""
    from datetime import datetime
    
    return {
        "type": notification_type,
        "title": title,
        "message": message,
        "data": data or {},
        "team_id": team_id,
        "task_id": task_id,
        "timestamp": datetime.utcnow().isoformat()
    }


async def notify_task_created(task: dict, team_id: str = None) -> None:
    """Notify about new task creation."""
    notification = create_notification(
        notification_type=NotificationType.TASK_CREATED,
        title="New Task Created",
        message=f"Task '{task['title']}' has been created",
        data={"task": task},
        team_id=team_id,
        task_id=task.get("id")
    )
    
    # Notify assignee
    if task.get("assignee_id"):
        await manager.send_to_user(task["assignee_id"], notification)
    
    # Notify team
    if team_id:
        await manager.send_to_team(
            team_id,
            notification,
            exclude_user=task.get("created_by_id")
        )


async def notify_task_assigned(task: dict, previous_assignee_id: str = None) -> None:
    """Notify about task assignment."""
    notification = create_notification(
        notification_type=NotificationType.TASK_ASSIGNED,
        title="Task Assigned",
        message=f"You have been assigned to '{task['title']}'",
        data={"task": task},
        team_id=task.get("team_id"),
        task_id=task.get("id")
    )
    
    if task.get("assignee_id") and task["assignee_id"] != previous_assignee_id:
        await manager.send_to_user(task["assignee_id"], notification)


async def notify_task_completed(task: dict) -> None:
    """Notify about task completion."""
    notification = create_notification(
        notification_type=NotificationType.TASK_COMPLETED,
        title="Task Completed",
        message=f"Task '{task['title']}' has been completed",
        data={"task": task},
        team_id=task.get("team_id"),
        task_id=task.get("id")
    )
    
    # Notify creator
    if task.get("created_by_id"):
        await manager.send_to_user(task["created_by_id"], notification)
    
    # Notify team
    if task.get("team_id"):
        await manager.send_to_team(
            task["team_id"],
            notification,
            exclude_user=task.get("assignee_id")
        )


@router.websocket("/ws/notifications")
async def websocket_notifications(websocket: WebSocket):
    """WebSocket endpoint for real-time notifications."""
    token = websocket.query_params.get("token")
    
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    
    # Validate token
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )
        user_id = payload.get("sub")
        if not user_id:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
    except JWTError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    
    await manager.connect(websocket, user_id)
    
    try:
        while True:
            # Receive and process messages from client
            data = await websocket.receive_json()
            
            message_type = data.get("type")
            
            if message_type == "subscribe_team":
                team_id = data.get("team_id")
                if team_id:
                    manager.subscribe_to_team(user_id, team_id)
                    await websocket.send_json({
                        "type": "subscribed",
                        "team_id": team_id
                    })
            
            elif message_type == "unsubscribe_team":
                team_id = data.get("team_id")
                if team_id:
                    manager.unsubscribe_from_team(user_id, team_id)
                    await websocket.send_json({
                        "type": "unsubscribed",
                        "team_id": team_id
                    })
            
            elif message_type == "ping":
                await websocket.send_json({"type": "pong"})
            
            else:
                await websocket.send_json({
                    "type": "error",
                    "message": f"Unknown message type: {message_type}"
                })
    
    except WebSocketDisconnect:
        manager.disconnect(websocket, user_id)
    except Exception as e:
        logger.error(f"WebSocket error for user {user_id}: {e}")
        manager.disconnect(websocket, user_id)


@router.get("/ws/stats")
async def get_websocket_stats() -> dict:
    """Get WebSocket connection statistics."""
    return {
        "connected_users": manager.get_user_count(),
        "active_connections": manager.get_connection_count(),
        "subscribed_teams": len(manager.team_subscriptions)
    }
