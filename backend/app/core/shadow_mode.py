"""
Shadow Mode Execution Framework

This module implements shadow mode execution, allowing new code paths to run
alongside existing code without affecting production responses. Results are
captured and compared for validation before full rollout.
"""

import asyncio
import logging
import time
import traceback
from typing import Any, Callable, Dict, List, Optional, TypeVar, Generic, Union
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from functools import wraps
import json
import hashlib

import redis.asyncio as redis
from pydantic import BaseModel

from app.core.config import settings
from app.core.metrics import (
    SHADOW_MODE_COMPARISONS,
    SHADOW_MODE_MISMATCHES,
    SHADOW_MODE_LATENCY,
    SHADOW_MODE_ERRORS
)

logger = logging.getLogger(__name__)

T = TypeVar('T')


class ComparisonResult(str, Enum):
    """Result of comparing shadow and production outputs."""
    MATCH = "match"
    MISMATCH = "mismatch"
    SHADOW_ERROR = "shadow_error"
    PRODUCTION_ERROR = "production_error"
    BOTH_ERROR = "both_error"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


class ShadowModeStatus(str, Enum):
    """Status of shadow mode execution."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass
class ExecutionResult(Generic[T]):
    """Result of a single execution (production or shadow)."""
    success: bool
    result: Optional[T] = None
    error: Optional[str] = None
    traceback: Optional[str] = None
    duration_ms: float = 0.0
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "success": self.success,
            "result": self._serialize_result(self.result),
            "error": self.error,
            "duration_ms": self.duration_ms,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
    
    def _serialize_result(self, result: Any) -> Any:
        """Safely serialize result for storage."""
        if result is None:
            return None
        if isinstance(result, (str, int, float, bool)):
            return result
        if isinstance(result, (list, dict)):
            try:
                return json.loads(json.dumps(result, default=str))
            except:
                return str(result)
        if isinstance(result, BaseModel):
            return result.dict()
        return str(result)


@dataclass
class ComparisonReport:
    """Report comparing production and shadow execution results."""
    comparison_id: str
    operation_name: str
    comparison_result: ComparisonResult
    production_result: ExecutionResult
    shadow_result: ExecutionResult
    differences: List[Dict[str, Any]] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "comparison_id": self.comparison_id,
            "operation_name": self.operation_name,
            "comparison_result": self.comparison_result.value,
            "production": self.production_result.to_dict(),
            "shadow": self.shadow_result.to_dict(),
            "differences": self.differences,
            "context": self.context,
            "timestamp": self.timestamp.isoformat(),
        }


class ResultComparator:
    """Compares results from production and shadow executions."""
    
    def __init__(
        self,
        tolerance: float = 0.001,  # For floating point comparisons
        ignore_fields: Optional[List[str]] = None,
        custom_comparators: Optional[Dict[str, Callable]] = None
    ):
        self.tolerance = tolerance
        self.ignore_fields = set(ignore_fields or [])
        self.custom_comparators = custom_comparators or {}
    
    def compare(
        self,
        production_result: Any,
        shadow_result: Any,
        path: str = "root"
    ) -> List[Dict[str, Any]]:
        """
        Compare two results and return list of differences.
        
        Returns:
            List of difference dictionaries with path, expected, and actual values.
        """
        differences = []
        
        # Handle None values
        if production_result is None and shadow_result is None:
            return differences
        
        if production_result is None or shadow_result is None:
            return [{
                "path": path,
                "type": "null_mismatch",
                "production": production_result,
                "shadow": shadow_result
            }]
        
        # Check for custom comparator
        if path in self.custom_comparators:
            if not self.custom_comparators[path](production_result, shadow_result):
                differences.append({
                    "path": path,
                    "type": "custom_mismatch",
                    "production": production_result,
                    "shadow": shadow_result
                })
            return differences
        
        # Check type
        if type(production_result) != type(shadow_result):
            differences.append({
                "path": path,
                "type": "type_mismatch",
                "production_type": type(production_result).__name__,
                "shadow_type": type(shadow_result).__name__,
                "production": production_result,
                "shadow": shadow_result
            })
            return differences
        
        # Compare based on type
        if isinstance(production_result, dict):
            differences.extend(self._compare_dicts(
                production_result, shadow_result, path
            ))
        elif isinstance(production_result, list):
            differences.extend(self._compare_lists(
                production_result, shadow_result, path
            ))
        elif isinstance(production_result, float):
            if abs(production_result - shadow_result) > self.tolerance:
                differences.append({
                    "path": path,
                    "type": "float_mismatch",
                    "production": production_result,
                    "shadow": shadow_result,
                    "difference": abs(production_result - shadow_result)
                })
        elif production_result != shadow_result:
            differences.append({
                "path": path,
                "type": "value_mismatch",
                "production": production_result,
                "shadow": shadow_result
            })
        
        return differences
    
    def _compare_dicts(
        self,
        prod: Dict,
        shadow: Dict,
        path: str
    ) -> List[Dict[str, Any]]:
        """Compare two dictionaries."""
        differences = []
        
        # Get all keys
        all_keys = set(prod.keys()) | set(shadow.keys())
        
        for key in all_keys:
            if key in self.ignore_fields:
                continue
            
            new_path = f"{path}.{key}"
            
            if key not in prod:
                differences.append({
                    "path": new_path,
                    "type": "missing_in_production",
                    "shadow": shadow[key]
                })
            elif key not in shadow:
                differences.append({
                    "path": new_path,
                    "type": "missing_in_shadow",
                    "production": prod[key]
                })
            else:
                differences.extend(self.compare(
                    prod[key], shadow[key], new_path
                ))
        
        return differences
    
    def _compare_lists(
        self,
        prod: List,
        shadow: List,
        path: str
    ) -> List[Dict[str, Any]]:
        """Compare two lists."""
        differences = []
        
        if len(prod) != len(shadow):
            differences.append({
                "path": path,
                "type": "length_mismatch",
                "production_length": len(prod),
                "shadow_length": len(shadow)
            })
        
        # Compare elements
        for i, (p, s) in enumerate(zip(prod, shadow)):
            differences.extend(self.compare(p, s, f"{path}[{i}]"))
        
        return differences


class ShadowModeExecutor:
    """
    Executes functions in shadow mode alongside production code.
    
    Usage:
        executor = ShadowModeExecutor()
        
        # In your endpoint
        result = await executor.execute(
            operation_name="create_task",
            production_fn=legacy_create_task,
            shadow_fn=new_create_task,
            args=(task_data,),
            kwargs={"user": current_user}
        )
        
        # result contains only the production result
        # comparison happens asynchronously
    """
    
    def __init__(
        self,
        redis_client: Optional[redis.Redis] = None,
        sampling_rate: float = 1.0,
        timeout_seconds: float = 5.0,
        max_concurrent_shadows: int = 100
    ):
        self.redis = redis_client
        self.sampling_rate = sampling_rate
        self.timeout_seconds = timeout_seconds
        self.max_concurrent_shadows = max_concurrent_shadows
        
        self._comparator = ResultComparator()
        self._semaphore = asyncio.Semaphore(max_concurrent_shadows)
        self._comparison_handlers: List[Callable[[ComparisonReport], None]] = []
    
    def add_comparison_handler(self, handler: Callable[[ComparisonReport], None]):
        """Add a handler to be called when comparisons complete."""
        self._comparison_handlers.append(handler)
    
    async def execute(
        self,
        operation_name: str,
        production_fn: Callable[..., T],
        shadow_fn: Callable[..., T],
        args: tuple = (),
        kwargs: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
        comparator: Optional[ResultComparator] = None,
        sample_key: Optional[str] = None
    ) -> T:
        """
        Execute production function and optionally run shadow function.
        
        Args:
            operation_name: Identifier for this operation
            production_fn: The production function to execute
            shadow_fn: The shadow function to compare against
            args: Positional arguments for both functions
            kwargs: Keyword arguments for both functions
            context: Additional context for comparison logging
            comparator: Custom comparator (uses default if not provided)
            sample_key: Key for consistent sampling
            
        Returns:
            Result from production_fn
        """
        kwargs = kwargs or {}
        context = context or {}
        
        # Check sampling
        should_sample = self._should_sample(sample_key or operation_name)
        
        # Execute production
        prod_result = await self._run_production(production_fn, args, kwargs)
        
        # Run shadow if sampled
        if should_sample and prod_result.success:
            asyncio.create_task(self._run_shadow_comparison(
                operation_name=operation_name,
                production_result=prod_result,
                shadow_fn=shadow_fn,
                args=args,
                kwargs=kwargs,
                context=context,
                comparator=comparator or self._comparator
            ))
        
        # Return production result (or raise if failed)
        if not prod_result.success:
            raise Exception(prod_result.error or "Production execution failed")
        
        return prod_result.result
    
    def _should_sample(self, key: str) -> bool:
        """Determine if this request should be sampled for shadow mode."""
        if self.sampling_rate >= 1.0:
            return True
        if self.sampling_rate <= 0:
            return False
        
        # Use hash for consistent sampling
        hash_value = int(hashlib.md5(key.encode()).hexdigest(), 16)
        return (hash_value % 100) < (self.sampling_rate * 100)
    
    async def _run_production(
        self,
        fn: Callable[..., T],
        args: tuple,
        kwargs: Dict[str, Any]
    ) -> ExecutionResult[T]:
        """Execute the production function."""
        start_time = time.time()
        result = ExecutionResult(success=False)
        
        try:
            if asyncio.iscoroutinefunction(fn):
                output = await fn(*args, **kwargs)
            else:
                output = fn(*args, **kwargs)
            
            result.success = True
            result.result = output
        except Exception as e:
            result.success = False
            result.error = str(e)
            result.traceback = traceback.format_exc()
            logger.error(f"Production execution failed: {e}")
        
        result.duration_ms = (time.time() - start_time) * 1000
        result.completed_at = datetime.now(timezone.utc)
        
        return result
    
    async def _run_shadow_comparison(
        self,
        operation_name: str,
        production_result: ExecutionResult,
        shadow_fn: Callable[..., T],
        args: tuple,
        kwargs: Dict[str, Any],
        context: Dict[str, Any],
        comparator: ResultComparator
    ):
        """Run shadow execution and compare results."""
        async with self._semaphore:
            # Execute shadow with timeout
            shadow_result = await self._run_shadow_with_timeout(
                shadow_fn, args, kwargs
            )
            
            # Compare results
            comparison = self._compare_results(
                operation_name=operation_name,
                production_result=production_result,
                shadow_result=shadow_result,
                comparator=comparator,
                context=context
            )
            
            # Store and notify
            await self._store_comparison(comparison)
            await self._notify_handlers(comparison)
    
    async def _run_shadow_with_timeout(
        self,
        fn: Callable[..., T],
        args: tuple,
        kwargs: Dict[str, Any]
    ) -> ExecutionResult[T]:
        """Execute shadow function with timeout."""
        start_time = time.time()
        result = ExecutionResult(success=False)
        
        try:
            if asyncio.iscoroutinefunction(fn):
                output = await asyncio.wait_for(
                    fn(*args, **kwargs),
                    timeout=self.timeout_seconds
                )
            else:
                # Run sync function in thread pool
                loop = asyncio.get_event_loop()
                output = await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: fn(*args, **kwargs)),
                    timeout=self.timeout_seconds
                )
            
            result.success = True
            result.result = output
        except asyncio.TimeoutError:
            result.success = False
            result.error = f"Shadow execution timed out after {self.timeout_seconds}s"
        except Exception as e:
            result.success = False
            result.error = str(e)
            result.traceback = traceback.format_exc()
            SHADOW_MODE_ERRORS.labels(operation="shadow_execution").inc()
        
        result.duration_ms = (time.time() - start_time) * 1000
        result.completed_at = datetime.now(timezone.utc)
        
        return result
    
    def _compare_results(
        self,
        operation_name: str,
        production_result: ExecutionResult,
        shadow_result: ExecutionResult,
        comparator: ResultComparator,
        context: Dict[str, Any]
    ) -> ComparisonReport:
        """Compare production and shadow results."""
        
        comparison_id = hashlib.sha256(
            f"{operation_name}:{datetime.now(timezone.utc).isoformat()}".encode()
        ).hexdigest()[:16]
        
        # Determine comparison result
        if not production_result.success and not shadow_result.success:
            comp_result = ComparisonResult.BOTH_ERROR
            differences = []
        elif not production_result.success:
            comp_result = ComparisonResult.PRODUCTION_ERROR
            differences = []
        elif not shadow_result.success:
            comp_result = ComparisonResult.SHADOW_ERROR
            differences = []
        else:
            # Both succeeded - compare outputs
            differences = comparator.compare(
                production_result.result,
                shadow_result.result
            )
            comp_result = ComparisonResult.MISMATCH if differences else ComparisonResult.MATCH
        
        # Update metrics
        SHADOW_MODE_COMPARISONS.labels(
            operation=operation_name,
            result=comp_result.value
        ).inc()
        
        if differences:
            SHADOW_MODE_MISMATCHES.labels(operation=operation_name).inc()
        
        # Record latency difference
        latency_diff = shadow_result.duration_ms - production_result.duration_ms
        SHADOW_MODE_LATENCY.labels(operation=operation_name).observe(latency_diff)
        
        return ComparisonReport(
            comparison_id=comparison_id,
            operation_name=operation_name,
            comparison_result=comp_result,
            production_result=production_result,
            shadow_result=shadow_result,
            differences=differences,
            context=context
        )
    
    async def _store_comparison(self, report: ComparisonReport):
        """Store comparison report to Redis."""
        if not self.redis:
            return
        
        try:
            key = f"shadow_mode:{settings.ENVIRONMENT}:{report.operation_name}:{report.comparison_id}"
            await self.redis.setex(
                key,
                86400 * 7,  # 7 days retention
                json.dumps(report.to_dict(), default=str)
            )
            
            # Add to recent comparisons list
            list_key = f"shadow_mode:{settings.ENVIRONMENT}:{report.operation_name}:recent"
            await self.redis.lpush(list_key, report.comparison_id)
            await self.redis.ltrim(list_key, 0, 999)  # Keep last 1000
            await self.redis.expire(list_key, 86400 * 7)
            
        except Exception as e:
            logger.error(f"Failed to store comparison: {e}")
    
    async def _notify_handlers(self, report: ComparisonReport):
        """Notify all registered comparison handlers."""
        for handler in self._comparison_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(report)
                else:
                    handler(report)
            except Exception as e:
                logger.error(f"Comparison handler failed: {e}")


# Decorator for shadow mode

def shadow_mode(
    operation_name: str,
    executor: Optional[ShadowModeExecutor] = None,
    sampling_rate: Optional[float] = None
):
    """
    Decorator to run a function in shadow mode.
    
    Usage:
        @shadow_mode("process_payment", sampling_rate=0.1)
        async def new_payment_processor(payment_data):
            ...
        
        # In your code:
        result = await new_payment_processor(payment_data, shadow_production_fn=old_processor)
    """
    exec_instance = executor or ShadowModeExecutor()
    if sampling_rate is not None:
        exec_instance.sampling_rate = sampling_rate
    
    def decorator(shadow_fn: Callable):
        @wraps(shadow_fn)
        async def wrapper(*args, **kwargs):
            # Extract production function
            production_fn = kwargs.pop('shadow_production_fn', None)
            context = kwargs.pop('shadow_context', {})
            
            if production_fn is None:
                # No production function - just run shadow
                return await shadow_fn(*args, **kwargs)
            
            # Execute with shadow comparison
            return await exec_instance.execute(
                operation_name=operation_name,
                production_fn=production_fn,
                shadow_fn=shadow_fn,
                args=args,
                kwargs=kwargs,
                context=context
            )
        
        return wrapper
    return decorator


# Analysis and reporting

class ShadowModeAnalyzer:
    """Analyze shadow mode comparison results."""
    
    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self.redis = redis_client
    
    async def get_comparison_stats(
        self,
        operation_name: Optional[str] = None,
        hours: int = 24
    ) -> Dict[str, Any]:
        """Get statistics on shadow mode comparisons."""
        if not self.redis:
            return {}
        
        # This would query Redis for aggregated stats
        # For now, return structure
        return {
            "period_hours": hours,
            "operation": operation_name or "all",
            "total_comparisons": 0,
            "results": {
                "match": 0,
                "mismatch": 0,
                "shadow_error": 0,
                "production_error": 0,
                "both_error": 0,
                "timeout": 0,
            },
            "mismatch_rate": 0.0,
            "average_latency_diff_ms": 0.0,
            "top_mismatches": []
        }
    
    async def get_recent_mismatches(
        self,
        operation_name: str,
        limit: int = 100
    ) -> List[ComparisonReport]:
        """Get recent mismatches for an operation."""
        if not self.redis:
            return []
        
        list_key = f"shadow_mode:{settings.ENVIRONMENT}:{operation_name}:recent"
        ids = await self.redis.lrange(list_key, 0, limit - 1)
        
        reports = []
        for comp_id in ids:
            key = f"shadow_mode:{settings.ENVIRONMENT}:{operation_name}:{comp_id}"
            data = await self.redis.get(key)
            if data:
                try:
                    reports.append(json.loads(data))
                except:
                    pass
        
        return reports


# Global executor instance
shadow_executor = ShadowModeExecutor()


# Initialization

async def initialize_shadow_mode(redis_url: Optional[str] = None):
    """Initialize shadow mode with Redis connection."""
    if redis_url:
        redis_client = redis.from_url(redis_url, decode_responses=True)
        shadow_executor.redis = redis_client
        logger.info("Shadow mode initialized with Redis")
    else:
        logger.warning("Shadow mode initialized without Redis - comparisons won't be persisted")
