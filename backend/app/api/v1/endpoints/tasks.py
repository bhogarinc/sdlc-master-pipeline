"""Task management endpoints"""
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import or_
from datetime import datetime

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.exceptions import NotFoundError, AuthorizationError
from app.core.dependencies import get_pagination, PaginationParams
from app.schemas.task import (
    TaskCreate, TaskUpdate, TaskResponse, TaskDetailResponse,
    TaskBulkUpdate, TaskCommentCreate, TaskCommentResponse, TaskStatus
)
from app.schemas.base import DataResponse, PaginatedResponse, PaginatedData, BaseResponse

router = APIRouter()


@router.post("/", response_model=DataResponse[TaskResponse], status_code=status.HTTP_201_CREATED)
async def create_task(task_data: TaskCreate, current_user = Depends(get_current_user), db: Session = Depends(get_db)) -> Any:
    """Create a new task."""
    from app.models.task import Task
    
    if task_data.team_id:
        team = current_user.teams.filter_by(id=task_data.team_id).first()
        if not team:
            raise AuthorizationError("Not a member of this team")
    
    task = Task(**task_data.model_dump(exclude_unset=True), creator_id=current_user.id)
    if not task.assignee_id:
        task.assignee_id = current_user.id
    
    db.add(task)
    db.commit()
    db.refresh(task)
    
    return DataResponse(data=task, message="Task created successfully")


@router.get("/", response_model=PaginatedResponse[List[TaskResponse]])
async def list_tasks(
    status: Optional[TaskStatus] = Query(None),
    priority: Optional[str] = Query(None),
    assignee_id: Optional[str] = Query(None),
    team_id: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    tags: Optional[List[str]] = Query(None),
    due_before: Optional[datetime] = Query(None),
    due_after: Optional[datetime] = Query(None),
    pagination: PaginationParams = Depends(get_pagination),
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Any:
    """List tasks with filtering and pagination."""
    from app.models.task import Task
    
    query = db.query(Task).filter(
        or_(
            Task.creator_id == current_user.id,
            Task.assignee_id == current_user.id,
            Task.team_id.in_([t.id for t in current_user.teams])
        )
    )
    
    if status:
        query = query.filter(Task.status == status)
    if priority:
        query = query.filter(Task.priority == priority)
    if assignee_id:
        query = query.filter(Task.assignee_id == assignee_id)
    if team_id:
        query = query.filter(Task.team_id == team_id)
    if search:
        search_filter = f"%{search}%"
        query = query.filter(or_(Task.title.ilike(search_filter), Task.description.ilike(search_filter)))
    if tags:
        query = query.filter(Task.tags.overlap(tags))
    if due_before:
        query = query.filter(Task.due_date <= due_before)
    if due_after:
        query = query.filter(Task.due_date >= due_after)
    
    query = query.order_by(Task.created_at.desc())
    
    total = query.count()
    tasks = query.offset(pagination.offset).limit(pagination.limit).all()
    pages = (total + pagination.limit - 1) // pagination.limit
    
    return PaginatedResponse(
        data=PaginatedData(items=tasks, total=total, page=pagination.page,
                          limit=pagination.limit, pages=pages)
    )


@router.get("/{task_id}", response_model=DataResponse[TaskDetailResponse])
async def get_task(task_id: str, current_user = Depends(get_current_user), db: Session = Depends(get_db)) -> Any:
    """Get task details by ID."""
    from app.models.task import Task
    
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise NotFoundError("Task", task_id)
    
    if not task.has_access(current_user):
        raise AuthorizationError("No access to this task")
    
    detail = TaskDetailResponse(
        **TaskResponse.model_validate(task).model_dump(),
        creator=task.creator,
        comments_count=len(task.comments),
        attachments_count=len(task.attachments)
    )
    
    return DataResponse(data=detail)


@router.put("/{task_id}", response_model=DataResponse[TaskResponse])
async def update_task(
    task_id: str,
    task_data: TaskUpdate,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Any:
    """Update task by ID."""
    from app.models.task import Task
    
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise NotFoundError("Task", task_id)
    
    if not task.can_edit(current_user):
        raise AuthorizationError("Cannot edit this task")
    
    update_data = task_data.model_dump(exclude_unset=True)
    old_status = task.status
    
    for field, value in update_data.items():
        setattr(task, field, value)
    
    if update_data.get("status") == TaskStatus.DONE and old_status != TaskStatus.DONE:
        task.completed_at = datetime.utcnow()
    
    db.commit()
    db.refresh(task)
    
    return DataResponse(data=task, message="Task updated successfully")


@router.delete("/{task_id}", response_model=BaseResponse)
async def delete_task(task_id: str, current_user = Depends(get_current_user), db: Session = Depends(get_db)) -> Any:
    """Delete task by ID."""
    from app.models.task import Task
    
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise NotFoundError("Task", task_id)
    
    if task.creator_id != current_user.id:
        if task.team_id:
            membership = current_user.team_memberships.filter_by(team_id=task.team_id).first()
            if not membership or membership.role not in ["owner", "admin"]:
                raise AuthorizationError("Cannot delete this task")
        else:
            raise AuthorizationError("Cannot delete this task")
    
    db.delete(task)
    db.commit()
    
    return BaseResponse(message="Task deleted successfully")


@router.post("/bulk-update", response_model=BaseResponse)
async def bulk_update_tasks(
    bulk_data: TaskBulkUpdate,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Any:
    """Update multiple tasks at once."""
    from app.models.task import Task
    
    tasks = db.query(Task).filter(Task.id.in_(bulk_data.task_ids)).all()
    update_count = 0
    update_data = bulk_data.model_dump(exclude={"task_ids"}, exclude_unset=True)
    
    for task in tasks:
        if task.can_edit(current_user):
            for field, value in update_data.items():
                setattr(task, field, value)
            update_count += 1
    
    db.commit()
    return BaseResponse(message=f"Updated {update_count} of {len(bulk_data.task_ids)} tasks")


@router.post("/{task_id}/comments", response_model=DataResponse[TaskCommentResponse])
async def add_comment(
    task_id: str,
    comment_data: TaskCommentCreate,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Any:
    """Add comment to task."""
    from app.models.task import Task, TaskComment
    
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise NotFoundError("Task", task_id)
    
    if not task.has_access(current_user):
        raise AuthorizationError("No access to this task")
    
    comment = TaskComment(task_id=task_id, author_id=current_user.id, content=comment_data.content)
    db.add(comment)
    db.commit()
    db.refresh(comment)
    
    return DataResponse(data=comment, message="Comment added successfully")
