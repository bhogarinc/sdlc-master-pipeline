"""
Authentication-related Pydantic schemas.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, ConfigDict, field_validator

from app.core.security import validate_password_strength


class Token(BaseModel):
    """JWT token response."""
    access_token: str = Field(description="JWT access token")
    refresh_token: str = Field(description="JWT refresh token")
    token_type: str = Field(default="bearer", description="Token type")
    expires_in: int = Field(description="Token expiration time in seconds")
    expires_at: datetime = Field(description="Token expiration timestamp")


class TokenPayload(BaseModel):
    """JWT token payload."""
    sub: str = Field(description="Subject (user ID)")
    exp: datetime = Field(description="Expiration time")
    iat: datetime = Field(description="Issued at time")
    type: str = Field(default="access", description="Token type")
    jti: Optional[str] = Field(default=None, description="JWT ID")


class UserLogin(BaseModel):
    """User login request."""
    email: EmailStr = Field(description="User email address")
    password: str = Field(min_length=8, description="User password")
    remember_me: bool = Field(default=False, description="Remember login session")


class UserRegister(BaseModel):
    """User registration request."""
    email: EmailStr = Field(description="User email address")
    password: str = Field(min_length=8, description="User password")
    confirm_password: str = Field(min_length=8, description="Password confirmation")
    first_name: str = Field(min_length=1, max_length=50, description="First name")
    last_name: str = Field(min_length=1, max_length=50, description="Last name")
    
    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        if "password" in info.data and v != info.data["password"]:
            raise ValueError("Passwords do not match")
        return v
    
    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        is_valid, error_msg = validate_password_strength(v)
        if not is_valid:
            raise ValueError(error_msg)
        return v


class PasswordReset(BaseModel):
    """Password reset request."""
    email: EmailStr = Field(description="User email address")


class PasswordResetConfirm(BaseModel):
    """Password reset confirmation."""
    token: str = Field(description="Password reset token")
    new_password: str = Field(min_length=8, description="New password")
    confirm_password: str = Field(min_length=8, description="Password confirmation")
    
    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        if "new_password" in info.data and v != info.data["new_password"]:
            raise ValueError("Passwords do not match")
        return v
    
    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        is_valid, error_msg = validate_password_strength(v)
        if not is_valid:
            raise ValueError(error_msg)
        return v


class RefreshToken(BaseModel):
    """Token refresh request."""
    refresh_token: str = Field(description="Valid refresh token")