"""Common dependencies for API endpoints"""
from typing import Optional
from fastapi import Query, Depends
from pydantic import BaseModel


class PaginationParams(BaseModel):
    """Pagination parameters"""
    page: int = 1
    limit: int = 20
    
    @property
    def offset(self) -> int:
        return (self.page - 1) * self.limit


def get_pagination(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page")
) -> PaginationParams:
    """Dependency for pagination parameters"""
    return PaginationParams(page=page, limit=limit)
