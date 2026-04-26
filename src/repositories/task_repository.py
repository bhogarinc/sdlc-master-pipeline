"""Task repository with filtering and search capabilities."""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy import Select, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.task import Task, TaskPriority, TaskStatus
from src.repositories.base import BaseRepository


class TaskRepository(BaseRepository[Task]):
    """Repository for Task entity operations."""
    
    def __init__(self, session: AsyncSession):
        super().__init__(Task, session)
    
    async def get_by_assignee(
        self,
        assignee_id: UUID,
        status: Optional[TaskStatus] = None,
        skip: int = 0,
        limit: int = 100
    ) -> List[Task]:
        """Get tasks assigned to a user."""
        query = select(Task).where(
            Task.assignee_id == assignee_id,
            Task.is_deleted == False
        )
        if status:
            query = query.where(Task.status == status)
        query = query.offset(skip).limit(limit)
        result = await self.session.execute(query)
        return result.scalars().all()
    
    async def get_by_team(
        self,
        team_id: UUID,
        status: Optional[TaskStatus] = None,
        skip: int = 0,
        limit: int = 100
    ) -> List[Task]:
        """Get tasks in a team."""
        query = select(Task).where(
            Task.team_id == team_id,
            Task.is_deleted == False
        )
        if status:
            query = query.where(Task.status == status)
        query = query.offset(skip).limit(limit)
        result = await self.session.execute(query)
        return result.scalars().all()
    
    async def get_subtasks(self, parent_id: UUID) -> List[Task]:
        """Get subtasks for a parent task."""
        query = select(Task).where(
            Task.parent_id == parent_id,
            Task.is_deleted == False
        )
        result = await self.session.execute(query)
        return result.scalars().all()
    
    async def search_tasks(
        self,
        query_str: str,
        user_id: Optional[UUID] = None,
        team_id: Optional[UUID] = None,
        skip: int = 0,
        limit: int = 20
    ) -> List[Task]:
        """Search tasks by title or description."""
        search_pattern = f"%{query_str}%"
        
        conditions = [
            or_(
                Task.title.ilike(search_pattern),
                Task.description.ilike(search_pattern)
            ),
            Task.is_deleted == False
        ]
        
        if user_id:
            conditions.append(
                or_(
                    Task.created_by_id == user_id,
                    Task.assignee_id == user_id
                )
            )
        
        if team_id:
            conditions.append(Task.team_id == team_id)
        
        query = select(Task).where(and_(*conditions)).offset(skip).limit(limit)
        result = await self.session.execute(query)
        return result.scalars().all()
    
    async def filter_tasks(
        self,
        created_by: Optional[UUID] = None,
        assignee_id: Optional[UUID] = None,
        team_id: Optional[UUID] = None,
        status: Optional[TaskStatus] = None,
        priority: Optional[TaskPriority] = None,
        due_before: Optional[datetime] = None,
        tags: Optional[List[str]] = None,
        skip: int = 0,
        limit: int = 100
    ) -> List[Task]:
        """Filter tasks by multiple criteria."""
        conditions = [Task.is_deleted == False]
        
        if created_by:
            conditions.append(Task.created_by_id == created_by)
        if assignee_id:
            conditions.append(Task.assignee_id == assignee_id)
        if team_id:
            conditions.append(Task.team_id == team_id)
        if status:
            conditions.append(Task.status == status)
        if priority:
            conditions.append(Task.priority == priority)
        if due_before:
            conditions.append(Task.due_date <= due_before)
        if tags:
            conditions.append(Task.tags.overlap(tags))
        
        query = select(Task).where(and_(*conditions)).offset(skip).limit(limit)
        result = await self.session.execute(query)
        return result.scalars().all()
    
    async def get_overdue_tasks(self, team_id: Optional[UUID] = None) -> List[Task]:
        """Get overdue tasks."""
        now = datetime.utcnow()
        conditions = [
            Task.due_date < now,
            Task.status.notin_([TaskStatus.DONE, TaskStatus.CANCELLED]),
            Task.is_deleted == False
        ]
        if team_id:
            conditions.append(Task.team_id == team_id)
        
        query = select(Task).where(and_(*conditions))
        result = await self.session.execute(query)
        return result.scalars().all()
    
    async def get_tasks_with_relations(self, task_id: UUID) -> Optional[Task]:
        """Get task with all related data loaded."""
        query = (
            select(Task)
            .options(
                selectinload(Task.creator),
                selectinload(Task.assignee),
                selectinload(Task.team),
                selectinload(Task.subtasks)
            )
            .where(Task.id == task_id)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()
