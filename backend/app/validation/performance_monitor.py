"""
Performance Monitoring Module

Tracks migration performance metrics including:
- Migration speed (rows/second)
- System resource utilization
- Downtime measurements
- Throughput bottlenecks
"""

import logging
import time
import psutil
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable
from datetime import datetime, timedelta
from contextlib import contextmanager

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass
class PerformanceMetrics:
    """Performance metrics for a migration operation."""
    operation_name: str
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_seconds: float = 0.0
    rows_processed: int = 0
    rows_per_second: float = 0.0
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    disk_io_read_mb: float = 0.0
    disk_io_write_mb: float = 0.0
    errors_encountered: int = 0
    warning_count: int = 0
    
    def finalize(self):
        """Finalize metrics after operation completes."""
        if self.end_time is None:
            self.end_time = datetime.utcnow()
        self.duration_seconds = (self.end_time - self.start_time).total_seconds()
        if self.duration_seconds > 0:
            self.rows_per_second = self.rows_processed / self.duration_seconds


@dataclass
class MigrationPerformanceReport:
    """Comprehensive performance report for entire migration."""
    migration_id: str
    start_time: datetime
    end_time: Optional[datetime] = None
    total_duration_seconds: float = 0.0
    total_rows_migrated: int = 0
    average_throughput: float = 0.0
    peak_memory_usage: float = 0.0
    peak_cpu_usage: float = 0.0
    estimated_downtime_seconds: float = 0.0
    actual_downtime_seconds: float = 0.0
    table_metrics: Dict[str, PerformanceMetrics] = field(default_factory=dict)
    bottlenecks: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    
    def finalize(self):
        """Finalize report after migration completes."""
        if self.end_time is None:
            self.end_time = datetime.utcnow()
        self.total_duration_seconds = (self.end_time - self.start_time).total_seconds()
        
        if self.total_duration_seconds > 0:
            self.average_throughput = self.total_rows_migrated / self.total_duration_seconds
        
        # Calculate peak usage
        for metrics in self.table_metrics.values():
            self.peak_memory_usage = max(self.peak_memory_usage, metrics.memory_percent)
            self.peak_cpu_usage = max(self.peak_cpu_usage, metrics.cpu_percent)


class PerformanceMonitor:
    """
    Monitors migration performance in real-time.
    
    Tracks:
    - Throughput (rows/second)
    - Resource utilization (CPU, memory, disk)
    - Operation timing
    - Bottleneck detection
    """
    
    # Performance thresholds
    SLA_THRESHOLDS = {
        'max_downtime_seconds': 300,  # 5 minutes
        'min_throughput_rows_per_second': 1000,
        'max_memory_percent': 80.0,
        'max_cpu_percent': 90.0,
    }
    
    def __init__(self, migration_id: str):
        self.migration_id = migration_id
        self.report = MigrationPerformanceReport(
            migration_id=migration_id,
            start_time=datetime.utcnow()
        )
        self.current_metrics: Optional[PerformanceMetrics] = None
        self._process = psutil.Process()
        self._baseline_cpu = None
        self._baseline_memory = None
        
    def capture_baseline(self):
        """Capture baseline system metrics before migration."""
        self._baseline_cpu = psutil.cpu_percent(interval=1)
        self._baseline_memory = psutil.virtual_memory().percent
        logger.info(
            f"Baseline metrics captured: CPU={self._baseline_cpu}%, "
            f"Memory={self._baseline_memory}%"
        )
    
    def _capture_system_metrics(self, metrics: PerformanceMetrics):
        """Capture current system metrics."""
        try:
            metrics.cpu_percent = psutil.cpu_percent(interval=0.1)
            metrics.memory_percent = psutil.virtual_memory().percent
            
            # Disk I/O
            disk_io = psutil.disk_io_counters()
            if disk_io:
                metrics.disk_io_read_mb = disk_io.read_bytes / (1024 * 1024)
                metrics.disk_io_write_mb = disk_io.write_bytes / (1024 * 1024)
        except Exception as e:
            logger.warning(f"Failed to capture system metrics: {e}")
    
    @contextmanager
    def monitor_operation(self, operation_name: str):
        """
        Context manager for monitoring a migration operation.
        
        Usage:
            with monitor.monitor_operation('migrate_users'):
                # Perform migration
                pass
        """
        metrics = PerformanceMetrics(
            operation_name=operation_name,
            start_time=datetime.utcnow()
        )
        self.current_metrics = metrics
        
        logger.info(f"Starting performance monitoring for: {operation_name}")
        
        try:
            yield metrics
        finally:
            metrics.end_time = datetime.utcnow()
            metrics.finalize()
            self._capture_system_metrics(metrics)
            
            self.report.table_metrics[operation_name] = metrics
            self.report.total_rows_migrated += metrics.rows_processed
            
            logger.info(
                f"Operation {operation_name} completed: "
                f"{metrics.rows_processed} rows in {metrics.duration_seconds:.2f}s "
                f"({metrics.rows_per_second:.2f} rows/s)"
            )
            
            self.current_metrics = None
    
    def update_progress(self, rows_processed: int, increment: bool = True):
        """Update progress for current operation."""
        if self.current_metrics:
            if increment:
                self.current_metrics.rows_processed += rows_processed
            else:
                self.current_metrics.rows_processed = rows_processed
    
    def record_error(self, error_message: str):
        """Record an error during migration."""
        if self.current_metrics:
            self.current_metrics.errors_encountered += 1
        logger.error(f"Migration error: {error_message}")
    
    def record_warning(self, warning_message: str):
        """Record a warning during migration."""
        if self.current_metrics:
            self.current_metrics.warning_count += 1
        logger.warning(f"Migration warning: {warning_message}")
    
    def detect_bottlenecks(self) -> List[str]:
        """Detect performance bottlenecks from collected metrics."""
        bottlenecks = []
        
        for operation_name, metrics in self.report.table_metrics.items():
            # Check throughput
            if metrics.rows_per_second < self.SLA_THRESHOLDS['min_throughput_rows_per_second']:
                bottlenecks.append(
                    f"{operation_name}: Low throughput ({metrics.rows_per_second:.2f} rows/s)"
                )
            
            # Check memory usage
            if metrics.memory_percent > self.SLA_THRESHOLDS['max_memory_percent']:
                bottlenecks.append(
                    f"{operation_name}: High memory usage ({metrics.memory_percent:.1f}%)"
                )
            
            # Check CPU usage
            if metrics.cpu_percent > self.SLA_THRESHOLDS['max_cpu_percent']:
                bottlenecks.append(
                    f"{operation_name}: High CPU usage ({metrics.cpu_percent:.1f}%)"
                )
            
            # Check for errors
            if metrics.errors_encountered > 0:
                bottlenecks.append(
                    f"{operation_name}: {metrics.errors_encountered} errors encountered"
                )
        
        self.report.bottlenecks = bottlenecks
        return bottlenecks
    
    def generate_recommendations(self) -> List[str]:
        """Generate performance improvement recommendations."""
        recommendations = []
        
        # Analyze bottlenecks
        for bottleneck in self.report.bottlenecks:
            if 'Low throughput' in bottleneck:
                recommendations.append(
                    "Consider increasing batch size or parallelizing table migrations"
                )
            elif 'High memory' in bottleneck:
                recommendations.append(
                    "Consider processing tables in smaller chunks or reducing batch size"
                )
            elif 'High CPU' in bottleneck:
                recommendations.append(
                    "Consider throttling migration to reduce CPU load"
                )
            elif 'errors' in bottleneck:
                recommendations.append(
                    "Review error logs and fix data quality issues before re-migration"
                )
        
        # Check overall performance
        if self.report.average_throughput < self.SLA_THRESHOLDS['min_throughput_rows_per_second']:
            recommendations.append(
                f"Overall throughput ({self.report.average_throughput:.2f} rows/s) is below SLA. "
                "Consider optimizing database indexes or increasing resources."
            )
        
        if self.report.estimated_downtime_seconds > self.SLA_THRESHOLDS['max_downtime_seconds']:
            recommendations.append(
                f"Estimated downtime ({self.report.estimated_downtime_seconds}s) exceeds SLA. "
                "Consider using blue-green deployment or incremental migration."
            )
        
        self.report.recommendations = list(set(recommendations))  # Remove duplicates
        return self.report.recommendations
    
    def get_sla_compliance(self) -> Dict:
        """Check SLA compliance for the migration."""
        return {
            'downtime_sla_met': (
                self.report.actual_downtime_seconds <= 
                self.SLA_THRESHOLDS['max_downtime_seconds']
            ),
            'throughput_sla_met': (
                self.report.average_throughput >= 
                self.SLA_THRESHOLDS['min_throughput_rows_per_second']
            ),
            'memory_sla_met': (
                self.report.peak_memory_usage <= 
                self.SLA_THRESHOLDS['max_memory_percent']
            ),
            'cpu_sla_met': (
                self.report.peak_cpu_usage <= 
                self.SLA_THRESHOLDS['max_cpu_percent']
            ),
            'error_free': all(
                m.errors_encountered == 0 
                for m in self.report.table_metrics.values()
            ),
        }
    
    def finalize_report(self) -> MigrationPerformanceReport:
        """Finalize and return the complete performance report."""
        self.report.finalize()
        self.detect_bottlenecks()
        self.generate_recommendations()
        
        logger.info(
            f"Migration {self.migration_id} performance report finalized: "
            f"{self.report.total_rows_migrated} rows in "
            f"{self.report.total_duration_seconds:.2f}s"
        )
        
        return self.report
    
    def get_real_time_stats(self) -> Dict:
        """Get real-time migration statistics."""
        if not self.current_metrics:
            return {'status': 'idle'}
        
        elapsed = (datetime.utcnow() - self.current_metrics.start_time).total_seconds()
        
        return {
            'status': 'running',
            'current_operation': self.current_metrics.operation_name,
            'rows_processed': self.current_metrics.rows_processed,
            'elapsed_seconds': elapsed,
            'current_throughput': (
                self.current_metrics.rows_processed / elapsed if elapsed > 0 else 0
            ),
            'total_rows_migrated': self.report.total_rows_migrated,
        }
    
    def estimate_remaining_time(self, remaining_rows: int) -> timedelta:
        """Estimate remaining migration time based on current throughput."""
        if self.report.average_throughput > 0:
            seconds_remaining = remaining_rows / self.report.average_throughput
            return timedelta(seconds=seconds_remaining)
        return timedelta.max