"""Task service with business logic and validation."""
import logging
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.task import Task, TaskPriority, TaskStatus, TaskType
from src.repositories.task_repository import TaskRepository
from src.repositories.user_repository import UserRepository

logger = logging.getLogger(__name__)


class TaskService:
    """Service for task business logic."""
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self.task_repo = TaskRepository(session)
        self.user_repo = UserRepository(session)
    
    async def create_task(
        self,
        title: str,
        created_by_id: UUID,
        description: Optional[str] = None,
        task_type: TaskType = TaskType.TASK,
        priority: TaskPriority = TaskPriority.MEDIUM,
        assignee_id: Optional[UUID] = None,
        team_id: Optional[UUID] = None,
        parent_id: Optional[UUID] = None,
        due_date: Optional[datetime] = None,
        story_points: Optional[int] = None,
        estimated_hours: Optional[float] = None,
        tags: Optional[List[str]] = None
    ) -> Task:
        """Create new task with validation."""
        # Validate assignee exists and is active
        if assignee_id:
            assignee = await self.user_repo.get_by_id(assignee_id)
            if not assignee or not assignee.is_active:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Assignee not found or inactive"
                )
        
        # Validate parent task exists
        if parent_id:
            parent = await self.task_repo.get_by_id(parent_id)
            if not parent or parent.is_deleted:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Parent task not found"
                )
        
        # Validate due date is in future
        if due_date and due_date < datetime.utcnow():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Due date must be in the future"
            )
        
        task_data = {
            "title": title,
            "description": description,
            "task_type": task_type,
            "status": TaskStatus.BACKLOG,
            "priority": priority,
            "created_by_id": created_by_id,
            "assignee_id": assignee_id,
            "team_id": team_id,
            "parent_id": parent_id,
            "due_date": due_date,
            "story_points": story_points,
            "estimated_hours": estimated_hours,
            "tags": tags or []
        }
        
        task = await self.task_repo.create(task_data)
        logger.info(f"Task created: {task.id} by user {created_by_id}")
        return task
    
    async def update_task(
        self,
        task_id: UUID,
        user_id: UUID,
        **updates
    ) -> Task:
        """Update task with permission checks."""
        task = await self.task_repo.get_by_id(task_id)
        if not task or task.is_deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Task not found"
            )
        
        # Check permissions (creator or assignee can update)
        if task.created_by_id != user_id and task.assignee_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to update this task"
            )
        
        # Validate status transition
        if "status" in updates:
            new_status = updates["status"]
            if not self._is_valid_status_transition(task.status, new_status):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid status transition from {task.status} to {new_status}"
                )
            
            # Set timestamps based on status
            if new_status == TaskStatus.IN_PROGRESS and not task.started_at:
                updates["started_at"] = datetime.utcnow()
            elif new_status == TaskStatus.DONE:
                updates["completed_at"] = datetime.utcnow()
        
        # Validate assignee change
        if "assignee_id" in updates and updates["assignee_id"]:
            assignee = await self.user_repo.get_by_id(updates["assignee_id"])
            if not assignee or not assignee.is_active:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Assignee not found or inactive"
                )
        
        updated_task = await self.task_repo.update(task_id, updates)
        logger.info(f"Task updated: {task_id} by user {user_id}")
        return updated_task
    
    async def delete_task(self, task_id: UUID, user_id: UUID) -> bool:
        """Soft delete task."""
        task = await self.task_repo.get_by_id(task_id)
        if not task or task.is_deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Task not found"
            )
        
        # Only creator can delete
        if task.created_by_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to delete this task"
            )
        
        # Check for subtasks
        subtasks = await self.task_repo.get_subtasks(task_id)
        if subtasks:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete task with subtasks. Delete subtasks first."
            )
        
        await self.task_repo.soft_delete(task_id)
        logger.info(f"Task soft deleted: {task_id} by user {user_id}")
        return True
    
    async def assign_task(
        self,
        task_id: UUID,
        assignee_id: Optional[UUID],
        assigned_by_id: UUID
    ) -> Task:
        """Assign task to user."""
        task = await self.task_repo.get_by_id(task_id)
        if not task or task.is_deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Task not found"
            )
        
        if assignee_id:
            assignee = await self.user_repo.get_by_id(assignee_id)
            if not assignee or not assignee.is_active:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Assignee not found or inactive"
                )
        
        task.assignee_id = assignee_id
        await self.session.flush()
        
        logger.info(f"Task {task_id} assigned to {assignee_id} by {assigned_by_id}")
        return task
    
    async def get_user_tasks(
        self,
        user_id: UUID,
        status: Optional[TaskStatus] = None,
        skip: int = 0,
        limit: int = 100
    ) -> List[Task]:
        """Get tasks for a user (created or assigned)."""
        return await self.task_repo.filter_tasks(
            created_by=user_id,
            assignee_id=user_id,
            status=status,
            skip=skip,
            limit=limit
        )
    
    async def get_team_tasks(
        self,
        team_id: UUID,
        status: Optional[TaskStatus] = None,
        skip: int = 0,
        limit: int = 100
    ) -> List[Task]:
        """Get tasks for a team."""
        return await self.task_repo.get_by_team(team_id, status, skip, limit)
    
    def _is_valid_status_transition(
        self,
        current: TaskStatus,
        new: TaskStatus
    ) -> bool:
        """Validate status transition."""
        allowed_transitions = {
            TaskStatus.BACKLOG: [TaskStatus.TODO, TaskStatus.CANCELLED],
            TaskStatus.TODO: [TaskStatus.IN_PROGRESS, TaskStatus.BACKLOG, TaskStatus.CANCELLED],
            TaskStatus.IN_PROGRESS: [TaskStatus.IN_REVIEW, TaskStatus.TODO, TaskStatus.CANCELLED],
            TaskStatus.IN_REVIEW: [TaskStatus.DONE, TaskStatus.IN_PROGRESS, TaskStatus.CANCELLED],
            TaskStatus.DONE: [TaskStatus.IN_REVIEW],
            TaskStatus.CANCELLED: [TaskStatus.BACKLOG]
        }
        return new in allowed_transitions.get(current, [])
