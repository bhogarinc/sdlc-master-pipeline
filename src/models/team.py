"""Team model."""

import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.config.database import Base


class TeamRole(str, PyEnum):
    """Team member roles."""
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class Team(Base):
    """Team database model."""
    
    __tablename__ = "teams"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
    
    # Relationships
    members: Mapped[list["TeamMember"]] = relationship(
        "TeamMember",
        back_populates="team",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    tasks: Mapped[list["Task"]] = relationship(
        "Task",
        back_populates="team",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    
    def __repr__(self) -> str:
        return f"<Team(id={self.id}, name={self.name})>"


class TeamMember(Base):
    """Team membership model."""
    
    __tablename__ = "team_members"
    
    __table_args__ = (
        UniqueConstraint("team_id", "user_id", name="uq_team_user"),
    )
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[TeamRole] = mapped_column(
        Enum(TeamRole),
        default=TeamRole.MEMBER,
        nullable=False,
    )
    
    # Timestamps
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )
    
    # Relationships
    team: Mapped["Team"] = relationship(
        "Team",
        back_populates="members",
        lazy="selectin",
    )
    user: Mapped["User"] = relationship(
        "User",
        back_populates="team_memberships",
        lazy="selectin",
    )
    
    def __repr__(self) -> str:
        return f"<TeamMember(team={self.team_id}, user={self.user_id}, role={self.role})>"
