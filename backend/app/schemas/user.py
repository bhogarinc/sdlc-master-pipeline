"""
User-related Pydantic schemas.
"""

from datetime import datetime
from typing import Optional
from enum import Enum

from pydantic import BaseModel, EmailStr, Field, ConfigDict

from app.schemas.common import PaginatedResponse


class UserRole(str, Enum):
    """User role enumeration."""
    ADMIN = "admin"
    MANAGER = "manager"
    MEMBER = "member"
    VIEWER = "viewer"


class UserStatus(str, Enum):
    """User account status."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    PENDING = "pending"
    SUSPENDED = "suspended"


class UserBase(BaseModel):
    """Base user schema."""
    email: EmailStr = Field(description="User email address")
    first_name: str = Field(min_length=1, max_length=50, description="First name")
    last_name: str = Field(min_length=1, max_length=50, description="Last name")
    avatar_url: Optional[str] = Field(default=None, description="Avatar image URL")
    timezone: str = Field(default="UTC", description="User timezone")
    language: str = Field(default="en", description="Preferred language")


class UserCreate(UserBase):
    """User creation schema."""
    password: str = Field(min_length=8, description="User password")
    role: UserRole = Field(default=UserRole.MEMBER, description="User role")


class UserUpdate(BaseModel):
    """User update schema (all fields optional)."""
    first_name: Optional[str] = Field(default=None, min_length=1, max_length=50)
    last_name: Optional[str] = Field(default=None, min_length=1, max_length=50)
    avatar_url: Optional[str] = Field(default=None)
    timezone: Optional[str] = Field(default=None)
    language: Optional[str] = Field(default=None)
    bio: Optional[str] = Field(default=None, max_length=500)


class UserResponse(UserBase):
    """User response schema."""
    id: str = Field(description="User unique identifier")
    role: UserRole = Field(description="User role")
    status: UserStatus = Field(description="Account status")
    email_verified: bool = Field(description="Email verification status")
    last_login_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(description="Account creation timestamp")
    updated_at: datetime = Field(description="Last update timestamp")
    
    model_config = ConfigDict(from_attributes=True)


class UserProfile(BaseModel):
    """Extended user profile."""
    id: str
    email: str
    first_name: str
    last_name: str
    full_name: str = Field(description="Computed full name")
    avatar_url: Optional[str]
    bio: Optional[str]
    timezone: str
    language: str
    role: UserRole
    status: UserStatus
    team_count: int = Field(description="Number of teams")
    task_count: int = Field(description="Total tasks")
    completed_tasks: int = Field(description="Completed tasks")
    created_at: datetime
    updated_at: datetime


class UserPreferences(BaseModel):
    """User preferences schema."""
    email_notifications: bool = Field(default=True)
    push_notifications: bool = Field(default=True)
    weekly_digest: bool = Field(default=True)
    task_reminders: bool = Field(default=True)
    mention_notifications: bool = Field(default=True)
    default_view: str = Field(default="board", description="list|board|calendar")
    theme: str = Field(default="system", description="light|dark|system")
    date_format: str = Field(default="MM/DD/YYYY")
    time_format: str = Field(default="12h", description="12h|24h")


PaginatedUserResponse = PaginatedResponse[UserResponse]