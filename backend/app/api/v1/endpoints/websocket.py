"""WebSocket endpoints for real-time features"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from typing import Dict, Set
import json
import logging

from app.core.security import decode_token

router = APIRouter()
logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections"""
    
    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        self.task_subscriptions: Dict[str, Set[str]] = {}
    
    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = set()
        self.active_connections[user_id].add(websocket)
        logger.info(f"User {user_id} connected")
    
    def disconnect(self, websocket: WebSocket, user_id: str):
        if user_id in self.active_connections:
            self.active_connections[user_id].discard(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
        for task_id, users in self.task_subscriptions.items():
            users.discard(user_id)
        logger.info(f"User {user_id} disconnected")
    
    def subscribe_to_task(self, user_id: str, task_id: str):
        if task_id not in self.task_subscriptions:
            self.task_subscriptions[task_id] = set()
        self.task_subscriptions[task_id].add(user_id)
    
    def unsubscribe_from_task(self, user_id: str, task_id: str):
        if task_id in self.task_subscriptions:
            self.task_subscriptions[task_id].discard(user_id)
    
    async def send_to_user(self, user_id: str, message: dict):
        if user_id in self.active_connections:
            disconnected = set()
            for connection in self.active_connections[user_id]:
                try:
                    await connection.send_json(message)
                except Exception:
                    disconnected.add(connection)
            for conn in disconnected:
                self.active_connections[user_id].discard(conn)
    
    async def broadcast_to_task(self, task_id: str, message: dict, exclude_user: str = None):
        if task_id in self.task_subscriptions:
            for user_id in self.task_subscriptions[task_id]:
                if user_id != exclude_user:
                    await self.send_to_user(user_id, message)


manager = ConnectionManager()


@router.websocket("/")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(...)):
    """WebSocket endpoint for real-time updates."""
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        await websocket.close(code=4001, reason="Invalid token")
        return
    
    user_id = payload.get("sub")
    if not user_id:
        await websocket.close(code=4001, reason="Invalid token")
        return
    
    await manager.connect(websocket, user_id)
    
    try:
        while True:
            data = await websocket.receive_text()
            
            try:
                message = json.loads(data)
                msg_type = message.get("type")
                payload_data = message.get("payload", {})
                
                if msg_type == "subscribe_task":
                    task_id = payload_data.get("task_id")
                    manager.subscribe_to_task(user_id, task_id)
                    await websocket.send_json({"type": "subscribed", "payload": {"task_id": task_id}})
                
                elif msg_type == "unsubscribe_task":
                    task_id = payload_data.get("task_id")
                    manager.unsubscribe_from_task(user_id, task_id)
                
                elif msg_type == "typing":
                    task_id = payload_data.get("task_id")
                    is_typing = payload_data.get("is_typing", False)
                    await manager.broadcast_to_task(
                        task_id,
                        {"type": "typing", "payload": {"task_id": task_id, "user_id": user_id, "is_typing": is_typing}},
                        exclude_user=user_id
                    )
                
                elif msg_type == "ping":
                    await websocket.send_json({"type": "pong"})
                
                else:
                    await websocket.send_json({"type": "error", "payload": {"message": f"Unknown type: {msg_type}"}})
            
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "payload": {"message": "Invalid JSON"}})
    
    except WebSocketDisconnect:
        manager.disconnect(websocket, user_id)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket, user_id)


async def notify_user(user_id: str, notification: dict):
    await manager.send_to_user(user_id, {"type": "notification", "payload": notification})


async def notify_task_update(task_id: str, update: dict, exclude_user: str = None):
    await manager.broadcast_to_task(task_id, {"type": "task_update", "payload": update}, exclude_user=exclude_user)
