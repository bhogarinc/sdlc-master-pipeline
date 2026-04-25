"""
Task Adapters for Legacy-Modern Task System Integration

Provides adapters for converting between legacy task formats and modern TaskFlow Pro models.
"""

from typing import Optional, List, Dict, Any, Union
from datetime import datetime
from enum import Enum
import logging

from .base import TwoWayAdapter, AdapterContext, AdaptationError, ValidationError

logger = logging.getLogger(__name__)


# Legacy task status values
class LegacyTaskStatus(Enum):
    PENDING = "P"
    IN_PROGRESS = "IP"
    COMPLETED = "C"
    CANCELLED = "X"
    ON_HOLD = "H"


# Modern task status values
class ModernTaskStatus(Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    DONE = "done"
    ARCHIVED = "archived"
    BLOCKED = "blocked"


# Legacy priority values (numeric)
class LegacyPriority(Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


# Modern priority values
class ModernPriority(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class LegacyTask:
    """Legacy task data structure."""
    
    def __init__(
        self,
        task_id: str,
        title: str,
        desc: Optional[str] = None,
        status: str = "P",
        priority: int = 2,
        owner_id: Optional[str] = None,
        assigned_to: Optional[str] = None,
        due_date: Optional[str] = None,
        created_date: Optional[str] = None,
        completed_date: Optional[str] = None,
        tags: Optional[str] = None,
        parent_task: Optional[str] = None,
        estimated_hours: Optional[float] = None,
        actual_hours: Optional[float] = None,
        custom_fields: Optional[Dict[str, Any]] = None
    ):
        self.task_id = task_id
        self.title = title
        self.desc = desc
        self.status = status
        self.priority = priority
        self.owner_id = owner_id
        self.assigned_to = assigned_to
        self.due_date = due_date
        self.created_date = created_date
        self.completed_date = completed_date
        self.tags = tags  # Comma-separated string
        self.parent_task = parent_task
        self.estimated_hours = estimated_hours
        self.actual_hours = actual_hours
        self.custom_fields = custom_fields or {}


class ModernTask:
    """Modern task data structure (TaskFlow Pro)."""
    
    def __init__(
        self,
        id: str,
        title: str,
        description: Optional[str] = None,
        status: str = "todo",
        priority: str = "medium",
        created_by: Optional[str] = None,
        assignee_id: Optional[str] = None,
        due_date: Optional[datetime] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
        labels: Optional[List[str]] = None,
        parent_id: Optional[str] = None,
        subtasks: Optional[List[str]] = None,
        estimated_duration: Optional[int] = None,  # Minutes
        actual_duration: Optional[int] = None,  # Minutes
        metadata: Optional[Dict[str, Any]] = None,
        team_id: Optional[str] = None,
        board_id: Optional[str] = None,
        position: int = 0
    ):
        self.id = id
        self.title = title
        self.description = description
        self.status = status
        self.priority = priority
        self.created_by = created_by
        self.assignee_id = assignee_id
        self.due_date = due_date
        self.created_at = created_at
        self.updated_at = updated_at
        self.completed_at = completed_at
        self.labels = labels or []
        self.parent_id = parent_id
        self.subtasks = subtasks or []
        self.estimated_duration = estimated_duration
        self.actual_duration = actual_duration
        self.metadata = metadata or {}
        self.team_id = team_id
        self.board_id = board_id
        self.position = position


class LegacyTaskAdapter(TwoWayAdapter[LegacyTask, ModernTask]):
    """
    Bidirectional adapter for legacy and modern task formats.
    
    Handles conversion of:
    - Status codes (P, IP, C, X, H) -> (todo, in_progress, done, archived, blocked)
    - Priority levels (1-4) -> (low, medium, high, urgent)
    - Date formats (string) -> (datetime)
    - Tags (comma-separated) -> (list of labels)
    - Hours -> Minutes conversion
    """
    
    # Status mapping from legacy to modern
    STATUS_TO_MODERN = {
        "P": "todo",
        "IP": "in_progress",
        "C": "done",
        "X": "archived",
        "H": "blocked"
    }
    
    # Status mapping from modern to legacy
    STATUS_TO_LEGACY = {v: k for k, v in STATUS_TO_MODERN.items()}
    
    # Priority mapping from legacy to modern
    PRIORITY_TO_MODERN = {
        1: "low",
        2: "medium",
        3: "high",
        4: "urgent"
    }
    
    # Priority mapping from modern to legacy
    PRIORITY_TO_LEGACY = {v: k for k, v in PRIORITY_TO_MODERN.items()}
    
    def __init__(self, context: Optional[AdapterContext] = None):
        super().__init__(context)
        self._date_format = "%Y-%m-%d %H:%M:%S"
    
    def to_modern(self, legacy_data: LegacyTask) -> ModernTask:
        """
        Convert legacy task to modern format.
        
        Args:
            legacy_data: Task in legacy format
            
        Returns:
            Task in modern format
            
        Raises:
            AdaptationError: If conversion fails
        """
        try:
            # Parse dates
            due_date = self._parse_date(legacy_data.due_date)
            created_at = self._parse_date(legacy_data.created_date) or datetime.utcnow()
            completed_at = self._parse_date(legacy_data.completed_date)
            
            # Convert status
            status = self.STATUS_TO_MODERN.get(legacy_data.status, "todo")
            
            # Convert priority
            priority = self.PRIORITY_TO_MODERN.get(legacy_data.priority, "medium")
            
            # Parse tags
            labels = self._parse_tags(legacy_data.tags)
            
            # Convert hours to minutes
            estimated_duration = self._hours_to_minutes(legacy_data.estimated_hours)
            actual_duration = self._hours_to_minutes(legacy_data.actual_hours)
            
            # Build metadata from custom fields
            metadata = {
                "legacy_task_id": legacy_data.task_id,
                "migrated_at": datetime.utcnow().isoformat(),
                **legacy_data.custom_fields
            }
            
            return ModernTask(
                id=legacy_data.task_id,
                title=legacy_data.title,
                description=legacy_data.desc,
                status=status,
                priority=priority,
                created_by=legacy_data.owner_id,
                assignee_id=legacy_data.assigned_to,
                due_date=due_date,
                created_at=created_at,
                updated_at=datetime.utcnow(),
                completed_at=completed_at,
                labels=labels,
                parent_id=legacy_data.parent_task,
                estimated_duration=estimated_duration,
                actual_duration=actual_duration,
                metadata=metadata
            )
            
        except Exception as e:
            logger.error(f"Failed to adapt legacy task {legacy_data.task_id}: {str(e)}")
            raise AdaptationError(
                f"Task adaptation failed: {str(e)}",
                legacy_data,
                self.context
            )
    
    def to_legacy(self, modern_data: ModernTask) -> LegacyTask:
        """
        Convert modern task to legacy format.
        
        Args:
            modern_data: Task in modern format
            
        Returns:
            Task in legacy format
        """
        try:
            # Convert status
            status = self.STATUS_TO_LEGACY.get(modern_data.status, "P")
            
            # Convert priority
            priority = self.PRIORITY_TO_LEGACY.get(modern_data.priority, 2)
            
            # Format dates
            due_date = self._format_date(modern_data.due_date)
            created_date = self._format_date(modern_data.created_at)
            completed_date = self._format_date(modern_data.completed_at)
            
            # Format tags
            tags = ",".join(modern_data.labels) if modern_data.labels else None
            
            # Convert minutes to hours
            estimated_hours = self._minutes_to_hours(modern_data.estimated_duration)
            actual_hours = self._minutes_to_hours(modern_data.actual_duration)
            
            # Extract custom fields from metadata
            custom_fields = {
                k: v for k, v in modern_data.metadata.items()
                if k not in ("legacy_task_id", "migrated_at")
            }
            
            return LegacyTask(
                task_id=modern_data.id,
                title=modern_data.title,
                desc=modern_data.description,
                status=status,
                priority=priority,
                owner_id=modern_data.created_by,
                assigned_to=modern_data.assignee_id,
                due_date=due_date,
                created_date=created_date,
                completed_date=completed_date,
                tags=tags,
                parent_task=modern_data.parent_id,
                estimated_hours=estimated_hours,
                actual_hours=actual_hours,
                custom_fields=custom_fields if custom_fields else None
            )
            
        except Exception as e:
            logger.error(f"Failed to convert modern task {modern_data.id} to legacy: {str(e)}")
            raise AdaptationError(
                f"Task conversion failed: {str(e)}",
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
            # Try alternative formats
            for fmt in ["%Y-%m-%d", "%m/%d/%Y", "%d-%m-%Y"]:
                try:
                    return datetime.strptime(date_str, fmt)
                except ValueError:
                    continue
            logger.warning(f"Could not parse date: {date_str}")
            return None
    
    def _format_date(self, dt: Optional[datetime]) -> Optional[str]:
        """Format datetime to string."""
        if not dt:
            return None
        return dt.strftime(self._date_format)
    
    def _parse_tags(self, tags_str: Optional[str]) -> List[str]:
        """Parse comma-separated tags to list."""
        if not tags_str:
            return []
        return [tag.strip() for tag in tags_str.split(",") if tag.strip()]
    
    def _hours_to_minutes(self, hours: Optional[float]) -> Optional[int]:
        """Convert hours to minutes."""
        if hours is None:
            return None
        return int(hours * 60)
    
    def _minutes_to_hours(self, minutes: Optional[int]) -> Optional[float]:
        """Convert minutes to hours."""
        if minutes is None:
            return None
        return round(minutes / 60, 2)


class ModernTaskAdapter(TwoWayAdapter[ModernTask, LegacyTask]):
    """
    Reverse adapter for modern to legacy conversion.
    
    This is essentially the inverse of LegacyTaskAdapter.
    """
    
    def __init__(self, context: Optional[AdapterContext] = None):
        super().__init__(context)
        # Use the main adapter for reverse operations
        self._reverse_adapter = LegacyTaskAdapter(context)
    
    def to_modern(self, legacy_data: ModernTask) -> LegacyTask:
        """Convert modern task to legacy (delegates to reverse adapter)."""
        return self._reverse_adapter.to_legacy(legacy_data)
    
    def to_legacy(self, modern_data: LegacyTask) -> ModernTask:
        """Convert legacy task to modern (delegates to reverse adapter)."""
        return self._reverse_adapter.to_modern(modern_data)


class TaskBatchAdapter:
    """
    Adapter for batch processing of tasks.
    
    Handles migration of multiple tasks with progress tracking.
    """
    
    def __init__(self, adapter: LegacyTaskAdapter = None):
        self.adapter = adapter or LegacyTaskAdapter()
        self.results = {
            "success": [],
            "failed": [],
            "total": 0
        }
    
    def adapt_batch(
        self,
        legacy_tasks: List[LegacyTask],
        on_progress: Optional[callable] = None
    ) -> Dict[str, Any]:
        """
        Adapt a batch of legacy tasks to modern format.
        
        Args:
            legacy_tasks: List of legacy tasks
            on_progress: Optional callback for progress updates
            
        Returns:
            Dict with success/failure results
        """
        self.results = {
            "success": [],
            "failed": [],
            "total": len(legacy_tasks)
        }
        
        for i, task in enumerate(legacy_tasks):
            try:
                modern_task = self.adapter.to_modern(task)
                self.results["success"].append({
                    "legacy_id": task.task_id,
                    "modern_task": modern_task
                })
            except AdaptationError as e:
                self.results["failed"].append({
                    "legacy_id": task.task_id,
                    "error": str(e)
                })
            
            if on_progress:
                on_progress(i + 1, len(legacy_tasks))
        
        return self.results
    
    def get_summary(self) -> Dict[str, Any]:
        """Get batch processing summary."""
        return {
            "total": self.results["total"],
            "successful": len(self.results["success"]),
            "failed": len(self.results["failed"]),
            "success_rate": (
                len(self.results["success"]) / self.results["total"] * 100
                if self.results["total"] > 0 else 0
            )
        }
