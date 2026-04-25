"""Authentication endpoints"""
from datetime import timedelta
from fastapi import APIRouter, Depends, status
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session
from typing import Any

from app.core.config import settings
from app.core.database import get_db
from app.core.security import (
    verify_password, get_password_hash, create_access_token,
    create_refresh_token, decode_token, get_current_user
)
from app.core.exceptions import AuthenticationError, ValidationError, ConflictError
from app.schemas.user import (
    UserCreate, UserResponse, LoginRequest, TokenResponse,
    RefreshTokenRequest, PasswordResetRequest, PasswordResetConfirm,
    ChangePasswordRequest
)
from app.schemas.base import DataResponse, BaseResponse

router = APIRouter()
security = HTTPBearer()


@router.post("/register", response_model=DataResponse[UserResponse], status_code=status.HTTP_201_CREATED)
async def register(user_data: UserCreate, db: Session = Depends(get_db)) -> Any:
    """Register a new user account."""
    from app.models.user import User
    
    if db.query(User).filter(User.email == user_data.email).first():
        raise ConflictError("User with this email already exists")
    
    user = User(
        email=user_data.email,
        first_name=user_data.first_name,
        last_name=user_data.last_name,
        hashed_password=get_password_hash(user_data.password)
    )
    
    db.add(user)
    db.commit()
    db.refresh(user)
    
    return DataResponse(data=user, message="User registered successfully")


@router.post("/login", response_model=DataResponse[TokenResponse])
async def login(credentials: LoginRequest, db: Session = Depends(get_db)) -> Any:
    """Authenticate user and return access tokens."""
    from app.models.user import User
    
    user = db.query(User).filter(User.email == credentials.email).first()
    if not user or not verify_password(credentials.password, user.hashed_password):
        raise AuthenticationError("Invalid email or password")
    
    if not user.is_active:
        raise AuthenticationError("Account is deactivated")
    
    token_data = {"sub": str(user.id)}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)
    
    return DataResponse(
        data=TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            user=user
        )
    )


@router.post("/refresh", response_model=DataResponse[TokenResponse])
async def refresh_token(refresh_data: RefreshTokenRequest, db: Session = Depends(get_db)) -> Any:
    """Refresh access token using refresh token."""
    payload = decode_token(refresh_data.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise AuthenticationError("Invalid refresh token")
    
    from app.models.user import User
    user_id = payload.get("sub")
    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    
    if not user:
        raise AuthenticationError("User not found or inactive")
    
    token_data = {"sub": str(user.id)}
    new_access_token = create_access_token(token_data)
    new_refresh_token = create_refresh_token(token_data)
    
    return DataResponse(
        data=TokenResponse(
            access_token=new_access_token,
            refresh_token=new_refresh_token,
            token_type="bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            user=user
        )
    )


@router.post("/logout", response_model=BaseResponse)
async def logout(current_user = Depends(get_current_user)) -> Any:
    """Logout user."""
    return BaseResponse(message="Logged out successfully")


@router.post("/password-reset-request", response_model=BaseResponse)
async def request_password_reset(reset_data: PasswordResetRequest, db: Session = Depends(get_db)) -> Any:
    """Request password reset email."""
    return BaseResponse(
        message="If an account exists with this email, a reset link has been sent"
    )


@router.post("/password-reset", response_model=BaseResponse)
async def confirm_password_reset(reset_data: PasswordResetConfirm, db: Session = Depends(get_db)) -> Any:
    """Confirm password reset with token."""
    payload = decode_token(reset_data.token)
    if not payload or payload.get("type") != "reset":
        raise ValidationError("Invalid or expired reset token")
    
    from app.models.user import User
    user_id = payload.get("sub")
    user = db.query(User).filter(User.id == user_id).first()
    
    if not user:
        raise AuthenticationError("User not found")
    
    user.hashed_password = get_password_hash(reset_data.new_password)
    db.commit()
    
    return BaseResponse(message="Password reset successfully")


@router.post("/change-password", response_model=BaseResponse)
async def change_password(
    password_data: ChangePasswordRequest,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Any:
    """Change password for authenticated user."""
    if not verify_password(password_data.current_password, current_user.hashed_password):
        raise ValidationError("Current password is incorrect")
    
    current_user.hashed_password = get_password_hash(password_data.new_password)
    db.commit()
    
    return BaseResponse(message="Password changed successfully")


@router.get("/me", response_model=DataResponse[UserResponse])
async def get_current_user_info(current_user = Depends(get_current_user)) -> Any:
    """Get current authenticated user information."""
    return DataResponse(data=current_user)
