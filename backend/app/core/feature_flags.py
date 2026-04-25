"""
Feature Flag System for TaskFlow Pro

This module implements a comprehensive feature flag infrastructure supporting:
- Boolean, percentage, user-segment, and time-based flags
- Redis-backed flag storage with local caching
- Flag evaluation context with user, request, and environment data
- WebSocket-based real-time flag updates
"""

import json
import hashlib
import logging
from enum import Enum
from typing import Any, Dict, List, Optional, Callable, Set, Union
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from functools import lru_cache
import asyncio
from contextvars import ContextVar

import redis.asyncio as redis
from pydantic import BaseModel, Field, validator

from app.core.config import settings
from app.core.metrics import FEATURE_FLAG_EVALUATIONS, FEATURE_FLAG_CACHE_HITS

logger = logging.getLogger(__name__)

# Context variable for current request context
flag_context: ContextVar[Optional[Dict[str, Any]]] = ContextVar('flag_context', default=None)


class FlagType(str, Enum):
    """Types of feature flags supported."""
    BOOLEAN = "boolean"           # Simple on/off
    PERCENTAGE = "percentage"     # Percentage-based rollout
    USER_SEGMENT = "user_segment" # Target specific user segments
    TIME_BASED = "time_based"     # Time-windowed flags
    EXPERIMENT = "experiment"     # A/B testing flags


class Operator(str, Enum):
    """Operators for segment conditions."""
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"
    IN = "in"
    NOT_IN = "not_in"
    REGEX = "regex"
    STARTS_WITH = "starts_with"
    ENDS_WITH = "ends_with"


@dataclass
class SegmentCondition:
    """Single condition for user segment matching."""
    attribute: str  # e.g., "user.role", "user.email_domain", "request.ip"
    operator: Operator
    value: Any
    
    def evaluate(self, context: Dict[str, Any]) -> bool:
        """Evaluate condition against context."""
        # Navigate nested attributes (e.g., "user.role")
        attr_value = context
        for key in self.attribute.split('.'):
            if isinstance(attr_value, dict):
                attr_value = attr_value.get(key)
            else:
                attr_value = None
            if attr_value is None:
                return False
        
        return self._compare(attr_value, self.value)
    
    def _compare(self, actual: Any, expected: Any) -> bool:
        """Compare actual value against expected using operator."""
        ops = {
            Operator.EQUALS: lambda a, e: a == e,
            Operator.NOT_EQUALS: lambda a, e: a != e,
            Operator.CONTAINS: lambda a, e: e in a if isinstance(a, (str, list)) else False,
            Operator.NOT_CONTAINS: lambda a, e: e not in a if isinstance(a, (str, list)) else True,
            Operator.GREATER_THAN: lambda a, e: a > e,
            Operator.LESS_THAN: lambda a, e: a < e,
            Operator.IN: lambda a, e: a in e,
            Operator.NOT_IN: lambda a, e: a not in e,
            Operator.REGEX: lambda a, e: bool(__import__('re').match(e, str(a))),
            Operator.STARTS_WITH: lambda a, e: str(a).startswith(str(e)),
            Operator.ENDS_WITH: lambda a, e: str(a).endswith(str(e)),
        }
        return ops.get(self.operator, lambda a, e: False)(actual, expected)


@dataclass
class UserSegment:
    """User segment definition with matching conditions."""
    id: str
    name: str
    description: str
    conditions: List[SegmentCondition]
    match_all: bool = True  # True = AND, False = OR
    
    def matches(self, context: Dict[str, Any]) -> bool:
        """Check if context matches this segment."""
        if not self.conditions:
            return False
        
        results = [cond.evaluate(context) for cond in self.conditions]
        return all(results) if self.match_all else any(results)


class FeatureFlag(BaseModel):
    """Feature flag definition with all configuration options."""
    
    # Identification
    key: str = Field(..., description="Unique flag identifier")
    name: str = Field(..., description="Human-readable name")
    description: str = Field(default="", description="Flag purpose and usage")
    
    # Type and value
    flag_type: FlagType = Field(default=FlagType.BOOLEAN)
    default_value: Any = Field(default=False)
    
    # Percentage rollout (for PERCENTAGE type)
    rollout_percentage: int = Field(default=0, ge=0, le=100)
    rollout_seed: str = Field(default="user_id", description="Attribute to hash for consistent bucketing")
    
    # User segments (for USER_SEGMENT type)
    target_segments: List[str] = Field(default_factory=list)
    
    # Time window (for TIME_BASED type)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    
    # Experiment configuration (for EXPERIMENT type)
    experiment_variants: List[Dict[str, Any]] = Field(default_factory=list)
    
    # Metadata
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str = Field(default="system")
    tags: List[str] = Field(default_factory=list)
    
    # Status
    enabled: bool = Field(default=True)
    archived: bool = Field(default=False)
    
    # Dependencies
    prerequisites: List[str] = Field(default_factory=list, description="Flags that must be true")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
    
    @validator('rollout_percentage')
    def validate_percentage(cls, v):
        if not 0 <= v <= 100:
            raise ValueError("Percentage must be between 0 and 100")
        return v


class FlagEvaluationResult(BaseModel):
    """Result of a feature flag evaluation."""
    flag_key: str
    value: Any
    source: str  # "default", "override", "percentage", "segment", "time", "experiment"
    reason: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    context_hash: Optional[str] = None


class FeatureFlagStore:
    """Redis-backed feature flag storage with local caching."""
    
    def __init__(self):
        self._redis: Optional[redis.Redis] = None
        self._local_cache: Dict[str, tuple[FeatureFlag, datetime]] = {}
        self._cache_ttl_seconds = 30
        self._lock = asyncio.Lock()
    
    async def connect(self):
        """Initialize Redis connection."""
        if settings.REDIS_URL:
            self._redis = redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                max_connections=50
            )
            logger.info("Feature flag store connected to Redis")
    
    async def disconnect(self):
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()
            self._redis = None
    
    def _cache_key(self, flag_key: str) -> str:
        return f"ff:{settings.ENVIRONMENT}:{flag_key}"
    
    def _all_flags_key(self) -> str:
        return f"ff:{settings.ENVIRONMENT}:all"
    
    async def get_flag(self, flag_key: str) -> Optional[FeatureFlag]:
        """Get flag from cache or Redis."""
        # Check local cache first
        now = datetime.now(timezone.utc)
        if flag_key in self._local_cache:
            flag, cached_at = self._local_cache[flag_key]
            if (now - cached_at).seconds < self._cache_ttl_seconds:
                FEATURE_FLAG_CACHE_HITS.inc()
                return flag
        
        # Fetch from Redis
        if not self._redis:
            return None
        
        try:
            data = await self._redis.get(self._cache_key(flag_key))
            if data:
                flag = FeatureFlag.parse_raw(data)
                self._local_cache[flag_key] = (flag, now)
                return flag
        except Exception as e:
            logger.error(f"Error fetching flag {flag_key}: {e}")
        
        return None
    
    async def get_all_flags(self) -> Dict[str, FeatureFlag]:
        """Get all active flags."""
        if not self._redis:
            return {}
        
        try:
            keys = await self._redis.smembers(self._all_flags_key())
            if not keys:
                return {}
            
            pipe = self._redis.pipeline()
            for key in keys:
                pipe.get(self._cache_key(key))
            
            results = await pipe.execute()
            flags = {}
            for key, data in zip(keys, results):
                if data:
                    try:
                        flag = FeatureFlag.parse_raw(data)
                        if flag.enabled and not flag.archived:
                            flags[key] = flag
                    except Exception as e:
                        logger.error(f"Error parsing flag {key}: {e}")
            
            return flags
        except Exception as e:
            logger.error(f"Error fetching all flags: {e}")
            return {}
    
    async def save_flag(self, flag: FeatureFlag) -> bool:
        """Save flag to Redis and update cache."""
        if not self._redis:
            return False
        
        try:
            flag.updated_at = datetime.now(timezone.utc)
            await self._redis.set(
                self._cache_key(flag.key),
                flag.json(),
                ex=86400 * 30  # 30 days
            )
            await self._redis.sadd(self._all_flags_key(), flag.key)
            
            self._local_cache[flag.key] = (flag, datetime.now(timezone.utc))
            
            # Publish update notification
            await self._redis.publish(
                f"ff:updates:{settings.ENVIRONMENT}",
                json.dumps({"type": "flag_updated", "key": flag.key})
            )
            
            return True
        except Exception as e:
            logger.error(f"Error saving flag {flag.key}: {e}")
            return False
    
    async def delete_flag(self, flag_key: str) -> bool:
        """Delete flag from Redis and cache."""
        if not self._redis:
            return False
        
        try:
            await self._redis.delete(self._cache_key(flag_key))
            await self._redis.srem(self._all_flags_key(), flag_key)
            self._local_cache.pop(flag_key, None)
            
            await self._redis.publish(
                f"ff:updates:{settings.ENVIRONMENT}",
                json.dumps({"type": "flag_deleted", "key": flag_key})
            )
            
            return True
        except Exception as e:
            logger.error(f"Error deleting flag {flag_key}: {e}")
            return False
    
    async def invalidate_cache(self, flag_key: Optional[str] = None):
        """Invalidate local cache."""
        async with self._lock:
            if flag_key:
                self._local_cache.pop(flag_key, None)
            else:
                self._local_cache.clear()


class FeatureFlagService:
    """Main service for feature flag evaluation and management."""
    
    def __init__(self):
        self.store = FeatureFlagStore()
        self.segments: Dict[str, UserSegment] = {}
        self._subscribers: List[Callable] = []
        self._update_task: Optional[asyncio.Task] = None
    
    async def initialize(self):
        """Initialize the feature flag service."""
        await self.store.connect()
        await self._load_segments()
        self._update_task = asyncio.create_task(self._listen_for_updates())
        logger.info("Feature flag service initialized")
    
    async def shutdown(self):
        """Shutdown the feature flag service."""
        if self._update_task:
            self._update_task.cancel()
            try:
                await self._update_task
            except asyncio.CancelledError:
                pass
        await self.store.disconnect()
    
    async def _load_segments(self):
        """Load user segments from storage."""
        # Load from Redis or database
        # For now, using hardcoded segments as examples
        self.segments = {
            "beta_users": UserSegment(
                id="beta_users",
                name="Beta Users",
                description="Users enrolled in beta program",
                conditions=[
                    SegmentCondition("user.beta_enrolled", Operator.EQUALS, True)
                ]
            ),
            "internal_users": UserSegment(
                id="internal_users",
                name="Internal Users",
                description="Company employees",
                conditions=[
                    SegmentCondition("user.email", Operator.ENDS_WITH, "@taskflow.pro")
                ]
            ),
            "premium_users": UserSegment(
                id="premium_users",
                name="Premium Users",
                description="Paid subscription users",
                conditions=[
                    SegmentCondition("user.subscription_tier", Operator.IN, ["premium", "enterprise"])
                ]
            ),
        }
    
    async def _listen_for_updates(self):
        """Listen for flag update notifications from Redis."""
        if not self.store._redis:
            return
        
        try:
            pubsub = self.store._redis.pubsub()
            await pubsub.subscribe(f"ff:updates:{settings.ENVIRONMENT}")
            
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        if data["type"] in ("flag_updated", "flag_deleted"):
                            await self.store.invalidate_cache(data.get("key"))
                            # Notify subscribers
                            for callback in self._subscribers:
                                asyncio.create_task(callback(data))
                    except Exception as e:
                        logger.error(f"Error processing flag update: {e}")
        except Exception as e:
            logger.error(f"Error in flag update listener: {e}")
    
    def subscribe(self, callback: Callable):
        """Subscribe to flag updates."""
        self._subscribers.append(callback)
    
    def unsubscribe(self, callback: Callable):
        """Unsubscribe from flag updates."""
        if callback in self._subscribers:
            self._subscribers.remove(callback)
    
    def _hash_for_percentage(self, identifier: str, flag_key: str) -> int:
        """Generate consistent hash for percentage-based rollouts."""
        hash_input = f"{flag_key}:{identifier}"
        hash_value = hashlib.md5(hash_input.encode()).hexdigest()
        return int(hash_value, 16) % 100
    
    async def evaluate(
        self,
        flag_key: str,
        context: Optional[Dict[str, Any]] = None,
        default_value: Any = False
    ) -> FlagEvaluationResult:
        """
        Evaluate a feature flag for the given context.
        
        Args:
            flag_key: The flag identifier
            context: Evaluation context (user, request, etc.)
            default_value: Value to return if flag not found
            
        Returns:
            FlagEvaluationResult with value and metadata
        """
        context = context or {}
        context_hash = self._hash_context(context)
        
        # Get flag definition
        flag = await self.store.get_flag(flag_key)
        
        if not flag:
            FEATURE_FLAG_EVALUATIONS.labels(
                flag_key=flag_key,
                result="default",
                source="missing"
            ).inc()
            return FlagEvaluationResult(
                flag_key=flag_key,
                value=default_value,
                source="default",
                reason="Flag not found",
                context_hash=context_hash
            )
        
        if flag.archived:
            return FlagEvaluationResult(
                flag_key=flag_key,
                value=flag.default_value,
                source="default",
                reason="Flag archived",
                context_hash=context_hash
            )
        
        if not flag.enabled:
            return FlagEvaluationResult(
                flag_key=flag_key,
                value=flag.default_value,
                source="default",
                reason="Flag disabled",
                context_hash=context_hash
            )
        
        # Check prerequisites
        for prereq_key in flag.prerequisites:
            prereq_result = await self.evaluate(prereq_key, context, False)
            if not prereq_result.value:
                return FlagEvaluationResult(
                    flag_key=flag_key,
                    value=flag.default_value,
                    source="default",
                    reason=f"Prerequisite flag '{prereq_key}' is false",
                    context_hash=context_hash
                )
        
        # Evaluate based on flag type
        result = await self._evaluate_by_type(flag, context, context_hash)
        
        FEATURE_FLAG_EVALUATIONS.labels(
            flag_key=flag_key,
            result=str(result.value).lower(),
            source=result.source
        ).inc()
        
        return result
    
    async def _evaluate_by_type(
        self,
        flag: FeatureFlag,
        context: Dict[str, Any],
        context_hash: str
    ) -> FlagEvaluationResult:
        """Evaluate flag based on its type."""
        
        if flag.flag_type == FlagType.BOOLEAN:
            return FlagEvaluationResult(
                flag_key=flag.key,
                value=True,
                source="override",
                context_hash=context_hash
            )
        
        elif flag.flag_type == FlagType.PERCENTAGE:
            seed_value = context.get(flag.rollout_seed, "")
            hash_value = self._hash_for_percentage(str(seed_value), flag.key)
            
            if hash_value < flag.rollout_percentage:
                return FlagEvaluationResult(
                    flag_key=flag.key,
                    value=True,
                    source="percentage",
                    reason=f"Hash {hash_value} < {flag.rollout_percentage}%",
                    context_hash=context_hash
                )
            else:
                return FlagEvaluationResult(
                    flag_key=flag.key,
                    value=flag.default_value,
                    source="percentage",
                    reason=f"Hash {hash_value} >= {flag.rollout_percentage}%",
                    context_hash=context_hash
                )
        
        elif flag.flag_type == FlagType.USER_SEGMENT:
            for segment_id in flag.target_segments:
                segment = self.segments.get(segment_id)
                if segment and segment.matches(context):
                    return FlagEvaluationResult(
                        flag_key=flag.key,
                        value=True,
                        source="segment",
                        reason=f"Matched segment: {segment.name}",
                        context_hash=context_hash
                    )
            
            return FlagEvaluationResult(
                flag_key=flag.key,
                value=flag.default_value,
                source="segment",
                reason="No matching segments",
                context_hash=context_hash
            )
        
        elif flag.flag_type == FlagType.TIME_BASED:
            now = datetime.now(timezone.utc)
            
            if flag.start_time and now < flag.start_time:
                return FlagEvaluationResult(
                    flag_key=flag.key,
                    value=flag.default_value,
                    source="time",
                    reason=f"Before start time: {flag.start_time}",
                    context_hash=context_hash
                )
            
            if flag.end_time and now > flag.end_time:
                return FlagEvaluationResult(
                    flag_key=flag.key,
                    value=flag.default_value,
                    source="time",
                    reason=f"After end time: {flag.end_time}",
                    context_hash=context_hash
                )
            
            return FlagEvaluationResult(
                flag_key=flag.key,
                value=True,
                source="time",
                context_hash=context_hash
            )
        
        elif flag.flag_type == FlagType.EXPERIMENT:
            return self._evaluate_experiment(flag, context, context_hash)
        
        return FlagEvaluationResult(
            flag_key=flag.key,
            value=flag.default_value,
            source="default",
            reason="Unknown flag type",
            context_hash=context_hash
        )
    
    def _evaluate_experiment(
        self,
        flag: FeatureFlag,
        context: Dict[str, Any],
        context_hash: str
    ) -> FlagEvaluationResult:
        """Evaluate experiment flag and assign variant."""
        if not flag.experiment_variants:
            return FlagEvaluationResult(
                flag_key=flag.key,
                value=flag.default_value,
                source="experiment",
                reason="No variants defined",
                context_hash=context_hash
            )
        
        # Use user_id for consistent variant assignment
        user_id = str(context.get("user_id", context.get("user", {}).get("id", "anonymous")))
        hash_value = self._hash_for_percentage(user_id, flag.key)
        
        # Assign variant based on weights
        cumulative = 0
        for variant in flag.experiment_variants:
            weight = variant.get("weight", 100 // len(flag.experiment_variants))
            cumulative += weight
            if hash_value < cumulative:
                return FlagEvaluationResult(
                    flag_key=flag.key,
                    value=variant.get("value"),
                    source="experiment",
                    reason=f"Assigned to variant: {variant.get('name', 'unknown')}",
                    context_hash=context_hash
                )
        
        # Fallback to first variant
        return FlagEvaluationResult(
            flag_key=flag.key,
            value=flag.experiment_variants[0].get("value"),
            source="experiment",
            reason="Fallback to control variant",
            context_hash=context_hash
        )
    
    def _hash_context(self, context: Dict[str, Any]) -> str:
        """Generate hash of context for caching."""
        try:
            return hashlib.sha256(
                json.dumps(context, sort_keys=True, default=str).encode()
            ).hexdigest()[:16]
        except Exception:
            return ""
    
    # Management API methods
    
    async def create_flag(self, flag: FeatureFlag) -> FeatureFlag:
        """Create a new feature flag."""
        existing = await self.store.get_flag(flag.key)
        if existing:
            raise ValueError(f"Flag '{flag.key}' already exists")
        
        await self.store.save_flag(flag)
        return flag
    
    async def update_flag(self, flag_key: str, updates: Dict[str, Any]) -> FeatureFlag:
        """Update an existing feature flag."""
        flag = await self.store.get_flag(flag_key)
        if not flag:
            raise ValueError(f"Flag '{flag_key}' not found")
        
        for key, value in updates.items():
            if hasattr(flag, key):
                setattr(flag, key, value)
        
        await self.store.save_flag(flag)
        return flag
    
    async def delete_flag(self, flag_key: str) -> bool:
        """Delete a feature flag."""
        return await self.store.delete_flag(flag_key)
    
    async def list_flags(
        self,
        tags: Optional[List[str]] = None,
        include_archived: bool = False
    ) -> List[FeatureFlag]:
        """List all feature flags."""
        flags = await self.store.get_all_flags()
        result = list(flags.values())
        
        if not include_archived:
            result = [f for f in result if not f.archived]
        
        if tags:
            result = [f for f in result if any(t in f.tags for t in tags)]
        
        return sorted(result, key=lambda f: f.updated_at, reverse=True)
    
    async def bulk_evaluate(
        self,
        flag_keys: List[str],
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, FlagEvaluationResult]:
        """Evaluate multiple flags at once."""
        results = {}
        for key in flag_keys:
            results[key] = await self.evaluate(key, context)
        return results


# Global service instance
feature_flag_service = FeatureFlagService()


# Convenience functions for common use cases

async def is_enabled(flag_key: str, context: Optional[Dict[str, Any]] = None) -> bool:
    """Check if a feature flag is enabled."""
    result = await feature_flag_service.evaluate(flag_key, context, default_value=False)
    return bool(result.value)


async def get_value(
    flag_key: str,
    context: Optional[Dict[str, Any]] = None,
    default_value: Any = None
) -> Any:
    """Get the value of a feature flag."""
    result = await feature_flag_service.evaluate(flag_key, context, default_value=default_value)
    return result.value if result.value is not None else default_value


def create_context(
    user: Optional[Dict[str, Any]] = None,
    request: Optional[Dict[str, Any]] = None,
    **kwargs
) -> Dict[str, Any]:
    """Create a standardized evaluation context."""
    context = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "environment": settings.ENVIRONMENT,
    }
    
    if user:
        context["user"] = user
        context["user_id"] = user.get("id")
    
    if request:
        context["request"] = request
    
    context.update(kwargs)
    return context


# Decorator for feature-flagged functions

def feature_flagged(
    flag_key: str,
    fallback: Optional[Callable] = None,
    context_extractor: Optional[Callable] = None
):
    """
    Decorator to conditionally execute a function based on a feature flag.
    
    Usage:
        @feature_flagged("new_feature")
        async def new_feature_implementation():
            ...
        
        @feature_flagged("new_feature", fallback=old_implementation)
        async def new_feature_implementation():
            ...
    """
    def decorator(func: Callable):
        async def wrapper(*args, **kwargs):
            # Extract context
            if context_extractor:
                context = await context_extractor(*args, **kwargs)
            else:
                context = kwargs.get("context", {})
            
            # Evaluate flag
            enabled = await is_enabled(flag_key, context)
            
            if enabled:
                return await func(*args, **kwargs)
            elif fallback:
                return await fallback(*args, **kwargs)
            else:
                raise FeatureNotEnabledError(f"Feature '{flag_key}' is not enabled")
        
        return wrapper
    return decorator


class FeatureNotEnabledError(Exception):
    """Raised when a feature flag is not enabled."""
    pass


# Predefined flags for TaskFlow Pro

DEFAULT_FLAGS = [
    FeatureFlag(
        key="new_dashboard",
        name="New Dashboard UI",
        description="Enable the redesigned dashboard interface",
        flag_type=FlagType.PERCENTAGE,
        rollout_percentage=10,
        tags=["ui", "dashboard", "v2"]
    ),
    FeatureFlag(
        key="realtime_collaboration",
        name="Real-time Collaboration",
        description="Enable WebSocket-based real-time task updates",
        flag_type=FlagType.USER_SEGMENT,
        target_segments=["beta_users", "premium_users"],
        tags=["collaboration", "websocket", "premium"]
    ),
    FeatureFlag(
        key="ai_task_suggestions",
        name="AI Task Suggestions",
        description="Enable AI-powered task recommendations",
        flag_type=FlagType.USER_SEGMENT,
        target_segments=["beta_users"],
        tags=["ai", "ml", "beta"]
    ),
    FeatureFlag(
        key="advanced_reporting",
        name="Advanced Reporting",
        description="Enable advanced analytics and reporting features",
        flag_type=FlagType.USER_SEGMENT,
        target_segments=["premium_users", "internal_users"],
        tags=["reporting", "analytics", "premium"]
    ),
    FeatureFlag(
        key="mobile_optimization",
        name="Mobile Optimization",
        description="Enable mobile-optimized UI components",
        flag_type=FlagType.BOOLEAN,
        enabled=True,
        tags=["mobile", "ui", "responsive"]
    ),
    FeatureFlag(
        key="dark_mode",
        name="Dark Mode",
        description="Enable dark mode theme option",
        flag_type=FlagType.BOOLEAN,
        enabled=True,
        tags=["ui", "theme", "accessibility"]
    ),
]


async def initialize_default_flags():
    """Initialize default feature flags if they don't exist."""
    for flag in DEFAULT_FLAGS:
        existing = await feature_flag_service.store.get_flag(flag.key)
        if not existing:
            await feature_flag_service.create_flag(flag)
            logger.info(f"Created default flag: {flag.key}")
