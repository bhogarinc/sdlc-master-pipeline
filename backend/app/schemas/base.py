"""Base schemas for API responses"""
from typing import Generic, TypeVar, Optional, List
from pydantic import BaseModel
from datetime import datetime

T = TypeVar("T")


class BaseResponse(BaseModel):
    """Base API response"""
    success: bool = True
    message: Optional[str] = None


class DataResponse(BaseResponse, Generic[T]):
    """Response with data payload"""
    data: T


class PaginatedData(BaseModel, Generic[T]):
    """Paginated data structure"""
    items: List[T]
    total: int
    page: int
    limit: int
    pages: int


class PaginatedResponse(BaseResponse, Generic[T]):
    """Paginated response"""
    data: PaginatedData[T]


class ErrorResponse(BaseModel):
    """Error response structure"""
    code: str
    message: str
    details: Optional[dict] = None


class ErrorBaseResponse(BaseModel):
    """Base error response"""
    success: bool = False
    error: ErrorResponse


class TimestampedSchema(BaseModel):
    """Base schema with timestamp fields"""
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True
