"""Authentication routes."""

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.auth import (
    PasswordReset,
    PasswordResetRequest,
    Token,
    UserCreate,
    UserLogin,
    UserResponse,
)
from src.api.schemas.common import MessageResponse
from src.config.database import get_db
from src.config.settings import get_settings
from src.services.auth import AuthService
from src.utils.security import create_access_token

router = APIRouter()
settings = get_settings()


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    user_data: UserCreate,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Register a new user."""
    auth_service = AuthService(db)
    user = await auth_service.register_user(user_data)
    return user


@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Login with username/email and password."""
    auth_service = AuthService(db)
    user = await auth_service.authenticate(form_data.username, form_data.password)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated",
        )
    
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user.id)},
        expires_delta=access_token_expires,
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


@router.post("/refresh", response_model=Token)
async def refresh_token(
    current_user: Any = Depends(AuthService.get_current_user),
) -> Any:
    """Refresh access token."""
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(current_user.id)},
        expires_delta=access_token_expires,
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


@router.post("/password-reset-request", response_model=MessageResponse)
async def password_reset_request(
    reset_data: PasswordResetRequest,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Request password reset email."""
    auth_service = AuthService(db)
    await auth_service.request_password_reset(reset_data.email)
    return {"message": "Password reset email sent if account exists"}


@router.post("/password-reset", response_model=MessageResponse)
async def password_reset(
    reset_data: PasswordReset,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Reset password with token."""
    auth_service = AuthService(db)
    await auth_service.reset_password(reset_data.token, reset_data.new_password)
    return {"message": "Password reset successfully"}


@router.get("/verify-email/{token}", response_model=MessageResponse)
async def verify_email(
    token: str,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Verify email address."""
    auth_service = AuthService(db)
    await auth_service.verify_email(token)
    return {"message": "Email verified successfully"}
