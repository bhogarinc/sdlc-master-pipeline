"""Base repository with CRUD operations."""
import logging
from typing import Any, Dict, Generic, List, Optional, Type, TypeVar
from uuid import UUID

from sqlalchemy import Select, asc, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from src.models.base import BaseModel

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class BaseRepository(Generic[T]):
    """Generic repository for CRUD operations."""
    
    def __init__(self, model: Type[T], session: AsyncSession):
        self.model = model
        self.session = session
    
    async def get_by_id(
        self,
        id: UUID,
        options: Optional[List[Any]] = None
    ) -> Optional[T]:
        """Get entity by ID with optional relationship loading."""
        query = select(self.model).where(self.model.id == id)
        if options:
            for option in options:
                query = query.options(option)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()
    
    async def get_by_ids(self, ids: List[UUID]) -> List[T]:
        """Get multiple entities by IDs."""
        query = select(self.model).where(self.model.id.in_(ids))
        result = await self.session.execute(query)
        return result.scalars().all()
    
    async def get_all(
        self,
        skip: int = 0,
        limit: int = 100,
        order_by: Optional[str] = None,
        order_desc: bool = False
    ) -> List[T]:
        """Get all entities with pagination."""
        query = select(self.model)
        if order_by and hasattr(self.model, order_by):
            order_col = getattr(self.model, order_by)
            query = query.order_by(desc(order_col) if order_desc else asc(order_col))
        query = query.offset(skip).limit(limit)
        result = await self.session.execute(query)
        return result.scalars().all()
    
    async def create(self, data: Dict[str, Any]) -> T:
        """Create new entity."""
        entity = self.model(**data)
        self.session.add(entity)
        await self.session.flush()
        await self.session.refresh(entity)
        logger.info(f"Created {self.model.__name__} with id={entity.id}")
        return entity
    
    async def create_many(self, data_list: List[Dict[str, Any]]) -> List[T]:
        """Batch create entities."""
        entities = [self.model(**data) for data in data_list]
        self.session.add_all(entities)
        await self.session.flush()
        for entity in entities:
            await self.session.refresh(entity)
        logger.info(f"Batch created {len(entities)} {self.model.__name__} entities")
        return entities
    
    async def update(self, id: UUID, data: Dict[str, Any]) -> Optional[T]:
        """Update entity by ID."""
        entity = await self.get_by_id(id)
        if not entity:
            return None
        
        for key, value in data.items():
            if hasattr(entity, key):
                setattr(entity, key, value)
        
        await self.session.flush()
        await self.session.refresh(entity)
        logger.info(f"Updated {self.model.__name__} with id={id}")
        return entity
    
    async def delete(self, id: UUID) -> bool:
        """Hard delete entity by ID."""
        entity = await self.get_by_id(id)
        if not entity:
            return False
        
        await self.session.delete(entity)
        logger.info(f"Deleted {self.model.__name__} with id={id}")
        return True
    
    async def soft_delete(self, id: UUID) -> Optional[T]:
        """Soft delete entity if it has is_deleted field."""
        if not hasattr(self.model, 'is_deleted'):
            raise AttributeError(f"{self.model.__name__} does not support soft delete")
        
        from datetime import datetime
        return await self.update(id, {
            'is_deleted': True,
            'deleted_at': datetime.utcnow()
        })
    
    async def count(self, filters: Optional[Dict[str, Any]] = None) -> int:
        """Count entities with optional filters."""
        query = select(func.count()).select_from(self.model)
        if filters:
            for key, value in filters.items():
                if hasattr(self.model, key):
                    query = query.where(getattr(self.model, key) == value)
        result = await self.session.execute(query)
        return result.scalar()
    
    async def exists(self, id: UUID) -> bool:
        """Check if entity exists."""
        query = select(func.count()).where(self.model.id == id)
        result = await self.session.execute(query)
        return result.scalar() > 0
