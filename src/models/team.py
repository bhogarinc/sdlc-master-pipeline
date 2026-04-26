"""Team model for collaboration and shared workspaces."""
import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import BaseModel

if TYPE_CHECKING:
    from src.models.task import Task
    from src.models.user import User


class TeamRole(str, enum.Enum):
    """Team member role enumeration."""
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    GUEST = "guest"


class Team(BaseModel):
    """Team entity for collaboration."""
    
    __tablename__ = "teams"
    
    # Basic Info
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False
    )
    slug: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        index=True,
        nullable=False
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )
    
    # Branding
    logo_url: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True
    )
    color: Mapped[Optional[str]] = mapped_column(
        String(7),
        nullable=True
    )
    
    # Settings
    is_private: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False
    )
    allow_guests: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False
    )
    
    # Relationships
    members: Mapped[List["TeamMember"]] = relationship(
        "TeamMember",
        back_populates="team",
        lazy="selectin",
        cascade="all, delete-orphan"
    )
    tasks: Mapped[List["Task"]] = relationship(
        "Task",
        back_populates="team",
        lazy="selectin"
    )
    
    # Invitations
    invitations: Mapped[List["TeamInvitation"]] = relationship(
        "TeamInvitation",
        back_populates="team",
        lazy="selectin",
        cascade="all, delete-orphan"
    )
    
    def to_dict(self) -> dict:
        """Convert team to dictionary."""
        return {
            "id": str(self.id),
            "name": self.name,
            "slug": self.slug,
            "description": self.description,
            "logo_url": self.logo_url,
            "color": self.color,
            "is_private": self.is_private,
            "allow_guests": self.allow_guests,
            "member_count": len(self.members),
            "task_count": len(self.tasks),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class TeamMember(BaseModel):
    """Team membership linking users to teams with roles."""
    
    __tablename__ = "team_members"
    
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False
    )
    role: Mapped[TeamRole] = mapped_column(
        Enum(TeamRole),
        default=TeamRole.MEMBER,
        nullable=False
    )
    
    # Joined timestamp
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False
    )
    
    # Relationships
    team: Mapped["Team"] = relationship("Team", back_populates="members")
    user: Mapped["User"] = relationship("User", back_populates="team_memberships")
    
    # Constraints
    __table_args__ = (
        UniqueConstraint("team_id", "user_id", name="uq_team_member"),
    )
    
    def to_dict(self) -> dict:
        """Convert team member to dictionary."""
        return {
            "id": str(self.id),
            "team_id": str(self.team_id),
            "user_id": str(self.user_id),
            "role": self.role.value,
            "joined_at": self.joined_at.isoformat() if self.joined_at else None,
        }


class TeamInvitation(BaseModel):
    """Team invitation for new members."""
    
    __tablename__ = "team_invitations"
    
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=False
    )
    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )
    role: Mapped[TeamRole] = mapped_column(
        Enum(TeamRole),
        default=TeamRole.MEMBER,
        nullable=False
    )
    token: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False
    )
    accepted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    invited_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False
    )
    
    # Relationships
    team: Mapped["Team"] = relationship("Team", back_populates="invitations")
    
    @property
    def is_expired(self) -> bool:
        """Check if invitation has expired."""
        return datetime.utcnow() > self.expires_at
    
    @property
    def is_accepted(self) -> bool:
        """Check if invitation has been accepted."""
        return self.accepted_at is not None
    
    def to_dict(self) -> dict:
        """Convert invitation to dictionary."""
        return {
            "id": str(self.id),
            "team_id": str(self.team_id),
            "email": self.email,
            "role": self.role.value,
            "expires_at": self.expires_at.isoformat(),
            "accepted_at": self.accepted_at.isoformat() if self.accepted_at else None,
            "is_expired": self.is_expired,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
