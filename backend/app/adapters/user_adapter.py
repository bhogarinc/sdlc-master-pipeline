"""
User Adapters for Legacy-Modern User System Integration

Provides adapters for converting between legacy user formats and modern TaskFlow Pro user models.
Includes support for user migration scenarios.
"""

from typing import Optional, List, Dict, Any, Set
from datetime import datetime
from enum import Enum
import re
import logging

from .base import TwoWayAdapter, AdapterContext, AdaptationError, ValidationError

logger = logging.getLogger(__name__)


class LegacyUserRole(Enum):
    """Legacy role values."""
    ADMIN = "A"
    MANAGER = "M"
    USER = "U"
    GUEST = "G"


class ModernUserRole(Enum):
    """Modern role values."""
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    TEAM_LEAD = "team_lead"
    MEMBER = "member"
    VIEWER = "viewer"


class LegacyUser:
    """Legacy user data structure."""
    
    def __init__(
        self,
        user_id: str,
        username: str,
        email: str,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        role: str = "U",
        is_active: bool = True,
        created_date: Optional[str] = None,
        last_login: Optional[str] = None,
        phone: Optional[str] = None,
        department: Optional[str] = None,
        employee_id: Optional[str] = None,
        preferences: Optional[Dict[str, Any]] = None,
        permissions: Optional[List[str]] = None
    ):
        self.user_id = user_id
        self.username = username
        self.email = email
        self.first_name = first_name
        self.last_name = last_name
        self.role = role
        self.is_active = is_active
        self.created_date = created_date
        self.last_login = last_login
        self.phone = phone
        self.department = department
        self.employee_id = employee_id
        self.preferences = preferences or {}
        self.permissions = permissions or []


class ModernUser:
    """Modern user data structure (TaskFlow Pro)."""
    
    def __init__(
        self,
        id: str,
        email: str,
        username: str,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        role: str = "member",
        is_active: bool = True,
        email_verified: bool = False,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
        last_login_at: Optional[datetime] = None,
        phone_number: Optional[str] = None,
        avatar_url: Optional[str] = None,
        timezone: str = "UTC",
        locale: str = "en",
        notification_preferences: Optional[Dict[str, Any]] = None,
        team_ids: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.id = id
        self.email = email
        self.username = username
        self.first_name = first_name
        self.last_name = last_name
        self.role = role
        self.is_active = is_active
        self.email_verified = email_verified
        self.created_at = created_at
        self.updated_at = updated_at
        self.last_login_at = last_login_at
        self.phone_number = phone_number
        self.avatar_url = avatar_url
        self.timezone = timezone
        self.locale = locale
        self.notification_preferences = notification_preferences or {}
        self.team_ids = team_ids or []
        self.metadata = metadata or {}


class LegacyUserAdapter(TwoWayAdapter[LegacyUser, ModernUser]):
    """
    Bidirectional adapter for legacy and modern user formats.
    
    Handles:
    - Role mapping (A, M, U, G) -> (super_admin, admin, team_lead, member, viewer)
    - Name splitting/combining
    - Date format conversions
    - Preference mapping
    - Permission translation
    """
    
    # Role mapping from legacy to modern
    ROLE_TO_MODERN = {
        "A": "admin",
        "M": "team_lead",
        "U": "member",
        "G": "viewer"
    }
    
    # Role mapping from modern to legacy (best fit)
    ROLE_TO_LEGACY = {
        "super_admin": "A",
        "admin": "A",
        "team_lead": "M",
        "member": "U",
        "viewer": "G"
    }
    
    # Legacy preference keys to modern mapping
    PREFERENCE_MAP = {
        "email_notifications": "email_enabled",
        "sms_notifications": "sms_enabled",
        "theme": "ui_theme",
        "language": "locale"
    }
    
    def __init__(self, context: Optional[AdapterContext] = None):
        super().__init__(context)
        self._date_format = "%Y-%m-%d %H:%M:%S"
    
    def to_modern(self, legacy_data: LegacyUser) -> ModernUser:
        """Convert legacy user to modern format."""
        try:
            # Parse dates
            created_at = self._parse_date(legacy_data.created_date) or datetime.utcnow()
            last_login_at = self._parse_date(legacy_data.last_login)
            
            # Convert role
            role = self.ROLE_TO_MODERN.get(legacy_data.role, "member")
            
            # Transform preferences
            notification_preferences = self._transform_preferences(legacy_data.preferences)
            
            # Build metadata
            metadata = {
                "legacy_user_id": legacy_data.user_id,
                "migrated_at": datetime.utcnow().isoformat(),
                "department": legacy_data.department,
                "employee_id": legacy_data.employee_id,
                "legacy_permissions": legacy_data.permissions
            }
            
            return ModernUser(
                id=legacy_data.user_id,
                email=legacy_data.email,
                username=legacy_data.username,
                first_name=legacy_data.first_name,
                last_name=legacy_data.last_name,
                role=role,
                is_active=legacy_data.is_active,
                email_verified=True,  # Assume verified from legacy
                created_at=created_at,
                updated_at=datetime.utcnow(),
                last_login_at=last_login_at,
                phone_number=legacy_data.phone,
                notification_preferences=notification_preferences,
                metadata=metadata
            )
            
        except Exception as e:
            logger.error(f"Failed to adapt legacy user {legacy_data.user_id}: {str(e)}")
            raise AdaptationError(
                f"User adaptation failed: {str(e)}",
                legacy_data,
                self.context
            )
    
    def to_legacy(self, modern_data: ModernUser) -> LegacyUser:
        """Convert modern user to legacy format."""
        try:
            # Convert role
            role = self.ROLE_TO_LEGACY.get(modern_data.role, "U")
            
            # Format dates
            created_date = self._format_date(modern_data.created_at)
            last_login = self._format_date(modern_data.last_login_at)
            
            # Reverse transform preferences
            preferences = self._reverse_transform_preferences(
                modern_data.notification_preferences
            )
            
            # Extract metadata
            department = modern_data.metadata.get("department")
            employee_id = modern_data.metadata.get("employee_id")
            permissions = modern_data.metadata.get("legacy_permissions", [])
            
            return LegacyUser(
                user_id=modern_data.id,
                username=modern_data.username,
                email=modern_data.email,
                first_name=modern_data.first_name,
                last_name=modern_data.last_name,
                role=role,
                is_active=modern_data.is_active,
                created_date=created_date,
                last_login=last_login,
                phone=modern_data.phone_number,
                department=department,
                employee_id=employee_id,
                preferences=preferences,
                permissions=permissions
            )
            
        except Exception as e:
            logger.error(f"Failed to convert modern user {modern_data.id} to legacy: {str(e)}")
            raise AdaptationError(
                f"User conversion failed: {str(e)}",
                modern_data,
                self.context
            )
    
    def _parse_date(self, date_str: Optional[str]) -> Optional[datetime]:
        """Parse date string to datetime."""
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str, self._date_format)
        except ValueError:
            logger.warning(f"Could not parse date: {date_str}")
            return None
    
    def _format_date(self, dt: Optional[datetime]) -> Optional[str]:
        """Format datetime to string."""
        if not dt:
            return None
        return dt.strftime(self._date_format)
    
    def _transform_preferences(self, legacy_prefs: Dict[str, Any]) -> Dict[str, Any]:
        """Transform legacy preferences to modern format."""
        modern_prefs = {}
        
        for key, value in legacy_prefs.items():
            modern_key = self.PREFERENCE_MAP.get(key, key)
            modern_prefs[modern_key] = value
        
        # Set defaults for missing keys
        modern_prefs.setdefault("email_enabled", True)
        modern_prefs.setdefault("push_enabled", True)
        modern_prefs.setdefault("digest_frequency", "daily")
        
        return modern_prefs
    
    def _reverse_transform_preferences(self, modern_prefs: Dict[str, Any]) -> Dict[str, Any]:
        """Transform modern preferences back to legacy format."""
        legacy_prefs = {}
        
        # Reverse the mapping
        reverse_map = {v: k for k, v in self.PREFERENCE_MAP.items()}
        
        for key, value in modern_prefs.items():
            legacy_key = reverse_map.get(key, key)
            legacy_prefs[legacy_key] = value
        
        return legacy_prefs


class UserMigrationAdapter:
    """
    Specialized adapter for user migration scenarios.
    
    Handles:
    - Password migration strategies
    - Email normalization
    - Duplicate detection
    - Migration validation
    """
    
    def __init__(self, user_adapter: Optional[LegacyUserAdapter] = None):
        self.user_adapter = user_adapter or LegacyUserAdapter()
        self.migrated_users: Dict[str, ModernUser] = {}
        self.conflicts: List[Dict[str, Any]] = []
    
    def migrate_user(
        self,
        legacy_user: LegacyUser,
        password_strategy: str = "require_reset",
        validate_email: bool = True
    ) -> ModernUser:
        """
        Migrate a single user with validation.
        
        Args:
            legacy_user: User to migrate
            password_strategy: How to handle passwords ("require_reset", "hash_migrate", "temp")
            validate_email: Whether to validate email format
            
        Returns:
            Migrated modern user
        """
        # Validate email if requested
        if validate_email and not self._validate_email(legacy_user.email):
            raise ValidationError(f"Invalid email format: {legacy_user.email}")
        
        # Check for duplicates
        if legacy_user.email in self.migrated_users:
            self.conflicts.append({
                "type": "duplicate_email",
                "legacy_id": legacy_user.user_id,
                "email": legacy_user.email
            })
            raise AdaptationError(f"Duplicate email detected: {legacy_user.email}")
        
        # Adapt the user
        modern_user = self.user_adapter.to_modern(legacy_user)
        
        # Add migration metadata
        modern_user.metadata["migration_strategy"] = password_strategy
        modern_user.metadata["requires_password_reset"] = (
            password_strategy == "require_reset"
        )
        
        self.migrated_users[legacy_user.email] = modern_user
        
        return modern_user
    
    def migrate_batch(
        self,
        legacy_users: List[LegacyUser],
        continue_on_error: bool = True
    ) -> Dict[str, Any]:
        """
        Migrate a batch of users.
        
        Args:
            legacy_users: List of users to migrate
            continue_on_error: Whether to continue on individual failures
            
        Returns:
            Migration results summary
        """
        results = {
            "successful": [],
            "failed": [],
            "total": len(legacy_users)
        }
        
        for user in legacy_users:
            try:
                modern_user = self.migrate_user(user)
                results["successful"].append({
                    "legacy_id": user.user_id,
                    "modern_id": modern_user.id,
                    "email": user.email
                })
            except (AdaptationError, ValidationError) as e:
                results["failed"].append({
                    "legacy_id": user.user_id,
                    "error": str(e)
                })
                if not continue_on_error:
                    break
        
        return results
    
    def _validate_email(self, email: str) -> bool:
        """Validate email format."""
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(pattern, email))
    
    def get_conflicts(self) -> List[Dict[str, Any]]:
        """Get list of migration conflicts."""
        return self.conflicts.copy()
    
    def generate_migration_report(self) -> Dict[str, Any]:
        """Generate comprehensive migration report."""
        return {
            "total_migrated": len(self.migrated_users),
            "total_conflicts": len(self.conflicts),
            "conflicts": self.conflicts,
            "unique_domains": self._extract_domains(),
            "role_distribution": self._role_distribution()
        }
    
    def _extract_domains(self) -> Set[str]:
        """Extract unique email domains."""
        domains = set()
        for user in self.migrated_users.values():
            if "@" in user.email:
                domains.add(user.email.split("@")[1])
        return domains
    
    def _role_distribution(self) -> Dict[str, int]:
        """Get distribution of user roles."""
        distribution = {}
        for user in self.migrated_users.values():
            distribution[user.role] = distribution.get(user.role, 0) + 1
        return distribution
