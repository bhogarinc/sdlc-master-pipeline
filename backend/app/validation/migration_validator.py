"""
Migration Validator - Main Orchestrator

Coordinates all validation activities during data migration.
Provides unified interface for comprehensive migration validation.
"""

import logging
import asyncio
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime
from enum import Enum

from sqlalchemy.ext.asyncio import AsyncSession

from .row_count_validator import RowCountValidator
from .checksum_validator import ChecksumValidator
from .referential_integrity_validator import ReferentialIntegrityValidator
from .business_rule_validator import BusinessRuleValidator
from .performance_monitor import PerformanceMonitor
from .rollback_verifier import RollbackVerifier

logger = logging.getLogger(__name__)


class ValidationPhase(Enum):
    """Phases of migration validation."""
    PRE_MIGRATION = "pre_migration"
    DURING_MIGRATION = "during_migration"
    POST_MIGRATION = "post_migration"
    ROLLBACK_VERIFICATION = "rollback_verification"


class MigrationStatus(Enum):
    """Overall migration status."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    VALIDATED = "validated"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


@dataclass
class MigrationValidationReport:
    """Comprehensive migration validation report."""
    migration_id: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    status: MigrationStatus = MigrationStatus.PENDING
    phase: ValidationPhase = ValidationPhase.PRE_MIGRATION
    
    # Individual validation results
    row_count_results: List[Dict] = field(default_factory=list)
    checksum_results: List[Dict] = field(default_factory=list)
    referential_integrity: Dict = field(default_factory=dict)
    business_rule_tests: List[Dict] = field(default_factory=list)
    performance_metrics: Dict = field(default_factory=dict)
    rollback_verified: bool = False
    
    # Summaries
    summary: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        """Convert report to dictionary format."""
        return {
            'migration_id': self.migration_id,
            'started_at': self.started_at.isoformat(),
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'status': self.status.value,
            'phase': self.phase.value,
            'row_count_checks': self.row_count_results,
            'checksum_results': self.checksum_results,
            'referential_integrity': self.referential_integrity,
            'business_rule_tests': self.business_rule_tests,
            'performance_metrics': self.performance_metrics,
            'rollback_verified': self.rollback_verified,
            'overall_status': self._determine_overall_status(),
            'summary': self.summary
        }
    
    def _determine_overall_status(self) -> str:
        """Determine overall migration status."""
        if self.status == MigrationStatus.ROLLED_BACK:
            return 'rolled_back'
        elif self.status == MigrationStatus.FAILED:
            return 'fail'
        elif any(r.get('status') == 'FAIL' for r in self.row_count_results):
            return 'fail'
        elif any(r.get('status') == 'MISMATCH' for r in self.checksum_results):
            return 'fail'
        elif self.referential_integrity.get('failed', 0) > 0:
            return 'fail'
        elif any(r.get('status') == 'FAIL' for r in self.business_rule_tests):
            return 'fail'
        elif any(r.get('status') == 'WARNING' for r in self.row_count_results):
            return 'warning'
        elif any(r.get('status') == 'WARNING' for r in self.business_rule_tests):
            return 'warning'
        elif self.status == MigrationStatus.VALIDATED:
            return 'pass'
        else:
            return 'pending'


class MigrationValidator:
    """
    Main orchestrator for migration validation.
    
    Coordinates all validation activities:
    1. Pre-migration: Capture baseline snapshots
    2. During migration: Monitor performance
    3. Post-migration: Validate data integrity
    4. Rollback verification: Ensure rollback works
    """
    
    # Core tables in TaskFlow Pro
    CORE_TABLES = [
        'users', 'teams', 'team_members', 'boards', 'columns',
        'tasks', 'task_assignees', 'comments', 'attachments',
        'notifications', 'user_preferences', 'password_reset_tokens'
    ]
    
    def __init__(
        self,
        migration_id: str,
        source_session: AsyncSession,
        destination_session: AsyncSession,
        config: Optional[Dict] = None
    ):
        self.migration_id = migration_id
        self.source_session = source_session
        self.destination_session = destination_session
        self.config = config or {}
        
        self.report = MigrationValidationReport(
            migration_id=migration_id,
            started_at=datetime.utcnow()
        )
        
        # Initialize validators
        self.row_count_validator = RowCountValidator(
            source_session, destination_session
        )
        self.checksum_validator = ChecksumValidator(
            source_session, destination_session
        )
        self.referential_integrity_validator = ReferentialIntegrityValidator(
            source_session, destination_session
        )
        self.business_rule_validator = BusinessRuleValidator(
            destination_session
        )
        self.performance_monitor = PerformanceMonitor(migration_id)
        self.rollback_verifier = RollbackVerifier(
            destination_session, migration_id
        )
        
    async def run_pre_migration_validation(self) -> Dict:
        """
        Run pre-migration validation checks.
        
        Captures baseline state and verifies source database health.
        """
        logger.info(f"Running pre-migration validation for {self.migration_id}")
        self.report.phase = ValidationPhase.PRE_MIGRATION
        
        results = {
            'source_health_check': await self._check_source_health(),
            'baseline_snapshots': {},
            'estimated_row_counts': {}
        }
        
        # Capture baseline snapshots for rollback verification
        for table in self.CORE_TABLES:
            try:
                snapshot = await self.rollback_verifier.capture_pre_migration_snapshot(table)
                results['baseline_snapshots'][table] = {
                    'row_count': snapshot['row_count'],
                    'checksum': snapshot['checksum'][:16] + '...'
                }
            except Exception as e:
                logger.error(f"Failed to capture snapshot for {table}: {e}")
                results['baseline_snapshots'][table] = {'error': str(e)}
        
        # Get estimated row counts
        for table in self.CORE_TABLES:
            try:
                count_result = await self.source_session.execute(
                    f"SELECT COUNT(*) FROM {table}"
                )
                results['estimated_row_counts'][table] = count_result.scalar()
            except Exception as e:
                logger.error(f"Failed to get row count for {table}: {e}")
        
        return results
    
    async def run_post_migration_validation(
        self,
        validate_checksums: bool = True,
        validate_referential: bool = True,
        validate_business_rules: bool = True
    ) -> MigrationValidationReport:
        """
        Run comprehensive post-migration validation.
        
        Args:
            validate_checksums: Whether to validate data checksums
            validate_referential: Whether to validate referential integrity
            validate_business_rules: Whether to validate business rules
            
        Returns:
            Complete migration validation report
        """
        logger.info(f"Running post-migration validation for {self.migration_id}")
        self.report.phase = ValidationPhase.POST_MIGRATION
        self.report.status = MigrationStatus.IN_PROGRESS
        
        # 1. Row Count Validation
        logger.info("Starting row count validation...")
        with self.performance_monitor.monitor_operation('row_count_validation'):
            row_results = await self.row_count_validator.validate_all_tables(
                self.CORE_TABLES
            )
            self.report.row_count_results = [
                {
                    'table_name': r.table_name,
                    'source_count': r.source_count,
                    'destination_count': r.destination_count,
                    'difference': r.difference,
                    'percentage_diff': r.percentage_diff,
                    'status': r.status,
                    'details': r.details
                }
                for r in row_results
            ]
        
        # 2. Checksum Validation
        if validate_checksums:
            logger.info("Starting checksum validation...")
            with self.performance_monitor.monitor_operation('checksum_validation'):
                # Validate critical tables with full checksums
                critical_tables = ['users', 'teams', 'tasks', 'boards']
                for table in critical_tables:
                    await self.checksum_validator.validate_table(table)
                
                # Validate large tables with partitioning
                large_tables = ['comments', 'notifications', 'attachments']
                for table in large_tables:
                    await self.checksum_validator.validate_table(
                        table, use_partitioning=True
                    )
                
                self.report.checksum_results = [
                    {
                        'table_name': r.table_name,
                        'source_checksum': r.source_checksum[:16] + '...',
                        'destination_checksum': r.destination_checksum[:16] + '...',
                        'status': r.status,
                        'row_count': r.row_count,
                        'details': r.details
                    }
                    for r in self.checksum_validator.results
                ]
        
        # 3. Referential Integrity Validation
        if validate_referential:
            logger.info("Starting referential integrity validation...")
            with self.performance_monitor.monitor_operation('referential_integrity'):
                await self.referential_integrity_validator.validate_all_relationships()
                self.report.referential_integrity = self.referential_integrity_validator.get_summary()
        
        # 4. Business Rule Validation
        if validate_business_rules:
            logger.info("Starting business rule validation...")
            with self.performance_monitor.monitor_operation('business_rules'):
                await self.business_rule_validator.validate_all_rules()
                self.report.business_rule_tests = [
                    {
                        'rule_name': r.rule_name,
                        'severity': r.severity.value,
                        'violation_count': r.violation_count,
                        'total_checked': r.total_checked,
                        'status': r.status,
                        'details': r.details
                    }
                    for r in self.business_rule_validator.results
                ]
        
        # 5. Capture Performance Metrics
        performance_report = self.performance_monitor.finalize_report()
        self.report.performance_metrics = {
            'total_duration_seconds': performance_report.total_duration_seconds,
            'total_rows_migrated': performance_report.total_rows_migrated,
            'average_throughput': performance_report.average_throughput,
            'peak_memory_usage': performance_report.peak_memory_usage,
            'peak_cpu_usage': performance_report.peak_cpu_usage,
            'bottlenecks': performance_report.bottlenecks,
            'recommendations': performance_report.recommendations,
            'table_metrics': {
                name: {
                    'duration_seconds': m.duration_seconds,
                    'rows_processed': m.rows_processed,
                    'rows_per_second': m.rows_per_second
                }
                for name, m in performance_report.table_metrics.items()
            }
        }
        
        # 6. Capture post-migration snapshots for rollback
        for table in self.CORE_TABLES:
            try:
                await self.rollback_verifier.capture_post_migration_state(table)
            except Exception as e:
                logger.error(f"Failed to capture post-migration state for {table}: {e}")
        
        # Finalize report
        self.report.completed_at = datetime.utcnow()
        self.report.status = MigrationStatus.VALIDATED
        self._generate_summary()
        
        return self.report
    
    async def verify_rollback(self) -> bool:
        """
        Verify that rollback procedure correctly restores data.
        
        Returns:
            True if rollback is verified, False otherwise
        """
        logger.info(f"Verifying rollback for {self.migration_id}")
        self.report.phase = ValidationPhase.ROLLBACK_VERIFICATION
        
        # Run rollback verification
        await self.rollback_verifier.verify_all_tables(self.CORE_TABLES)
        
        # Generate report
        rollback_report = self.rollback_verifier.generate_report()
        
        self.report.rollback_verified = self.rollback_verifier.is_rollback_verified()
        
        if not self.report.rollback_verified:
            failed_tables = self.rollback_verifier.get_failed_tables()
            logger.error(f"Rollback verification failed for tables: {failed_tables}")
        
        return self.report.rollback_verified
    
    async def _check_source_health(self) -> Dict:
        """Check health of source database before migration."""
        try:
            # Test connection
            result = await self.source_session.execute("SELECT 1")
            connection_ok = result.scalar() == 1
            
            # Check for locks
            locks_result = await self.source_session.execute("""
                SELECT COUNT(*) FROM pg_locks 
                WHERE NOT granted
            """)
            waiting_locks = locks_result.scalar()
            
            # Check disk space
            # This would need to be adapted for your specific database
            
            return {
                'connection_ok': connection_ok,
                'waiting_locks': waiting_locks,
                'healthy': connection_ok and waiting_locks < 10
            }
        except Exception as e:
            logger.error(f"Source health check failed: {e}")
            return {'connection_ok': False, 'error': str(e), 'healthy': False}
    
    def _generate_summary(self):
        """Generate summary of validation results."""
        row_summary = self.row_count_validator.get_summary()
        checksum_summary = self.checksum_validator.get_summary()
        referential_summary = self.referential_integrity_validator.get_summary()
        business_summary = self.business_rule_validator.get_summary()
        
        self.report.summary = {
            'row_count_validation': row_summary,
            'checksum_validation': checksum_summary,
            'referential_integrity': referential_summary,
            'business_rules': business_summary,
            'total_issues': (
                row_summary.get('failed', 0) +
                checksum_summary.get('mismatched', 0) +
                referential_summary.get('failed', 0) +
                business_summary.get('failed', 0)
            ),
            'total_warnings': (
                row_summary.get('warnings', 0) +
                business_summary.get('warnings', 0)
            )
        }
    
    def is_migration_valid(self) -> bool:
        """Check if migration passed all validations."""
        return self.report._determine_overall_status() == 'pass'
    
    def get_validation_errors(self) -> List[str]:
        """Get list of validation errors."""
        errors = []
        
        # Row count errors
        for result in self.report.row_count_results:
            if result['status'] in ('FAIL', 'ERROR'):
                errors.append(f"Row count mismatch in {result['table_name']}: {result['details']}")
        
        # Checksum errors
        for result in self.report.checksum_results:
            if result['status'] == 'MISMATCH':
                errors.append(f"Checksum mismatch in {result['table_name']}")
        
        # Referential integrity errors
        if self.report.referential_integrity.get('failed', 0) > 0:
            errors.append(f"Referential integrity failures: {self.report.referential_integrity['failed']}")
        
        # Business rule errors
        for result in self.report.business_rule_tests:
            if result['status'] == 'FAIL' and result['severity'] == 'critical':
                errors.append(f"Critical business rule violation: {result['rule_name']}")
        
        return errors
    
    def get_report(self) -> Dict:
        """Get complete validation report as dictionary."""
        return self.report.to_dict()
    
    def get_report_json(self) -> str:
        """Get validation report as JSON string."""
        import json
        return json.dumps(self.report.to_dict(), indent=2, default=str)