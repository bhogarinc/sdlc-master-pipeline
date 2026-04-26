"""Task model with workflow and collaboration features."""
import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, Index
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import BaseModel

if TYPE_CHECKING:
    from src.models.team import Team
    from src.models.user import User


class TaskStatus(str, enum.Enum):
    """Task status enumeration."""
    BACKLOG = "backlog"
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    DONE = "done"
    CANCELLED = "cancelled"


class TaskPriority(str, enum.Enum):
    """Task priority enumeration."""
    LOWEST = "lowest"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    HIGHEST = "highest"


class TaskType(str, enum.Enum):
    """Task type enumeration."""
    TASK = "task"
    BUG = "bug"
    FEATURE = "feature"
    EPIC = "epic"
    STORY = "story"


class Task(BaseModel):
    """Task entity with workflow and collaboration support."""
    
    __tablename__ = "tasks"
    
    # Basic Info
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )
    task_type: Mapped[TaskType] = mapped_column(
        Enum(TaskType),
        default=TaskType.TASK,
        nullable=False
    )
    
    # Status & Priority
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus),
        default=TaskStatus.BACKLOG,
        nullable=False,
        index=True
    )
    priority: Mapped[TaskPriority] = mapped_column(
        Enum(TaskPriority),
        default=TaskPriority.MEDIUM,
        nullable=False
    )
    
    # Estimation
    story_points: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True
    )
    estimated_hours: Mapped[Optional[float]] = mapped_column(
        nullable=True
    )
    actual_hours: Mapped[Optional[float]] = mapped_column(
        nullable=True
    )
    
    # Scheduling
    due_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    
    # Relationships
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False
    )
    creator: Mapped["User"] = relationship(
        "User",
        foreign_keys=[created_by_id],
        back_populates="created_tasks"
    )
    
    assignee_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )
    assignee: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[assignee_id],
        back_populates="assigned_tasks"
    )
    
    team_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=True,
        index=True
    )
    team: Mapped[Optional["Team"]] = relationship(
        "Team",
        back_populates="tasks"
    )
    
    # Hierarchy
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=True
    )
    subtasks: Mapped[List["Task"]] = relationship(
        "Task",
        back_populates="parent",
        remote_side="Task.id",
        lazy="selectin"
    )
    parent: Mapped[Optional["Task"]] = relationship(
        "Task",
        back_populates="subtasks",
        remote_side="Task.id"
    )
    
    # Metadata
    tags: Mapped[List[str]] = mapped_column(
        ARRAY(String),
        default=list,
        nullable=False
    )
    attachments: Mapped[List[str]] = mapped_column(
        ARRAY(String),
        default=list,
        nullable=False
    )
    
    # Soft delete
    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    
    # Indexes
    __table_args__ = (
        Index("idx_task_status_priority", "status", "priority"),
        Index("idx_task_due_date", "due_date"),
        Index("idx_task_team_status", "team_id", "status"),
    )
    
    def to_dict(self) -> dict:
        """Convert task to dictionary."""
        return {
            "id": str(self.id),
            "title": self.title,
            "description": self.description,
            "task_type": self.task_type.value,
            "status": self.status.value,
            "priority": self.priority.value,
            "story_points": self.story_points,
            "estimated_hours": self.estimated_hours,
            "actual_hours": self.actual_hours,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "created_by_id": str(self.created_by_id),
            "assignee_id": str(self.assignee_id) if self.assignee_id else None,
            "team_id": str(self.team_id) if self.team_id else None,
            "parent_id": str(self.parent_id) if self.parent_id else None,
            "tags": self.tags,
            "attachments": self.attachments,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
