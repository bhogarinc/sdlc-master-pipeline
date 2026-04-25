"""User management endpoints"""
from typing import Any, List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.exceptions import NotFoundError
from app.core.dependencies import get_pagination, PaginationParams
from app.schemas.user import UserUpdate, UserResponse, UserProfileResponse
from app.schemas.base import DataResponse, PaginatedResponse, PaginatedData

router = APIRouter()


@router.get("/profile", response_model=DataResponse[UserProfileResponse])
async def get_user_profile(current_user = Depends(get_current_user), db: Session = Depends(get_db)) -> Any:
    """Get detailed profile for current user."""
    teams_count = len(current_user.teams)
    tasks_count = len(current_user.assigned_tasks)
    
    profile_data = UserProfileResponse(
        **UserResponse.model_validate(current_user).model_dump(),
        teams_count=teams_count,
        tasks_count=tasks_count
    )
    
    return DataResponse(data=profile_data)


@router.put("/profile", response_model=DataResponse[UserResponse])
async def update_profile(
    user_data: UserUpdate,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Any:
    """Update current user profile."""
    update_data = user_data.model_dump(exclude_unset=True)
    
    for field, value in update_data.items():
        setattr(current_user, field, value)
    
    db.commit()
    db.refresh(current_user)
    
    return DataResponse(data=current_user, message="Profile updated successfully")


@router.get("/{user_id}", response_model=DataResponse[UserResponse])
async def get_user(user_id: str, current_user = Depends(get_current_user), db: Session = Depends(get_db)) -> Any:
    """Get user by ID."""
    from app.models.user import User
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise NotFoundError("User", user_id)
    
    return DataResponse(data=user)


@router.get("/", response_model=PaginatedResponse[List[UserResponse]])
async def list_users(
    search: str = Query(None, description="Search by name or email"),
    pagination: PaginationParams = Depends(get_pagination),
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Any:
    """List users with pagination and search."""
    from app.models.user import User
    
    query = db.query(User).filter(User.is_active == True)
    
    if search:
        search_filter = f"%{search}%"
        query = query.filter(
            (User.first_name.ilike(search_filter)) |
            (User.last_name.ilike(search_filter)) |
            (User.email.ilike(search_filter))
        )
    
    total = query.count()
    users = query.offset(pagination.offset).limit(pagination.limit).all()
    pages = (total + pagination.limit - 1) // pagination.limit
    
    return PaginatedResponse(
        data=PaginatedData(
            items=users, total=total, page=pagination.page,
            limit=pagination.limit, pages=pages
        )
    )


@router.delete("/account", response_model=DataResponse[dict])
async def delete_account(current_user = Depends(get_current_user), db: Session = Depends(get_db)) -> Any:
    """Delete current user account (soft delete)."""
    current_user.is_active = False
    db.commit()
    
    return DataResponse(data={"deleted": True}, message="Account deactivated successfully")
