"""Unit tests for team collaboration service."""
import pytest
from datetime import datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.team import Team, TeamInvitation, TeamMember, TeamRole
from src.models.user import User, UserRole
from src.repositories.base import BaseRepository
from src.repositories.user_repository import UserRepository


@pytest.fixture
async def test_owner(db_session: AsyncSession):
    """Create team owner."""
    repo = UserRepository(db_session)
    return await repo.create({
        "email": "owner@example.com",
        "hashed_password": "hashed",
        "is_active": True,
        "role": UserRole.MEMBER
    })


@pytest.fixture
async def test_member(db_session: AsyncSession):
    """Create team member."""
    repo = UserRepository(db_session)
    return await repo.create({
        "email": "member@example.com",
        "hashed_password": "hashed",
        "is_active": True,
        "role": UserRole.MEMBER
    })


@pytest.fixture
async def test_team(db_session: AsyncSession, test_owner):
    """Create test team."""
    team_repo = BaseRepository(Team, db_session)
    member_repo = BaseRepository(TeamMember, db_session)
    
    team = await team_repo.create({
        "name": "Test Team",
        "slug": "test-team-abc123",
        "description": "A test team",
        "is_private": True
    })
    
    await member_repo.create({
        "team_id": team.id,
        "user_id": test_owner.id,
        "role": TeamRole.OWNER
    })
    
    return team


class TestTeamOperations:
    """Test cases for team operations."""
    
    async def test_create_team(self, db_session, test_owner):
        """Test team creation."""
        team_repo = BaseRepository(Team, db_session)
        member_repo = BaseRepository(TeamMember, db_session)
        
        team = await team_repo.create({
            "name": "New Team",
            "slug": "new-team-xyz789",
            "is_private": True
        })
        
        await member_repo.create({
            "team_id": team.id,
            "user_id": test_owner.id,
            "role": TeamRole.OWNER
        })
        
        assert team.name == "New Team"
        assert team.is_private is True
    
    async def test_team_member_role(self, db_session, test_team, test_owner):
        """Test team member role assignment."""
        member_repo = BaseRepository(TeamMember, db_session)
        
        member = await member_repo.create({
            "team_id": test_team.id,
            "user_id": test_owner.id,
            "role": TeamRole.ADMIN
        })
        
        assert member.role == TeamRole.ADMIN
    
    async def test_team_invitation(self, db_session, test_team, test_owner):
        """Test team invitation creation."""
        invitation_repo = BaseRepository(TeamInvitation, db_session)
        
        invitation = await invitation_repo.create({
            "team_id": test_team.id,
            "email": "invited@example.com",
            "role": TeamRole.MEMBER,
            "token": str(uuid4()),
            "expires_at": datetime.utcnow() + timedelta(days=7),
            "invited_by_id": test_owner.id
        })
        
        assert invitation.email == "invited@example.com"
        assert invitation.role == TeamRole.MEMBER
        assert invitation.is_expired is False
        assert invitation.is_accepted is False
    
    async def test_expired_invitation(self, db_session, test_team, test_owner):
        """Test expired invitation detection."""
        invitation_repo = BaseRepository(TeamInvitation, db_session)
        
        invitation = await invitation_repo.create({
            "team_id": test_team.id,
            "email": "expired@example.com",
            "role": TeamRole.MEMBER,
            "token": str(uuid4()),
            "expires_at": datetime.utcnow() - timedelta(days=1),
            "invited_by_id": test_owner.id
        })
        
        assert invitation.is_expired is True
    
    async def test_accepted_invitation(self, db_session, test_team, test_owner):
        """Test accepted invitation detection."""
        invitation_repo = BaseRepository(TeamInvitation, db_session)
        
        invitation = await invitation_repo.create({
            "team_id": test_team.id,
            "email": "accepted@example.com",
            "role": TeamRole.MEMBER,
            "token": str(uuid4()),
            "expires_at": datetime.utcnow() + timedelta(days=7),
            "invited_by_id": test_owner.id,
            "accepted_at": datetime.utcnow()
        })
        
        assert invitation.is_accepted is True


class TestTeamPermissions:
    """Test cases for team permissions."""
    
    async def test_owner_can_delete_team(self, db_session, test_team, test_owner):
        """Test owner can delete team."""
        member_repo = BaseRepository(TeamMember, db_session)
        
        # Verify owner membership
        from sqlalchemy import select
        result = await db_session.execute(
            select(TeamMember).where(
                TeamMember.team_id == test_team.id,
                TeamMember.user_id == test_owner.id,
                TeamMember.role == TeamRole.OWNER
            )
        )
        membership = result.scalar_one_or_none()
        
        assert membership is not None
        assert membership.role == TeamRole.OWNER
    
    async def test_member_cannot_delete_team(self, db_session, test_team, test_member):
        """Test member cannot delete team."""
        member_repo = BaseRepository(TeamMember, db_session)
        
        # Add as member
        await member_repo.create({
            "team_id": test_team.id,
            "user_id": test_member.id,
            "role": TeamRole.MEMBER
        })
        
        # Verify member role
        from sqlalchemy import select
        result = await db_session.execute(
            select(TeamMember).where(
                TeamMember.team_id == test_team.id,
                TeamMember.user_id == test_member.id
            )
        )
        membership = result.scalar_one_or_none()
        
        assert membership.role == TeamRole.MEMBER
        assert membership.role != TeamRole.OWNER
    
    async def test_admin_can_invite_members(self, db_session, test_team, test_owner):
        """Test admin can invite members."""
        # Owner is also admin
        from sqlalchemy import select
        result = await db_session.execute(
            select(TeamMember).where(
                TeamMember.team_id == test_team.id,
                TeamMember.user_id == test_owner.id
            )
        )
        membership = result.scalar_one_or_none()
        
        assert membership.role in [TeamRole.OWNER, TeamRole.ADMIN]


class TestTeamRepository:
    """Test cases for team repository operations."""
    
    async def test_get_team_by_id(self, db_session, test_team):
        """Test retrieving team by ID."""
        team_repo = BaseRepository(Team, db_session)
        found = await team_repo.get_by_id(test_team.id)
        
        assert found is not None
        assert found.id == test_team.id
        assert found.name == test_team.name
    
    async def test_update_team(self, db_session, test_team):
        """Test updating team."""
        team_repo = BaseRepository(Team, db_session)
        
        updated = await team_repo.update(
            test_team.id,
            {"name": "Updated Team Name"}
        )
        
        assert updated.name == "Updated Team Name"
    
    async def test_delete_team(self, db_session, test_team):
        """Test deleting team."""
        team_repo = BaseRepository(Team, db_session)
        
        result = await team_repo.delete(test_team.id)
        assert result is True
        
        # Verify deletion
        found = await team_repo.get_by_id(test_team.id)
        assert found is None
    
    async def test_team_exists(self, db_session, test_team):
        """Test checking team existence."""
        team_repo = BaseRepository(Team, db_session)
        
        assert await team_repo.exists(test_team.id) is True
        assert await team_repo.exists(uuid4()) is False
