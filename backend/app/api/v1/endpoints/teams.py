"""Team management endpoints"""
from typing import Any, List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
import secrets

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.exceptions import NotFoundError, AuthorizationError, ConflictError
from app.core.dependencies import get_pagination, PaginationParams
from app.schemas.team import (
    TeamCreate, TeamUpdate, TeamResponse, TeamDetailResponse,
    TeamMemberInvite, TeamMemberUpdate, JoinTeamRequest, TeamRole
)
from app.schemas.base import DataResponse, PaginatedResponse, PaginatedData, BaseResponse

router = APIRouter()


def check_team_permission(user, team, required_roles: List[str] = None) -> bool:
    if team.owner_id == user.id:
        return True
    membership = user.team_memberships.filter_by(team_id=team.id).first()
    if not membership:
        return False
    if required_roles and membership.role not in required_roles:
        return False
    return True


@router.post("/", response_model=DataResponse[TeamResponse], status_code=201)
async def create_team(team_data: TeamCreate, current_user = Depends(get_current_user), db: Session = Depends(get_db)) -> Any:
    """Create a new team."""
    from app.models.team import Team, TeamMember
    
    team = Team(
        **team_data.model_dump(),
        owner_id=current_user.id,
        invite_code=secrets.token_urlsafe(16)[:16]
    )
    db.add(team)
    db.commit()
    db.refresh(team)
    
    membership = TeamMember(team_id=team.id, user_id=current_user.id, role=TeamRole.OWNER)
    db.add(membership)
    db.commit()
    
    return DataResponse(data=team, message="Team created successfully")


@router.get("/", response_model=PaginatedResponse[List[TeamResponse]])
async def list_teams(
    search: str = Query(None),
    pagination: PaginationParams = Depends(get_pagination),
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Any:
    """List teams user is member of."""
    from app.models.team import Team
    
    team_ids = [m.team_id for m in current_user.team_memberships.all()]
    query = db.query(Team).filter(Team.id.in_(team_ids))
    
    if search:
        query = query.filter(Team.name.ilike(f"%{search}%"))
    
    total = query.count()
    teams = query.order_by(Team.created_at.desc()).offset(pagination.offset).limit(pagination.limit).all()
    pages = (total + pagination.limit - 1) // pagination.limit
    
    return PaginatedResponse(
        data=PaginatedData(items=teams, total=total, page=pagination.page,
                          limit=pagination.limit, pages=pages)
    )


@router.get("/{team_id}", response_model=DataResponse[TeamDetailResponse])
async def get_team(team_id: str, current_user = Depends(get_current_user), db: Session = Depends(get_db)) -> Any:
    """Get team details with members."""
    from app.models.team import Team
    
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise NotFoundError("Team", team_id)
    
    if not check_team_permission(current_user, team):
        raise AuthorizationError("Not a member of this team")
    
    tasks_count = len(team.tasks)
    completed_tasks_count = len([t for t in team.tasks if t.status == "done"])
    
    detail = TeamDetailResponse(
        **TeamResponse.model_validate(team).model_dump(),
        tasks_count=tasks_count,
        completed_tasks_count=completed_tasks_count
    )
    
    return DataResponse(data=detail)


@router.put("/{team_id}", response_model=DataResponse[TeamResponse])
async def update_team(
    team_id: str, team_data: TeamUpdate,
    current_user = Depends(get_current_user), db: Session = Depends(get_db)
) -> Any:
    """Update team details."""
    from app.models.team import Team
    
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise NotFoundError("Team", team_id)
    
    if not check_team_permission(current_user, team, [TeamRole.OWNER, TeamRole.ADMIN]):
        raise AuthorizationError("Only team owner or admin can update")
    
    update_data = team_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(team, field, value)
    
    db.commit()
    db.refresh(team)
    return DataResponse(data=team, message="Team updated successfully")


@router.delete("/{team_id}", response_model=BaseResponse)
async def delete_team(team_id: str, current_user = Depends(get_current_user), db: Session = Depends(get_db)) -> Any:
    """Delete team."""
    from app.models.team import Team
    
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise NotFoundError("Team", team_id)
    
    if team.owner_id != current_user.id:
        raise AuthorizationError("Only team owner can delete")
    
    db.delete(team)
    db.commit()
    return BaseResponse(message="Team deleted successfully")


@router.post("/{team_id}/members", response_model=DataResponse[dict])
async def invite_member(
    team_id: str, invite_data: TeamMemberInvite,
    current_user = Depends(get_current_user), db: Session = Depends(get_db)
) -> Any:
    """Invite member to team by email."""
    from app.models.team import Team
    from app.models.user import User
    
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise NotFoundError("Team", team_id)
    
    if not check_team_permission(current_user, team, [TeamRole.OWNER, TeamRole.ADMIN]):
        raise AuthorizationError("Only team owner or admin can invite members")
    
    existing_user = db.query(User).filter(User.email == invite_data.email).first()
    if existing_user:
        from app.models.team import TeamMember
        existing_member = db.query(TeamMember).filter_by(team_id=team_id, user_id=existing_user.id).first()
        if existing_member:
            raise ConflictError("User is already a team member")
    
    return DataResponse(data={"invited": True, "email": invite_data.email},
                       message=f"Invitation sent to {invite_data.email}")


@router.post("/join", response_model=DataResponse[TeamResponse])
async def join_team(join_data: JoinTeamRequest, current_user = Depends(get_current_user), db: Session = Depends(get_db)) -> Any:
    """Join team using invite code."""
    from app.models.team import Team, TeamMember
    
    team = db.query(Team).filter(Team.invite_code == join_data.invite_code).first()
    if not team:
        from app.core.exceptions import ValidationError
        raise ValidationError("Invalid invite code")
    
    existing = db.query(TeamMember).filter_by(team_id=team.id, user_id=current_user.id).first()
    if existing:
        raise ConflictError("Already a member of this team")
    
    membership = TeamMember(team_id=team.id, user_id=current_user.id, role=TeamRole.MEMBER)
    db.add(membership)
    db.commit()
    
    return DataResponse(data=team, message="Joined team successfully")


@router.put("/{team_id}/members/{user_id}", response_model=DataResponse[dict])
async def update_member_role(
    team_id: str, user_id: str, role_data: TeamMemberUpdate,
    current_user = Depends(get_current_user), db: Session = Depends(get_db)
) -> Any:
    """Update member role."""
    from app.models.team import Team, TeamMember
    from app.core.exceptions import ValidationError
    
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise NotFoundError("Team", team_id)
    
    if team.owner_id != current_user.id:
        raise AuthorizationError("Only team owner can change roles")
    
    if user_id == team.owner_id:
        raise ValidationError("Cannot change owner's role")
    
    membership = db.query(TeamMember).filter_by(team_id=team_id, user_id=user_id).first()
    if not membership:
        raise NotFoundError("Team member")
    
    membership.role = role_data.role
    db.commit()
    
    return DataResponse(data={"updated": True, "new_role": role_data.role},
                       message="Member role updated")


@router.delete("/{team_id}/members/{user_id}", response_model=BaseResponse)
async def remove_member(
    team_id: str, user_id: str,
    current_user = Depends(get_current_user), db: Session = Depends(get_db)
) -> Any:
    """Remove member from team."""
    from app.models.team import Team, TeamMember
    from app.core.exceptions import ValidationError
    
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise NotFoundError("Team", team_id)
    
    can_remove = (team.owner_id == current_user.id or user_id == str(current_user.id))
    if not can_remove:
        raise AuthorizationError("Cannot remove this member")
    
    if user_id == team.owner_id:
        raise ValidationError("Cannot remove team owner")
    
    membership = db.query(TeamMember).filter_by(team_id=team_id, user_id=user_id).first()
    if not membership:
        raise NotFoundError("Team member")
    
    db.delete(membership)
    db.commit()
    return BaseResponse(message="Member removed successfully")
