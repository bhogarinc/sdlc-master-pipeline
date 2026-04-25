"""
Task management API endpoints.
"""

from typing import Any, List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.core.database import get_db
from app.core.deps import get_current_user, require_permissions
from app.schemas.task import (
    TaskCreate,
    TaskUpdate,
    TaskResponse,
    TaskFilter,
    TaskStatus,
    TaskPriority,
    PaginatedTaskResponse,
    TaskAssigneeUpdate,
    TaskStatusUpdate
)
from app.schemas.common import PaginationParams
from app.services.task_service import TaskService
from app.services.notification_service import NotificationService

router = APIRouter()
logger = structlog.get_logger()


@router.get("", response_model=PaginatedTaskResponse)
async def list_tasks(
    pagination: PaginationParams = Depends(),
    status: Optional[List[TaskStatus]] = Query(default=None),
    priority: Optional[List[TaskPriority]] = Query(default=None),
    assignee_id: Optional[List[str]] = Query(default=None),
    board_id: Optional[str] = None,
    team_id: Optional[str] = None,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
) -> Any:
    """
    List tasks with filtering and pagination.
    
    Supports filtering by status, priority, assignee, board, team.
    Full-text search on title and description.
    """
    filters = TaskFilter(
        status=status,
        priority=priority,
        assignee_id=assignee_id,
        board_id=board_id,
        team_id=team_id,
        search=search
    )
    
    task_service = TaskService(db)
    tasks, total = await task_service.get_tasks(
        user_id=current_user.id,
        filters=filters,
        pagination=pagination
    )
    
    return PaginatedTaskResponse.create(
        items=tasks,
        total=total,
        page=pagination.page,
        page_size=pagination.page_size
    )


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    task_in: TaskCreate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
) -> Any:
    """
    Create a new task.
    
    Requires board membership. Sends notification if assigned.
    """
    task_service = TaskService(db)
    
    # Create task
    task = await task_service.create(
        task_data=task_in,
        created_by=current_user.id
    )
    
    # Send notification if assigned
    if task_in.assignee_id and task_in.assignee_id != current_user.id:
        await NotificationService.send_task_assigned(
            user_id=task_in.assignee_id,
            task_id=task.id,
            assigned_by=current_user.id
        )
    
    logger.info("task_created", task_id=task.id, user_id=current_user.id)
    
    return task


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
) -> Any:
    """
    Get task by ID with full details.
    """
    task_service = TaskService(db)
    task = await task_service.get_by_id(task_id, user_id=current_user.id)
    
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )
    
    return task


@router.patch("/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: str,
    task_update: TaskUpdate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
) -> Any:
    """
    Update task fields.
    
    Supports partial updates. Sends notifications for significant changes.
    """
    task_service = TaskService(db)
    
    # Get existing task
    existing = await task_service.get_by_id(task_id, user_id=current_user.id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )
    
    # Update task
    task = await task_service.update(
        task_id=task_id,
        update_data=task_update,
        user_id=current_user.id
    )
    
    # Send notifications for changes
    if task_update.assignee_id and task_update.assignee_id != existing.assignee_id:
        if task_update.assignee_id:
            await NotificationService.send_task_assigned(
                user_id=task_update.assignee_id,
                task_id=task_id,
                assigned_by=current_user.id
            )
    
    logger.info("task_updated", task_id=task_id, user_id=current_user.id)
    
    return task


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_permissions(["task:delete"]))
) -> None:
    """
    Delete task permanently.
    
    Requires delete permission. Cascades to comments and attachments.
    """
    task_service = TaskService(db)
    
    success = await task_service.delete(task_id, user_id=current_user.id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )
    
    logger.info("task_deleted", task_id=task_id, user_id=current_user.id)


@router.patch("/{task_id}/assignee", response_model=TaskResponse)
async def update_task_assignee(
    task_id: str,
    assignee_update: TaskAssigneeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
) -> Any:
    """
    Update task assignee.
    
    Send notification to new assignee.
    """
    task_service = TaskService(db)
    
    task = await task_service.update_assignee(
        task_id=task_id,
        assignee_id=assignee_update.assignee_id,
        user_id=current_user.id
    )
    
    if assignee_update.assignee_id:
        await NotificationService.send_task_assigned(
            user_id=assignee_update.assignee_id,
            task_id=task_id,
            assigned_by=current_user.id
        )
    
    return task


@router.patch("/{task_id}/status", response_model=TaskResponse)
async def update_task_status(
    task_id: str,
    status_update: TaskStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
) -> Any:
    """
    Update task status.
    
    Validates status transitions. Sends completion notification.
    """
    task_service = TaskService(db)
    
    task = await task_service.update_status(
        task_id=task_id,
        status=status_update.status,
        user_id=current_user.id,
        comment=status_update.comment
    )
    
    # Notify creator if task completed
    if status_update.status == TaskStatus.DONE:
        await NotificationService.send_task_completed(
            task_id=task_id,
            completed_by=current_user.id
        )
    
    return task


@router.get("/my/assigned", response_model=PaginatedTaskResponse)
async def get_my_assigned_tasks(
    pagination: PaginationParams = Depends(),
    status: Optional[List[TaskStatus]] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
) -> Any:
    """
    Get tasks assigned to current user.
    """
    task_service = TaskService(db)
    
    tasks, total = await task_service.get_assigned_tasks(
        user_id=current_user.id,
        status=status,
        pagination=pagination
    )
    
    return PaginatedTaskResponse.create(
        items=tasks,
        total=total,
        page=pagination.page,
        page_size=pagination.page_size
    )


@router.get("/my/created", response_model=PaginatedTaskResponse)
async def get_my_created_tasks(
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
) -> Any:
    """
    Get tasks created by current user.
    """
    task_service = TaskService(db)
    
    tasks, total = await task_service.get_created_tasks(
        user_id=current_user.id,
        pagination=pagination
    )
    
    return PaginatedTaskResponse.create(
        items=tasks,
        total=total,
        page=pagination.page,
        page_size=pagination.page_size
    )