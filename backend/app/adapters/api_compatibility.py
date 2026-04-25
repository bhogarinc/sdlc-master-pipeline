"""
API Compatibility Layer for Legacy API Support

Provides backward-compatible API endpoints that serve both old and new formats.
Enables gradual migration of API consumers.
"""

from typing import Dict, Any, Optional, List, Callable, Union
from enum import Enum
from datetime import datetime
import json
import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class APIVersion(Enum):
    """Supported API versions."""
    LEGACY_V1 = "v1"
    LEGACY_V2 = "v2"
    MODERN_V1 = "2024-01"
    MODERN_V2 = "2024-06"


class ResponseFormat(Enum):
    """Response format types."""
    LEGACY = "legacy"
    MODERN = "modern"
    COMPATIBILITY = "compatibility"  # Both formats


class VersionedAPIRouter:
    """
    Router for versioned API endpoints.
    
    Routes requests to appropriate handlers based on version.
    """
    
    def __init__(self):
        self._routes: Dict[str, Dict[str, Callable]] = {}
        self._default_version = APIVersion.MODERN_V1
    
    def register_route(
        self,
        path: str,
        version: APIVersion,
        handler: Callable,
        methods: Optional[List[str]] = None
    ):
        """
        Register a route for a specific API version.
        
        Args:
            path: Route path
            version: API version
            handler: Route handler
            methods: HTTP methods
        """
        if path not in self._routes:
            self._routes[path] = {}
        
        self._routes[path][version] = {
            "handler": handler,
            "methods": methods or ["GET"]
        }
    
    def get_handler(
        self,
        path: str,
        version: Optional[APIVersion] = None
    ) -> Optional[Callable]:
        """
        Get handler for a route and version.
        
        Args:
            path: Route path
            version: Requested API version
            
        Returns:
            Handler function or None
        """
        route_versions = self._routes.get(path)
        if not route_versions:
            return None
        
        # Try requested version
        if version and version in route_versions:
            return route_versions[version]["handler"]
        
        # Fall back to default
        if self._default_version in route_versions:
            return route_versions[self._default_version]["handler"]
        
        # Return any available version
        if route_versions:
            return list(route_versions.values())[0]["handler"]
        
        return None
    
    def get_supported_versions(self, path: str) -> List[APIVersion]:
        """Get supported versions for a route."""
        route_versions = self._routes.get(path, {})
        return list(route_versions.keys())


class ResponseTransformer:
    """
    Transforms responses between legacy and modern formats.
    
    Supports multiple output formats based on client requirements.
    """
    
    def __init__(self):
        self._transformers: Dict[str, Callable] = {}
        self._field_mappings: Dict[str, Dict[str, str]] = {}
    
    def register_transformer(
        self,
        entity_type: str,
        transformer: Callable
    ):
        """Register a custom transformer for an entity type."""
        self._transformers[entity_type] = transformer
    
    def register_field_mapping(
        self,
        entity_type: str,
        legacy_field: str,
        modern_field: str
    ):
        """Register field name mapping."""
        if entity_type not in self._field_mappings:
            self._field_mappings[entity_type] = {}
        self._field_mappings[entity_type][legacy_field] = modern_field
    
    def transform(
        self,
        data: Dict[str, Any],
        entity_type: str,
        target_format: ResponseFormat
    ) -> Dict[str, Any]:
        """
        Transform response to target format.
        
        Args:
            data: Response data
            entity_type: Type of entity
            target_format: Target response format
            
        Returns:
            Transformed response
        """
        if target_format == ResponseFormat.LEGACY:
            return self._to_legacy(data, entity_type)
        elif target_format == ResponseFormat.MODERN:
            return self._to_modern(data, entity_type)
        elif target_format == ResponseFormat.COMPATIBILITY:
            return self._to_compatibility(data, entity_type)
        
        return data
    
    def _to_legacy(self, data: Dict[str, Any], entity_type: str) -> Dict[str, Any]:
        """Transform to legacy format."""
        # Apply custom transformer if available
        if entity_type in self._transformers:
            return self._transformers[entity_type](data, "legacy")
        
        # Apply field mappings
        mappings = self._field_mappings.get(entity_type, {})
        reverse_mappings = {v: k for k, v in mappings.items()}
        
        return {reverse_mappings.get(k, k): v for k, v in data.items()}
    
    def _to_modern(self, data: Dict[str, Any], entity_type: str) -> Dict[str, Any]:
        """Transform to modern format."""
        # Apply custom transformer if available
        if entity_type in self._transformers:
            return self._transformers[entity_type](data, "modern")
        
        # Apply field mappings
        mappings = self._field_mappings.get(entity_type, {})
        
        return {mappings.get(k, k): v for k, v in data.items()}
    
    def _to_compatibility(self, data: Dict[str, Any], entity_type: str) -> Dict[str, Any]:
        """Transform to compatibility format (both legacy and modern)."""
        modern = self._to_modern(data, entity_type)
        legacy = self._to_legacy(data, entity_type)
        
        return {
            "data": modern,
            "legacy": legacy,
            "meta": {
                "format": "compatibility",
                "generated_at": datetime.utcnow().isoformat()
            }
        }


class LegacyAPICompatibilityLayer:
    """
    Compatibility layer for legacy API endpoints.
    
    Provides:
    - Version negotiation
    - Response format transformation
    - Deprecation warnings
    - Migration hints
    """
    
    def __init__(
        self,
        router: Optional[VersionedAPIRouter] = None,
        transformer: Optional[ResponseTransformer] = None
    ):
        self.router = router or VersionedAPIRouter()
        self.transformer = transformer or ResponseTransformer()
        self._deprecation_notices: Dict[str, Dict[str, Any]] = {}
        self._sunset_dates: Dict[str, datetime] = {}
    
    def deprecate_endpoint(
        self,
        path: str,
        version: APIVersion,
        sunset_date: datetime,
        migration_guide: Optional[str] = None
    ):
        """
        Mark an endpoint as deprecated.
        
        Args:
            path: Endpoint path
            version: API version
            sunset_date: When endpoint will be removed
            migration_guide: URL to migration documentation
        """
        key = f"{path}:{version.value}"
        self._deprecation_notices[key] = {
            "sunset_date": sunset_date.isoformat(),
            "migration_guide": migration_guide,
            "deprecated_at": datetime.utcnow().isoformat()
        }
        self._sunset_dates[key] = sunset_date
    
    def is_deprecated(self, path: str, version: APIVersion) -> bool:
        """Check if an endpoint is deprecated."""
        key = f"{path}:{version.value}"
        return key in self._deprecation_notices
    
    def get_deprecation_headers(
        self,
        path: str,
        version: APIVersion
    ) -> Dict[str, str]:
        """Get deprecation HTTP headers."""
        key = f"{path}:{version.value}"
        notice = self._deprecation_notices.get(key)
        
        if not notice:
            return {}
        
        headers = {
            "Deprecation": f"sunset=\"{notice['sunset_date']}\"",
            "Sunset": notice["sunset_date"]
        }
        
        if notice.get("migration_guide"):
            headers["Link"] = f'<{notice["migration_guide"]}>; rel="migration"'
        
        return headers
    
    def handle_request(
        self,
        path: str,
        version: Optional[APIVersion] = None,
        requested_format: Optional[ResponseFormat] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Handle an API request with compatibility layer.
        
        Args:
            path: API endpoint path
            version: Requested API version
            requested_format: Requested response format
            **kwargs: Additional request parameters
            
        Returns:
            Response with compatibility transformations
        """
        # Get appropriate handler
        handler = self.router.get_handler(path, version)
        if not handler:
            raise ValueError(f"No handler found for {path} version {version}")
        
        # Execute handler
        result = handler(**kwargs)
        
        # Determine response format
        if not requested_format:
            requested_format = (
                ResponseFormat.LEGACY 
                if version in (APIVersion.LEGACY_V1, APIVersion.LEGACY_V2)
                else ResponseFormat.MODERN
            )
        
        # Transform response
        entity_type = kwargs.get("entity_type", "default")
        transformed = self.transformer.transform(
            result,
            entity_type,
            requested_format
        )
        
        # Build response
        response = {
            "data": transformed,
            "meta": {
                "api_version": (version or self.router._default_version).value,
                "response_format": requested_format.value,
                "timestamp": datetime.utcnow().isoformat()
            }
        }
        
        # Add deprecation info if applicable
        if version and self.is_deprecated(path, version):
            response["meta"]["deprecated"] = True
            response["meta"]["deprecation_info"] = self._deprecation_notices.get(
                f"{path}:{version.value}"
            )
        
        return response
    
    def get_version_info(self) -> Dict[str, Any]:
        """Get information about API versions."""
        return {
            "versions": [v.value for v in APIVersion],
            "default": self.router._default_version.value,
            "deprecated_endpoints": [
                {
                    "endpoint": key.split(":")[0],
                    "version": key.split(":")[1],
                    **info
                }
                for key, info in self._deprecation_notices.items()
            ],
            "formats": [f.value for f in ResponseFormat]
        }


class ContentNegotiator:
    """
    Handles content negotiation for API responses.
    
    Determines best response format based on client preferences.
    """
    
    def __init__(self):
        self._format_parsers: Dict[str, Callable] = {
            "application/json": self._parse_json,
            "application/legacy+json": self._parse_legacy_json,
            "application/vnd.api+json": self._parse_json_api
        }
    
    def negotiate_format(
        self,
        accept_header: Optional[str],
        query_param: Optional[str] = None
    ) -> ResponseFormat:
        """
        Negotiate response format from request.
        
        Args:
            accept_header: HTTP Accept header
            query_param: Format query parameter
            
        Returns:
            Negotiated response format
        """
        # Query parameter takes precedence
        if query_param:
            format_map = {
                "legacy": ResponseFormat.LEGACY,
                "modern": ResponseFormat.MODERN,
                "compat": ResponseFormat.COMPATIBILITY
            }
            return format_map.get(query_param.lower(), ResponseFormat.MODERN)
        
        # Parse Accept header
        if accept_header:
            if "legacy" in accept_header.lower():
                return ResponseFormat.LEGACY
            elif "compat" in accept_header.lower():
                return ResponseFormat.COMPATIBILITY
        
        return ResponseFormat.MODERN
    
    def parse_request_body(
        self,
        body: str,
        content_type: str
    ) -> Dict[str, Any]:
        """Parse request body based on content type."""
        parser = self._format_parsers.get(content_type, self._parse_json)
        return parser(body)
    
    def _parse_json(self, body: str) -> Dict[str, Any]:
        """Parse standard JSON."""
        return json.loads(body)
    
    def _parse_legacy_json(self, body: str) -> Dict[str, Any]:
        """Parse legacy JSON format."""
        data = json.loads(body)
        # Transform legacy field names to modern
        return self._transform_legacy_fields(data)
    
    def _parse_json_api(self, body: str) -> Dict[str, Any]:
        """Parse JSON:API format."""
        data = json.loads(body)
        # Extract data from JSON:API structure
        if "data" in data:
            return data["data"]
        return data
    
    def _transform_legacy_fields(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Transform legacy field names to modern."""
        field_map = {
            "task_id": "id",
            "user_id": "id",
            "desc": "description",
            "created_date": "created_at"
        }
        
        return {field_map.get(k, k): v for k, v in data.items()}


# Example usage helpers
def create_compatibility_layer() -> LegacyAPICompatibilityLayer:
    """Create a pre-configured compatibility layer."""
    router = VersionedAPIRouter()
    transformer = ResponseTransformer()
    
    # Register common field mappings
    transformer.register_field_mapping("task", "task_id", "id")
    transformer.register_field_mapping("task", "desc", "description")
    transformer.register_field_mapping("user", "user_id", "id")
    transformer.register_field_mapping("user", "phone", "phone_number")
    
    return LegacyAPICompatibilityLayer(router, transformer)
