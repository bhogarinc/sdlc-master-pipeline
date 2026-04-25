"""
Data Mappers for Legacy-Modern Data Transformation

Provides mappers for transforming data between legacy and modern formats
for various domain entities.
"""

from typing import Dict, Any, Optional, List, TypeVar, Generic
from datetime import datetime
from abc import ABC, abstractmethod
import logging

logger = logging.getLogger(__name__)

T = TypeVar('T')


class DataMapper(ABC, Generic[T]):
    """
    Abstract base class for data mappers.
    
    Mappers transform data between different representations while
    maintaining data integrity.
    """
    
    def __init__(self, strict: bool = False):
        self.strict = strict
        self._field_mappings: Dict[str, str] = {}
        self._transforms: Dict[str, callable] = {}
        self._validators: Dict[str, callable] = {}
    
    @abstractmethod
    def to_modern(self, legacy_data: Dict[str, Any]) -> Dict[str, Any]:
        """Transform legacy data to modern format."""
        pass
    
    @abstractmethod
    def to_legacy(self, modern_data: Dict[str, Any]) -> Dict[str, Any]:
        """Transform modern data to legacy format."""
        pass
    
    def add_field_mapping(self, legacy_field: str, modern_field: str):
        """Add a field name mapping."""
        self._field_mappings[legacy_field] = modern_field
        return self
    
    def add_transform(self, field: str, transform: callable):
        """Add a transformation function for a field."""
        self._transforms[field] = transform
        return self
    
    def add_validator(self, field: str, validator: callable):
        """Add a validation function for a field."""
        self._validators[field] = validator
        return self
    
    def _apply_mapping(self, data: Dict[str, Any], direction: str) -> Dict[str, Any]:
        """Apply field name mappings."""
        result = {}
        
        if direction == "to_modern":
            for legacy_key, value in data.items():
                modern_key = self._field_mappings.get(legacy_key, legacy_key)
                result[modern_key] = value
        else:  # to_legacy
            reverse_mapping = {v: k for k, v in self._field_mappings.items()}
            for modern_key, value in data.items():
                legacy_key = reverse_mapping.get(modern_key, modern_key)
                result[legacy_key] = value
        
        return result
    
    def _apply_transforms(
        self,
        data: Dict[str, Any],
        direction: str
    ) -> Dict[str, Any]:
        """Apply transformation functions."""
        result = data.copy()
        
        for field, transform in self._transforms.items():
            if field in result:
                try:
                    result[field] = transform(result[field], direction)
                except Exception as e:
                    if self.strict:
                        raise ValueError(f"Transform failed for {field}: {e}")
                    logger.warning(f"Transform failed for {field}: {e}")
        
        return result
    
    def _validate(self, data: Dict[str, Any]) -> bool:
        """Validate data using registered validators."""
        for field, validator in self._validators.items():
            if field in data:
                if not validator(data[field]):
                    if self.strict:
                        raise ValueError(f"Validation failed for {field}")
                    logger.warning(f"Validation failed for {field}")
                    return False
        return True


class TaskDataMapper(DataMapper):
    """
    Data mapper for Task entities.
    
    Maps between legacy task fields and modern task schema.
    """
    
    def __init__(self, strict: bool = False):
        super().__init__(strict)
        
        # Field mappings
        self.add_field_mapping("task_id", "id")
        self.add_field_mapping("desc", "description")
        self.add_field_mapping("owner_id", "created_by")
        self.add_field_mapping("assigned_to", "assignee_id")
        self.add_field_mapping("parent_task", "parent_id")
        self.add_field_mapping("created_date", "created_at")
        self.add_field_mapping("completed_date", "completed_at")
        
        # Status transform
        self.add_transform("status", self._transform_status)
        
        # Priority transform
        self.add_transform("priority", self._transform_priority)
        
        # Tags/Labels transform
        self.add_transform("tags", self._transform_tags)
        
        # Date transforms
        self.add_transform("due_date", self._transform_date)
        self.add_transform("created_at", self._transform_date)
        self.add_transform("completed_at", self._transform_date)
    
    def to_modern(self, legacy_data: Dict[str, Any]) -> Dict[str, Any]:
        """Transform legacy task data to modern format."""
        # Apply field mappings
        data = self._apply_mapping(legacy_data, "to_modern")
        
        # Apply transforms
        data = self._apply_transforms(data, "to_modern")
        
        # Validate
        self._validate(data)
        
        # Add metadata
        data["metadata"] = {
            "migrated_at": datetime.utcnow().isoformat(),
            "source": "legacy"
        }
        
        return data
    
    def to_legacy(self, modern_data: Dict[str, Any]) -> Dict[str, Any]:
        """Transform modern task data to legacy format."""
        # Apply field mappings
        data = self._apply_mapping(modern_data, "to_legacy")
        
        # Apply transforms
        data = self._apply_transforms(data, "to_legacy")
        
        # Validate
        self._validate(data)
        
        return data
    
    def _transform_status(self, value: str, direction: str) -> str:
        """Transform status values."""
        status_map = {
            "P": "todo",
            "IP": "in_progress",
            "C": "done",
            "X": "archived",
            "H": "blocked"
        }
        reverse_map = {v: k for k, v in status_map.items()}
        
        if direction == "to_modern":
            return status_map.get(value, "todo")
        return reverse_map.get(value, "P")
    
    def _transform_priority(self, value, direction: str) -> str:
        """Transform priority values."""
        priority_map = {
            1: "low",
            2: "medium",
            3: "high",
            4: "urgent"
        }
        reverse_map = {v: k for k, v in priority_map.items()}
        
        if direction == "to_modern":
            if isinstance(value, int):
                return priority_map.get(value, "medium")
            return value
        
        if isinstance(value, str):
            return reverse_map.get(value, 2)
        return value
    
    def _transform_tags(self, value, direction: str):
        """Transform tags between comma-separated string and list."""
        if direction == "to_modern":
            if isinstance(value, str):
                return [tag.strip() for tag in value.split(",") if tag.strip()]
            return value or []
        
        if isinstance(value, list):
            return ",".join(value)
        return value
    
    def _transform_date(self, value, direction: str):
        """Transform date formats."""
        if direction == "to_modern":
            if isinstance(value, str):
                for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y"]:
                    try:
                        return datetime.strptime(value, fmt)
                    except ValueError:
                        continue
                return None
            return value
        
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        return value


class UserDataMapper(DataMapper):
    """
    Data mapper for User entities.
    
    Maps between legacy user fields and modern user schema.
    """
    
    def __init__(self, strict: bool = False):
        super().__init__(strict)
        
        # Field mappings
        self.add_field_mapping("user_id", "id")
        self.add_field_mapping("first_name", "first_name")
        self.add_field_mapping("last_name", "last_name")
        self.add_field_mapping("phone", "phone_number")
        self.add_field_mapping("created_date", "created_at")
        self.add_field_mapping("last_login", "last_login_at")
        
        # Role transform
        self.add_transform("role", self._transform_role)
        
        # Preferences transform
        self.add_transform("preferences", self._transform_preferences)
    
    def to_modern(self, legacy_data: Dict[str, Any]) -> Dict[str, Any]:
        """Transform legacy user data to modern format."""
        data = self._apply_mapping(legacy_data, "to_modern")
        data = self._apply_transforms(data, "to_modern")
        self._validate(data)
        
        # Add metadata
        data["metadata"] = {
            "migrated_at": datetime.utcnow().isoformat(),
            "source": "legacy",
            "department": legacy_data.get("department"),
            "employee_id": legacy_data.get("employee_id")
        }
        
        data["email_verified"] = True
        
        return data
    
    def to_legacy(self, modern_data: Dict[str, Any]) -> Dict[str, Any]:
        """Transform modern user data to legacy format."""
        data = self._apply_mapping(modern_data, "to_legacy")
        data = self._apply_transforms(data, "to_legacy")
        self._validate(data)
        
        # Extract from metadata
        metadata = modern_data.get("metadata", {})
        data["department"] = metadata.get("department")
        data["employee_id"] = metadata.get("employee_id")
        
        return data
    
    def _transform_role(self, value: str, direction: str) -> str:
        """Transform role values."""
        role_map = {
            "A": "admin",
            "M": "team_lead",
            "U": "member",
            "G": "viewer"
        }
        reverse_map = {
            "super_admin": "A",
            "admin": "A",
            "team_lead": "M",
            "member": "U",
            "viewer": "G"
        }
        
        if direction == "to_modern":
            return role_map.get(value, "member")
        return reverse_map.get(value, "U")
    
    def _transform_preferences(self, value: Dict[str, Any], direction: str) -> Dict[str, Any]:
        """Transform user preferences."""
        pref_map = {
            "email_notifications": "email_enabled",
            "sms_notifications": "sms_enabled",
            "theme": "ui_theme",
            "language": "locale"
        }
        reverse_map = {v: k for k, v in pref_map.items()}
        
        if direction == "to_modern":
            return {pref_map.get(k, k): v for k, v in value.items()}
        return {reverse_map.get(k, k): v for k, v in value.items()}


class NotificationDataMapper(DataMapper):
    """
    Data mapper for Notification entities.
    
    Maps between legacy notification fields and modern notification schema.
    """
    
    def __init__(self, strict: bool = False):
        super().__init__(strict)
        
        self.add_field_mapping("notification_id", "id")
        self.add_field_mapping("recipient_id", "user_id")
        self.add_field_mapping("subject", "title")
        self.add_field_mapping("message", "content")
        self.add_field_mapping("created_date", "created_at")
        self.add_field_mapping("sent_date", "sent_at")
        self.add_field_mapping("read_date", "read_at")
        
        self.add_transform("type", self._transform_type)
        self.add_transform("priority", self._transform_priority)
        self.add_transform("metadata", self._transform_metadata)
    
    def to_modern(self, legacy_data: Dict[str, Any]) -> Dict[str, Any]:
        """Transform legacy notification to modern format."""
        data = self._apply_mapping(legacy_data, "to_modern")
        data = self._apply_transforms(data, "to_modern")
        self._validate(data)
        
        # Build action object
        if legacy_data.get("action_url"):
            data["action"] = {
                "url": legacy_data["action_url"],
                "label": legacy_data.get("action_label", "View")
            }
        
        return data
    
    def to_legacy(self, modern_data: Dict[str, Any]) -> Dict[str, Any]:
        """Transform modern notification to legacy format."""
        data = self._apply_mapping(modern_data, "to_legacy")
        data = self._apply_transforms(data, "to_legacy")
        self._validate(data)
        
        # Extract action fields
        action = modern_data.get("action")
        if action:
            data["action_url"] = action.get("url")
            data["action_label"] = action.get("label")
        
        return data
    
    def _transform_type(self, value: str, direction: str) -> str:
        """Transform notification type."""
        type_map = {
            "E": "email",
            "S": "sms",
            "P": "push",
            "I": "in_app"
        }
        reverse_map = {v: k for k, v in type_map.items()}
        
        if direction == "to_modern":
            return type_map.get(value, "in_app")
        return reverse_map.get(value, "I")
    
    def _transform_priority(self, value, direction: str) -> str:
        """Transform priority values."""
        priority_map = {
            1: "low",
            2: "normal",
            3: "high",
            4: "urgent"
        }
        reverse_map = {v: k for k, v in priority_map.items()}
        
        if direction == "to_modern":
            if isinstance(value, int):
                return priority_map.get(value, "normal")
            return value
        
        if isinstance(value, str):
            return reverse_map.get(value, 2)
        return value
    
    def _transform_metadata(self, value, direction: str):
        """Transform metadata between JSON string and dict."""
        import json
        
        if direction == "to_modern":
            if isinstance(value, str):
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    return {"raw": value}
            return value or {}
        
        if isinstance(value, dict):
            return json.dumps(value)
        return value


class TeamDataMapper(DataMapper):
    """
    Data mapper for Team entities.
    
    Maps between legacy team/project fields and modern team schema.
    """
    
    def __init__(self, strict: bool = False):
        super().__init__(strict)
        
        self.add_field_mapping("project_id", "id")
        self.add_field_mapping("project_name", "name")
        self.add_field_mapping("project_desc", "description")
        self.add_field_mapping("lead_id", "owner_id")
        self.add_field_mapping("member_ids", "member_ids")
        self.add_field_mapping("created_date", "created_at")
    
    def to_modern(self, legacy_data: Dict[str, Any]) -> Dict[str, Any]:
        """Transform legacy team/project to modern format."""
        data = self._apply_mapping(legacy_data, "to_modern")
        data = self._apply_transforms(data, "to_modern")
        self._validate(data)
        
        # Ensure member_ids is a list
        if "member_ids" in data and isinstance(data["member_ids"], str):
            data["member_ids"] = [m.strip() for m in data["member_ids"].split(",")]
        
        data.setdefault("member_ids", [])
        
        return data
    
    def to_legacy(self, modern_data: Dict[str, Any]) -> Dict[str, Any]:
        """Transform modern team to legacy format."""
        data = self._apply_mapping(modern_data, "to_legacy")
        data = self._apply_transforms(data, "to_legacy")
        self._validate(data)
        
        # Convert member_ids to comma-separated string
        if "member_ids" in data and isinstance(data["member_ids"], list):
            data["member_ids"] = ",".join(data["member_ids"])
        
        return data


class MapperRegistry:
    """
    Registry for managing multiple data mappers.
    
    Provides centralized access to all mappers.
    """
    
    _mappers: Dict[str, DataMapper] = {}
    
    @classmethod
    def register(cls, entity_type: str, mapper: DataMapper):
        """Register a mapper for an entity type."""
        cls._mappers[entity_type] = mapper
    
    @classmethod
    def get(cls, entity_type: str) -> Optional[DataMapper]:
        """Get mapper for entity type."""
        return cls._mappers.get(entity_type)
    
    @classmethod
    def to_modern(cls, entity_type: str, legacy_data: Dict[str, Any]) -> Dict[str, Any]:
        """Transform legacy data to modern format using registered mapper."""
        mapper = cls.get(entity_type)
        if not mapper:
            raise ValueError(f"No mapper registered for entity type: {entity_type}")
        return mapper.to_modern(legacy_data)
    
    @classmethod
    def to_legacy(cls, entity_type: str, modern_data: Dict[str, Any]) -> Dict[str, Any]:
        """Transform modern data to legacy format using registered mapper."""
        mapper = cls.get(entity_type)
        if not mapper:
            raise ValueError(f"No mapper registered for entity type: {entity_type}")
        return mapper.to_legacy(modern_data)


# Register default mappers
MapperRegistry.register("task", TaskDataMapper())
MapperRegistry.register("user", UserDataMapper())
MapperRegistry.register("notification", NotificationDataMapper())
MapperRegistry.register("team", TeamDataMapper())
