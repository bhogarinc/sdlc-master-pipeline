"""
FastAPI dependency injection utilities.
"""

from typing import Generator, Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.schemas.auth import TokenPayload
from app.services.user_service import UserService

# OAuth2 scheme for token URL
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login",
    auto_error=False
)


async def get_current_user(
    db: AsyncSession = Depends(get_db),
    token: str = Depends(oauth2_scheme)
) -> Optional[dict]:
    """
    Validate JWT token and return current user.
    
    Raises:
        HTTPException: If token is invalid or user not found
    """
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    try:
        payload = jwt.decode(
            token, 
            settings.SECRET_KEY, 
            algorithms=[settings.ALGORITHM]
        )
        token_data = TokenPayload(**payload)
        
        if token_data.type != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
                headers={"WWW-Authenticate": "Bearer"},
            )
            
    except (JWTError, ValidationError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user_service = UserService(db)
    user = await user_service.get_by_id(token_data.sub)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user"
        )
    
    return user


async def get_current_active_superuser(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """
    Check if current user is superuser.
    """
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    return current_user


def require_permissions(required_permissions: list[str]):
    """
    Dependency factory for permission checking.
    
    Usage:
        @router.delete("/{id}", dependencies=[Depends(require_permissions(["task:delete"]))])
    """
    async def permission_checker(
        current_user: dict = Depends(get_current_user),
    ) -> dict:
        # Check if user has required permissions
        user_permissions = getattr(current_user, 'permissions', [])
        
        # Superusers have all permissions
        if current_user.is_superuser:
            return current_user
        
        # Check specific permissions
        for permission in required_permissions:
            if permission not in user_permissions:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Missing permission: {permission}"
                )
        
        return current_user
    
    return permission_checker


def require_team_permission(permission: str):
    """
    Dependency factory for team-specific permissions.
    
    Checks if user has permission within a team context.
    """
    async def team_permission_checker(
        team_id: str = None,
        current_user: dict = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> dict:
        from app.services.team_service import TeamService
        
        team_service = TeamService(db)
        has_permission = await team_service.check_permission(
            team_id=team_id,
            user_id=current_user.id,
            permission=permission
        )
        
        if not has_permission and not current_user.is_superuser:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing team permission: {permission}"
            )
        
        return current_user
    
    return team_permission_checker


async def get_optional_current_user(
    db: AsyncSession = Depends(get_db),
    token: str = Depends(oauth2_scheme)
) -> Optional[dict]:
    """
    Get current user if authenticated, None otherwise.
    Used for endpoints that work for both authenticated and anonymous users.
    """
    if not token:
        return None
    
    try:
        return await get_current_user(db, token)
    except HTTPException:
        return None