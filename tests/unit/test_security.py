"""Unit tests for security utilities."""

import pytest

from src.utils.security import (
    create_access_token,
    decode_token,
    get_password_hash,
    verify_password,
)


class TestPasswordHashing:
    """Test password hashing functionality."""
    
    def test_password_hashing(self):
        """Test password hashing and verification."""
        password = "mysecretpassword"
        hashed = get_password_hash(password)
        
        assert hashed != password
        assert verify_password(password, hashed) is True
        assert verify_password("wrongpassword", hashed) is False
    
    def test_different_passwords_different_hashes(self):
        """Test that different passwords produce different hashes."""
        password1 = "password1"
        password2 = "password2"
        
        hash1 = get_password_hash(password1)
        hash2 = get_password_hash(password2)
        
        assert hash1 != hash2


class TestJWTToken:
    """Test JWT token functionality."""
    
    def test_create_and_decode_token(self):
        """Test token creation and decoding."""
        data = {"sub": "user123", "email": "test@example.com"}
        token = create_access_token(data)
        
        assert token is not None
        assert isinstance(token, str)
        
        decoded = decode_token(token)
        assert decoded is not None
        assert decoded["sub"] == "user123"
        assert decoded["email"] == "test@example.com"
    
    def test_decode_invalid_token(self):
        """Test decoding invalid token."""
        result = decode_token("invalid.token.here")
        assert result is None
    
    def test_decode_malformed_token(self):
        """Test decoding malformed token."""
        result = decode_token("not-a-token")
        assert result is None
