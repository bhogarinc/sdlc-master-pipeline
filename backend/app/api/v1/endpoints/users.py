"""
User management API endpoints.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.core.database import get_db
from app.core.deps import get_current_user
from app.schemas.user import (
    UserResponse,
    UserUpdate,
    UserProfile,
    UserPreferences
)
from app.services.user_service import UserService
from app.services.file_service import FileService

router = APIRouter()
logger = structlog.get_logger()


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user = Depends(get_current_user)
) -> Any:
    """
    Get current authenticated user information.
    """
    return current_user


@router.get("/me/profile", response_model=UserProfile)
async def get_user_profile(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
) -> Any:
    """
    Get detailed user profile with statistics.
    """
    user_service = UserService(db)
    profile = await user_service.get_profile(current_user.id)
    
    return profile


@router.patch("/me", response_model=UserResponse)
async def update_current_user(
    user_update: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
) -> Any:
    """
    Update current user profile.
    """
    user_service = UserService(db)
    
    updated_user = await user_service.update(
        user_id=current_user.id,
        update_data=user_update
    )
    
    logger.info("user_updated", user_id=current_user.id)
    
    return updated_user


@router.post("/me/avatar", response_model=UserResponse)
async def upload_avatar(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
) -> Any:
    """
    Upload user avatar image.
    
    Supports: JPEG, PNG, GIF (max 5MB)
    """
    # Validate file type
    allowed_types = ["image/jpeg", "image/png", "image/gif"]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file type. Allowed: JPEG, PNG, GIF"
        )
    
    # Upload file
    file_service = FileService()
    avatar_url = await file_service.upload_avatar(
        user_id=current_user.id,
        file=file
    )
    
    # Update user
    user_service = UserService(db)
    updated_user = await user_service.update_avatar(
        user_id=current_user.id,
        avatar_url=avatar_url
    )
    
    logger.info("avatar_uploaded", user_id=current_user.id)
    
    return updated_user


@router.get("/me/preferences", response_model=UserPreferences)
async def get_user_preferences(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
) -> Any:
    """
    Get user notification and display preferences.
    """
    user_service = UserService(db)
    preferences = await user_service.get_preferences(current_user.id)
    
    return preferences


@router.put("/me/preferences", response_model=UserPreferences)
async def update_user_preferences(
    preferences: UserPreferences,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
) -> Any:
    """
    Update user preferences.
    """
    user_service = UserService(db)
    
    updated_preferences = await user_service.update_preferences(
        user_id=current_user.id,
        preferences=preferences
    )
    
    return updated_preferences


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
) -> None:
    """
    Delete current user account permanently.
    
    Cascades to all user data. Cannot be undone.
    """
    user_service = UserService(db)
    
    await user_service.delete_account(current_user.id)
    
    logger.info("user_deleted", user_id=current_user.id)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user_by_id(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
) -> Any:
    """
    Get user by ID (public info only).
    
    Returns limited information for privacy.
    """
    user_service = UserService(db)
    user = await user_service.get_public_profile(user_id)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    return user


@router.post("/me/change-password", status_code=status.HTTP_200_OK)
async def change_password(
    current_password: str,
    new_password: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
) -> dict:
    """
    Change user password.
    
    Requires current password verification.
    """
    user_service = UserService(db)
    
    success = await user_service.change_password(
        user_id=current_user.id,
        current_password=current_password,
        new_password=new_password
    )
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect"
        )
    
    logger.info("password_changed", user_id=current_user.id)
    
    return {"message": "Password changed successfully"}