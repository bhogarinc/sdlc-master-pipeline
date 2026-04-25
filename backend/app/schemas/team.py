"""
Team-related Pydantic schemas.
"""

from datetime import datetime
from typing import Optional, List
from enum import Enum

from pydantic import BaseModel, EmailStr, Field, ConfigDict

from app.schemas.common import PaginatedResponse


class TeamMemberRole(str, Enum):
    """Team member role enumeration."""
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    GUEST = "guest"


class TeamMemberStatus(str, Enum):
    """Team member status."""
    ACTIVE = "active"
    PENDING = "pending"
    INVITED = "invited"
    SUSPENDED = "suspended"


class TeamBase(BaseModel):
    """Base team schema."""
    name: str = Field(min_length=1, max_length=100, description="Team name")
    description: Optional[str] = Field(default=None, max_length=1000)
    avatar_url: Optional[str] = Field(default=None)
    is_public: bool = Field(default=False)


class TeamCreate(TeamBase):
    """Team creation schema."""
    pass


class TeamUpdate(BaseModel):
    """Team update schema."""
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    description: Optional[str] = Field(default=None, max_length=1000)
    avatar_url: Optional[str] = Field(default=None)
    is_public: Optional[bool] = Field(default=None)


class TeamResponse(TeamBase):
    """Team response schema."""
    id: str
    slug: str
    owner_id: str
    member_count: int
    task_count: int
    board_count: int
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class TeamMember(BaseModel):
    """Team member schema."""
    id: str
    user_id: str
    team_id: str
    role: TeamMemberRole
    status: TeamMemberStatus
    joined_at: datetime
    invited_by: Optional[str]
    user: Optional[dict] = Field(default=None)


class TeamInvitation(BaseModel):
    """Team invitation schema."""
    email: EmailStr
    role: TeamMemberRole = Field(default=TeamMemberRole.MEMBER)
    message: Optional[str] = Field(default=None, max_length=500)


class UpdateMemberRole(BaseModel):
    """Update team member role."""
    role: TeamMemberRole


PaginatedTeamResponse = PaginatedResponse[TeamResponse]