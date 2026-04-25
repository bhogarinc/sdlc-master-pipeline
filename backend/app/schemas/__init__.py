"""
TaskFlow Pro - Pydantic Schemas
===============================
Request/response validation schemas for all API endpoints.
"""

from app.schemas.auth import (
    Token,
    TokenPayload,
    UserLogin,
    UserRegister,
    PasswordReset,
    PasswordResetConfirm,
    RefreshToken
)
from app.schemas.user import (
    UserBase,
    UserCreate,
    UserUpdate,
    UserResponse,
    UserProfile,
    UserPreferences,
    PaginatedUserResponse
)
from app.schemas.task import (
    TaskBase,
    TaskCreate,
    TaskUpdate,
    TaskResponse,
    TaskStatus,
    TaskPriority,
    TaskFilter,
    PaginatedTaskResponse,
    TaskAssigneeUpdate,
    TaskStatusUpdate
)
from app.schemas.team import (
    TeamBase,
    TeamCreate,
    TeamUpdate,
    TeamResponse,
    TeamMember,
    TeamMemberRole,
    TeamInvitation,
    PaginatedTeamResponse
)
from app.schemas.board import (
    BoardBase,
    BoardCreate,
    BoardUpdate,
    BoardResponse,
    BoardColumn,
    ColumnCreate,
    ColumnUpdate
)
from app.schemas.comment import (
    CommentBase,
    CommentCreate,
    CommentUpdate,
    CommentResponse,
    PaginatedCommentResponse
)
from app.schemas.attachment import (
    AttachmentBase,
    AttachmentCreate,
    AttachmentResponse,
    PaginatedAttachmentResponse
)
from app.schemas.notification import (
    NotificationBase,
    NotificationCreate,
    NotificationResponse,
    NotificationPreferences,
    PaginatedNotificationResponse
)
from app.schemas.common import (
    PaginationParams,
    PaginatedResponse,
    APIResponse,
    ErrorResponse,
    ValidationError,
    SortOrder
)

__all__ = [
    # Auth
    "Token", "TokenPayload", "UserLogin", "UserRegister",
    "PasswordReset", "PasswordResetConfirm", "RefreshToken",
    # User
    "UserBase", "UserCreate", "UserUpdate", "UserResponse",
    "UserProfile", "UserPreferences", "PaginatedUserResponse",
    # Task
    "TaskBase", "TaskCreate", "TaskUpdate", "TaskResponse",
    "TaskStatus", "TaskPriority", "TaskFilter", "PaginatedTaskResponse",
    "TaskAssigneeUpdate", "TaskStatusUpdate",
    # Team
    "TeamBase", "TeamCreate", "TeamUpdate", "TeamResponse",
    "TeamMember", "TeamMemberRole", "TeamInvitation", "PaginatedTeamResponse",
    # Board
    "BoardBase", "BoardCreate", "BoardUpdate", "BoardResponse",
    "BoardColumn", "ColumnCreate", "ColumnUpdate",
    # Comment
    "CommentBase", "CommentCreate", "CommentUpdate", "CommentResponse",
    "PaginatedCommentResponse",
    # Attachment
    "AttachmentBase", "AttachmentCreate", "AttachmentResponse",
    "PaginatedAttachmentResponse",
    # Notification
    "NotificationBase", "NotificationCreate", "NotificationResponse",
    "NotificationPreferences", "PaginatedNotificationResponse",
    # Common
    "PaginationParams", "PaginatedResponse", "APIResponse",
    "ErrorResponse", "ValidationError", "SortOrder"
]