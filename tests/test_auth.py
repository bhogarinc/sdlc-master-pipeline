"""Unit tests for authentication service."""
import pytest
from datetime import timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import User, UserRole
from src.services.auth_service import AuthService
from src.config.settings import get_settings


@pytest.fixture
def auth_service(db_session: AsyncSession):
    """Create auth service fixture."""
    return AuthService(db_session)


@pytest.fixture
async def test_user(db_session: AsyncSession):
    """Create test user fixture."""
    from src.repositories.user_repository import UserRepository
    repo = UserRepository(db_session)
    
    user = await repo.create({
        "email": "test@example.com",
        "hashed_password": "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewKyNiAYMyzJ/IhK",  # 'password123'
        "first_name": "Test",
        "last_name": "User",
        "is_active": True,
        "is_verified": True,
        "role": UserRole.MEMBER
    })
    return user


class TestAuthService:
    """Test cases for AuthService."""
    
    async def test_hash_password(self, auth_service):
        """Test password hashing."""
        password = "testpassword123"
        hashed = auth_service.hash_password(password)
        
        assert hashed != password
        assert hashed.startswith("$2b$")  # bcrypt prefix
    
    async def test_verify_password(self, auth_service):
        """Test password verification."""
        password = "testpassword123"
        hashed = auth_service.hash_password(password)
        
        assert auth_service.verify_password(password, hashed) is True
        assert auth_service.verify_password("wrongpassword", hashed) is False
    
    async def test_create_access_token(self, auth_service):
        """Test JWT access token creation."""
        user_id = uuid4()
        token = auth_service.create_access_token(user_id)
        
        assert isinstance(token, str)
        assert len(token) > 0
        
        # Decode and verify
        payload = auth_service.decode_token(token)
        assert payload["sub"] == str(user_id)
        assert payload["type"] == "access"
    
    async def test_create_refresh_token(self, auth_service):
        """Test JWT refresh token creation."""
        user_id = uuid4()
        token = auth_service.create_refresh_token(user_id)
        
        assert isinstance(token, str)
        
        payload = auth_service.decode_token(token)
        assert payload["sub"] == str(user_id)
        assert payload["type"] == "refresh"
    
    async def test_decode_invalid_token(self, auth_service):
        """Test decoding invalid token raises exception."""
        with pytest.raises(HTTPException) as exc_info:
            auth_service.decode_token("invalid.token.here")
        
        assert exc_info.value.status_code == 401
    
    async def test_authenticate_user_success(self, auth_service, test_user):
        """Test successful user authentication."""
        # Update with known password hash
        test_user.hashed_password = auth_service.hash_password("password123")
        await auth_service.session.flush()
        
        user = await auth_service.authenticate_user("test@example.com", "password123")
        
        assert user is not None
        assert user.email == "test@example.com"
        assert user.last_login is not None
    
    async def test_authenticate_user_wrong_password(self, auth_service, test_user):
        """Test authentication with wrong password."""
        test_user.hashed_password = auth_service.hash_password("password123")
        await auth_service.session.flush()
        
        user = await auth_service.authenticate_user("test@example.com", "wrongpassword")
        
        assert user is None
        assert test_user.failed_login_attempts == 1
    
    async def test_authenticate_user_not_found(self, auth_service):
        """Test authentication for non-existent user."""
        user = await auth_service.authenticate_user("nonexistent@example.com", "password")
        
        assert user is None
    
    async def test_authenticate_user_inactive(self, auth_service, test_user):
        """Test authentication for inactive user."""
        test_user.is_active = False
        test_user.hashed_password = auth_service.hash_password("password123")
        await auth_service.session.flush()
        
        user = await auth_service.authenticate_user("test@example.com", "password123")
        
        assert user is None
    
    async def test_authenticate_user_locked(self, auth_service, test_user):
        """Test authentication for locked account."""
        from datetime import datetime, timedelta
        
        test_user.locked_until = datetime.utcnow() + timedelta(minutes=30)
        await auth_service.session.flush()
        
        with pytest.raises(HTTPException) as exc_info:
            await auth_service.authenticate_user("test@example.com", "password123")
        
        assert exc_info.value.status_code == 403
    
    async def test_register_user_success(self, auth_service):
        """Test successful user registration."""
        user = await auth_service.register_user(
            email="newuser@example.com",
            password="securepassword123",
            first_name="New",
            last_name="User"
        )
        
        assert user.email == "newuser@example.com"
        assert user.first_name == "New"
        assert user.is_active is True
        assert user.is_verified is False
    
    async def test_register_user_duplicate_email(self, auth_service, test_user):
        """Test registration with duplicate email."""
        with pytest.raises(HTTPException) as exc_info:
            await auth_service.register_user(
                email="test@example.com",
                password="password123"
            )
        
        assert exc_info.value.status_code == 400
    
    async def test_register_user_short_password(self, auth_service):
        """Test registration with short password."""
        with pytest.raises(HTTPException) as exc_info:
            await auth_service.register_user(
                email="new@example.com",
                password="short"
            )
        
        assert exc_info.value.status_code == 400
    
    async def test_change_password_success(self, auth_service, test_user):
        """Test successful password change."""
        test_user.hashed_password = auth_service.hash_password("oldpassword")
        await auth_service.session.flush()
        
        result = await auth_service.change_password(
            user_id=test_user.id,
            current_password="oldpassword",
            new_password="newpassword123"
        )
        
        assert result is True
        assert auth_service.verify_password("newpassword123", test_user.hashed_password)
    
    async def test_change_password_wrong_current(self, auth_service, test_user):
        """Test password change with wrong current password."""
        test_user.hashed_password = auth_service.hash_password("oldpassword")
        await auth_service.session.flush()
        
        with pytest.raises(HTTPException) as exc_info:
            await auth_service.change_password(
                user_id=test_user.id,
                current_password="wrongpassword",
                new_password="newpassword123"
            )
        
        assert exc_info.value.status_code == 400
    
    async def test_change_password_short_new(self, auth_service, test_user):
        """Test password change with short new password."""
        test_user.hashed_password = auth_service.hash_password("oldpassword")
        await auth_service.session.flush()
        
        with pytest.raises(HTTPException) as exc_info:
            await auth_service.change_password(
                user_id=test_user.id,
                current_password="oldpassword",
                new_password="short"
            )
        
        assert exc_info.value.status_code == 400
