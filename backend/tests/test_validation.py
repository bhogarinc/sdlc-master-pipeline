"""
Tests for Data Migration Validation Framework

Comprehensive test suite covering all validation components.
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from decimal import Decimal

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from app.validation.row_count_validator import RowCountValidator, RowCountResult
from app.validation.checksum_validator import ChecksumValidator, ChecksumResult
from app.validation.referential_integrity_validator import ReferentialIntegrityValidator, ReferentialIntegrityResult
from app.validation.business_rule_validator import BusinessRuleValidator, BusinessRuleResult, RuleSeverity
from app.validation.performance_monitor import PerformanceMonitor, PerformanceMetrics
from app.validation.rollback_verifier import RollbackVerifier, RollbackVerificationResult, RollbackStatus
from app.validation.migration_validator import MigrationValidator, MigrationValidationReport, ValidationPhase, MigrationStatus


# Fixtures
@pytest.fixture
def mock_source_session():
    """Create mock source database session."""
    session = AsyncMock()
    return session


@pytest.fixture
def mock_dest_session():
    """Create mock destination database session."""
    session = AsyncMock()
    return session


@pytest.fixture
def sample_row_data():
    """Sample row data for testing."""
    return {
        'id': 1,
        'name': 'Test User',
        'email': 'test@example.com',
        'created_at': datetime(2024, 1, 1, 12, 0, 0),
        'is_active': True,
        'metadata': {'role': 'admin'}
    }


# Row Count Validator Tests
class TestRowCountValidator:
    """Tests for RowCountValidator."""
    
    @pytest.mark.asyncio
    async def test_validate_table_exact_match(self, mock_source_session, mock_dest_session):
        """Test validation when row counts match exactly."""
        # Setup
        mock_source_session.execute.return_value.scalar.return_value = 100
        mock_dest_session.execute.return_value.scalar.return_value = 100
        
        validator = RowCountValidator(mock_source_session, mock_dest_session)
        
        # Execute
        result = await validator.validate_table('users')
        
        # Assert
        assert result.table_name == 'users'
        assert result.source_count == 100
        assert result.destination_count == 100
        assert result.difference == 0
        assert result.status == 'PASS'
        assert result.percentage_diff == 0.0
    
    @pytest.mark.asyncio
    async def test_validate_table_within_tolerance(self, mock_source_session, mock_dest_session):
        """Test validation when row count difference is within tolerance."""
        mock_source_session.execute.return_value.scalar.return_value = 10000
        mock_dest_session.execute.return_value.scalar.return_value = 10005  # 0.05% difference
        
        validator = RowCountValidator(mock_source_session, mock_dest_session)
        
        result = await validator.validate_table('team_members')  # 0.1% tolerance
        
        assert result.status == 'PASS'
        assert result.percentage_diff == 0.05
    
    @pytest.mark.asyncio
    async def test_validate_table_exceeds_tolerance(self, mock_source_session, mock_dest_session):
        """Test validation when row count difference exceeds tolerance."""
        mock_source_session.execute.return_value.scalar.return_value = 100
        mock_dest_session.execute.return_value.scalar.return_value = 95  # 5% difference
        
        validator = RowCountValidator(mock_source_session, mock_dest_session)
        
        result = await validator.validate_table('users')  # 0% tolerance
        
        assert result.status == 'FAIL'
        assert result.percentage_diff == 5.0
    
    @pytest.mark.asyncio
    async def test_validate_all_tables(self, mock_source_session, mock_dest_session):
        """Test validating multiple tables."""
        mock_source_session.execute.return_value.scalar.side_effect = [100, 50, 200]
        mock_dest_session.execute.return_value.scalar.side_effect = [100, 50, 200]
        
        validator = RowCountValidator(mock_source_session, mock_dest_session)
        
        results = await validator.validate_all_tables(['users', 'teams', 'tasks'])
        
        assert len(results) == 3
        assert all(r.status == 'PASS' for r in results)
    
    def test_get_summary(self, mock_source_session, mock_dest_session):
        """Test summary generation."""
        validator = RowCountValidator(mock_source_session, mock_dest_session)
        validator.results = [
            RowCountResult('users', 100, 100, 0, 0, 0, 'PASS', datetime.utcnow()),
            RowCountResult('teams', 50, 45, -5, 10, 0, 'FAIL', datetime.utcnow()),
            RowCountResult('tasks', 200, 201, 1, 0.5, 1, 'WARNING', datetime.utcnow()),
        ]
        
        summary = validator.get_summary()
        
        assert summary['total'] == 3
        assert summary['passed'] == 1
        assert summary['failed'] == 1
        assert summary['warnings'] == 1
        assert 'teams' in summary['tables_with_issues']


# Checksum Validator Tests
class TestChecksumValidator:
    """Tests for ChecksumValidator."""
    
    def test_serialize_value(self):
        """Test value serialization for hashing."""
        validator = ChecksumValidator(Mock(), Mock())
        
        assert validator._serialize_value(None) == 'NULL'
        assert validator._serialize_value(datetime(2024, 1, 1)) == '2024-01-01T00:00:00'
        assert validator._serialize_value(Decimal('10.5')) == '10.5'
        assert validator._serialize_value({'key': 'value'}) == '{"key": "value"}'
        assert validator._serialize_value('test') == 'test'
    
    def test_compute_row_hash(self):
        """Test row hash computation."""
        validator = ChecksumValidator(Mock(), Mock())
        
        row = {'id': 1, 'name': 'Test', 'value': None}
        hash1 = validator._compute_row_hash(row)
        hash2 = validator._compute_row_hash({'name': 'Test', 'id': 1, 'value': None})
        
        # Hash should be same regardless of key order
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 hex length
    
    @pytest.mark.asyncio
    async def test_validate_table_match(self, mock_source_session, mock_dest_session):
        """Test checksum validation when data matches."""
        # Setup mock to return same data
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = [
            {'id': 1, 'name': 'Test'},
            {'id': 2, 'name': 'Test2'}
        ]
        mock_source_session.execute.return_value = mock_result
        mock_dest_session.execute.return_value = mock_result
        
        validator = ChecksumValidator(mock_source_session, mock_dest_session)
        
        result = await validator.validate_table('users')
        
        assert result.status == 'MATCH'
        assert result.row_count == 2
    
    @pytest.mark.asyncio
    async def test_validate_table_mismatch(self, mock_source_session, mock_dest_session):
        """Test checksum validation when data differs."""
        source_result = MagicMock()
        source_result.mappings.return_value.all.return_value = [{'id': 1, 'name': 'Test'}]
        
        dest_result = MagicMock()
        dest_result.mappings.return_value.all.return_value = [{'id': 1, 'name': 'Different'}]
        
        mock_source_session.execute.return_value = source_result
        mock_dest_session.execute.return_value = dest_result
        
        validator = ChecksumValidator(mock_source_session, mock_dest_session)
        
        result = await validator.validate_table('users')
        
        assert result.status == 'MISMATCH'


# Referential Integrity Tests
class TestReferentialIntegrityValidator:
    """Tests for ReferentialIntegrityValidator."""
    
    @pytest.mark.asyncio
    async def test_validate_relationship_no_orphans(self, mock_source_session, mock_dest_session):
        """Test relationship validation with no orphaned records."""
        mock_result = MagicMock()
        mock_result.scalar.side_effect = [0, 100]  # 0 orphans, 100 total
        mock_dest_session.execute.return_value = mock_result
        
        validator = ReferentialIntegrityValidator(mock_source_session, mock_dest_session)
        
        result = await validator.validate_relationship(
            'users', 'id', 'tasks', 'created_by'
        )
        
        assert result.orphaned_count == 0
        assert result.status == 'PASS'
    
    @pytest.mark.asyncio
    async def test_validate_relationship_with_orphans(self, mock_source_session, mock_dest_session):
        """Test relationship validation with orphaned records."""
        mock_result = MagicMock()
        mock_result.scalar.side_effect = [5, 100]  # 5 orphans, 100 total
        mock_dest_session.execute.return_value = mock_result
        
        validator = ReferentialIntegrityValidator(mock_source_session, mock_dest_session)
        
        result = await validator.validate_relationship(
            'users', 'id', 'tasks', 'created_by'
        )
        
        assert result.orphaned_count == 5
        assert result.orphaned_percentage == 5.0
        assert result.status == 'FAIL'
    
    def test_has_failures(self, mock_source_session, mock_dest_session):
        """Test failure detection."""
        validator = ReferentialIntegrityValidator(mock_source_session, mock_dest_session)
        validator.results = [
            ReferentialIntegrityResult('test1', 'users', 'tasks', 'id', 'user_id', 0, 100, 0, 'PASS'),
            ReferentialIntegrityResult('test2', 'teams', 'tasks', 'id', 'team_id', 5, 100, 5, 'FAIL'),
        ]
        
        assert validator.has_failures()
        assert validator.get_failed_relationships() == ['test2']


# Business Rule Tests
class TestBusinessRuleValidator:
    """Tests for BusinessRuleValidator."""
    
    @pytest.mark.asyncio
    async def test_validate_email_format_valid(self, mock_dest_session):
        """Test email validation with valid emails."""
        mock_result = MagicMock()
        mock_result.scalar.side_effect = [0, 100]  # 0 violations, 100 total
        mock_dest_session.execute.return_value = mock_result
        
        validator = BusinessRuleValidator(mock_dest_session)
        
        result = await validator.validate_email_format()
        
        assert result.violation_count == 0
        assert result.status == 'PASS'
        assert result.severity == RuleSeverity.CRITICAL
    
    @pytest.mark.asyncio
    async def test_validate_email_format_invalid(self, mock_dest_session):
        """Test email validation with invalid emails."""
        mock_result = MagicMock()
        mock_result.scalar.side_effect = [5, 100]  # 5 violations
        mock_result.mappings.return_value.all.return_value = [
            {'id': 1, 'email': 'invalid-email'},
            {'id': 2, 'email': 'another@bad'},
        ]
        mock_dest_session.execute.return_value = mock_result
        
        validator = BusinessRuleValidator(mock_dest_session)
        
        result = await validator.validate_email_format()
        
        assert result.violation_count == 5
        assert result.status == 'FAIL'
    
    @pytest.mark.asyncio
    async def test_validate_task_status(self, mock_dest_session):
        """Test task status validation."""
        mock_result = MagicMock()
        mock_result.scalar.side_effect = [0, 50]
        mock_dest_session.execute.return_value = mock_result
        
        validator = BusinessRuleValidator(mock_dest_session)
        
        result = await validator.validate_task_status_transitions()
        
        assert result.rule_name == 'task_status_validation'
        assert result.status == 'PASS'


# Performance Monitor Tests
class TestPerformanceMonitor:
    """Tests for PerformanceMonitor."""
    
    def test_capture_baseline(self):
        """Test baseline metrics capture."""
        monitor = PerformanceMonitor('test_migration')
        
        with patch('psutil.cpu_percent', return_value=25.0), \
             patch('psutil.virtual_memory') as mock_mem:
            mock_mem.return_value.percent = 60.0
            monitor.capture_baseline()
        
        assert monitor._baseline_cpu == 25.0
        assert monitor._baseline_memory == 60.0
    
    def test_monitor_operation(self):
        """Test operation monitoring context manager."""
        monitor = PerformanceMonitor('test_migration')
        
        with patch('psutil.cpu_percent', return_value=30.0), \
             patch('psutil.virtual_memory') as mock_mem:
            mock_mem.return_value.percent = 65.0
            
            with monitor.monitor_operation('test_operation') as metrics:
                metrics.rows_processed = 1000
        
        assert 'test_operation' in monitor.report.table_metrics
        assert monitor.report.table_metrics['test_operation'].rows_processed == 1000
        assert monitor.report.total_rows_migrated == 1000
    
    def test_detect_bottlenecks(self):
        """Test bottleneck detection."""
        monitor = PerformanceMonitor('test_migration')
        
        # Add metrics with issues
        metrics = PerformanceMetrics(
            operation_name='slow_operation',
            start_time=datetime.utcnow(),
            rows_processed=100,  # Very slow
            duration_seconds=10.0
        )
        metrics.finalize()
        monitor.report.table_metrics['slow_operation'] = metrics
        
        bottlenecks = monitor.detect_bottlenecks()
        
        assert len(bottlenecks) > 0
        assert any('Low throughput' in b for b in bottlenecks)
    
    def test_sla_compliance(self):
        """Test SLA compliance checking."""
        monitor = PerformanceMonitor('test_migration')
        monitor.report.total_duration_seconds = 200  # Under 300s limit
        monitor.report.average_throughput = 2000  # Over 1000 rows/s
        monitor.report.peak_memory_usage = 70.0  # Under 80%
        monitor.report.peak_cpu_usage = 80.0  # Under 90%
        
        compliance = monitor.get_sla_compliance()
        
        assert compliance['downtime_sla_met']
        assert compliance['throughput_sla_met']
        assert compliance['memory_sla_met']
        assert compliance['cpu_sla_met']


# Rollback Verifier Tests
class TestRollbackVerifier:
    """Tests for RollbackVerifier."""
    
    @pytest.mark.asyncio
    async def test_capture_pre_migration_snapshot(self, mock_dest_session):
        """Test pre-migration snapshot capture."""
        mock_result = MagicMock()
        mock_result.scalar.side_effect = [100, 'abc123hash']  # count, checksum
        mock_result.fetchall.return_value = [(1,), (2,), (3,)]
        mock_dest_session.execute.return_value = mock_result
        
        verifier = RollbackVerifier(mock_dest_session, 'test_migration')
        
        snapshot = await verifier.capture_pre_migration_snapshot('users')
        
        assert snapshot['table_name'] == 'users'
        assert snapshot['row_count'] == 100
        assert snapshot['checksum'] == 'abc123hash'
        assert len(snapshot['keys']) == 3
    
    @pytest.mark.asyncio
    async def test_verify_rollback_success(self, mock_dest_session):
        """Test successful rollback verification."""
        mock_result = MagicMock()
        mock_result.scalar.side_effect = [100, 'abc123', 100, 'abc123']  # Pre and post match
        mock_dest_session.execute.return_value = mock_result
        
        verifier = RollbackVerifier(mock_dest_session, 'test_migration')
        
        # Manually set snapshot
        verifier._snapshots['pre_users'] = {
            'table_name': 'users',
            'row_count': 100,
            'checksum': 'abc123',
            'keys': {1, 2, 3},
            'captured_at': datetime.utcnow()
        }
        
        result = await verifier.verify_rollback('users')
        
        assert result.status == RollbackStatus.VERIFIED
        assert result.row_count_pre == result.row_count_rollback
    
    @pytest.mark.asyncio
    async def test_verify_rollback_failure(self, mock_dest_session):
        """Test failed rollback verification."""
        mock_result = MagicMock()
        mock_result.scalar.side_effect = [100, 'abc123', 95, 'xyz789']  # Don't match
        mock_dest_session.execute.return_value = mock_result
        
        verifier = RollbackVerifier(mock_dest_session, 'test_migration')
        
        verifier._snapshots['pre_users'] = {
            'table_name': 'users',
            'row_count': 100,
            'checksum': 'abc123',
            'keys': {1, 2, 3},
            'captured_at': datetime.utcnow()
        }
        
        result = await verifier.verify_rollback('users')
        
        assert result.status == RollbackStatus.FAILED
    
    def test_generate_report(self, mock_dest_session):
        """Test rollback report generation."""
        verifier = RollbackVerifier(mock_dest_session, 'test_migration')
        verifier.report.table_results = [
            RollbackVerificationResult(
                'users', 'hash1', 'hash2', 'hash1',
                RollbackStatus.VERIFIED, 100, 100, 100, datetime.utcnow()
            ),
            RollbackVerificationResult(
                'tasks', 'hash1', 'hash2', 'hash3',
                RollbackStatus.FAILED, 50, 50, 45, datetime.utcnow()
            ),
        ]
        
        report = verifier.generate_report()
        
        assert report.overall_status == RollbackStatus.FAILED
        assert report.summary['verified'] == 1
        assert report.summary['failed'] == 1


# Migration Validator Tests
class TestMigrationValidator:
    """Tests for MigrationValidator."""
    
    @pytest.mark.asyncio
    async def test_run_pre_migration_validation(self, mock_source_session, mock_dest_session):
        """Test pre-migration validation."""
        mock_result = MagicMock()
        mock_result.scalar.side_effect = [1, 0, 100]  # health check, locks, row count
        mock_source_session.execute.return_value = mock_result
        
        validator = MigrationValidator(
            'test_migration', mock_source_session, mock_dest_session
        )
        
        with patch.object(validator.rollback_verifier, 'capture_pre_migration_snapshot') as mock_snapshot:
            mock_snapshot.return_value = {
                'table_name': 'users',
                'row_count': 100,
                'checksum': 'abc123',
                'keys': set(),
                'captured_at': datetime.utcnow()
            }
            results = await validator.run_pre_migration_validation()
        
        assert 'source_health_check' in results
        assert 'baseline_snapshots' in results
    
    @pytest.mark.asyncio
    async def test_is_migration_valid_pass(self, mock_source_session, mock_dest_session):
        """Test migration validity check - pass."""
        validator = MigrationValidator(
            'test_migration', mock_source_session, mock_dest_session
        )
        
        validator.report.row_count_results = [
            {'table_name': 'users', 'status': 'PASS'}
        ]
        validator.report.checksum_results = [
            {'table_name': 'users', 'status': 'MATCH'}
        ]
        validator.report.referential_integrity = {'failed': 0}
        validator.report.business_rule_tests = [
            {'rule_name': 'test', 'status': 'PASS', 'severity': 'critical'}
        ]
        validator.report.status = MigrationStatus.VALIDATED
        
        assert validator.is_migration_valid()
    
    @pytest.mark.asyncio
    async def test_is_migration_valid_fail(self, mock_source_session, mock_dest_session):
        """Test migration validity check - fail."""
        validator = MigrationValidator(
            'test_migration', mock_source_session, mock_dest_session
        )
        
        validator.report.row_count_results = [
            {'table_name': 'users', 'status': 'FAIL'}
        ]
        
        assert not validator.is_migration_valid()
    
    def test_get_validation_errors(self, mock_source_session, mock_dest_session):
        """Test error extraction."""
        validator = MigrationValidator(
            'test_migration', mock_source_session, mock_dest_session
        )
        
        validator.report.row_count_results = [
            {'table_name': 'users', 'status': 'FAIL', 'details': 'Count mismatch'}
        ]
        validator.report.checksum_results = [
            {'table_name': 'teams', 'status': 'MISMATCH'}
        ]
        validator.report.referential_integrity = {'failed': 1}
        validator.report.business_rule_tests = [
            {'rule_name': 'email_validation', 'status': 'FAIL', 'severity': 'critical'}
        ]
        
        errors = validator.get_validation_errors()
        
        assert len(errors) == 4
        assert any('users' in e for e in errors)
        assert any('teams' in e for e in errors)
        assert any('email_validation' in e for e in errors)


# Integration Tests
@pytest.mark.integration
class TestIntegration:
    """Integration tests requiring actual database."""
    
    @pytest.mark.skip(reason="Requires database connection")
    @pytest.mark.asyncio
    async def test_full_validation_workflow(self):
        """Test complete validation workflow."""
        # This would require actual database connections
        pass


# Main entry point for running tests
if __name__ == '__main__':
    pytest.main([__file__, '-v'])