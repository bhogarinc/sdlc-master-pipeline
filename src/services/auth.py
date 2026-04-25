"""Authentication service."""

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.auth import UserCreate
from src.config.database import get_db
from src.config.settings import get_settings
from src.models.user import User, UserRole
from src.utils.email import send_password_reset_email, send_verification_email
from src.utils.security import verify_password

settings = get_settings()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


class AuthService:
    """Authentication service for user management."""
    
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
    
    async def register_user(self, user_data: UserCreate) -> User:
        """Register a new user."""
        # Check if email exists
        result = await self.db.execute(
            select(User).where(User.email == user_data.email)
        )
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
            )
        
        from src.utils.security import get_password_hash
        
        # Create user
        user = User(
            email=user_data.email,
            hashed_password=get_password_hash(user_data.password),
            first_name=user_data.first_name,
            last_name=user_data.last_name,
            role=UserRole.MEMBER,
            is_active=True,
            is_verified=False,
        )
        
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        
        # Send verification email
        await send_verification_email(user.email)
        
        return user
    
    async def authenticate(self, email: str, password: str) -> User | None:
        """Authenticate user with email and password."""
        result = await self.db.execute(
            select(User).where(User.email == email)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            return None
        
        if not verify_password(password, user.hashed_password):
            return None
        
        # Update last login
        user.last_login = datetime.utcnow()
        await self.db.commit()
        
        return user
    
    async def request_password_reset(self, email: str) -> None:
        """Send password reset email."""
        result = await self.db.execute(
            select(User).where(User.email == email)
        )
        user = result.scalar_one_or_none()
        
        if user:
            # Generate reset token
            from src.utils.security import create_access_token
            token = create_access_token(
                data={"sub": str(user.id), "type": "password_reset"},
                expires_delta=timedelta(hours=24),
            )
            await send_password_reset_email(user.email, token)
    
    async def reset_password(self, token: str, new_password: str) -> None:
        """Reset user password."""
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            user_id: str = payload.get("sub")
            token_type: str = payload.get("type")
            
            if user_id is None or token_type != "password_reset":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid token",
                )
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid token",
            )
        
        result = await self.db.execute(
            select(User).where(User.id == UUID(user_id))
        )
        user = result.scalar_one_or_none()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )
        
        from src.utils.security import get_password_hash
        user.hashed_password = get_password_hash(new_password)
        await self.db.commit()
    
    async def verify_email(self, token: str) -> None:
        """Verify user email."""
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            user_id: str = payload.get("sub")
            token_type: str = payload.get("type")
            
            if user_id is None or token_type != "email_verification":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid token",
                )
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid token",
            )
        
        result = await self.db.execute(
            select(User).where(User.id == UUID(user_id))
        )
        user = result.scalar_one_or_none()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )
        
        user.is_verified = True
        await self.db.commit()
    
    @staticmethod
    async def get_current_user(
        token: str = Depends(oauth2_scheme),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        """Get current authenticated user."""
        credentials_exception = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            user_id: str = payload.get("sub")
            if user_id is None:
                raise credentials_exception
        except JWTError:
            raise credentials_exception
        
        result = await db.execute(
            select(User).where(User.id == UUID(user_id))
        )
        user = result.scalar_one_or_none()
        
        if user is None:
            raise credentials_exception
        
        return user
    
    @staticmethod
    async def get_current_active_user(
        current_user: User = Depends(get_current_user),
    ) -> User:
        """Get current active user."""
        if not current_user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Inactive user",
            )
        return current_user
