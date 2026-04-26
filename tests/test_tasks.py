"""Unit tests for task service."""
import pytest
from datetime import datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.task import Task, TaskPriority, TaskStatus, TaskType
from src.models.user import User, UserRole
from src.repositories.task_repository import TaskRepository
from src.repositories.user_repository import UserRepository
from src.services.task_service import TaskService


@pytest.fixture
async def test_user(db_session: AsyncSession):
    """Create test user."""
    repo = UserRepository(db_session)
    return await repo.create({
        "email": "taskuser@example.com",
        "hashed_password": "hashed",
        "is_active": True,
        "role": UserRole.MEMBER
    })


@pytest.fixture
async def test_assignee(db_session: AsyncSession):
    """Create test assignee."""
    repo = UserRepository(db_session)
    return await repo.create({
        "email": "assignee@example.com",
        "hashed_password": "hashed",
        "is_active": True,
        "role": UserRole.MEMBER
    })


@pytest.fixture
def task_service(db_session: AsyncSession):
    """Create task service."""
    return TaskService(db_session)


class TestTaskService:
    """Test cases for TaskService."""
    
    async def test_create_task(self, task_service, test_user):
        """Test task creation."""
        task = await task_service.create_task(
            title="Test Task",
            created_by_id=test_user.id,
            description="Test description",
            priority=TaskPriority.HIGH
        )
        
        assert task.title == "Test Task"
        assert task.description == "Test description"
        assert task.priority == TaskPriority.HIGH
        assert task.status == TaskStatus.BACKLOG
        assert task.created_by_id == test_user.id
    
    async def test_create_task_with_assignee(self, task_service, test_user, test_assignee):
        """Test task creation with assignee."""
        task = await task_service.create_task(
            title="Assigned Task",
            created_by_id=test_user.id,
            assignee_id=test_assignee.id
        )
        
        assert task.assignee_id == test_assignee.id
    
    async def test_create_task_invalid_assignee(self, task_service, test_user):
        """Test task creation with invalid assignee."""
        with pytest.raises(HTTPException) as exc_info:
            await task_service.create_task(
                title="Test Task",
                created_by_id=test_user.id,
                assignee_id=uuid4()  # Non-existent user
            )
        
        assert exc_info.value.status_code == 400
    
    async def test_create_task_past_due_date(self, task_service, test_user):
        """Test task creation with past due date."""
        past_date = datetime.utcnow() - timedelta(days=1)
        
        with pytest.raises(HTTPException) as exc_info:
            await task_service.create_task(
                title="Test Task",
                created_by_id=test_user.id,
                due_date=past_date
            )
        
        assert exc_info.value.status_code == 400
    
    async def test_update_task(self, task_service, test_user):
        """Test task update."""
        # Create task
        task = await task_service.create_task(
            title="Original Title",
            created_by_id=test_user.id
        )
        
        # Update task
        updated = await task_service.update_task(
            task_id=task.id,
            user_id=test_user.id,
            title="Updated Title",
            priority=TaskPriority.HIGH
        )
        
        assert updated.title == "Updated Title"
        assert updated.priority == TaskPriority.HIGH
    
    async def test_update_task_unauthorized(self, task_service, test_user, test_assignee):
        """Test task update by unauthorized user."""
        # Create task
        task = await task_service.create_task(
            title="Test Task",
            created_by_id=test_user.id
        )
        
        # Try to update as different user
        with pytest.raises(HTTPException) as exc_info:
            await task_service.update_task(
                task_id=task.id,
                user_id=test_assignee.id,
                title="Hacked Title"
            )
        
        assert exc_info.value.status_code == 403
    
    async def test_update_task_invalid_status_transition(self, task_service, test_user):
        """Test invalid status transition."""
        # Create task
        task = await task_service.create_task(
            title="Test Task",
            created_by_id=test_user.id,
            status=TaskStatus.BACKLOG
        )
        
        # Try invalid transition: backlog -> done
        with pytest.raises(HTTPException) as exc_info:
            await task_service.update_task(
                task_id=task.id,
                user_id=test_user.id,
                status=TaskStatus.DONE
            )
        
        assert exc_info.value.status_code == 400
    
    async def test_delete_task(self, task_service, test_user):
        """Test task deletion."""
        # Create task
        task = await task_service.create_task(
            title="To Delete",
            created_by_id=test_user.id
        )
        
        # Delete task
        result = await task_service.delete_task(task.id, test_user.id)
        assert result is True
        
        # Verify soft delete
        repo = TaskRepository(task_service.session)
        deleted_task = await repo.get_by_id(task.id)
        assert deleted_task.is_deleted is True
    
    async def test_delete_task_with_subtasks(self, task_service, test_user):
        """Test deletion of task with subtasks."""
        # Create parent task
        parent = await task_service.create_task(
            title="Parent Task",
            created_by_id=test_user.id
        )
        
        # Create subtask
        await task_service.create_task(
            title="Subtask",
            created_by_id=test_user.id,
            parent_id=parent.id
        )
        
        # Try to delete parent
        with pytest.raises(HTTPException) as exc_info:
            await task_service.delete_task(parent.id, test_user.id)
        
        assert exc_info.value.status_code == 400
    
    async def test_assign_task(self, task_service, test_user, test_assignee):
        """Test task assignment."""
        # Create task
        task = await task_service.create_task(
            title="Test Task",
            created_by_id=test_user.id
        )
        
        # Assign task
        assigned = await task_service.assign_task(
            task_id=task.id,
            assignee_id=test_assignee.id,
            assigned_by_id=test_user.id
        )
        
        assert assigned.assignee_id == test_assignee.id
    
    async def test_get_user_tasks(self, task_service, test_user, test_assignee):
        """Test getting user tasks."""
        # Create tasks
        await task_service.create_task(
            title="Created Task",
            created_by_id=test_user.id
        )
        await task_service.create_task(
            title="Assigned Task",
            created_by_id=test_user.id,
            assignee_id=test_assignee.id
        )
        
        # Get tasks
        tasks = await task_service.get_user_tasks(test_user.id)
        assert len(tasks) >= 1
    
    async def test_valid_status_transitions(self, task_service):
        """Test valid status transitions."""
        # Valid transitions
        valid = [
            (TaskStatus.BACKLOG, TaskStatus.TODO),
            (TaskStatus.TODO, TaskStatus.IN_PROGRESS),
            (TaskStatus.IN_PROGRESS, TaskStatus.IN_REVIEW),
            (TaskStatus.IN_REVIEW, TaskStatus.DONE),
            (TaskStatus.DONE, TaskStatus.IN_REVIEW),
            (TaskStatus.CANCELLED, TaskStatus.BACKLOG),
        ]
        
        for current, new in valid:
            assert task_service._is_valid_status_transition(current, new) is True
        
        # Invalid transitions
        invalid = [
            (TaskStatus.BACKLOG, TaskStatus.DONE),
            (TaskStatus.DONE, TaskStatus.TODO),
            (TaskStatus.CANCELLED, TaskStatus.DONE),
        ]
        
        for current, new in invalid:
            assert task_service._is_valid_status_transition(current, new) is False
