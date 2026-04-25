"""Task schemas for request/response validation"""
from typing import Optional, List
from pydantic import BaseModel, Field
from datetime import datetime
from uuid import UUID
from enum import Enum

from app.schemas.base import TimestampedSchema
from app.schemas.user import UserResponse


class TaskStatus(str, Enum):
    """Task status enum"""
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    DONE = "done"
    CANCELLED = "cancelled"


class TaskPriority(str, Enum):
    """Task priority enum"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class TaskBase(BaseModel):
    """Base task schema"""
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=5000)
    status: TaskStatus = TaskStatus.TODO
    priority: TaskPriority = TaskPriority.MEDIUM
    due_date: Optional[datetime] = None
    estimated_hours: Optional[float] = Field(None, ge=0, le=1000)
    tags: List[str] = []


class TaskCreate(TaskBase):
    """Task creation schema"""
    team_id: Optional[UUID] = None
    assignee_id: Optional[UUID] = None


class TaskUpdate(BaseModel):
    """Task update schema"""
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=5000)
    status: Optional[TaskStatus] = None
    priority: Optional[TaskPriority] = None
    due_date: Optional[datetime] = None
    estimated_hours: Optional[float] = Field(None, ge=0, le=1000)
    assignee_id: Optional[UUID] = None
    tags: Optional[List[str]] = None


class TaskResponse(TaskBase, TimestampedSchema):
    """Task response schema"""
    id: UUID
    creator_id: UUID
    assignee: Optional[UserResponse] = None
    team_id: Optional[UUID] = None
    completed_at: Optional[datetime] = None
    actual_hours: Optional[float] = None
    
    class Config:
        from_attributes = True


class TaskDetailResponse(TaskResponse):
    """Task with full details"""
    creator: UserResponse
    comments_count: int = 0
    attachments_count: int = 0


class TaskBulkUpdate(BaseModel):
    """Bulk task update"""
    task_ids: List[UUID]
    status: Optional[TaskStatus] = None
    priority: Optional[TaskPriority] = None
    assignee_id: Optional[UUID] = None


class TaskCommentCreate(BaseModel):
    """Task comment creation"""
    content: str = Field(..., min_length=1, max_length=2000)


class TaskCommentResponse(BaseModel):
    """Task comment response"""
    id: UUID
    content: str
    author: UserResponse
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True
