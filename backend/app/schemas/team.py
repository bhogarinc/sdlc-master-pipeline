"""Team schemas for request/response validation"""
from typing import Optional, List
from pydantic import BaseModel, Field
from datetime import datetime
from uuid import UUID
from enum import Enum

from app.schemas.base import TimestampedSchema


class TeamRole(str, Enum):
    """Team member roles"""
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class TeamBase(BaseModel):
    """Base team schema"""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    avatar_url: Optional[str] = None


class TeamCreate(TeamBase):
    """Team creation schema"""
    pass


class TeamUpdate(BaseModel):
    """Team update schema"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    avatar_url: Optional[str] = None


class TeamMemberInvite(BaseModel):
    """Team member invitation"""
    email: str
    role: TeamRole = TeamRole.MEMBER


class TeamMemberUpdate(BaseModel):
    """Update team member role"""
    role: TeamRole


class TeamResponse(TeamBase, TimestampedSchema):
    """Team response schema"""
    id: UUID
    owner_id: UUID
    invite_code: Optional[str] = None
    
    class Config:
        from_attributes = True


class TeamDetailResponse(TeamResponse):
    """Team with members and stats"""
    tasks_count: int = 0
    completed_tasks_count: int = 0


class JoinTeamRequest(BaseModel):
    """Join team with invite code"""
    invite_code: str = Field(..., min_length=8, max_length=50)
