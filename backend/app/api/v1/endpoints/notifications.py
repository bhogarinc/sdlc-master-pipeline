"""
Notification API endpoints.
"""

from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.core.database import get_db
from app.core.deps import get_current_user
from app.schemas.notification import (
    NotificationResponse,
    NotificationPreferences,
    PaginatedNotificationResponse
)
from app.schemas.common import PaginationParams
from app.services.notification_service import NotificationService
from app.websockets.connection_manager import ConnectionManager

router = APIRouter()
logger = structlog.get_logger()
manager = ConnectionManager()


@router.get("", response_model=PaginatedNotificationResponse)
async def list_notifications(
    unread_only: bool = False,
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
) -> Any:
    """
    List user notifications.
    
    - unread_only: Filter to unread notifications only
    - Ordered by created_at desc
    """
    notification_service = NotificationService(db)
    
    notifications, total = await notification_service.get_user_notifications(
        user_id=current_user.id,
        unread_only=unread_only,
        pagination=pagination
    )
    
    return PaginatedNotificationResponse.create(
        items=notifications,
        total=total,
        page=pagination.page,
        page_size=pagination.page_size
    )


@router.get("/unread-count")
async def get_unread_count(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
) -> dict:
    """
    Get count of unread notifications.
    
    Used for notification badges.
    """
    notification_service = NotificationService(db)
    
    count = await notification_service.get_unread_count(current_user.id)
    
    return {"unread_count": count}


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
async def mark_as_read(
    notification_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
) -> Any:
    """
    Mark notification as read.
    """
    notification_service = NotificationService(db)
    
    notification = await notification_service.mark_as_read(
        notification_id=notification_id,
        user_id=current_user.id
    )
    
    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found"
        )
    
    return notification


@router.post("/mark-all-read", status_code=status.HTTP_200_OK)
async def mark_all_as_read(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
) -> dict:
    """
    Mark all notifications as read.
    """
    notification_service = NotificationService(db)
    
    count = await notification_service.mark_all_as_read(current_user.id)
    
    return {"marked_as_read": count}


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notification(
    notification_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
) -> None:
    """
    Delete notification.
    """
    notification_service = NotificationService(db)
    
    success = await notification_service.delete(
        notification_id=notification_id,
        user_id=current_user.id
    )
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found"
        )
    
    logger.info("notification_deleted", notification_id=notification_id)


@router.get("/preferences", response_model=NotificationPreferences)
async def get_notification_preferences(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
) -> Any:
    """
    Get user notification preferences.
    """
    notification_service = NotificationService(db)
    
    preferences = await notification_service.get_preferences(current_user.id)
    
    return preferences


@router.put("/preferences", response_model=NotificationPreferences)
async def update_notification_preferences(
    preferences: NotificationPreferences,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
) -> Any:
    """
    Update notification preferences.
    """
    notification_service = NotificationService(db)
    
    updated_preferences = await notification_service.update_preferences(
        user_id=current_user.id,
        preferences=preferences
    )
    
    return updated_preferences


# WebSocket endpoint for real-time notifications
@router.websocket("/ws")
async def notification_websocket(
    websocket: WebSocket,
    token: str
):
    """
    WebSocket endpoint for real-time notifications.
    
    - Connection: ws://api.example.com/api/v1/notifications/ws?token=JWT_TOKEN
    - Messages: JSON format
    - Auto-disconnect on invalid token
    """
    # Validate token and get user
    from app.core.security import verify_token
    
    user_id = verify_token(token)
    if not user_id:
        await websocket.close(code=4001, reason="Invalid token")
        return
    
    # Accept connection
    await manager.connect(websocket, user_id)
    
    try:
        # Send initial unread count
        await websocket.send_json({
            "type": "connection_established",
            "user_id": user_id
        })
        
        while True:
            # Keep connection alive and handle client messages
            data = await websocket.receive_text()
            message = {"type": "ack", "received": data}
            await websocket.send_json(message)
            
    except WebSocketDisconnect:
        manager.disconnect(user_id)
        logger.info("websocket_disconnected", user_id=user_id)
    except Exception as e:
        manager.disconnect(user_id)
        logger.error("websocket_error", user_id=user_id, error=str(e))