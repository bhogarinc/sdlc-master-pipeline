"""Team collaboration API routes."""
from datetime import datetime, timedelta
from typing import List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.routes.auth import get_current_user
from src.config.database import get_db
from src.models.team import Team, TeamInvitation, TeamMember, TeamRole
from src.repositories.base import BaseRepository

router = APIRouter(prefix="/teams", tags=["Teams"])


class TeamCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    is_private: bool = True
    allow_guests: bool = False
    color: Optional[str] = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")


class TeamUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    is_private: Optional[bool] = None
    allow_guests: Optional[bool] = None
    color: Optional[str] = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")


class TeamMemberUpdateRequest(BaseModel):
    role: TeamRole


class TeamInvitationRequest(BaseModel):
    email: EmailStr
    role: TeamRole = TeamRole.MEMBER


class TeamResponse(BaseModel):
    id: str
    name: str
    slug: str
    description: Optional[str]
    color: Optional[str]
    is_private: bool
    allow_guests: bool
    member_count: int
    task_count: int
    created_at: str
    updated_at: str


class TeamMemberResponse(BaseModel):
    id: str
    team_id: str
    user_id: str
    role: str
    joined_at: str
    user: dict


def generate_slug(name: str) -> str:
    """Generate URL-friendly slug from team name."""
    import re
    slug = re.sub(r'[^\w\s-]', '', name.lower())
    slug = re.sub(r'[-\s]+', '-', slug)
    return f"{slug}-{str(uuid4())[:8]}"


@router.post("", response_model=TeamResponse, status_code=status.HTTP_201_CREATED)
async def create_team(
    request: TeamCreateRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> TeamResponse:
    """Create new team."""
    team_repo = BaseRepository(Team, db)
    member_repo = BaseRepository(TeamMember, db)
    
    # Create team
    team = await team_repo.create({
        "name": request.name,
        "slug": generate_slug(request.name),
        "description": request.description,
        "is_private": request.is_private,
        "allow_guests": request.allow_guests,
        "color": request.color
    })
    
    # Add creator as owner
    await member_repo.create({
        "team_id": team.id,
        "user_id": UUID(current_user["id"]),
        "role": TeamRole.OWNER
    })
    
    await db.refresh(team)
    return TeamResponse(**team.to_dict())


@router.get("", response_model=List[TeamResponse])
async def list_teams(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> List[TeamResponse]:
    """List teams for current user."""
    from sqlalchemy import select
    from src.models.user import User
    
    user_id = UUID(current_user["id"])
    user = await db.get(User, user_id)
    
    teams = []
    for membership in user.team_memberships:
        await db.refresh(membership.team)
        teams.append(membership.team)
    
    return [TeamResponse(**team.to_dict()) for team in teams]


@router.get("/{team_id}", response_model=TeamResponse)
async def get_team(
    team_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> TeamResponse:
    """Get team by ID."""
    team_repo = BaseRepository(Team, db)
    team = await team_repo.get_by_id(team_id)
    
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found"
        )
    
    # Check membership
    member_repo = BaseRepository(TeamMember, db)
    member = await db.execute(
        select(TeamMember).where(
            TeamMember.team_id == team_id,
            TeamMember.user_id == UUID(current_user["id"])
        )
    )
    if not member.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this team"
        )
    
    return TeamResponse(**team.to_dict())


@router.patch("/{team_id}", response_model=TeamResponse)
async def update_team(
    team_id: UUID,
    request: TeamUpdateRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> TeamResponse:
    """Update team."""
    team_repo = BaseRepository(Team, db)
    team = await team_repo.get_by_id(team_id)
    
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found"
        )
    
    # Check admin permission
    member_repo = BaseRepository(TeamMember, db)
    member = await db.execute(
        select(TeamMember).where(
            TeamMember.team_id == team_id,
            TeamMember.user_id == UUID(current_user["id"])
        )
    )
    membership = member.scalar_one_or_none()
    if not membership or membership.role not in [TeamRole.OWNER, TeamRole.ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin permission required"
        )
    
    update_data = request.model_dump(exclude_unset=True)
    team = await team_repo.update(team_id, update_data)
    return TeamResponse(**team.to_dict())


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(
    team_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> None:
    """Delete team (owner only)."""
    team_repo = BaseRepository(Team, db)
    team = await team_repo.get_by_id(team_id)
    
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found"
        )
    
    # Check owner permission
    from sqlalchemy import select
    member = await db.execute(
        select(TeamMember).where(
            TeamMember.team_id == team_id,
            TeamMember.user_id == UUID(current_user["id"]),
            TeamMember.role == TeamRole.OWNER
        )
    )
    if not member.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner permission required"
        )
    
    await team_repo.delete(team_id)


@router.get("/{team_id}/members", response_model=List[TeamMemberResponse])
async def list_members(
    team_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> List[TeamMemberResponse]:
    """List team members."""
    # Check membership
    from sqlalchemy import select
    from src.models.user import User
    
    member_check = await db.execute(
        select(TeamMember).where(
            TeamMember.team_id == team_id,
            TeamMember.user_id == UUID(current_user["id"])
        )
    )
    if not member_check.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this team"
        )
    
    members = await db.execute(
        select(TeamMember).where(TeamMember.team_id == team_id)
    )
    
    result = []
    for member in members.scalars().all():
        user = await db.get(User, member.user_id)
        result.append({
            **member.to_dict(),
            "user": user.to_dict() if user else {}
        })
    
    return [TeamMemberResponse(**m) for m in result]


@router.post("/{team_id}/invite")
async def invite_member(
    team_id: UUID,
    request: TeamInvitationRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Invite member to team."""
    # Check admin permission
    from sqlalchemy import select
    member = await db.execute(
        select(TeamMember).where(
            TeamMember.team_id == team_id,
            TeamMember.user_id == UUID(current_user["id"])
        )
    )
    membership = member.scalar_one_or_none()
    if not membership or membership.role not in [TeamRole.OWNER, TeamRole.ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin permission required"
        )
    
    # Create invitation
    invitation_repo = BaseRepository(TeamInvitation, db)
    invitation = await invitation_repo.create({
        "team_id": team_id,
        "email": request.email,
        "role": request.role,
        "token": str(uuid4()),
        "expires_at": datetime.utcnow() + timedelta(days=7),
        "invited_by_id": UUID(current_user["id"])
    })
    
    # TODO: Send invitation email
    
    return {
        "message": "Invitation sent",
        "invitation": invitation.to_dict()
    }


@router.post("/invitations/{token}/accept")
async def accept_invitation(
    token: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Accept team invitation."""
    from sqlalchemy import select
    
    # Find invitation
    invitation_result = await db.execute(
        select(TeamInvitation).where(TeamInvitation.token == token)
    )
    invitation = invitation_result.scalar_one_or_none()
    
    if not invitation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invitation not found"
        )
    
    if invitation.is_expired:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitation has expired"
        )
    
    if invitation.is_accepted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitation already accepted"
        )
    
    # Check email matches
    if invitation.email != current_user["email"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invitation email does not match"
        )
    
    # Add member to team
    member_repo = BaseRepository(TeamMember, db)
    await member_repo.create({
        "team_id": invitation.team_id,
        "user_id": UUID(current_user["id"]),
        "role": invitation.role
    })
    
    # Mark invitation as accepted
    invitation.accepted_at = datetime.utcnow()
    await db.flush()
    
    return {"message": "Successfully joined team"}


@router.patch("/{team_id}/members/{member_id}")
async def update_member_role(
    team_id: UUID,
    member_id: UUID,
    request: TeamMemberUpdateRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Update member role."""
    # Check owner/admin permission
    from sqlalchemy import select
    
    current_member = await db.execute(
        select(TeamMember).where(
            TeamMember.team_id == team_id,
            TeamMember.user_id == UUID(current_user["id"])
        )
    )
    current_membership = current_member.scalar_one_or_none()
    
    if not current_membership or current_membership.role not in [TeamRole.OWNER, TeamRole.ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin permission required"
        )
    
    # Cannot change owner role unless you're owner
    target_member = await db.get(TeamMember, member_id)
    if target_member and target_member.role == TeamRole.OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot change owner role"
        )
    
    target_member.role = request.role
    await db.flush()
    
    return {"message": "Member role updated"}


@router.delete("/{team_id}/members/{member_id}")
async def remove_member(
    team_id: UUID,
    member_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Remove member from team."""
    from sqlalchemy import select
    
    # Check permission
    current_member = await db.execute(
        select(TeamMember).where(
            TeamMember.team_id == team_id,
            TeamMember.user_id == UUID(current_user["id"])
        )
    )
    current_membership = current_member.scalar_one_or_none()
    
    # Users can remove themselves, or admins can remove others
    target_member = await db.get(TeamMember, member_id)
    if not target_member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found"
        )
    
    is_self = target_member.user_id == UUID(current_user["id"])
    is_admin = current_membership and current_membership.role in [TeamRole.OWNER, TeamRole.ADMIN]
    
    if not (is_self or is_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied"
        )
    
    # Cannot remove owner
    if target_member.role == TeamRole.OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot remove team owner"
        )
    
    await db.delete(target_member)
    await db.flush()
    
    return {"message": "Member removed from team"}
