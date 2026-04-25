"""User schemas for request/response validation"""
from typing import Optional, List
from pydantic import BaseModel, EmailStr, Field, ConfigDict
from datetime import datetime
from uuid import UUID

from app.schemas.base import TimestampedSchema


class UserBase(BaseModel):
    """Base user schema"""
    email: EmailStr
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    avatar_url: Optional[str] = None


class UserCreate(UserBase):
    """User registration schema"""
    password: str = Field(..., min_length=8, max_length=100)


class UserUpdate(BaseModel):
    """User update schema"""
    first_name: Optional[str] = Field(None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(None, min_length=1, max_length=100)
    avatar_url: Optional[str] = None


class UserResponse(UserBase, TimestampedSchema):
    """User response schema"""
    id: UUID
    is_active: bool
    is_verified: bool
    
    class Config:
        from_attributes = True


class UserProfileResponse(UserResponse):
    """Extended user profile with stats"""
    teams_count: int = 0
    tasks_count: int = 0


class LoginRequest(BaseModel):
    """Login request schema"""
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Token response schema"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse


class RefreshTokenRequest(BaseModel):
    """Refresh token request"""
    refresh_token: str


class PasswordResetRequest(BaseModel):
    """Password reset request"""
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    """Password reset confirmation"""
    token: str
    new_password: str = Field(..., min_length=8, max_length=100)


class ChangePasswordRequest(BaseModel):
    """Change password request"""
    current_password: str
    new_password: str = Field(..., min_length=8, max_length=100)


class TeamMemberResponse(UserBase):
    """Team member response"""
    id: UUID
    role: str
    joined_at: datetime
