"""Notification schemas for WebSocket and API responses"""
from typing import Optional, Dict, Any, List
from pydantic import BaseModel
from datetime import datetime
from uuid import UUID
from enum import Enum

from app.schemas.base import TimestampedSchema


class NotificationType(str, Enum):
    """Notification types"""
    TASK_ASSIGNED = "task_assigned"
    TASK_COMPLETED = "task_completed"
    TASK_COMMENTED = "task_commented"
    TASK_DUE_SOON = "task_due_soon"
    TASK_OVERDUE = "task_overdue"
    TEAM_INVITATION = "team_invitation"
    MEMBER_JOINED = "member_joined"
    MENTION = "mention"
    SYSTEM = "system"


class NotificationBase(BaseModel):
    """Base notification schema"""
    type: NotificationType
    title: str
    message: str
    data: Optional[Dict[str, Any]] = None
    link: Optional[str] = None


class NotificationResponse(NotificationBase, TimestampedSchema):
    """Notification response"""
    id: UUID
    user_id: UUID
    is_read: bool
    read_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class NotificationListResponse(BaseModel):
    """Notification list with unread count"""
    notifications: List[NotificationResponse]
    unread_count: int
    total_count: int


class NotificationMarkRead(BaseModel):
    """Mark notifications as read"""
    notification_ids: Optional[List[UUID]] = None
