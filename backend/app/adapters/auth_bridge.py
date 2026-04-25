"""
Authentication Bridge for Legacy-Modern Auth System Integration

Unifies old and new authentication mechanisms, providing seamless
auth experience during migration.
"""

from typing import Optional, Dict, Any, List, Callable
from datetime import datetime, timedelta
from enum import Enum
import hashlib
import secrets
import logging
from abc import ABC, abstractmethod

from .base import AdapterContext, AdaptationError, ValidationError

logger = logging.getLogger(__name__)


class AuthMethod(Enum):
    """Supported authentication methods."""
    LEGACY_PASSWORD = "legacy_password"
    MODERN_JWT = "jwt"
    OAUTH2 = "oauth2"
    SAML = "saml"
    API_KEY = "api_key"
    MFA = "mfa"


class LegacyAuthToken:
    """Legacy authentication token structure."""
    
    def __init__(
        self,
        token_id: str,
        user_id: str,
        session_key: str,
        created_at: str,
        expires_at: str,
        permissions: Optional[List[str]] = None
    ):
        self.token_id = token_id
        self.user_id = user_id
        self.session_key = session_key
        self.created_at = created_at
        self.expires_at = expires_at
        self.permissions = permissions or []


class ModernAuthToken:
    """Modern JWT token structure."""
    
    def __init__(
        self,
        access_token: str,
        refresh_token: str,
        token_type: str = "Bearer",
        expires_in: int = 3600,
        scope: Optional[List[str]] = None,
        claims: Optional[Dict[str, Any]] = None
    ):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.token_type = token_type
        self.expires_in = expires_in
        self.scope = scope or []
        self.claims = claims or {}


class LegacyAuthAdapter:
    """
    Adapter for legacy authentication system.
    
    Handles legacy session-based authentication.
    """
    
    def __init__(self, context: Optional[AdapterContext] = None):
        self.context = context
        self._session_store: Dict[str, Dict[str, Any]] = {}
        self._hash_algorithm = "md5"  # Legacy uses weaker hashing
    
    def authenticate(
        self,
        username: str,
        password: str,
        legacy_user_store: Dict[str, Any]
    ) -> Optional[LegacyAuthToken]:
        """
        Authenticate using legacy credentials.
        
        Args:
            username: User's username
            password: User's password
            legacy_user_store: Legacy user data store
            
        Returns:
            LegacyAuthToken if successful, None otherwise
        """
        user = legacy_user_store.get(username)
        if not user:
            return None
        
        # Verify password using legacy hashing
        hashed_password = self._hash_password(password)
        if hashed_password != user.get("password_hash"):
            return None
        
        # Create session
        session_key = secrets.token_urlsafe(32)
        token_id = secrets.token_hex(16)
        
        now = datetime.utcnow()
        expires = now + timedelta(hours=24)  # Legacy sessions last 24 hours
        
        token = LegacyAuthToken(
            token_id=token_id,
            user_id=user.get("user_id"),
            session_key=session_key,
            created_at=now.isoformat(),
            expires_at=expires.isoformat(),
            permissions=user.get("permissions", [])
        )
        
        # Store session
        self._session_store[session_key] = {
            "token": token,
            "user": user,
            "created_at": now
        }
        
        return token
    
    def verify_token(self, session_key: str) -> Optional[Dict[str, Any]]:
        """Verify a legacy session token."""
        session = self._session_store.get(session_key)
        if not session:
            return None
        
        token = session["token"]
        expires = datetime.fromisoformat(token.expires_at)
        
        if datetime.utcnow() > expires:
            del self._session_store[session_key]
            return None
        
        return session["user"]
    
    def invalidate_session(self, session_key: str) -> bool:
        """Invalidate a legacy session."""
        if session_key in self._session_store:
            del self._session_store[session_key]
            return True
        return False
    
    def _hash_password(self, password: str) -> str:
        """Hash password using legacy algorithm."""
        return hashlib.md5(password.encode()).hexdigest()


class ModernAuthAdapter:
    """
    Adapter for modern JWT-based authentication.
    
    Handles OAuth2/JWT token generation and validation.
    """
    
    def __init__(
        self,
        secret_key: str,
        algorithm: str = "HS256",
        access_token_expire: int = 3600,
        refresh_token_expire: int = 86400 * 7,  # 7 days
        context: Optional[AdapterContext] = None
    ):
        self.context = context
        self.secret_key = secret_key
        self.algorithm = algorithm
        self.access_token_expire = access_token_expire
        self.refresh_token_expire = refresh_token_expire
        self._refresh_tokens: Dict[str, Dict[str, Any]] = {}
    
    def create_tokens(
        self,
        user_id: str,
        claims: Optional[Dict[str, Any]] = None
    ) -> ModernAuthToken:
        """
        Create new access and refresh tokens.
        
        Args:
            user_id: User identifier
            claims: Additional JWT claims
            
        Returns:
            ModernAuthToken with access and refresh tokens
        """
        try:
            import jwt
        except ImportError:
            logger.error("PyJWT library required for modern auth")
            raise AdaptationError("JWT library not available")
        
        now = datetime.utcnow()
        
        # Create access token
        access_claims = {
            "sub": user_id,
            "iat": now,
            "exp": now + timedelta(seconds=self.access_token_expire),
            "type": "access",
            **(claims or {})
        }
        
        access_token = jwt.encode(
            access_claims,
            self.secret_key,
            algorithm=self.algorithm
        )
        
        # Create refresh token
        refresh_token = secrets.token_urlsafe(32)
        refresh_claims = {
            "sub": user_id,
            "iat": now,
            "exp": now + timedelta(seconds=self.refresh_token_expire),
            "type": "refresh",
            "jti": secrets.token_hex(16)
        }
        
        # Store refresh token
        self._refresh_tokens[refresh_token] = {
            "user_id": user_id,
            "claims": refresh_claims,
            "created_at": now
        }
        
        return ModernAuthToken(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=self.access_token_expire,
            claims=access_claims
        )
    
    def verify_access_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Verify and decode an access token."""
        try:
            import jwt
            
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm]
            )
            
            if payload.get("type") != "access":
                return None
            
            return payload
            
        except jwt.ExpiredSignatureError:
            logger.warning("Access token expired")
            return None
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid access token: {e}")
            return None
    
    def refresh_access_token(self, refresh_token: str) -> Optional[ModernAuthToken]:
        """Create new access token using refresh token."""
        token_data = self._refresh_tokens.get(refresh_token)
        if not token_data:
            return None
        
        # Check expiration
        exp = token_data["claims"].get("exp")
        if exp and datetime.utcnow().timestamp() > exp:
            del self._refresh_tokens[refresh_token]
            return None
        
        # Create new tokens
        return self.create_tokens(
            token_data["user_id"],
            claims=token_data["claims"]
        )
    
    def revoke_refresh_token(self, refresh_token: str) -> bool:
        """Revoke a refresh token."""
        if refresh_token in self._refresh_tokens:
            del self._refresh_tokens[refresh_token]
            return True
        return False


class AuthenticationBridge:
    """
    Bridge unifying legacy and modern authentication.
    
    Provides seamless auth experience during migration:
    - Try modern auth first
    - Fall back to legacy auth
    - Migrate legacy sessions to JWT
    """
    
    def __init__(
        self,
        modern_adapter: ModernAuthAdapter,
        legacy_adapter: Optional[LegacyAuthAdapter] = None,
        migration_mode: bool = True
    ):
        self.modern = modern_adapter
        self.legacy = legacy_adapter or LegacyAuthAdapter()
        self.migration_mode = migration_mode
        self._migration_callbacks: List[Callable] = []
    
    def authenticate(
        self,
        username: str,
        password: str,
        legacy_user_store: Optional[Dict[str, Any]] = None,
        preferred_method: AuthMethod = AuthMethod.MODERN_JWT
    ) -> Optional[ModernAuthToken]:
        """
        Authenticate user using available methods.
        
        Args:
            username: User's username
            password: User's password
            legacy_user_store: Legacy user data (if using legacy auth)
            preferred_method: Preferred authentication method
            
        Returns:
            ModernAuthToken if successful
        """
        # Try preferred method first
        if preferred_method == AuthMethod.MODERN_JWT:
            # Try modern auth
            modern_result = self._try_modern_auth(username, password)
            if modern_result:
                return modern_result
            
            # Fall back to legacy if in migration mode
            if self.migration_mode and legacy_user_store:
                return self._migrate_legacy_auth(username, password, legacy_user_store)
        
        elif preferred_method == AuthMethod.LEGACY_PASSWORD:
            if legacy_user_store:
                return self._migrate_legacy_auth(username, password, legacy_user_store)
        
        return None
    
    def verify_token(
        self,
        token: str,
        token_type: str = "jwt"
    ) -> Optional[Dict[str, Any]]:
        """
        Verify token (JWT or legacy session).
        
        Args:
            token: Token to verify
            token_type: "jwt" or "legacy"
            
        Returns:
            Token payload if valid
        """
        if token_type == "jwt":
            return self.modern.verify_access_token(token)
        elif token_type == "legacy":
            return self.legacy.verify_token(token)
        
        # Auto-detect
        result = self.modern.verify_access_token(token)
        if result:
            return result
        
        return self.legacy.verify_token(token)
    
    def on_migration(self, callback: Callable):
        """Register callback for migration events."""
        self._migration_callbacks.append(callback)
    
    def _try_modern_auth(self, username: str, password: str) -> Optional[ModernAuthToken]:
        """Attempt modern authentication."""
        # This would integrate with your modern auth system
        # For now, return None to trigger legacy fallback
        return None
    
    def _migrate_legacy_auth(
        self,
        username: str,
        password: str,
        legacy_user_store: Dict[str, Any]
    ) -> Optional[ModernAuthToken]:
        """
        Authenticate via legacy and migrate to modern tokens.
        
        Args:
            username: User's username
            password: User's password
            legacy_user_store: Legacy user data
            
        Returns:
            ModernAuthToken if legacy auth succeeds
        """
        # Authenticate with legacy system
        legacy_token = self.legacy.authenticate(
            username, password, legacy_user_store
        )
        
        if not legacy_token:
            return None
        
        # Create modern tokens
        modern_token = self.modern.create_tokens(
            legacy_token.user_id,
            claims={
                "migrated_from_legacy": True,
                "legacy_permissions": legacy_token.permissions
            }
        )
        
        # Trigger migration callbacks
        for callback in self._migration_callbacks:
            try:
                callback({
                    "user_id": legacy_token.user_id,
                    "legacy_token": legacy_token,
                    "modern_token": modern_token
                })
            except Exception as e:
                logger.error(f"Migration callback error: {e}")
        
        logger.info(f"Migrated user {legacy_token.user_id} from legacy auth")
        
        return modern_token
    
    def migrate_session(self, legacy_session_key: str) -> Optional[ModernAuthToken]:
        """
        Migrate an active legacy session to modern tokens.
        
        Args:
            legacy_session_key: Legacy session identifier
            
        Returns:
            ModernAuthToken if session is valid
        """
        user = self.legacy.verify_token(legacy_session_key)
        if not user:
            return None
        
        # Create modern tokens
        modern_token = self.modern.create_tokens(
            user.get("user_id"),
            claims={
                "migrated_from_legacy": True,
                "session_migration": True
            }
        )
        
        # Invalidate legacy session
        self.legacy.invalidate_session(legacy_session_key)
        
        return modern_token


class PasswordMigrationStrategy:
    """
    Strategies for migrating passwords from legacy to modern systems.
    """
    
    @staticmethod
    def require_reset(user_id: str) -> Dict[str, Any]:
        """Require user to reset password on next login."""
        return {
            "strategy": "require_reset",
            "user_id": user_id,
            "requires_action": True,
            "action": "password_reset"
        }
    
    @staticmethod
    def hash_rehash(
        legacy_hash: str,
        modern_hasher: Callable[[str], str]
    ) -> Dict[str, Any]:
        """
        Re-hash legacy hash with modern algorithm.
        
        Note: This is less secure but allows seamless migration.
        """
        return {
            "strategy": "hash_rehash",
            "hash": modern_hasher(legacy_hash),
            "requires_action": False
        }
    
    @staticmethod
    def progressive_upgrade(
        user_id: str,
        legacy_hash: str
    ) -> Dict[str, Any]:
        """
        Upgrade password hash on next successful login.
        
        Store legacy hash temporarily and upgrade on successful auth.
        """
        return {
            "strategy": "progressive_upgrade",
            "user_id": user_id,
            "legacy_hash": legacy_hash,
            "requires_action": False,
            "upgrade_on_login": True
        }
