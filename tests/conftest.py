"""Pytest configuration and fixtures."""
import asyncio
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.config.database import Base
from src.config.settings import Settings

# Test database URL
TEST_DATABASE_URL = "postgresql+asyncpg://test:test@localhost:5432/taskflow_test"


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """Create test database engine."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        future=True
    )
    
    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    yield engine
    
    # Drop tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create test database session."""
    async_session = sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False
    )
    
    async with async_session() as session:
        yield session
        # Rollback after test
        await session.rollback()


@pytest.fixture
def test_settings():
    """Create test settings."""
    return Settings(
        DATABASE_URL="postgresql://test:test@localhost:5432/taskflow_test",
        SECRET_KEY="test-secret-key-for-testing-only",
        DEBUG=True,
        ENVIRONMENT="testing"
    )


@pytest.fixture
def mock_user_data():
    """Sample user data for tests."""
    return {
        "email": "test@example.com",
        "password": "testpassword123",
        "first_name": "Test",
        "last_name": "User"
    }


@pytest.fixture
def mock_task_data():
    """Sample task data for tests."""
    return {
        "title": "Test Task",
        "description": "This is a test task",
        "priority": "medium",
        "task_type": "task"
    }


@pytest.fixture
def mock_team_data():
    """Sample team data for tests."""
    return {
        "name": "Test Team",
        "description": "A team for testing"
    }
