"""
Comment-related Pydantic schemas.
"""

from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field, ConfigDict

from app.schemas.common import PaginatedResponse


class CommentBase(BaseModel):
    """Base comment schema."""
    content: str = Field(min_length=1, max_length=10000, description="Comment content")


class CommentCreate(CommentBase):
    """Comment creation schema."""
    task_id: str = Field(description="Task ID")
    parent_id: Optional[str] = Field(default=None, description="Parent comment ID for replies")


class CommentUpdate(BaseModel):
    """Comment update schema."""
    content: str = Field(min_length=1, max_length=10000)


class CommentResponse(CommentBase):
    """Comment response schema."""
    id: str
    task_id: str
    author_id: str
    author: Optional[dict] = Field(default=None)
    parent_id: Optional[str]
    reply_count: int = Field(default=0)
    is_edited: bool = Field(default=False)
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


PaginatedCommentResponse = PaginatedResponse[CommentResponse]