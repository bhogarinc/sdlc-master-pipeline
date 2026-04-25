"""
Team collaboration API endpoints.
"""

from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.core.database import get_db
from app.core.deps import get_current_user, require_team_permission
from app.schemas.team import (
    TeamCreate,
    TeamUpdate,
    TeamResponse,
    TeamMember,
    TeamInvitation,
    PaginatedTeamResponse,
    TeamMemberRole,
    UpdateMemberRole
)
from app.schemas.common import PaginationParams
from app.services.team_service import TeamService
from app.services.notification_service import NotificationService

router = APIRouter()
logger = structlog.get_logger()


@router.get("", response_model=PaginatedTeamResponse)
async def list_teams(
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
) -> Any:
    """
    List teams where user is a member.
    """
    team_service = TeamService(db)
    teams, total = await team_service.get_user_teams(
        user_id=current_user.id,
        pagination=pagination
    )
    
    return PaginatedTeamResponse.create(
        items=teams,
        total=total,
        page=pagination.page,
        page_size=pagination.page_size
    )


@router.post("", response_model=TeamResponse, status_code=status.HTTP_201_CREATED)
async def create_team(
    team_in: TeamCreate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
) -> Any:
    """
    Create a new team.
    
    Creator becomes owner automatically.
    """
    team_service = TeamService(db)
    
    team = await team_service.create(
        team_data=team_in,
        owner_id=current_user.id
    )
    
    logger.info("team_created", team_id=team.id, owner_id=current_user.id)
    
    return team


@router.get("/{team_id}", response_model=TeamResponse)
async def get_team(
    team_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
) -> Any:
    """
    Get team details by ID.
    """
    team_service = TeamService(db)
    team = await team_service.get_by_id(team_id, user_id=current_user.id)
    
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found"
        )
    
    return team


@router.patch("/{team_id}", response_model=TeamResponse)
async def update_team(
    team_id: str,
    team_update: TeamUpdate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_team_permission("team:update"))
) -> Any:
    """
    Update team details.
    
    Requires team admin or owner permission.
    """
    team_service = TeamService(db)
    
    team = await team_service.update(
        team_id=team_id,
        update_data=team_update,
        user_id=current_user.id
    )
    
    logger.info("team_updated", team_id=team_id, user_id=current_user.id)
    
    return team


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(
    team_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_team_permission("team:delete"))
) -> None:
    """
    Delete team permanently.
    
    Only team owner can delete.
    """
    team_service = TeamService(db)
    
    success = await team_service.delete(team_id, user_id=current_user.id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found"
        )
    
    logger.info("team_deleted", team_id=team_id, user_id=current_user.id)


@router.get("/{team_id}/members", response_model=List[TeamMember])
async def list_team_members(
    team_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
) -> Any:
    """
    List all team members.
    """
    team_service = TeamService(db)
    members = await team_service.get_members(team_id, user_id=current_user.id)
    
    return members


@router.post("/{team_id}/members", response_model=TeamMember, status_code=status.HTTP_201_CREATED)
async def invite_member(
    team_id: str,
    invitation: TeamInvitation,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_team_permission("team:invite"))
) -> Any:
    """
    Invite a new member to team.
    
    Sends invitation email. Creates pending membership.
    """
    team_service = TeamService(db)
    
    member = await team_service.invite_member(
        team_id=team_id,
        email=invitation.email,
        role=invitation.role,
        invited_by=current_user.id,
        message=invitation.message
    )
    
    # Send notification
    await NotificationService.send_team_invitation(
        email=invitation.email,
        team_id=team_id,
        invited_by=current_user.id
    )
    
    logger.info(
        "team_member_invited",
        team_id=team_id,
        email=invitation.email,
        invited_by=current_user.id
    )
    
    return member


@router.patch("/{team_id}/members/{member_id}", response_model=TeamMember)
async def update_member_role(
    team_id: str,
    member_id: str,
    role_update: UpdateMemberRole,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_team_permission("team:manage_members"))
) -> Any:
    """
    Update team member role.
    
    Cannot change owner's role.
    """
    team_service = TeamService(db)
    
    member = await team_service.update_member_role(
        team_id=team_id,
        member_id=member_id,
        new_role=role_update.role,
        updated_by=current_user.id
    )
    
    return member


@router.delete("/{team_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    team_id: str,
    member_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_team_permission("team:manage_members"))
) -> None:
    """
    Remove member from team.
    
    Cannot remove owner. Members can remove themselves.
    """
    team_service = TeamService(db)
    
    await team_service.remove_member(
        team_id=team_id,
        member_id=member_id,
        removed_by=current_user.id
    )
    
    logger.info("team_member_removed", team_id=team_id, member_id=member_id)


@router.post("/invitations/{token}/accept", response_model=TeamMember)
async def accept_invitation(
    token: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
) -> Any:
    """
    Accept team invitation.
    """
    team_service = TeamService(db)
    
    member = await team_service.accept_invitation(
        token=token,
        user_id=current_user.id
    )
    
    logger.info("team_invitation_accepted", team_id=member.team_id, user_id=current_user.id)
    
    return member


@router.post("/invitations/{token}/decline", status_code=status.HTTP_200_OK)
async def decline_invitation(
    token: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
) -> dict:
    """
    Decline team invitation.
    """
    team_service = TeamService(db)
    
    await team_service.decline_invitation(token=token, user_id=current_user.id)
    
    return {"message": "Invitation declined"}


@router.get("/public/search", response_model=PaginatedTeamResponse)
async def search_public_teams(
    query: str,
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Search public teams by name.
    """
    team_service = TeamService(db)
    
    teams, total = await team_service.search_public_teams(
        query=query,
        pagination=pagination
    )
    
    return PaginatedTeamResponse.create(
        items=teams,
        total=total,
        page=pagination.page,
        page_size=pagination.page_size
    )