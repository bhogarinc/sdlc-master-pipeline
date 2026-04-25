"""
Attachment-related Pydantic schemas.
"""

from datetime import datetime
from typing import Optional
from enum import Enum

from pydantic import BaseModel, Field, ConfigDict

from app.schemas.common import PaginatedResponse


class AttachmentType(str, Enum):
    """Attachment type enumeration."""
    IMAGE = "image"
    DOCUMENT = "document"
    SPREADSHEET = "spreadsheet"
    PRESENTATION = "presentation"
    ARCHIVE = "archive"
    CODE = "code"
    OTHER = "other"


class AttachmentBase(BaseModel):
    """Base attachment schema."""
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(description="MIME type")
    size_bytes: int = Field(ge=0, description="File size in bytes")


class AttachmentCreate(AttachmentBase):
    """Attachment creation schema."""
    task_id: str = Field(description="Task ID")
    storage_key: str = Field(description="Storage location key")
    attachment_type: AttachmentType = Field(default=AttachmentType.OTHER)


class AttachmentResponse(AttachmentBase):
    """Attachment response schema."""
    id: str
    task_id: str
    uploaded_by: str
    attachment_type: AttachmentType
    download_url: Optional[str] = Field(default=None)
    thumbnail_url: Optional[str] = Field(default=None)
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


PaginatedAttachmentResponse = PaginatedResponse[AttachmentResponse]