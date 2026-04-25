"""
Board-related Pydantic schemas.
"""

from datetime import datetime
from typing import Optional, List
from enum import Enum

from pydantic import BaseModel, Field, ConfigDict


class BoardVisibility(str, Enum):
    """Board visibility enumeration."""
    PRIVATE = "private"
    TEAM = "team"
    PUBLIC = "public"


class BoardBase(BaseModel):
    """Base board schema."""
    name: str = Field(min_length=1, max_length=100, description="Board name")
    description: Optional[str] = Field(default=None, max_length=1000)
    visibility: BoardVisibility = Field(default=BoardVisibility.TEAM)


class BoardCreate(BoardBase):
    """Board creation schema."""
    team_id: str = Field(description="Team ID")
    columns: Optional[List["ColumnCreate"]] = Field(default=None)


class BoardUpdate(BaseModel):
    """Board update schema."""
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    description: Optional[str] = Field(default=None, max_length=1000)
    visibility: Optional[BoardVisibility] = Field(default=None)


class BoardResponse(BoardBase):
    """Board response schema."""
    id: str
    team_id: str
    created_by: str
    task_count: int = Field(default=0)
    column_count: int = Field(default=0)
    created_at: datetime
    updated_at: datetime
    columns: Optional[List["BoardColumn"]] = Field(default=None)
    
    model_config = ConfigDict(from_attributes=True)


class ColumnCreate(BaseModel):
    """Board column creation."""
    name: str = Field(min_length=1, max_length=50)
    color: Optional[str] = Field(default=None)
    position: int = Field(default=0, ge=0)
    wip_limit: Optional[int] = Field(default=None, ge=0)


class ColumnUpdate(BaseModel):
    """Board column update."""
    name: Optional[str] = Field(default=None, min_length=1, max_length=50)
    color: Optional[str] = Field(default=None)
    position: Optional[int] = Field(default=None, ge=0)
    wip_limit: Optional[int] = Field(default=None, ge=0)


class BoardColumn(BaseModel):
    """Board column schema."""
    id: str
    board_id: str
    name: str
    color: Optional[str]
    position: int
    wip_limit: Optional[int]
    task_count: int = Field(default=0)
    created_at: datetime
    updated_at: datetime