"""
Notification-related Pydantic schemas.
"""

from datetime import datetime
from typing import Optional, List
from enum import Enum

from pydantic import BaseModel, Field, ConfigDict

from app.schemas.common import PaginatedResponse


class NotificationType(str, Enum):
    """Notification type enumeration."""
    TASK_ASSIGNED = "task_assigned"
    TASK_UNASSIGNED = "task_unassigned"
    TASK_COMPLETED = "task_completed"
    TASK_COMMENT = "task_comment"
    TASK_MENTION = "task_mention"
    TASK_DUE_SOON = "task_due_soon"
    TASK_OVERDUE = "task_overdue"
    TEAM_INVITATION = "team_invitation"
    TEAM_MEMBER_JOINED = "team_member_joined"
    BOARD_SHARED = "board_shared"


class NotificationPriority(str, Enum):
    """Notification priority."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class NotificationBase(BaseModel):
    """Base notification schema."""
    type: NotificationType
    title: str = Field(max_length=200)
    message: str = Field(max_length=1000)
    priority: NotificationPriority = Field(default=NotificationPriority.NORMAL)


class NotificationCreate(NotificationBase):
    """Notification creation schema."""
    user_id: str
    entity_type: Optional[str] = Field(default=None)
    entity_id: Optional[str] = Field(default=None)
    metadata: Optional[dict] = Field(default=None)


class NotificationResponse(NotificationBase):
    """Notification response schema."""
    id: str
    user_id: str
    is_read: bool
    read_at: Optional[datetime]
    entity_type: Optional[str]
    entity_id: Optional[str]
    metadata: Optional[dict]
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class NotificationPreferences(BaseModel):
    """User notification preferences."""
    email_task_assigned: bool = Field(default=True)
    email_task_completed: bool = Field(default=True)
    email_task_comment: bool = Field(default=True)
    email_task_mention: bool = Field(default=True)
    email_task_due: bool = Field(default=True)
    email_team_invitation: bool = Field(default=True)
    push_task_assigned: bool = Field(default=True)
    push_task_comment: bool = Field(default=True)
    push_task_mention: bool = Field(default=True)
    push_task_due: bool = Field(default=True)
    digest_frequency: str = Field(default="daily")  # never, daily, weekly


PaginatedNotificationResponse = PaginatedResponse[NotificationResponse]