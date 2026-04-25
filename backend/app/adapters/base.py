"""
Base Adapter Classes for Legacy-Modern System Integration

Provides foundational adapter patterns including:
- Adapter: Basic one-way adaptation
- TwoWayAdapter: Bidirectional adaptation
- BaseAdapter: Abstract base with common functionality
"""

from abc import ABC, abstractmethod
from typing import TypeVar, Generic, Optional, Dict, Any, List
from dataclasses import dataclass
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

T = TypeVar('T')  # Legacy type
U = TypeVar('U')  # Modern type


@dataclass
class AdapterContext:
    """Context object passed through adaptation operations."""
    request_id: str
    timestamp: datetime
    source_system: str
    target_system: str
    metadata: Dict[str, Any]
    
    @classmethod
    def create(
        cls,
        source: str,
        target: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> "AdapterContext":
        import uuid
        return cls(
            request_id=str(uuid.uuid4()),
            timestamp=datetime.utcnow(),
            source_system=source,
            target_system=target,
            metadata=metadata or {}
        )


class AdapterError(Exception):
    """Base exception for adapter operations."""
    pass


class AdaptationError(AdapterError):
    """Raised when adaptation fails."""
    
    def __init__(self, message: str, source_data: Any = None, context: Optional[AdapterContext] = None):
        super().__init__(message)
        self.source_data = source_data
        self.context = context


class ValidationError(AdapterError):
    """Raised when data validation fails during adaptation."""
    pass


class Adapter(ABC, Generic[T, U]):
    """
    Abstract base class for one-way adapters.
    
    Converts from legacy type T to modern type U.
    """
    
    def __init__(self, context: Optional[AdapterContext] = None):
        self.context = context
        self._validation_rules: List[callable] = []
        self._transform_hooks: List[callable] = []
    
    @abstractmethod
    def adapt(self, legacy_data: T) -> U:
        """
        Adapt legacy data to modern format.
        
        Args:
            legacy_data: Data in legacy format
            
        Returns:
            Data in modern format
            
        Raises:
            AdaptationError: If adaptation fails
            ValidationError: If validation fails
        """
        pass
    
    def add_validation_rule(self, rule: callable) -> "Adapter":
        """Add a validation rule to the adapter chain."""
        self._validation_rules.append(rule)
        return self
    
    def add_transform_hook(self, hook: callable) -> "Adapter":
        """Add a transform hook to the adapter chain."""
        self._transform_hooks.append(hook)
        return self
    
    def validate(self, data: T) -> bool:
        """
        Run all validation rules against the data.
        
        Args:
            data: Data to validate
            
        Returns:
            True if all validations pass
            
        Raises:
            ValidationError: If any validation fails
        """
        for rule in self._validation_rules:
            if not rule(data):
                raise ValidationError(f"Validation failed for rule: {rule.__name__}")
        return True
    
    def apply_transform_hooks(self, data: U) -> U:
        """Apply all transform hooks to the adapted data."""
        result = data
        for hook in self._transform_hooks:
            result = hook(result)
        return result


class TwoWayAdapter(ABC, Generic[T, U]):
    """
    Abstract base class for bidirectional adapters.
    
    Supports conversion in both directions:
    - to_modern: Legacy -> Modern
    - to_legacy: Modern -> Legacy
    """
    
    def __init__(self, context: Optional[AdapterContext] = None):
        self.context = context
        self._to_modern_validators: List[callable] = []
        self._to_legacy_validators: List[callable] = []
    
    @abstractmethod
    def to_modern(self, legacy_data: T) -> U:
        """Convert legacy data to modern format."""
        pass
    
    @abstractmethod
    def to_legacy(self, modern_data: U) -> T:
        """Convert modern data to legacy format."""
        pass
    
    def adapt(self, data: T, direction: str = "to_modern") -> U:
        """
        Adapt data in the specified direction.
        
        Args:
            data: Data to adapt
            direction: "to_modern" or "to_legacy"
            
        Returns:
            Adapted data
        """
        if direction == "to_modern":
            return self.to_modern(data)
        elif direction == "to_legacy":
            # Note: This requires U to be passed, but we have T
            # This method signature is for convenience when type is known
            raise NotImplementedError("Use to_legacy() directly for legacy conversion")
        else:
            raise ValueError(f"Invalid direction: {direction}")


class BaseAdapter(ABC):
    """
    Enhanced base adapter with logging, metrics, and error handling.
    """
    
    def __init__(
        self,
        name: str,
        context: Optional[AdapterContext] = None,
        enable_logging: bool = True,
        enable_metrics: bool = True
    ):
        self.name = name
        self.context = context or AdapterContext.create("unknown", "unknown")
        self.enable_logging = enable_logging
        self.enable_metrics = enable_metrics
        self._metrics = {
            "adaptations": 0,
            "failures": 0,
            "last_adaptation": None
        }
    
    def _log_adaptation(self, source: Any, result: Any, success: bool = True):
        """Log adaptation operation."""
        if not self.enable_logging:
            return
            
        if success:
            logger.info(
                f"[{self.name}] Adaptation successful",
                extra={
                    "request_id": self.context.request_id,
                    "source_type": type(source).__name__,
                    "result_type": type(result).__name__
                }
            )
        else:
            logger.error(
                f"[{self.name}] Adaptation failed",
                extra={
                    "request_id": self.context.request_id,
                    "source_type": type(source).__name__
                }
            )
    
    def _record_metric(self, metric_name: str, value: Any = None):
        """Record adaptation metric."""
        if not self.enable_metrics:
            return
            
        if metric_name == "adaptation":
            self._metrics["adaptations"] += 1
            self._metrics["last_adaptation"] = datetime.utcnow().isoformat()
        elif metric_name == "failure":
            self._metrics["failures"] += 1
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get adapter metrics."""
        return self._metrics.copy()
    
    @abstractmethod
    def supports(self, data: Any) -> bool:
        """Check if this adapter supports the given data."""
        pass


class ChainedAdapter(BaseAdapter, Generic[T, U]):
    """
    Adapter that chains multiple adapters together.
    
    Useful for multi-step transformations.
    """
    
    def __init__(self, adapters: List[Adapter], name: str = "ChainedAdapter"):
        super().__init__(name)
        self.adapters = adapters
    
    def adapt(self, data: Any) -> Any:
        """Adapt data through the entire chain."""
        result = data
        for adapter in self.adapters:
            result = adapter.adapt(result)
        return result
    
    def supports(self, data: Any) -> bool:
        """Check if first adapter supports the data."""
        return self.adapters[0].supports(data) if self.adapters else False


class ConditionalAdapter(BaseAdapter, Generic[T, U]):
    """
    Adapter that selects appropriate adapter based on conditions.
    """
    
    def __init__(self, name: str = "ConditionalAdapter"):
        super().__init__(name)
        self._adapters: List[tuple] = []  # (condition, adapter)
        self._default_adapter: Optional[Adapter] = None
    
    def add_adapter(self, condition: callable, adapter: Adapter) -> "ConditionalAdapter":
        """Add an adapter with a condition."""
        self._adapters.append((condition, adapter))
        return self
    
    def set_default_adapter(self, adapter: Adapter) -> "ConditionalAdapter":
        """Set the default adapter when no conditions match."""
        self._default_adapter = adapter
        return self
    
    def adapt(self, data: T) -> U:
        """Adapt using the first matching adapter."""
        for condition, adapter in self._adapters:
            if condition(data):
                return adapter.adapt(data)
        
        if self._default_adapter:
            return self._default_adapter.adapt(data)
        
        raise AdaptationError("No suitable adapter found for data", data)
    
    def supports(self, data: Any) -> bool:
        """Check if any adapter supports the data."""
        for condition, _ in self._adapters:
            if condition(data):
                return True
        return self._default_adapter is not None
