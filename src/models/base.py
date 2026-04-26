"""Base model with common fields and utilities."""
import uuid
from datetime import datetime
from typing import Any, Dict

from sqlalchemy import Column, DateTime, String, inspect
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.config.database import Base


class BaseModel(Base):
    """Abstract base model with common fields."""
    
    __abstract__ = True
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False
    )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert model instance to dictionary."""
        result = {}
        for column in inspect(self).mapper.column_attrs:
            value = getattr(self, column.key)
            if isinstance(value, uuid.UUID):
                value = str(value)
            elif isinstance(value, datetime):
                value = value.isoformat()
            result[column.key] = value
        return result
    
    def update(self, **kwargs: Any) -> None:
        """Update model attributes."""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
