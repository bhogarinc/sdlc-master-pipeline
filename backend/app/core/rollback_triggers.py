"""
Automated Rollback Triggers

This module implements automated rollback based on error rate thresholds,
latency spikes, and other health metrics.
"""

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from abc import ABC, abstractmethod

from pydantic import BaseModel, Field
import redis.asyncio as redis

from app.core.config import settings
from app.core.metrics import (
    ROLLBACK_TRIGGERS_FIRED,
    ROLLBACK_EXECUTIONS,
    HEALTH_CHECK_FAILURES
)

logger = logging.getLogger(__name__)


class TriggerType(str, Enum):
    """Types of rollback triggers."""
    ERROR_RATE = "error_rate"
    LATENCY_P99 = "latency_p99"
    LATENCY_P95 = "latency_p95"
    ERROR_INCREASE = "error_increase"
    LATENCY_INCREASE = "latency_increase"
    CUSTOM_METRIC = "custom_metric"
    MANUAL = "manual"
    CIRCUIT_BREAKER = "circuit_breaker"


class TriggerSeverity(str, Enum):
    """Severity levels for triggers."""
    WARNING = "warning"      # Alert only
    CRITICAL = "critical"    # Alert and prepare rollback
    EMERGENCY = "emergency"  # Immediate rollback


class RollbackAction(str, Enum):
    """Actions to take when trigger fires."""
    ALERT = "alert"                    # Send alert only
    THROTTLE = "throttle"              # Reduce traffic
    PARTIAL_ROLLBACK = "partial"       # Rollback partial traffic
    FULL_ROLLBACK = "full"             # Complete rollback
    CIRCUIT_BREAK = "circuit_break"    # Open circuit breaker


@dataclass
class TriggerThreshold:
    """Threshold configuration for a trigger."""
    value: float
    comparison: str = "greater_than"  # greater_than, less_than, equals
    duration_seconds: int = 300  # Must exceed threshold for this duration
    min_samples: int = 100  # Minimum samples required


@dataclass
class TriggerState:
    """Current state of a trigger."""
    triggered: bool = False
    triggered_at: Optional[datetime] = None
    last_value: Optional[float] = None
    consecutive_violations: int = 0
    total_violations: int = 0


class RollbackTrigger(BaseModel):
    """Configuration for a rollback trigger."""
    
    id: str
    name: str
    description: str = ""
    
    # Trigger configuration
    trigger_type: TriggerType
    severity: TriggerSeverity = TriggerSeverity.CRITICAL
    threshold: TriggerThreshold
    
    # Action configuration
    action: RollbackAction = RollbackAction.ALERT
    action_config: Dict[str, Any] = Field(default_factory=dict)
    
    # Scope
    services: List[str] = Field(default_factory=list)
    endpoints: List[str] = Field(default_factory=list)
    
    # Timing
    cooldown_minutes: int = 15  # Minutes before trigger can fire again
    auto_resolve: bool = True
    
    # Notification
    alert_channels: List[str] = Field(default_factory=lambda: ["slack", "pagerduty"])
    
    enabled: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class HealthSnapshot:
    """Snapshot of service health metrics."""
    timestamp: datetime
    service: str
    endpoint: Optional[str]
    
    # Request metrics
    total_requests: int
    error_requests: int
    error_rate: float
    
    # Latency metrics (ms)
    latency_p50: float
    latency_p95: float
    latency_p99: float
    
    # Comparison to baseline
    error_rate_baseline: float
    latency_p99_baseline: float
    
    # Additional metrics
    custom_metrics: Dict[str, float] = field(default_factory=dict)


class MetricsCollector(ABC):
    """Abstract base class for metrics collection."""
    
    @abstractmethod
    async def collect_health_snapshot(
        self,
        service: str,
        endpoint: Optional[str] = None,
        window_minutes: int = 5
    ) -> Optional[HealthSnapshot]:
        """Collect health snapshot for a service/endpoint."""
        pass
    
    @abstractmethod
    async def get_baseline_metrics(
        self,
        service: str,
        endpoint: Optional[str] = None
    ) -> Dict[str, float]:
        """Get baseline metrics for comparison."""
        pass


class PrometheusMetricsCollector(MetricsCollector):
    """Collector that fetches metrics from Prometheus."""
    
    def __init__(self, prometheus_url: str):
        self.prometheus_url = prometheus_url
        self._http_client = None
    
    async def collect_health_snapshot(
        self,
        service: str,
        endpoint: Optional[str] = None,
        window_minutes: int = 5
    ) -> Optional[HealthSnapshot]:
        """Collect metrics from Prometheus."""
        # This would make actual Prometheus API calls
        # For now, return a placeholder
        return HealthSnapshot(
            timestamp=datetime.now(timezone.utc),
            service=service,
            endpoint=endpoint,
            total_requests=1000,
            error_requests=10,
            error_rate=0.01,
            latency_p50=100,
            latency_p95=200,
            latency_p99=500,
            error_rate_baseline=0.005,
            latency_p99_baseline=400
        )
    
    async def get_baseline_metrics(
        self,
        service: str,
        endpoint: Optional[str] = None
    ) -> Dict[str, float]:
        """Get baseline from historical data."""
        return {
            "error_rate": 0.01,
            "latency_p99": 500,
            "latency_p95": 300
        }


class RollbackTriggerEngine:
    """Engine for evaluating and executing rollback triggers."""
    
    def __init__(
        self,
        metrics_collector: MetricsCollector,
        redis_client: Optional[redis.Redis] = None
    ):
        self.metrics = metrics_collector
        self.redis = redis_client
        self._triggers: Dict[str, RollbackTrigger] = {}
        self._trigger_states: Dict[str, TriggerState] = {}
        self._handlers: List[Callable[[RollbackTrigger, HealthSnapshot], None]] = []
        self._rollback_handlers: Dict[str, Callable] = {}
        self._last_triggered: Dict[str, datetime] = {}
        self._running = False
    
    def register_trigger(self, trigger: RollbackTrigger):
        """Register a rollback trigger."""
        self._triggers[trigger.id] = trigger
        self._trigger_states[trigger.id] = TriggerState()
        logger.info(f"Registered rollback trigger: {trigger.id}")
    
    def register_rollback_handler(
        self,
        service: str,
        handler: Callable[[str, RollbackAction], None]
    ):
        """Register a handler for rollback execution."""
        self._rollback_handlers[service] = handler
    
    def add_trigger_handler(
        self,
        handler: Callable[[RollbackTrigger, HealthSnapshot], None]
    ):
        """Add a handler to be called when triggers fire."""
        self._handlers.append(handler)
    
    async def start_monitoring(self, interval_seconds: int = 60):
        """Start the monitoring loop."""
        self._running = True
        logger.info("Starting rollback trigger monitoring")
        
        while self._running:
            try:
                await self._evaluate_all_triggers()
            except Exception as e:
                logger.error(f"Error evaluating triggers: {e}")
            
            await asyncio.sleep(interval_seconds)
    
    def stop_monitoring(self):
        """Stop the monitoring loop."""
        self._running = False
    
    async def _evaluate_all_triggers(self):
        """Evaluate all registered triggers."""
        for trigger_id, trigger in self._triggers.items():
            if not trigger.enabled:
                continue
            
            # Check cooldown
            last_triggered = self._last_triggered.get(trigger_id)
            if last_triggered:
                cooldown = timedelta(minutes=trigger.cooldown_minutes)
                if datetime.now(timezone.utc) - last_triggered < cooldown:
                    continue
            
            # Evaluate trigger for each service
            for service in trigger.services:
                snapshot = await self.metrics.collect_health_snapshot(service)
                if snapshot:
                    await self._evaluate_trigger(trigger, snapshot)
    
    async def _evaluate_trigger(
        self,
        trigger: RollbackTrigger,
        snapshot: HealthSnapshot
    ):
        """Evaluate a single trigger against health snapshot."""
        state = self._trigger_states[trigger.id]
        
        # Get current value based on trigger type
        current_value = self._get_metric_value(trigger.trigger_type, snapshot)
        state.last_value = current_value
        
        if current_value is None:
            return
        
        # Check threshold
        threshold = trigger.threshold
        violated = self._compare_value(
            current_value,
            threshold.value,
            threshold.comparison
        )
        
        if violated:
            state.consecutive_violations += 1
            state.total_violations += 1
            
            # Check if enough samples
            if snapshot.total_requests < threshold.min_samples:
                return
            
            # Check if duration threshold met
            violation_duration = state.consecutive_violations * 60  # Assuming 60s intervals
            if violation_duration >= threshold.duration_seconds:
                if not state.triggered:
                    await self._fire_trigger(trigger, snapshot, state)
        else:
            # Reset consecutive violations
            if state.consecutive_violations > 0 and trigger.auto_resolve:
                logger.info(f"Trigger {trigger.id} auto-resolved")
            state.consecutive_violations = 0
            state.triggered = False
    
    def _get_metric_value(
        self,
        trigger_type: TriggerType,
        snapshot: HealthSnapshot
    ) -> Optional[float]:
        """Get the relevant metric value for trigger evaluation."""
        metrics_map = {
            TriggerType.ERROR_RATE: snapshot.error_rate,
            TriggerType.LATENCY_P99: snapshot.latency_p99,
            TriggerType.LATENCY_P95: snapshot.latency_p95,
            TriggerType.ERROR_INCREASE: (
                snapshot.error_rate / max(snapshot.error_rate_baseline, 0.0001)
            ),
            TriggerType.LATENCY_INCREASE: (
                snapshot.latency_p99 / max(snapshot.latency_p99_baseline, 1)
            ),
        }
        return metrics_map.get(trigger_type)
    
    def _compare_value(
        self,
        current: float,
        threshold: float,
        comparison: str
    ) -> bool:
        """Compare current value against threshold."""
        comparisons = {
            "greater_than": lambda a, b: a > b,
            "less_than": lambda a, b: a < b,
            "equals": lambda a, b: abs(a - b) < 0.0001,
            "greater_than_or_equal": lambda a, b: a >= b,
            "less_than_or_equal": lambda a, b: a <= b,
        }
        return comparisons.get(comparison, lambda a, b: False)(current, threshold)
    
    async def _fire_trigger(
        self,
        trigger: RollbackTrigger,
        snapshot: HealthSnapshot,
        state: TriggerState
    ):
        """Fire a trigger and execute associated action."""
        state.triggered = True
        state.triggered_at = datetime.now(timezone.utc)
        self._last_triggered[trigger.id] = state.triggered_at
        
        ROLLBACK_TRIGGERS_FIRED.labels(
            trigger_id=trigger.id,
            trigger_type=trigger.trigger_type.value,
            severity=trigger.severity.value
        ).inc()
        
        logger.warning(
            f"Rollback trigger fired: {trigger.id} ({trigger.name}) - "
            f"{trigger.trigger_type.value} = {state.last_value:.4f}, "
            f"action={trigger.action.value}"
        )
        
        # Notify handlers
        for handler in self._handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(trigger, snapshot)
                else:
                    handler(trigger, snapshot)
            except Exception as e:
                logger.error(f"Trigger handler failed: {e}")
        
        # Execute action
        await self._execute_action(trigger, snapshot)
    
    async def _execute_action(
        self,
        trigger: RollbackTrigger,
        snapshot: HealthSnapshot
    ):
        """Execute the rollback action."""
        action = trigger.action
        
        if action == RollbackAction.ALERT:
            # Just alert, no rollback
            return
        
        if action in (RollbackAction.THROTTLE, RollbackAction.PARTIAL_ROLLBACK, 
                      RollbackAction.FULL_ROLLBACK, RollbackAction.CIRCUIT_BREAK):
            # Execute rollback for each affected service
            for service in trigger.services:
                handler = self._rollback_handlers.get(service)
                if handler:
                    try:
                        if asyncio.iscoroutinefunction(handler):
                            await handler(service, action)
                        else:
                            handler(service, action)
                        
                        ROLLBACK_EXECUTIONS.labels(
                            service=service,
                            action=action.value,
                            success="true"
                        ).inc()
                        
                    except Exception as e:
                        logger.error(f"Rollback handler failed for {service}: {e}")
                        ROLLBACK_EXECUTIONS.labels(
                            service=service,
                            action=action.value,
                            success="false"
                        ).inc()
    
    async def manual_rollback(
        self,
        service: str,
        reason: str = "manual",
        triggered_by: str = "operator"
    ) -> bool:
        """Manually trigger a rollback."""
        logger.warning(f"Manual rollback triggered for {service} by {triggered_by}: {reason}")
        
        handler = self._rollback_handlers.get(service)
        if handler:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(service, RollbackAction.FULL_ROLLBACK)
                else:
                    handler(service, RollbackAction.FULL_ROLLBACK)
                return True
            except Exception as e:
                logger.error(f"Manual rollback failed: {e}")
                return False
        
        return False
    
    async def get_trigger_status(self, trigger_id: str) -> Optional[Dict[str, Any]]:
        """Get current status of a trigger."""
        trigger = self._triggers.get(trigger_id)
        state = self._trigger_states.get(trigger_id)
        
        if not trigger:
            return None
        
        return {
            "trigger_id": trigger_id,
            "name": trigger.name,
            "enabled": trigger.enabled,
            "triggered": state.triggered if state else False,
            "last_value": state.last_value if state else None,
            "consecutive_violations": state.consecutive_violations if state else 0,
            "total_violations": state.total_violations if state else 0,
            "last_triggered": self._last_triggered.get(trigger_id),
        }


# Predefined triggers for TaskFlow Pro

DEFAULT_TRIGGERS = [
    RollbackTrigger(
        id="high_error_rate",
        name="High Error Rate",
        description="Error rate exceeds 5% for 5 minutes",
        trigger_type=TriggerType.ERROR_RATE,
        severity=TriggerSeverity.CRITICAL,
        threshold=TriggerThreshold(
            value=0.05,
            comparison="greater_than",
            duration_seconds=300,
            min_samples=100
        ),
        action=RollbackAction.PARTIAL_ROLLBACK,
        services=["task-service", "user-service", "notification-service"],
        alert_channels=["slack", "pagerduty"]
    ),
    RollbackTrigger(
        id="latency_spike",
        name="Latency Spike",
        description="P99 latency exceeds 5 seconds for 3 minutes",
        trigger_type=TriggerType.LATENCY_P99,
        severity=TriggerSeverity.CRITICAL,
        threshold=TriggerThreshold(
            value=5000,
            comparison="greater_than",
            duration_seconds=180,
            min_samples=50
        ),
        action=RollbackAction.THROTTLE,
        services=["task-service", "api-gateway"],
        alert_channels=["slack"]
    ),
    RollbackTrigger(
        id="error_increase",
        name="Error Rate Increase",
        description="Error rate increases by 3x from baseline",
        trigger_type=TriggerType.ERROR_INCREASE,
        severity=TriggerSeverity.WARNING,
        threshold=TriggerThreshold(
            value=3.0,
            comparison="greater_than",
            duration_seconds=120,
            min_samples=50
        ),
        action=RollbackAction.ALERT,
        services=["task-service", "user-service", "notification-service"],
        alert_channels=["slack"]
    ),
    RollbackTrigger(
        id="emergency_error_rate",
        name="Emergency Error Rate",
        description="Error rate exceeds 20% - immediate rollback",
        trigger_type=TriggerType.ERROR_RATE,
        severity=TriggerSeverity.EMERGENCY,
        threshold=TriggerThreshold(
            value=0.20,
            comparison="greater_than",
            duration_seconds=60,
            min_samples=20
        ),
        action=RollbackAction.FULL_ROLLBACK,
        services=["task-service", "user-service", "notification-service", "api-gateway"],
        alert_channels=["slack", "pagerduty", "email"]
    ),
]


# Global engine instance
rollback_engine: Optional[RollbackTriggerEngine] = None


async def initialize_rollback_triggers(
    prometheus_url: Optional[str] = None,
    redis_url: Optional[str] = None
):
    """Initialize the rollback trigger engine."""
    global rollback_engine
    
    # Create metrics collector
    if prometheus_url:
        collector = PrometheusMetricsCollector(prometheus_url)
    else:
        collector = PrometheusMetricsCollector("http://prometheus:9090")
    
    # Create Redis client
    redis_client = None
    if redis_url:
        redis_client = redis.from_url(redis_url, decode_responses=True)
    
    rollback_engine = RollbackTriggerEngine(collector, redis_client)
    
    # Register default triggers
    for trigger in DEFAULT_TRIGGERS:
        rollback_engine.register_trigger(trigger)
    
    logger.info("Rollback trigger engine initialized")
    
    # Start monitoring
    asyncio.create_task(rollback_engine.start_monitoring())
