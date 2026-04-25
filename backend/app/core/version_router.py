"""
Version Router for Multi-Version Runtime Compatibility

This module implements version-aware request routing, allowing simultaneous
operation of multiple API versions with seamless migration paths.
"""

import logging
import re
from typing import Any, Callable, Dict, List, Optional, Type, Union, Awaitable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import wraps

from fastapi import Request, Response, HTTPException, Depends
from fastapi.routing import APIRoute
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.core.feature_flags import (
    feature_flag_service,
    is_enabled,
    create_context,
    FlagEvaluationResult
)
from app.core.metrics import (
    VERSION_ROUTING_DECISIONS,
    VERSION_INCOMPATIBLE_REQUESTS,
    MIGRATION_PROGRESS
)

logger = logging.getLogger(__name__)


class VersionPolicy(str, Enum):
    """Version routing policies."""
    STRICT = "strict"           # Only exact version matches
    LATEST = "latest"           # Route to latest if exact not available
    COMPATIBLE = "compatible"   # Route to nearest compatible version
    DEPRECATED = "deprecated"   # Version is deprecated, warn but allow
    SUNSET = "sunset"          # Version is being removed, error


class RouteStrategy(str, Enum):
    """Strategies for version routing."""
    HEADER = "header"           # X-API-Version header
    PATH = "path"              # /v1/, /v2/ in URL path
    QUERY = "query"            # ?version=1 query param
    CONTENT_TYPE = "content_type"  # application/vnd.api.v1+json
    DEFAULT = "default"        # Use system default


@dataclass
class VersionInfo:
    """Information about an API version."""
    version: str
    release_date: datetime
    sunset_date: Optional[datetime] = None
    policy: VersionPolicy = VersionPolicy.COMPATIBLE
    breaking_changes: List[str] = field(default_factory=list)
    migrations_required: List[str] = field(default_factory=list)
    feature_flags: List[str] = field(default_factory=list)
    compatible_versions: List[str] = field(default_factory=list)
    deprecated_endpoints: List[str] = field(default_factory=list)


@dataclass
class RouteMapping:
    """Mapping between API versions for a specific endpoint."""
    endpoint: str
    version_mappings: Dict[str, str] = field(default_factory=dict)
    transformers: Dict[str, Callable] = field(default_factory=dict)


@dataclass
class RoutingDecision:
    """Result of a version routing decision."""
    requested_version: str
    routed_version: str
    strategy: RouteStrategy
    policy: VersionPolicy
    reason: str
    warnings: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class VersionRegistry:
    """Registry of all API versions and their configurations."""
    
    # Version definitions
    VERSIONS: Dict[str, VersionInfo] = {
        "1.0": VersionInfo(
            version="1.0",
            release_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            policy=VersionPolicy.COMPATIBLE,
            compatible_versions=["1.1", "1.2"]
        ),
        "1.1": VersionInfo(
            version="1.1",
            release_date=datetime(2024, 3, 1, tzinfo=timezone.utc),
            policy=VersionPolicy.COMPATIBLE,
            compatible_versions=["1.0", "1.2"],
            migrations_required=["task_priority_enum"]
        ),
        "1.2": VersionInfo(
            version="1.2",
            release_date=datetime(2024, 6, 1, tzinfo=timezone.utc),
            policy=VersionPolicy.LATEST,
            compatible_versions=["1.1", "1.0"],
            feature_flags=["new_dashboard", "realtime_collaboration"]
        ),
        "2.0": VersionInfo(
            version="2.0",
            release_date=datetime(2024, 9, 1, tzinfo=timezone.utc),
            sunset_date=datetime(2025, 9, 1, tzinfo=timezone.utc),
            policy=VersionPolicy.LATEST,
            breaking_changes=[
                "Task.status changed from string to enum",
                "Removed deprecated /tasks/bulk endpoint",
                "User.profile now requires organization_id"
            ],
            feature_flags=["new_dashboard", "realtime_collaboration", "ai_task_suggestions"]
        ),
    }
    
    # Default version for requests without version specification
    DEFAULT_VERSION = "1.2"
    
    # Minimum supported version
    MINIMUM_VERSION = "1.0"
    
    # Endpoint-specific version mappings
    ENDPOINT_MAPPINGS: Dict[str, RouteMapping] = {}
    
    @classmethod
    def get_version_info(cls, version: str) -> Optional[VersionInfo]:
        """Get information about a specific version."""
        return cls.VERSIONS.get(version)
    
    @classmethod
    def is_supported(cls, version: str) -> bool:
        """Check if a version is currently supported."""
        info = cls.get_version_info(version)
        if not info:
            return False
        
        if info.policy == VersionPolicy.SUNSET:
            if info.sunset_date and datetime.now(timezone.utc) > info.sunset_date:
                return False
        
        return True
    
    @classmethod
    def get_compatible_versions(cls, version: str) -> List[str]:
        """Get list of versions compatible with the given version."""
        info = cls.get_version_info(version)
        if info:
            return [version] + info.compatible_versions
        return [version]
    
    @classmethod
    def register_endpoint_mapping(
        cls,
        endpoint: str,
        version_mappings: Dict[str, str],
        transformers: Optional[Dict[str, Callable]] = None
    ):
        """Register version mappings for a specific endpoint."""
        cls.ENDPOINT_MAPPINGS[endpoint] = RouteMapping(
            endpoint=endpoint,
            version_mappings=version_mappings,
            transformers=transformers or {}
        )
    
    @classmethod
    def get_endpoint_mapping(cls, endpoint: str) -> Optional[RouteMapping]:
        """Get version mapping for an endpoint."""
        return cls.ENDPOINT_MAPPINGS.get(endpoint)


class VersionRouter:
    """Routes requests to appropriate API version handlers."""
    
    def __init__(self):
        self._handlers: Dict[str, Dict[str, Callable]] = {}
        self._transformers: Dict[str, Dict[str, Callable]] = {}
        self._middlewares: List[Callable] = []
    
    def register_handler(
        self,
        endpoint: str,
        version: str,
        handler: Callable,
        request_transformer: Optional[Callable] = None,
        response_transformer: Optional[Callable] = None
    ):
        """Register a handler for a specific endpoint and version."""
        if endpoint not in self._handlers:
            self._handlers[endpoint] = {}
            self._transformers[endpoint] = {}
        
        self._handlers[endpoint][version] = handler
        
        if request_transformer or response_transformer:
            self._transformers[endpoint][version] = {
                "request": request_transformer,
                "response": response_transformer
            }
    
    async def route(
        self,
        request: Request,
        endpoint: str,
        **kwargs
    ) -> Any:
        """
        Route a request to the appropriate version handler.
        
        Args:
            request: The incoming request
            endpoint: The endpoint identifier
            **kwargs: Additional arguments to pass to the handler
            
        Returns:
            Response from the routed handler
        """
        # Determine requested version
        requested_version = self._extract_version(request)
        
        # Make routing decision
        decision = await self._make_routing_decision(
            request, endpoint, requested_version
        )
        
        # Log routing decision
        VERSION_ROUTING_DECISIONS.labels(
            requested_version=decision.requested_version,
            routed_version=decision.routed_version,
            strategy=decision.strategy.value
        ).inc()
        
        logger.info(
            f"Version routing: {endpoint} - "
            f"requested={decision.requested_version}, "
            f"routed={decision.routed_version}, "
            f"reason={decision.reason}"
        )
        
        # Get handler for routed version
        handler = self._get_handler(endpoint, decision.routed_version)
        if not handler:
            VERSION_INCOMPATIBLE_REQUESTS.labels(
                version=decision.requested_version,
                reason="no_handler"
            ).inc()
            raise HTTPException(
                status_code=404,
                detail=f"No handler found for endpoint '{endpoint}' version '{decision.routed_version}'"
            )
        
        # Apply request transformation if needed
        if decision.requested_version != decision.routed_version:
            transformer = self._get_transformer(
                endpoint,
                decision.requested_version,
                decision.routed_version,
                "request"
            )
            if transformer:
                request = await transformer(request)
        
        # Execute handler
        response = await handler(request, **kwargs)
        
        # Apply response transformation if needed
        if decision.requested_version != decision.routed_version:
            transformer = self._get_transformer(
                endpoint,
                decision.routed_version,
                decision.requested_version,
                "response"
            )
            if transformer:
                response = await transformer(response)
        
        # Add version headers
        if isinstance(response, Response):
            response.headers["X-API-Version"] = decision.routed_version
            if decision.warnings:
                response.headers["X-API-Warnings"] = "; ".join(decision.warnings)
        
        return response
    
    def _extract_version(self, request: Request) -> str:
        """Extract requested API version from request."""
        # Check header first
        version = request.headers.get("X-API-Version")
        if version:
            return version
        
        # Check query parameter
        version = request.query_params.get("api-version")
        if version:
            return version
        
        # Check Content-Type header for versioned media type
        content_type = request.headers.get("Content-Type", "")
        match = re.search(r'vnd\.api\.(v?\d+\.?\d*)\+json', content_type)
        if match:
            return match.group(1)
        
        # Check Accept header
        accept = request.headers.get("Accept", "")
        match = re.search(r'vnd\.api\.(v?\d+\.?\d*)\+json', accept)
        if match:
            return match.group(1)
        
        # Extract from path
        path = request.url.path
        match = re.search(r'/v(\d+\.?\d*)/', path)
        if match:
            return match.group(1)
        
        # Return default
        return VersionRegistry.DEFAULT_VERSION
    
    async def _make_routing_decision(
        self,
        request: Request,
        endpoint: str,
        requested_version: str
    ) -> RoutingDecision:
        """Determine which version to route to based on policy."""
        
        version_info = VersionRegistry.get_version_info(requested_version)
        
        # Check if version is supported
        if not VersionRegistry.is_supported(requested_version):
            # Try to route to compatible version
            compatible = VersionRegistry.get_compatible_versions(
                VersionRegistry.DEFAULT_VERSION
            )
            
            return RoutingDecision(
                requested_version=requested_version,
                routed_version=compatible[0],
                strategy=RouteStrategy.DEFAULT,
                policy=VersionPolicy.LATEST,
                reason=f"Version {requested_version} is not supported, using compatible version",
                warnings=[f"API version {requested_version} is not supported"]
            )
        
        # Check endpoint-specific mapping
        mapping = VersionRegistry.get_endpoint_mapping(endpoint)
        if mapping and requested_version in mapping.version_mappings:
            mapped_version = mapping.version_mappings[requested_version]
            return RoutingDecision(
                requested_version=requested_version,
                routed_version=mapped_version,
                strategy=RouteStrategy.PATH,
                policy=version_info.policy if version_info else VersionPolicy.COMPATIBLE,
                reason="Endpoint-specific version mapping"
            )
        
        # Check if exact handler exists
        if self._handler_exists(endpoint, requested_version):
            # Check feature flags for this version
            if version_info and version_info.feature_flags:
                context = await self._build_context(request)
                
                all_flags_enabled = True
                for flag_key in version_info.feature_flags:
                    enabled = await is_enabled(flag_key, context)
                    if not enabled:
                        all_flags_enabled = False
                        break
                
                if not all_flags_enabled:
                    # Fall back to compatible version
                    compatible = version_info.compatible_versions
                    for compat_version in compatible:
                        if self._handler_exists(endpoint, compat_version):
                            return RoutingDecision(
                                requested_version=requested_version,
                                routed_version=compat_version,
                                strategy=RouteStrategy.DEFAULT,
                                policy=VersionPolicy.COMPATIBLE,
                                reason="Required feature flags not enabled",
                                warnings=["Some features required for this version are not enabled"]
                            )
            
            return RoutingDecision(
                requested_version=requested_version,
                routed_version=requested_version,
                strategy=RouteStrategy.HEADER,
                policy=version_info.policy if version_info else VersionPolicy.COMPATIBLE,
                reason="Exact version match"
            )
        
        # Try compatible versions
        if version_info:
            for compat_version in version_info.compatible_versions:
                if self._handler_exists(endpoint, compat_version):
                    return RoutingDecision(
                        requested_version=requested_version,
                        routed_version=compat_version,
                        strategy=RouteStrategy.COMPATIBLE,
                        policy=VersionPolicy.COMPATIBLE,
                        reason=f"Routed to compatible version {compat_version}",
                        warnings=[f"Using compatible version {compat_version}"]
                    )
        
        # Fall back to default version
        default = VersionRegistry.DEFAULT_VERSION
        if self._handler_exists(endpoint, default):
            return RoutingDecision(
                requested_version=requested_version,
                routed_version=default,
                strategy=RouteStrategy.DEFAULT,
                policy=VersionPolicy.LATEST,
                reason="Using system default version",
                warnings=[f"Version {requested_version} not available, using default"]
            )
        
        # No suitable version found
        raise HTTPException(
            status_code=400,
            detail=f"No compatible version found for '{requested_version}'"
        )
    
    def _handler_exists(self, endpoint: str, version: str) -> bool:
        """Check if a handler exists for the endpoint and version."""
        return endpoint in self._handlers and version in self._handlers[endpoint]
    
    def _get_handler(self, endpoint: str, version: str) -> Optional[Callable]:
        """Get the handler for an endpoint and version."""
        return self._handlers.get(endpoint, {}).get(version)
    
    def _get_transformer(
        self,
        endpoint: str,
        from_version: str,
        to_version: str,
        direction: str
    ) -> Optional[Callable]:
        """Get transformer for version conversion."""
        # Check for specific version pair transformer
        key = f"{from_version}_to_{to_version}"
        transformers = self._transformers.get(endpoint, {})
        
        if key in transformers:
            return transformers[key].get(direction)
        
        return None
    
    async def _build_context(self, request: Request) -> Dict[str, Any]:
        """Build feature flag context from request."""
        user = getattr(request.state, "user", None)
        
        return create_context(
            user=user,
            request={
                "path": request.url.path,
                "method": request.method,
                "headers": dict(request.headers),
            }
        )


# Global router instance
version_router = VersionRouter()


# Decorator for versioned endpoints

def versioned_endpoint(
    endpoint: str,
    version: str,
    request_transformer: Optional[Callable] = None,
    response_transformer: Optional[Callable] = None
):
    """
    Decorator to register a function as a versioned endpoint handler.
    
    Usage:
        @versioned_endpoint("tasks.create", "2.0")
        async def create_task_v2(request: Request):
            ...
    """
    def decorator(func: Callable):
        version_router.register_handler(
            endpoint=endpoint,
            version=version,
            handler=func,
            request_transformer=request_transformer,
            response_transformer=response_transformer
        )
        return func
    return decorator


# Version middleware

class VersionRoutingMiddleware(BaseHTTPMiddleware):
    """Middleware to handle version routing for all requests."""
    
    async def dispatch(self, request: Request, call_next):
        """Process request with version routing."""
        # Extract version info
        version = self._extract_version(request)
        request.state.api_version = version
        
        # Check if version is deprecated
        version_info = VersionRegistry.get_version_info(version)
        if version_info and version_info.policy == VersionPolicy.DEPRECATED:
            logger.warning(f"Deprecated API version used: {version}")
        
        # Continue processing
        response = await call_next(request)
        
        # Add version headers
        response.headers["X-API-Version"] = getattr(
            request.state, "routed_version", version
        )
        
        # Add deprecation warning if applicable
        if version_info and version_info.sunset_date:
            response.headers["Sunset"] = version_info.sunset_date.isoformat()
        
        return response
    
    def _extract_version(self, request: Request) -> str:
        """Extract API version from request."""
        # Check header
        version = request.headers.get("X-API-Version")
        if version:
            return version
        
        # Check query parameter
        version = request.query_params.get("api-version")
        if version:
            return version
        
        # Check path
        path = request.url.path
        match = re.search(r'/v(\d+\.?\d*)/', path)
        if match:
            return match.group(1)
        
        return VersionRegistry.DEFAULT_VERSION


# Version compatibility utilities

class VersionCompatibilityChecker:
    """Check compatibility between API versions."""
    
    @staticmethod
    def is_compatible(client_version: str, server_version: str) -> bool:
        """Check if client version is compatible with server version."""
        client_info = VersionRegistry.get_version_info(client_version)
        
        if not client_info:
            return False
        
        if server_version == client_version:
            return True
        
        return server_version in client_info.compatible_versions
    
    @staticmethod
    def get_migration_path(from_version: str, to_version: str) -> List[str]:
        """Get the migration path from one version to another."""
        # Simple implementation - in production, this would use a graph
        if from_version == to_version:
            return []
        
        from_info = VersionRegistry.get_version_info(from_version)
        if from_info and to_version in from_info.compatible_versions:
            return [to_version]
        
        # Try via intermediate versions
        if from_info:
            for compat in from_info.compatible_versions:
                compat_info = VersionRegistry.get_version_info(compat)
                if compat_info and to_version in compat_info.compatible_versions:
                    return [compat, to_version]
        
        return []
    
    @staticmethod
    def get_breaking_changes(from_version: str, to_version: str) -> List[str]:
        """Get list of breaking changes between versions."""
        changes = []
        
        # Collect changes from all versions in the path
        current = from_version
        path = VersionCompatibilityChecker.get_migration_path(from_version, to_version)
        
        for next_version in path:
            info = VersionRegistry.get_version_info(next_version)
            if info:
                changes.extend(info.breaking_changes)
            current = next_version
        
        return changes


# Request/Response transformers for common conversions

class VersionTransformers:
    """Standard transformers for version conversions."""
    
    @staticmethod
    async def v1_to_v2_task_status(request: Request) -> Request:
        """Transform v1 task status strings to v2 enums."""
        # This would modify the request body
        # Implementation depends on request structure
        return request
    
    @staticmethod
    async def v2_to_v1_task_status(response: Response) -> Response:
        """Transform v2 task status enums back to v1 strings."""
        # This would modify the response body
        return response
    
    @staticmethod
    async def v1_to_v2_user_profile(request: Request) -> Request:
        """Add organization_id to user profile if missing."""
        return request
    
    @staticmethod
    async def add_deprecation_warning(response: Response, message: str) -> Response:
        """Add deprecation warning header to response."""
        response.headers["Deprecation"] = "true"
        response.headers["Warning"] = f'299 - "{message}"'
        return response


# Initialize version registry with TaskFlow Pro specific mappings

def initialize_version_registry():
    """Initialize version registry with TaskFlow Pro mappings."""
    
    # Register endpoint-specific version mappings
    VersionRegistry.register_endpoint_mapping(
        endpoint="tasks.create",
        version_mappings={
            "1.0": "1.2",  # Route v1.0 to v1.2 with transformation
            "1.1": "1.2",
        }
    )
    
    VersionRegistry.register_endpoint_mapping(
        endpoint="tasks.update",
        version_mappings={
            "1.0": "1.2",
            "1.1": "1.2",
        }
    )
    
    VersionRegistry.register_endpoint_mapping(
        endpoint="users.profile",
        version_mappings={
            "1.0": "2.0",  # Requires organization_id
            "1.1": "2.0",
            "1.2": "2.0",
        }
    )
    
    logger.info("Version registry initialized")


# Dependency for FastAPI

async def get_api_version(request: Request) -> str:
    """Dependency to get API version from request."""
    return getattr(request.state, "api_version", VersionRegistry.DEFAULT_VERSION)


async def require_version(min_version: str):
    """Dependency factory to require minimum API version."""
    async def checker(request: Request):
        version = getattr(request.state, "api_version", VersionRegistry.DEFAULT_VERSION)
        
        # Simple version comparison (assumes semver)
        if version < min_version:
            raise HTTPException(
                status_code=400,
                detail=f"API version {min_version} or higher required"
            )
        return version
    return checker
