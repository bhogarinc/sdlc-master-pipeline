"""User repository with specialized queries."""
from typing import List, Optional
from uuid import UUID

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import User, UserRole
from src.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    """Repository for User entity operations."""
    
    def __init__(self, session: AsyncSession):
        super().__init__(User, session)
    
    async def get_by_email(self, email: str) -> Optional[User]:
        """Get user by email address."""
        query = select(User).where(User.email == email.lower())
        result = await self.session.execute(query)
        return result.scalar_one_or_none()
    
    async def get_by_password_reset_token(self, token: str) -> Optional[User]:
        """Get user by password reset token."""
        query = select(User).where(User.password_reset_token == token)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()
    
    async def get_active_users(
        self,
        skip: int = 0,
        limit: int = 100
    ) -> List[User]:
        """Get active users with pagination."""
        query = (
            select(User)
            .where(User.is_active == True)
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(query)
        return result.scalars().all()
    
    async def search_users(
        self,
        query_str: str,
        skip: int = 0,
        limit: int = 20
    ) -> List[User]:
        """Search users by name or email."""
        search_pattern = f"%{query_str}%"
        query = (
            select(User)
            .where(
                or_(
                    User.email.ilike(search_pattern),
                    User.first_name.ilike(search_pattern),
                    User.last_name.ilike(search_pattern)
                ),
                User.is_active == True
            )
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(query)
        return result.scalars().all()
    
    async def get_by_role(self, role: UserRole) -> List[User]:
        """Get users by role."""
        query = select(User).where(User.role == role)
        result = await self.session.execute(query)
        return result.scalars().all()
    
    async def email_exists(self, email: str) -> bool:
        """Check if email already exists."""
        query = select(User).where(User.email == email.lower())
        result = await self.session.execute(query)
        return result.scalar_one_or_none() is not None
