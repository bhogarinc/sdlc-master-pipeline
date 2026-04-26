"""Task API routes."""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.routes.auth import get_current_user
from src.config.database import get_db
from src.models.task import TaskPriority, TaskStatus, TaskType
from src.services.task_service import TaskService

router = APIRouter(prefix="/tasks", tags=["Tasks"])


class TaskCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    task_type: TaskType = TaskType.TASK
    priority: TaskPriority = TaskPriority.MEDIUM
    assignee_id: Optional[UUID] = None
    team_id: Optional[UUID] = None
    parent_id: Optional[UUID] = None
    due_date: Optional[datetime] = None
    story_points: Optional[int] = Field(None, ge=0, le=100)
    estimated_hours: Optional[float] = Field(None, ge=0)
    tags: Optional[List[str]] = None


class TaskUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    priority: Optional[TaskPriority] = None
    status: Optional[TaskStatus] = None
    assignee_id: Optional[UUID] = None
    due_date: Optional[datetime] = None
    story_points: Optional[int] = Field(None, ge=0, le=100)
    estimated_hours: Optional[float] = Field(None, ge=0)
    actual_hours: Optional[float] = Field(None, ge=0)
    tags: Optional[List[str]] = None


class TaskResponse(BaseModel):
    id: str
    title: str
    description: Optional[str]
    task_type: str
    status: str
    priority: str
    story_points: Optional[int]
    estimated_hours: Optional[float]
    actual_hours: Optional[float]
    due_date: Optional[str]
    created_by_id: str
    assignee_id: Optional[str]
    team_id: Optional[str]
    parent_id: Optional[str]
    tags: List[str]
    created_at: str
    updated_at: str


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    request: TaskCreateRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> TaskResponse:
    """Create new task."""
    task_service = TaskService(db)
    task = await task_service.create_task(
        title=request.title,
        created_by_id=UUID(current_user["id"]),
        description=request.description,
        task_type=request.task_type,
        priority=request.priority,
        assignee_id=request.assignee_id,
        team_id=request.team_id,
        parent_id=request.parent_id,
        due_date=request.due_date,
        story_points=request.story_points,
        estimated_hours=request.estimated_hours,
        tags=request.tags
    )
    return TaskResponse(**task.to_dict())


@router.get("", response_model=List[TaskResponse])
async def list_tasks(
    status: Optional[TaskStatus] = None,
    priority: Optional[TaskPriority] = None,
    team_id: Optional[UUID] = None,
    assignee_id: Optional[UUID] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> List[TaskResponse]:
    """List tasks with filtering."""
    task_service = TaskService(db)
    
    if team_id:
        tasks = await task_service.get_team_tasks(team_id, status, skip, limit)
    else:
        user_id = UUID(current_user["id"])
        if assignee_id:
            tasks = await task_service.task_repo.get_by_assignee(
                assignee_id, status, skip, limit
            )
        else:
            tasks = await task_service.get_user_tasks(user_id, status, skip, limit)
    
    return [TaskResponse(**task.to_dict()) for task in tasks]


@router.get("/search", response_model=List[TaskResponse])
async def search_tasks(
    q: str = Query(..., min_length=1),
    team_id: Optional[UUID] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> List[TaskResponse]:
    """Search tasks by title or description."""
    task_service = TaskService(db)
    tasks = await task_service.task_repo.search_tasks(
        query_str=q,
        user_id=UUID(current_user["id"]),
        team_id=team_id,
        skip=skip,
        limit=limit
    )
    return [TaskResponse(**task.to_dict()) for task in tasks]


@router.get("/overdue", response_model=List[TaskResponse])
async def get_overdue_tasks(
    team_id: Optional[UUID] = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> List[TaskResponse]:
    """Get overdue tasks."""
    task_service = TaskService(db)
    tasks = await task_service.task_repo.get_overdue_tasks(team_id)
    return [TaskResponse(**task.to_dict()) for task in tasks]


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> TaskResponse:
    """Get task by ID."""
    task_service = TaskService(db)
    task = await task_service.task_repo.get_tasks_with_relations(task_id)
    
    if not task or task.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )
    
    return TaskResponse(**task.to_dict())


@router.patch("/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: UUID,
    request: TaskUpdateRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> TaskResponse:
    """Update task."""
    task_service = TaskService(db)
    
    update_data = request.model_dump(exclude_unset=True)
    task = await task_service.update_task(
        task_id=task_id,
        user_id=UUID(current_user["id"]),
        **update_data
    )
    return TaskResponse(**task.to_dict())


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> None:
    """Delete task."""
    task_service = TaskService(db)
    await task_service.delete_task(task_id, UUID(current_user["id"]))


@router.post("/{task_id}/assign", response_model=TaskResponse)
async def assign_task(
    task_id: UUID,
    assignee_id: Optional[UUID],
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> TaskResponse:
    """Assign task to user."""
    task_service = TaskService(db)
    task = await task_service.assign_task(
        task_id=task_id,
        assignee_id=assignee_id,
        assigned_by_id=UUID(current_user["id"])
    )
    return TaskResponse(**task.to_dict())


@router.get("/{task_id}/subtasks", response_model=List[TaskResponse])
async def get_subtasks(
    task_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> List[TaskResponse]:
    """Get subtasks for a task."""
    task_service = TaskService(db)
    subtasks = await task_service.task_repo.get_subtasks(task_id)
    return [TaskResponse(**task.to_dict()) for task in subtasks]
