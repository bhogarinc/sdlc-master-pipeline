"""Integration tests for authentication endpoints."""

import pytest
from httpx import AsyncClient


class TestAuthEndpoints:
    """Test authentication endpoints."""
    
    async def test_register_user(self, client: AsyncClient):
        """Test user registration."""
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "newuser@example.com",
                "password": "password123",
                "first_name": "New",
                "last_name": "User",
            },
        )
        
        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "newuser@example.com"
        assert data["first_name"] == "New"
        assert data["last_name"] == "User"
        assert "id" in data
    
    async def test_register_duplicate_email(self, client: AsyncClient, test_user):
        """Test registration with duplicate email."""
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": test_user.email,
                "password": "password123",
                "first_name": "Test",
                "last_name": "User",
            },
        )
        
        assert response.status_code == 400
        assert "already registered" in response.json()["detail"]
    
    async def test_login_success(self, client: AsyncClient, test_user):
        """Test successful login."""
        response = await client.post(
            "/api/v1/auth/login",
            data={"username": test_user.email, "password": "password123"},
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert "expires_in" in data
    
    async def test_login_invalid_credentials(self, client: AsyncClient):
        """Test login with invalid credentials."""
        response = await client.post(
            "/api/v1/auth/login",
            data={"username": "nonexistent@example.com", "password": "wrongpassword"},
        )
        
        assert response.status_code == 401
