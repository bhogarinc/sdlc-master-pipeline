"""Notification endpoints"""
from typing import Any, List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.dependencies import get_pagination, PaginationParams
from app.schemas.notification import NotificationResponse, NotificationListResponse, NotificationMarkRead
from app.schemas.base import DataResponse, BaseResponse

router = APIRouter()


@router.get("/", response_model=DataResponse[NotificationListResponse])
async def list_notifications(
    unread_only: bool = Query(False),
    pagination: PaginationParams = Depends(get_pagination),
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Any:
    """Get user notifications with unread count."""
    from app.models.notification import Notification
    from datetime import datetime
    
    query = db.query(Notification).filter(Notification.user_id == current_user.id)
    
    if unread_only:
        query = query.filter(Notification.is_read == False)
    
    total = query.count()
    unread_count = db.query(Notification).filter(
        Notification.user_id == current_user.id,
        Notification.is_read == False
    ).count()
    
    notifications = query.order_by(Notification.created_at.desc()).offset(
        pagination.offset
    ).limit(pagination.limit).all()
    
    return DataResponse(
        data=NotificationListResponse(
            notifications=notifications,
            unread_count=unread_count,
            total_count=total
        )
    )


@router.post("/mark-read", response_model=BaseResponse)
async def mark_notifications_read(
    mark_data: NotificationMarkRead,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Any:
    """Mark notifications as read."""
    from app.models.notification import Notification
    from datetime import datetime
    
    query = db.query(Notification).filter(
        Notification.user_id == current_user.id,
        Notification.is_read == False
    )
    
    if mark_data.notification_ids:
        query = query.filter(Notification.id.in_(mark_data.notification_ids))
    
    count = query.count()
    query.update({"is_read": True, "read_at": datetime.utcnow()})
    db.commit()
    
    return BaseResponse(message=f"Marked {count} notifications as read")


@router.delete("/{notification_id}", response_model=BaseResponse)
async def delete_notification(
    notification_id: str,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Any:
    """Delete a notification."""
    from app.models.notification import Notification
    from app.core.exceptions import NotFoundError
    
    notification = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.user_id == current_user.id
    ).first()
    
    if not notification:
        raise NotFoundError("Notification", notification_id)
    
    db.delete(notification)
    db.commit()
    return BaseResponse(message="Notification deleted")
