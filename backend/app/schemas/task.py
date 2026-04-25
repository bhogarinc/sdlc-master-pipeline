"""
Task-related Pydantic schemas.
"""

from datetime import datetime
from typing import Optional, List
from enum import Enum

from pydantic import BaseModel, Field, ConfigDict

from app.schemas.common import PaginatedResponse


class TaskStatus(str, Enum):
    """Task status enumeration."""
    BACKLOG = "backlog"
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    DONE = "done"
    CANCELLED = "cancelled"


class TaskPriority(str, Enum):
    """Task priority enumeration."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class TaskBase(BaseModel):
    """Base task schema."""
    title: str = Field(min_length=1, max_length=200, description="Task title")
    description: Optional[str] = Field(default=None, max_length=10000)
    status: TaskStatus = Field(default=TaskStatus.BACKLOG)
    priority: TaskPriority = Field(default=TaskPriority.MEDIUM)
    due_date: Optional[datetime] = Field(default=None)
    estimated_hours: Optional[float] = Field(default=None, ge=0)
    tags: List[str] = Field(default_factory=list)


class TaskCreate(TaskBase):
    """Task creation schema."""
    board_id: str = Field(description="Board ID")
    column_id: Optional[str] = Field(default=None)
    assignee_id: Optional[str] = Field(default=None)
    parent_task_id: Optional[str] = Field(default=None)


class TaskUpdate(BaseModel):
    """Task update schema (all fields optional)."""
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=10000)
    status: Optional[TaskStatus] = Field(default=None)
    priority: Optional[TaskPriority] = Field(default=None)
    due_date: Optional[datetime] = Field(default=None)
    estimated_hours: Optional[float] = Field(default=None, ge=0)
    actual_hours: Optional[float] = Field(default=None, ge=0)
    tags: Optional[List[str]] = Field(default=None)
    assignee_id: Optional[str] = Field(default=None)
    column_id: Optional[str] = Field(default=None)
    position: Optional[int] = Field(default=None, ge=0)


class TaskResponse(TaskBase):
    """Task response schema."""
    id: str
    board_id: str
    column_id: Optional[str]
    assignee_id: Optional[str]
    assignee: Optional[dict] = Field(default=None)
    parent_task_id: Optional[str]
    position: int
    created_by: str
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime]
    actual_hours: Optional[float]
    subtask_count: int = Field(default=0)
    comment_count: int = Field(default=0)
    attachment_count: int = Field(default=0)
    
    model_config = ConfigDict(from_attributes=True)


class TaskFilter(BaseModel):
    """Task filter parameters."""
    status: Optional[List[TaskStatus]] = Field(default=None)
    priority: Optional[List[TaskPriority]] = Field(default=None)
    assignee_id: Optional[List[str]] = Field(default=None)
    board_id: Optional[str] = Field(default=None)
    team_id: Optional[str] = Field(default=None)
    created_by: Optional[str] = Field(default=None)
    tags: Optional[List[str]] = Field(default=None)
    due_before: Optional[datetime] = Field(default=None)
    due_after: Optional[datetime] = Field(default=None)
    search: Optional[str] = Field(default=None)


class TaskAssigneeUpdate(BaseModel):
    """Task assignee update."""
    assignee_id: Optional[str] = Field(description="New assignee user ID or null to unassign")


class TaskStatusUpdate(BaseModel):
    """Task status update."""
    status: TaskStatus
    comment: Optional[str] = Field(default=None, description="Optional status change comment")


PaginatedTaskResponse = PaginatedResponse[TaskResponse]