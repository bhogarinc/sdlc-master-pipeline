"""
Anti-Corruption Layers for Legacy System Integration

Prevents legacy domain concepts from leaking into the modern system.
Provides clean boundaries between legacy and modern domains.
"""

from typing import Dict, Any, Optional, List, Set, Callable
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class DomainContext:
    """Context for domain isolation."""
    domain: str
    operation: str
    timestamp: datetime
    metadata: Dict[str, Any]


class DomainBoundary(ABC):
    """
    Abstract base for domain boundaries.
    
    Ensures clean separation between legacy and modern domains.
    """
    
    def __init__(self, name: str):
        self.name = name
        self._validators: List[Callable] = []
        self._transformers: List[Callable] = []
        self._violation_count = 0
    
    def add_validator(self, validator: Callable):
        """Add a validation rule for domain data."""
        self._validators.append(validator)
    
    def add_transformer(self, transformer: Callable):
        """Add a data transformer."""
        self._transformers.append(transformer)
    
    def validate(self, data: Dict[str, Any], context: DomainContext) -> bool:
        """
        Validate data at domain boundary.
        
        Args:
            data: Data crossing boundary
            context: Operation context
            
        Returns:
            True if valid
        """
        for validator in self._validators:
            if not validator(data, context):
                self._violation_count += 1
                logger.warning(
                    f"Domain boundary violation in {self.name}: "
                    f"{context.operation}"
                )
                return False
        return True
    
    def transform(
        self,
        data: Dict[str, Any],
        direction: str,
        context: DomainContext
    ) -> Dict[str, Any]:
        """
        Transform data crossing domain boundary.
        
        Args:
            data: Data to transform
            direction: "to_modern" or "to_legacy"
            context: Operation context
            
        Returns:
            Transformed data
        """
        result = data
        for transformer in self._transformers:
            result = transformer(result, direction, context)
        return result
    
    def get_violation_count(self) -> int:
        """Get number of boundary violations."""
        return self._violation_count


class TaskDomainACL(DomainBoundary):
    """
    Anti-Corruption Layer for Task domain.
    
    Prevents legacy task concepts from leaking into modern system.
    """
    
    # Legacy concepts that should not leak
    LEGACY_CONCEPTS = {
        "task_codes",
        "legacy_workflow_state",
        "old_priority_scale",
        "department_codes",
        "legacy_assignee_format"
    }
    
    # Modern concepts that legacy system shouldn't see
    MODERN_CONCEPTS = {
        "board_position",
        "sprint_id",
        "story_points",
        "epic_id",
        "automation_rules"
    }
    
    def __init__(self):
        super().__init__("TaskDomain")
        
        # Add validators
        self.add_validator(self._validate_no_legacy_concepts)
        self.add_validator(self._validate_required_modern_fields)
        
        # Add transformers
        self.add_transformer(self._sanitize_legacy_data)
        self.add_transformer(self._enrich_modern_data)
    
    def _validate_no_legacy_concepts(
        self,
        data: Dict[str, Any],
        context: DomainContext
    ) -> bool:
        """Ensure no legacy concepts leak into modern system."""
        if context.operation == "to_modern":
            data_keys = set(data.keys())
            violations = data_keys & self.LEGACY_CONCEPTS
            if violations:
                logger.error(f"Legacy concepts detected: {violations}")
                return False
        return True
    
    def _validate_required_modern_fields(
        self,
        data: Dict[str, Any],
        context: DomainContext
    ) -> bool:
        """Validate required fields for modern system."""
        if context.operation == "to_modern":
            required = {"id", "title", "status"}
            if not required.issubset(set(data.keys())):
                missing = required - set(data.keys())
                logger.error(f"Missing required fields: {missing}")
                return False
        return True
    
    def _sanitize_legacy_data(
        self,
        data: Dict[str, Any],
        direction: str,
        context: DomainContext
    ) -> Dict[str, Any]:
        """Remove legacy-specific fields."""
        if direction == "to_modern":
            return {k: v for k, v in data.items() 
                   if k not in self.LEGACY_CONCEPTS}
        return data
    
    def _enrich_modern_data(
        self,
        data: Dict[str, Any],
        direction: str,
        context: DomainContext
    ) -> Dict[str, Any]:
        """Add modern-specific enrichments."""
        if direction == "to_modern":
            data["domain_context"] = {
                "migrated_at": datetime.utcnow().isoformat(),
                "source": "legacy",
                "acl_version": "1.0"
            }
        return data


class UserDomainACL(DomainBoundary):
    """
    Anti-Corruption Layer for User domain.
    
    Ensures user data boundary is maintained.
    """
    
    LEGACY_CONCEPTS = {
        "legacy_role_codes",
        "old_permission_format",
        "department_id_legacy",
        "employee_number_old"
    }
    
    def __init__(self):
        super().__init__("UserDomain")
        
        self.add_validator(self._validate_email_format)
        self.add_validator(self._validate_role_mapping)
        self.add_transformer(self._sanitize_user_data)
    
    def _validate_email_format(
        self,
        data: Dict[str, Any],
        context: DomainContext
    ) -> bool:
        """Validate email format."""
        if "email" in data:
            email = data["email"]
            if "@" not in email or "." not in email.split("@")[-1]:
                logger.error(f"Invalid email format: {email}")
                return False
        return True
    
    def _validate_role_mapping(
        self,
        data: Dict[str, Any],
        context: DomainContext
    ) -> bool:
        """Validate role mapping is valid."""
        valid_roles = {"admin", "team_lead", "member", "viewer"}
        if "role" in data and data["role"] not in valid_roles:
            logger.error(f"Invalid role: {data['role']}")
            return False
        return True
    
    def _sanitize_user_data(
        self,
        data: Dict[str, Any],
        direction: str,
        context: DomainContext
    ) -> Dict[str, Any]:
        """Sanitize user data at boundary."""
        if direction == "to_modern":
            # Remove legacy concepts
            data = {k: v for k, v in data.items() 
                   if k not in self.LEGACY_CONCEPTS}
            
            # Normalize email
            if "email" in data:
                data["email"] = data["email"].lower().strip()
        
        return data


class NotificationACL(DomainBoundary):
    """
    Anti-Corruption Layer for Notification domain.
    """
    
    LEGACY_CONCEPTS = {
        "legacy_channel_codes",
        "old_template_format",
        "notification_batch_id"
    }
    
    def __init__(self):
        super().__init__("NotificationDomain")
        
        self.add_validator(self._validate_notification_structure)
        self.add_transformer(self._transform_notification_data)
    
    def _validate_notification_structure(
        self,
        data: Dict[str, Any],
        context: DomainContext
    ) -> bool:
        """Validate notification has required structure."""
        if context.operation == "to_modern":
            required = {"user_id", "type", "title"}
            if not required.issubset(set(data.keys())):
                return False
        return True
    
    def _transform_notification_data(
        self,
        data: Dict[str, Any],
        direction: str,
        context: DomainContext
    ) -> Dict[str, Any]:
        """Transform notification data."""
        if direction == "to_modern":
            # Remove legacy fields
            data = {k: v for k, v in data.items() 
                   if k not in self.LEGACY_CONCEPTS}
            
            # Normalize type
            if "type" in data:
                type_mapping = {
                    "E": "email",
                    "S": "sms",
                    "P": "push",
                    "I": "in_app"
                }
                data["type"] = type_mapping.get(data["type"], data["type"])
        
        return data


class LegacyContextIsolator:
    """
    Ensures legacy context doesn't leak into modern system.
    
    Provides complete isolation of legacy execution context.
    """
    
    def __init__(self):
        self._legacy_contexts: Dict[str, Dict[str, Any]] = {}
        self._isolation_log: List[Dict[str, Any]] = []
    
    def create_isolated_context(
        self,
        context_id: str,
        legacy_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create an isolated context for legacy operations.
        
        Args:
            context_id: Unique context identifier
            legacy_data: Legacy context data
            
        Returns:
            Isolated context metadata
        """
        isolated_context = {
            "context_id": context_id,
            "created_at": datetime.utcnow().isoformat(),
            "legacy_data": legacy_data,
            "isolation_level": "strict"
        }
        
        self._legacy_contexts[context_id] = isolated_context
        
        self._isolation_log.append({
            "action": "create",
            "context_id": context_id,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        return isolated_context
    
    def execute_in_isolation(
        self,
        context_id: str,
        operation: Callable,
        *args,
        **kwargs
    ) -> Any:
        """
        Execute an operation in isolated legacy context.
        
        Args:
            context_id: Isolation context ID
            operation: Function to execute
            *args: Positional arguments
            **kwargs: Keyword arguments
            
        Returns:
            Operation result
        """
        context = self._legacy_contexts.get(context_id)
        if not context:
            raise ValueError(f"Isolation context not found: {context_id}")
        
        try:
            # Execute with isolation
            result = operation(*args, **kwargs)
            
            # Sanitize result to prevent leakage
            sanitized_result = self._sanitize_result(result)
            
            self._isolation_log.append({
                "action": "execute",
                "context_id": context_id,
                "success": True,
                "timestamp": datetime.utcnow().isoformat()
            })
            
            return sanitized_result
            
        except Exception as e:
            self._isolation_log.append({
                "action": "execute",
                "context_id": context_id,
                "success": False,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            })
            raise
    
    def destroy_context(self, context_id: str) -> bool:
        """Destroy an isolated context."""
        if context_id in self._legacy_contexts:
            del self._legacy_contexts[context_id]
            
            self._isolation_log.append({
                "action": "destroy",
                "context_id": context_id,
                "timestamp": datetime.utcnow().isoformat()
            })
            
            return True
        return False
    
    def _sanitize_result(self, result: Any) -> Any:
        """Sanitize operation result to prevent legacy leakage."""
        if isinstance(result, dict):
            # Remove legacy-specific keys
            legacy_keys = {
                "legacy_id", "old_format", "deprecated_field",
                "internal_legacy_ref"
            }
            return {k: v for k, v in result.items() if k not in legacy_keys}
        return result
    
    def get_isolation_report(self) -> Dict[str, Any]:
        """Get report of isolation activities."""
        return {
            "active_contexts": len(self._legacy_contexts),
            "total_operations": len(self._isolation_log),
            "context_ids": list(self._legacy_contexts.keys()),
            "recent_activity": self._isolation_log[-10:]  # Last 10 entries
        }


class ACLManager:
    """
    Central manager for all Anti-Corruption Layers.
    
    Coordinates ACLs across all domains.
    """
    
    def __init__(self):
        self._acls: Dict[str, DomainBoundary] = {}
        self._isolator = LegacyContextIsolator()
    
    def register_acl(self, domain: str, acl: DomainBoundary):
        """Register an ACL for a domain."""
        self._acls[domain] = acl
    
    def get_acl(self, domain: str) -> Optional[DomainBoundary]:
        """Get ACL for a domain."""
        return self._acls.get(domain)
    
    def validate_crossing(
        self,
        domain: str,
        data: Dict[str, Any],
        operation: str
    ) -> bool:
        """
        Validate data crossing domain boundary.
        
        Args:
            domain: Domain name
            data: Data to validate
            operation: Operation type
            
        Returns:
            True if validation passes
        """
        acl = self._acls.get(domain)
        if not acl:
            return True
        
        context = DomainContext(
            domain=domain,
            operation=operation,
            timestamp=datetime.utcnow(),
            metadata={}
        )
        
        return acl.validate(data, context)
    
    def transform_crossing(
        self,
        domain: str,
        data: Dict[str, Any],
        direction: str
    ) -> Dict[str, Any]:
        """
        Transform data crossing domain boundary.
        
        Args:
            domain: Domain name
            data: Data to transform
            direction: "to_modern" or "to_legacy"
            
        Returns:
            Transformed data
        """
        acl = self._acls.get(domain)
        if not acl:
            return data
        
        context = DomainContext(
            domain=domain,
            operation=direction,
            timestamp=datetime.utcnow(),
            metadata={}
        )
        
        return acl.transform(data, direction, context)
    
    def get_violations_report(self) -> Dict[str, int]:
        """Get violations report for all ACLs."""
        return {
            domain: acl.get_violation_count()
            for domain, acl in self._acls.items()
        }


# Initialize default ACLs
default_acl_manager = ACLManager()
default_acl_manager.register_acl("task", TaskDomainACL())
default_acl_manager.register_acl("user", UserDomainACL())
default_acl_manager.register_acl("notification", NotificationACL())
