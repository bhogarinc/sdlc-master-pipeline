"""
Canary Deployment Logic

This module implements percentage-based traffic splitting for gradual rollouts,
with automatic monitoring and rollback capabilities.
"""

import asyncio
import logging
import random
import hashlib
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from functools import wraps

import redis.asyncio as redis
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.metrics import (
    CANARY_REQUESTS,
    CANARY_ERRORS,
    CANARY_LATENCY,
    CANARY_ROLLBACK_TRIGGERS
)

logger = logging.getLogger(__name__)


class CanaryStatus(str, Enum):
    """Status of a canary deployment."""
    PENDING = "pending"           # Waiting to start
    RUNNING = "running"           # Currently rolling out
    PAUSED = "paused"             # Temporarily stopped
    COMPLETED = "completed"       # Fully rolled out
    ROLLED_BACK = "rolled_back"   # Rolled back to previous
    FAILED = "failed"             # Failed and rolled back


class CanaryStrategy(str, Enum):
    """Strategies for canary traffic splitting."""
    RANDOM = "random"             # Random sampling
    STICKY = "sticky"             # Sticky sessions (user-based)
    GEOGRAPHIC = "geographic"     # Geographic regions
    ATTRIBUTE = "attribute"       # Based on request attributes


@dataclass
class HealthCheck:
    """Health check configuration for canary monitoring."""
    metric_name: str
    threshold: float
    comparison: str = "greater_than"  # greater_than, less_than, equals
    window_minutes: int = 5
    consecutive_violations: int = 3


@dataclass
class RollbackTrigger:
    """Configuration for automatic rollback triggers."""
    error_rate_threshold: float = 0.05  # 5% error rate
    latency_p99_threshold_ms: float = 5000  # 5 seconds
    error_increase_threshold: float = 2.0  # 2x increase
    min_requests: int = 100  # Minimum requests before evaluating


class CanaryDeployment(BaseModel):
    """Configuration for a canary deployment."""
    
    # Identification
    id: str
    name: str
    description: str = ""
    
    # Target
    service: str                  # Service being deployed
    version: str                  # New version being rolled out
    previous_version: str         # Version being replaced
    
    # Rollout configuration
    strategy: CanaryStrategy = CanaryStrategy.STICKY
    steps: List[int] = Field(default_factory=lambda: [1, 5, 10, 25, 50, 100])
    current_step: int = 0
    step_duration_minutes: int = 30
    
    # Traffic splitting
    traffic_percentage: float = 0.0
    sticky_attribute: str = "user_id"  # For sticky strategy
    
    # Monitoring
    health_checks: List[HealthCheck] = Field(default_factory=list)
    rollback_triggers: RollbackTrigger = Field(default_factory=RollbackTrigger)
    
    # Status
    status: CanaryStatus = CanaryStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    current_step_started_at: Optional[datetime] = None
    
    # Statistics
    total_requests: int = 0
    canary_requests: int = 0
    canary_errors: int = 0
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
    
    @property
    def current_percentage(self) -> int:
        """Get current rollout percentage."""
        if self.current_step < len(self.steps):
            return self.steps[self.current_step]
        return 100
    
    @property
    def is_active(self) -> bool:
        """Check if canary is currently active."""
        return self.status in (CanaryStatus.RUNNING, CanaryStatus.PAUSED)


class CanaryRouter:
    """Routes traffic between canary and stable versions."""
    
    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self.redis = redis_client
        self._deployments: Dict[str, CanaryDeployment] = {}
        self._sticky_cache: Dict[str, str] = {}  # user_id -> version
        self._lock = asyncio.Lock()
    
    def _get_key(self, deployment_id: str) -> str:
        return f"canary:{settings.ENVIRONMENT}:{deployment_id}"
    
    def _get_sticky_key(self, deployment_id: str, attribute_value: str) -> str:
        return f"canary:{settings.ENVIRONMENT}:{deployment_id}:sticky:{attribute_value}"
    
    async def create_deployment(self, deployment: CanaryDeployment) -> CanaryDeployment:
        """Create a new canary deployment."""
        async with self._lock:
            self._deployments[deployment.id] = deployment
            
            if self.redis:
                await self.redis.set(
                    self._get_key(deployment.id),
                    deployment.json(),
                    ex=86400 * 30
                )
        
        logger.info(f"Created canary deployment: {deployment.id}")
        return deployment
    
    async def get_deployment(self, deployment_id: str) -> Optional[CanaryDeployment]:
        """Get a canary deployment by ID."""
        # Check local cache first
        if deployment_id in self._deployments:
            return self._deployments[deployment_id]
        
        # Fetch from Redis
        if self.redis:
            data = await self.redis.get(self._get_key(deployment_id))
            if data:
                deployment = CanaryDeployment.parse_raw(data)
                self._deployments[deployment_id] = deployment
                return deployment
        
        return None
    
    async def start_deployment(self, deployment_id: str) -> bool:
        """Start a canary deployment."""
        deployment = await self.get_deployment(deployment_id)
        if not deployment:
            return False
        
        deployment.status = CanaryStatus.RUNNING
        deployment.started_at = datetime.now(timezone.utc)
        deployment.current_step_started_at = datetime.now(timezone.utc)
        
        await self._save_deployment(deployment)
        
        logger.info(f"Started canary deployment: {deployment_id}")
        return True
    
    async def pause_deployment(self, deployment_id: str) -> bool:
        """Pause a running canary deployment."""
        deployment = await self.get_deployment(deployment_id)
        if not deployment or deployment.status != CanaryStatus.RUNNING:
            return False
        
        deployment.status = CanaryStatus.PAUSED
        await self._save_deployment(deployment)
        
        logger.info(f"Paused canary deployment: {deployment_id}")
        return True
    
    async def resume_deployment(self, deployment_id: str) -> bool:
        """Resume a paused canary deployment."""
        deployment = await self.get_deployment(deployment_id)
        if not deployment or deployment.status != CanaryStatus.PAUSED:
            return False
        
        deployment.status = CanaryStatus.RUNNING
        deployment.current_step_started_at = datetime.now(timezone.utc)
        await self._save_deployment(deployment)
        
        logger.info(f"Resumed canary deployment: {deployment_id}")
        return True
    
    async def promote_step(self, deployment_id: str) -> bool:
        """Promote canary to next percentage step."""
        deployment = await self.get_deployment(deployment_id)
        if not deployment:
            return False
        
        if deployment.current_step >= len(deployment.steps) - 1:
            # Complete the deployment
            deployment.status = CanaryStatus.COMPLETED
            deployment.completed_at = datetime.now(timezone.utc)
            deployment.traffic_percentage = 100.0
            logger.info(f"Completed canary deployment: {deployment_id}")
        else:
            deployment.current_step += 1
            deployment.current_step_started_at = datetime.now(timezone.utc)
            deployment.traffic_percentage = float(deployment.current_percentage)
            logger.info(
                f"Promoted canary deployment {deployment_id} to "
                f"{deployment.current_percentage}%"
            )
        
        await self._save_deployment(deployment)
        return True
    
    async def rollback_deployment(
        self,
        deployment_id: str,
        reason: str = "manual"
    ) -> bool:
        """Rollback a canary deployment."""
        deployment = await self.get_deployment(deployment_id)
        if not deployment:
            return False
        
        deployment.status = CanaryStatus.ROLLED_BACK
        deployment.completed_at = datetime.now(timezone.utc)
        deployment.traffic_percentage = 0.0
        
        await self._save_deployment(deployment)
        
        CANARY_ROLLBACK_TRIGGERS.labels(
            deployment=deployment_id,
            reason=reason
        ).inc()
        
        logger.warning(f"Rolled back canary deployment {deployment_id}: {reason}")
        return True
    
    async def should_route_to_canary(
        self,
        deployment_id: str,
        context: Dict[str, Any]
    ) -> bool:
        """
        Determine if request should be routed to canary version.
        
        Args:
            deployment_id: The canary deployment ID
            context: Request context for routing decisions
            
        Returns:
            True if request should go to canary, False for stable
        """
        deployment = await self.get_deployment(deployment_id)
        if not deployment or not deployment.is_active:
            return False
        
        percentage = deployment.current_percentage
        
        if percentage <= 0:
            return False
        if percentage >= 100:
            return True
        
        # Route based on strategy
        if deployment.strategy == CanaryStrategy.RANDOM:
            return random.random() * 100 < percentage
        
        elif deployment.strategy == CanaryStrategy.STICKY:
            return await self._sticky_route(deployment, context, percentage)
        
        elif deployment.strategy == CanaryStrategy.GEOGRAPHIC:
            region = context.get("region", "unknown")
            # Route specific regions to canary
            regions_in_canary = self._get_canary_regions(percentage)
            return region in regions_in_canary
        
        elif deployment.strategy == CanaryStrategy.ATTRIBUTE:
            # Route based on custom attribute
            attr_value = context.get(deployment.sticky_attribute)
            if attr_value:
                hash_val = self._hash_for_routing(str(attr_value))
                return hash_val < percentage
            return False
        
        return False
    
    async def _sticky_route(
        self,
        deployment: CanaryDeployment,
        context: Dict[str, Any],
        percentage: float
    ) -> bool:
        """Route using sticky sessions."""
        attr_value = context.get(deployment.sticky_attribute)
        if not attr_value:
            # Fall back to random
            return random.random() * 100 < percentage
        
        # Check cache first
        cache_key = self._get_sticky_key(deployment.id, str(attr_value))
        
        if self.redis:
            cached = await self.redis.get(cache_key)
            if cached:
                return cached == "canary"
        
        # Make routing decision
        hash_val = self._hash_for_routing(str(attr_value))
        is_canary = hash_val < percentage
        
        # Cache decision
        if self.redis:
            await self.redis.setex(
                cache_key,
                86400,  # 24 hours
                "canary" if is_canary else "stable"
            )
        
        return is_canary
    
    def _hash_for_routing(self, value: str) -> float:
        """Generate consistent hash for routing decisions."""
        hash_int = int(hashlib.md5(value.encode()).hexdigest(), 16)
        return (hash_int % 10000) / 100.0  # 0-100 with 2 decimal precision
    
    def _get_canary_regions(self, percentage: float) -> Set[str]:
        """Get set of regions to route to canary based on percentage."""
        all_regions = ["us-east", "us-west", "eu-west", "eu-central", "ap-south", "ap-northeast"]
        num_regions = max(1, int(len(all_regions) * percentage / 100))
        return set(all_regions[:num_regions])
    
    async def record_request(
        self,
        deployment_id: str,
        is_canary: bool,
        success: bool,
        latency_ms: float
    ):
        """Record metrics for a request."""
        deployment = await self.get_deployment(deployment_id)
        if not deployment:
            return
        
        deployment.total_requests += 1
        if is_canary:
            deployment.canary_requests += 1
            if not success:
                deployment.canary_errors += 1
        
        await self._save_deployment(deployment)
        
        # Record metrics
        CANARY_REQUESTS.labels(
            deployment=deployment_id,
            version="canary" if is_canary else "stable"
        ).inc()
        
        if not success:
            CANARY_ERRORS.labels(
                deployment=deployment_id,
                version="canary" if is_canary else "stable"
            ).inc()
        
        CANARY_LATENCY.labels(
            deployment=deployment_id,
            version="canary" if is_canary else "stable"
        ).observe(latency_ms)
    
    async def check_health(self, deployment_id: str) -> Dict[str, Any]:
        """Check health of canary deployment."""
        deployment = await self.get_deployment(deployment_id)
        if not deployment:
            return {"healthy": False, "error": "Deployment not found"}
        
        if deployment.canary_requests < deployment.rollback_triggers.min_requests:
            return {"healthy": True, "reason": "Insufficient data"}
        
        error_rate = deployment.canary_errors / max(deployment.canary_requests, 1)
        
        checks = {
            "error_rate": {
                "value": error_rate,
                "threshold": deployment.rollback_triggers.error_rate_threshold,
                "passed": error_rate < deployment.rollback_triggers.error_rate_threshold
            },
            "total_requests": deployment.total_requests,
            "canary_requests": deployment.canary_requests,
            "canary_errors": deployment.canary_errors,
        }
        
        healthy = all(c["passed"] for c in checks.values() if isinstance(c, dict) and "passed" in c)
        
        return {
            "healthy": healthy,
            "deployment_id": deployment_id,
            "status": deployment.status.value,
            "checks": checks
        }
    
    async def auto_promote(self, deployment_id: str) -> bool:
        """Automatically promote canary if health checks pass."""
        deployment = await self.get_deployment(deployment_id)
        if not deployment or deployment.status != CanaryStatus.RUNNING:
            return False
        
        # Check if step duration has elapsed
        if deployment.current_step_started_at:
            elapsed = datetime.now(timezone.utc) - deployment.current_step_started_at
            if elapsed < timedelta(minutes=deployment.step_duration_minutes):
                return False
        
        # Check health
        health = await self.check_health(deployment_id)
        if not health.get("healthy"):
            return False
        
        # Promote to next step
        return await self.promote_step(deployment_id)
    
    async def should_rollback(self, deployment_id: str) -> Tuple[bool, str]:
        """Check if deployment should be automatically rolled back."""
        deployment = await self.get_deployment(deployment_id)
        if not deployment or not deployment.is_active:
            return False, ""
        
        if deployment.canary_requests < deployment.rollback_triggers.min_requests:
            return False, ""
        
        error_rate = deployment.canary_errors / max(deployment.canary_requests, 1)
        
        if error_rate > deployment.rollback_triggers.error_rate_threshold:
            return True, f"Error rate {error_rate:.2%} exceeds threshold {deployment.rollback_triggers.error_rate_threshold:.2%}"
        
        return False, ""
    
    async def _save_deployment(self, deployment: CanaryDeployment):
        """Save deployment to storage."""
        self._deployments[deployment.id] = deployment
        
        if self.redis:
            await self.redis.set(
                self._get_key(deployment.id),
                deployment.json(),
                ex=86400 * 30
            )
    
    async def list_deployments(
        self,
        service: Optional[str] = None,
        status: Optional[CanaryStatus] = None
    ) -> List[CanaryDeployment]:
        """List canary deployments."""
        deployments = list(self._deployments.values())
        
        if service:
            deployments = [d for d in deployments if d.service == service]
        
        if status:
            deployments = [d for d in deployments if d.status == status]
        
        return sorted(deployments, key=lambda d: d.started_at or datetime.min, reverse=True)


# Global router instance
canary_router = CanaryRouter()


# Decorator for canary-routed functions

def canary_routed(
    deployment_id: str,
    stable_fn: Optional[Callable] = None,
    canary_fn: Optional[Callable] = None
):
    """
    Decorator to route between stable and canary implementations.
    
    Usage:
        @canary_routing("task-service-v2")
        async def process_task(task_data):
            # This is the canary implementation
            ...
        
        # Call with stable function:
        result = await process_task(task_data, stable_fn=old_process_task)
    """
    def decorator(fn: Callable):
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            # Extract stable function
            stable = kwargs.pop('stable_fn', stable_fn)
            context = kwargs.pop('canary_context', {})
            
            # Determine routing
            use_canary = await canary_router.should_route_to_canary(
                deployment_id, context
            )
            
            start_time = asyncio.get_event_loop().time()
            success = True
            
            try:
                if use_canary:
                    result = await fn(*args, **kwargs)
                else:
                    if stable is None:
                        raise ValueError("No stable function provided")
                    result = await stable(*args, **kwargs)
                
                return result
            except Exception as e:
                success = False
                raise
            finally:
                latency_ms = (asyncio.get_event_loop().time() - start_time) * 1000
                asyncio.create_task(canary_router.record_request(
                    deployment_id=deployment_id,
                    is_canary=use_canary,
                    success=success,
                    latency_ms=latency_ms
                ))
        
        return wrapper
    return decorator


# Background task for canary management

async def canary_management_task():
    """Background task to manage canary deployments."""
    while True:
        try:
            # Get all active deployments
            deployments = await canary_router.list_deployments(status=CanaryStatus.RUNNING)
            
            for deployment in deployments:
                # Check if should rollback
                should_rollback, reason = await canary_router.should_rollback(deployment.id)
                if should_rollback:
                    await canary_router.rollback_deployment(deployment.id, reason)
                    continue
                
                # Check if should auto-promote
                await canary_router.auto_promote(deployment.id)
            
        except Exception as e:
            logger.error(f"Error in canary management task: {e}")
        
        await asyncio.sleep(60)  # Check every minute


# Predefined canary configurations for TaskFlow Pro

DEFAULT_CANARY_CONFIGS = {
    "task-service-v2": CanaryDeployment(
        id="task-service-v2",
        name="Task Service v2 Rollout",
        description="Rolling out new task processing service",
        service="task-service",
        version="2.0.0",
        previous_version="1.5.2",
        strategy=CanaryStrategy.STICKY,
        steps=[1, 5, 10, 25, 50, 75, 100],
        step_duration_minutes=30,
        rollback_triggers=RollbackTrigger(
            error_rate_threshold=0.05,
            latency_p99_threshold_ms=3000,
            min_requests=100
        )
    ),
    "notification-service-websocket": CanaryDeployment(
        id="notification-service-websocket",
        name="WebSocket Notification Service",
        description="New real-time notification system",
        service="notification-service",
        version="2.0.0",
        previous_version="1.0.0",
        strategy=CanaryStrategy.GEOGRAPHIC,
        steps=[10, 25, 50, 100],
        step_duration_minutes=60,
        rollback_triggers=RollbackTrigger(
            error_rate_threshold=0.02,
            min_requests=50
        )
    ),
}


async def initialize_canary_deployments():
    """Initialize default canary deployments."""
    for deployment_id, config in DEFAULT_CANARY_CONFIGS.items():
        existing = await canary_router.get_deployment(deployment_id)
        if not existing:
            await canary_router.create_deployment(config)
            logger.info(f"Created canary deployment: {deployment_id}")
