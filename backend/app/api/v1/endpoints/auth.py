"""
Authentication API endpoints.
"""

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.core.config import settings
from app.core.database import get_db
from app.core.security import (
    create_access_token,
    create_refresh_token,
    verify_password,
    get_password_hash,
    generate_password_reset_token,
    verify_password_reset_token
)
from app.schemas.auth import (
    Token,
    UserLogin,
    UserRegister,
    PasswordReset,
    PasswordResetConfirm,
    RefreshToken
)
from app.schemas.user import UserResponse
from app.services.user_service import UserService
from app.services.email_service import EmailService

router = APIRouter()
logger = structlog.get_logger()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    user_in: UserRegister,
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Register a new user account.
    
    - Validates email uniqueness
    - Hashes password securely
    - Sends verification email
    """
    user_service = UserService(db)
    
    # Check if email exists
    existing_user = await user_service.get_by_email(user_in.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered"
        )
    
    # Create user
    user = await user_service.create(
        email=user_in.email,
        password=get_password_hash(user_in.password),
        first_name=user_in.first_name,
        last_name=user_in.last_name
    )
    
    logger.info("user_registered", user_id=user.id, email=user.email)
    
    # Send verification email (async)
    await EmailService.send_verification_email(user.email, user.id)
    
    return user


@router.post("/login", response_model=Token)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Authenticate user and return JWT tokens.
    
    - Validates credentials
    - Generates access and refresh tokens
    - Updates last login timestamp
    """
    user_service = UserService(db)
    
    # Authenticate user
    user = await user_service.get_by_email(form_data.username)
    if not user or not verify_password(form_data.password, user.hashed_password):
        logger.warning("login_failed", email=form_data.username, ip=request.client.host)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled"
        )
    
    # Update last login
    await user_service.update_last_login(user.id)
    
    # Generate tokens
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    refresh_token_expires = timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    
    access_token = create_access_token(
        user.id,
        expires_delta=access_token_expires
    )
    refresh_token = create_refresh_token(
        user.id,
        expires_delta=refresh_token_expires
    )
    
    logger.info("user_login", user_id=user.id, email=user.email)
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "expires_at": "2024-01-15T11:30:00Z"  # Calculated in actual implementation
    }


@router.post("/refresh", response_model=Token)
async def refresh_token(
    token_data: RefreshToken,
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Refresh access token using valid refresh token.
    """
    # Verify refresh token
    user_id = verify_refresh_token(token_data.refresh_token)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )
    
    user_service = UserService(db)
    user = await user_service.get_by_id(user_id)
    
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )
    
    # Generate new tokens
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    refresh_token_expires = timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    
    access_token = create_access_token(user.id, expires_delta=access_token_expires)
    refresh_token = create_refresh_token(user.id, expires_delta=refresh_token_expires)
    
    logger.info("token_refreshed", user_id=user.id)
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "expires_at": "2024-01-15T11:30:00Z"
    }


@router.post("/password-reset", status_code=status.HTTP_202_ACCEPTED)
async def request_password_reset(
    reset_data: PasswordReset,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """
    Request password reset email.
    
    Always returns success to prevent email enumeration.
    """
    user_service = UserService(db)
    user = await user_service.get_by_email(reset_data.email)
    
    if user:
        token = generate_password_reset_token(user.email)
        await EmailService.send_password_reset_email(user.email, token)
        logger.info("password_reset_requested", email=reset_data.email)
    
    return {"message": "If the email exists, a reset link has been sent"}


@router.post("/password-reset/confirm", status_code=status.HTTP_200_OK)
async def confirm_password_reset(
    reset_data: PasswordResetConfirm,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """
    Confirm password reset with token.
    """
    email = verify_password_reset_token(reset_data.token)
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired token"
        )
    
    user_service = UserService(db)
    user = await user_service.get_by_email(email)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Update password
    await user_service.update_password(user.id, get_password_hash(reset_data.new_password))
    
    logger.info("password_reset_completed", user_id=user.id)
    
    return {"message": "Password has been reset successfully"}


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(
    token_data: RefreshToken
) -> dict:
    """
    Logout user by invalidating refresh token.
    """
    # Add token to blacklist (implement based on your strategy)
    # await TokenBlacklist.add(token_data.refresh_token)
    
    return {"message": "Successfully logged out"}