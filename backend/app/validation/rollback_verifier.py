"""
Rollback Verification Module

Verifies that rollback procedures restore data to pre-migration state.
Ensures data integrity is maintained during rollback operations.
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Any
from datetime import datetime
from enum import Enum

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class RollbackStatus(Enum):
    """Status of rollback verification."""
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    VERIFIED = "verified"
    FAILED = "failed"
    PARTIAL = "partial"


@dataclass
class RollbackVerificationResult:
    """Result of rollback verification."""
    table_name: str
    pre_migration_checksum: str
    post_migration_checksum: str
    post_rollback_checksum: str
    status: RollbackStatus
    row_count_pre: int
    row_count_post: int
    row_count_rollback: int
    verified_at: datetime
    differences: Optional[List[Dict]] = None
    details: Optional[str] = None


@dataclass
class RollbackReport:
    """Comprehensive rollback verification report."""
    migration_id: str
    rollback_id: str
    start_time: datetime
    end_time: Optional[datetime] = None
    overall_status: RollbackStatus = RollbackStatus.NOT_STARTED
    table_results: List[RollbackVerificationResult] = None
    summary: Dict = None
    
    def __post_init__(self):
        if self.table_results is None:
            self.table_results = []


class RollbackVerifier:
    """
    Verifies that rollback procedures correctly restore data.
    
    Performs:
    - Pre-migration snapshot capture
    - Post-migration state recording
    - Post-rollback verification
    - Data integrity comparison
    """
    
    def __init__(
        self,
        session: AsyncSession,
        migration_id: str,
        backup_prefix: str = "rollback_backup"
    ):
        self.session = session
        self.migration_id = migration_id
        self.backup_prefix = backup_prefix
        self.report = RollbackReport(
            migration_id=migration_id,
            rollback_id=f"rollback_{migration_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
            start_time=datetime.utcnow()
        )
        self._snapshots: Dict[str, Dict] = {}
        
    async def capture_pre_migration_snapshot(
        self,
        table_name: str,
        key_column: str = 'id'
    ) -> Dict:
        """
        Capture pre-migration state snapshot for a table.
        
        Args:
            table_name: Table to snapshot
            key_column: Primary key column for row identification
            
        Returns:
            Snapshot data including checksums and row counts
        """
        logger.info(f"Capturing pre-migration snapshot for {table_name}")
        
        # Get row count
        count_query = f"SELECT COUNT(*) FROM {table_name}"
        count_result = await self.session.execute(text(count_query))
        row_count = count_result.scalar()
        
        # Get table checksum
        checksum_query = f"""
            SELECT MD5(string_agg(
                {key_column}::text || '|' || 
                extract(epoch from coalesce(updated_at, created_at))::text,
                ',' ORDER BY {key_column}
            )) as checksum
            FROM {table_name}
        """
        checksum_result = await self.session.execute(text(checksum_query))
        checksum = checksum_result.scalar() or ""
        
        # Get key values for detailed comparison
        keys_query = f"SELECT {key_column} FROM {table_name} ORDER BY {key_column}"
        keys_result = await self.session.execute(text(keys_query))
        keys = [row[0] for row in keys_result.fetchall()]
        
        snapshot = {
            'table_name': table_name,
            'row_count': row_count,
            'checksum': checksum,
            'keys': set(keys),
            'captured_at': datetime.utcnow(),
        }
        
        self._snapshots[f"pre_{table_name}"] = snapshot
        
        logger.info(
            f"Pre-migration snapshot captured for {table_name}: "
            f"{row_count} rows, checksum: {checksum[:16]}..."
        )
        
        return snapshot
    
    async def capture_post_migration_state(
        self,
        table_name: str,
        key_column: str = 'id'
    ) -> Dict:
        """Capture post-migration state for comparison."""
        logger.info(f"Capturing post-migration state for {table_name}")
        
        # Get row count
        count_query = f"SELECT COUNT(*) FROM {table_name}"
        count_result = await self.session.execute(text(count_query))
        row_count = count_result.scalar()
        
        # Get table checksum
        checksum_query = f"""
            SELECT MD5(string_agg(
                {key_column}::text || '|' || 
                extract(epoch from coalesce(updated_at, created_at))::text,
                ',' ORDER BY {key_column}
            )) as checksum
            FROM {table_name}
        """
        checksum_result = await self.session.execute(text(checksum_query))
        checksum = checksum_result.scalar() or ""
        
        snapshot = {
            'table_name': table_name,
            'row_count': row_count,
            'checksum': checksum,
            'captured_at': datetime.utcnow(),
        }
        
        self._snapshots[f"post_{table_name}"] = snapshot
        return snapshot
    
    async def verify_rollback(
        self,
        table_name: str,
        key_column: str = 'id',
        detailed_comparison: bool = False
    ) -> RollbackVerificationResult:
        """
        Verify that rollback restored table to pre-migration state.
        
        Args:
            table_name: Table to verify
            key_column: Primary key column
            detailed_comparison: Whether to perform detailed row comparison
            
        Returns:
            RollbackVerificationResult with verification details
        """
        logger.info(f"Verifying rollback for {table_name}")
        
        pre_snapshot = self._snapshots.get(f"pre_{table_name}")
        post_snapshot = self._snapshots.get(f"post_{table_name}")
        
        if not pre_snapshot:
            raise ValueError(f"No pre-migration snapshot found for {table_name}")
        
        # Get current (post-rollback) state
        count_query = f"SELECT COUNT(*) FROM {table_name}"
        count_result = await self.session.execute(text(count_query))
        current_row_count = count_result.scalar()
        
        checksum_query = f"""
            SELECT MD5(string_agg(
                {key_column}::text || '|' || 
                extract(epoch from coalesce(updated_at, created_at))::text,
                ',' ORDER BY {key_column}
            )) as checksum
            FROM {table_name}
        """
        checksum_result = await self.session.execute(text(checksum_query))
        current_checksum = checksum_result.scalar() or ""
        
        # Compare with pre-migration state
        checksum_match = pre_snapshot['checksum'] == current_checksum
        row_count_match = pre_snapshot['row_count'] == current_row_count
        
        differences = []
        
        if detailed_comparison and not checksum_match:
            differences = await self._find_differences(
                table_name, key_column, pre_snapshot['keys']
            )
        
        # Determine status
        if checksum_match and row_count_match:
            status = RollbackStatus.VERIFIED
            details = f"Rollback verified: {table_name} matches pre-migration state"
        elif row_count_match:
            status = RollbackStatus.PARTIAL
            details = f"Rollback partial: {table_name} row count matches but checksum differs"
        else:
            status = RollbackStatus.FAILED
            details = (
                f"Rollback failed: {table_name} does not match pre-migration state. "
                f"Expected {pre_snapshot['row_count']} rows, found {current_row_count}"
            )
        
        result = RollbackVerificationResult(
            table_name=table_name,
            pre_migration_checksum=pre_snapshot['checksum'],
            post_migration_checksum=post_snapshot['checksum'] if post_snapshot else "",
            post_rollback_checksum=current_checksum,
            status=status,
            row_count_pre=pre_snapshot['row_count'],
            row_count_post=post_snapshot['row_count'] if post_snapshot else 0,
            row_count_rollback=current_row_count,
            verified_at=datetime.utcnow(),
            differences=differences,
            details=details
        )
        
        self.report.table_results.append(result)
        
        logger.info(f"Rollback verification for {table_name}: {status.value}")
        
        return result
    
    async def _find_differences(
        self,
        table_name: str,
        key_column: str,
        expected_keys: set
    ) -> List[Dict]:
        """Find specific differences between expected and actual state."""
        differences = []
        
        # Get current keys
        keys_query = f"SELECT {key_column} FROM {table_name} ORDER BY {key_column}"
        keys_result = await self.session.execute(text(keys_query))
        current_keys = set(row[0] for row in keys_result.fetchall())
        
        # Find missing keys
        missing_keys = expected_keys - current_keys
        for key in list(missing_keys)[:10]:  # Limit to 10 examples
            differences.append({
                'type': 'MISSING_ROW',
                'key': key,
                'description': f'Row with {key_column}={key} missing after rollback'
            })
        
        # Find extra keys
        extra_keys = current_keys - expected_keys
        for key in list(extra_keys)[:10]:
            differences.append({
                'type': 'EXTRA_ROW',
                'key': key,
                'description': f'Unexpected row with {key_column}={key} after rollback'
            })
        
        return differences
    
    async def verify_all_tables(
        self,
        tables: List[str],
        detailed_comparison: bool = False
    ) -> List[RollbackVerificationResult]:
        """
        Verify rollback for all specified tables.
        
        Args:
            tables: List of table names to verify
            detailed_comparison: Whether to perform detailed comparison
            
        Returns:
            List of verification results
        """
        logger.info(f"Starting rollback verification for {len(tables)} tables")
        
        for table_name in tables:
            try:
                await self.verify_rollback(table_name, detailed_comparison=detailed_comparison)
            except Exception as e:
                logger.error(f"Failed to verify rollback for {table_name}: {e}")
                self.report.table_results.append(RollbackVerificationResult(
                    table_name=table_name,
                    pre_migration_checksum="",
                    post_migration_checksum="",
                    post_rollback_checksum="",
                    status=RollbackStatus.FAILED,
                    row_count_pre=0,
                    row_count_post=0,
                    row_count_rollback=0,
                    verified_at=datetime.utcnow(),
                    details=f"Verification failed: {str(e)}"
                ))
        
        return self.report.table_results
    
    def generate_report(self) -> RollbackReport:
        """Generate comprehensive rollback verification report."""
        self.report.end_time = datetime.utcnow()
        
        # Determine overall status
        statuses = [r.status for r in self.report.table_results]
        
        if all(s == RollbackStatus.VERIFIED for s in statuses):
            self.report.overall_status = RollbackStatus.VERIFIED
        elif any(s == RollbackStatus.FAILED for s in statuses):
            self.report.overall_status = RollbackStatus.FAILED
        elif any(s == RollbackStatus.PARTIAL for s in statuses):
            self.report.overall_status = RollbackStatus.PARTIAL
        else:
            self.report.overall_status = RollbackStatus.NOT_STARTED
        
        # Generate summary
        self.report.summary = {
            'total_tables': len(self.report.table_results),
            'verified': sum(1 for r in self.report.table_results if r.status == RollbackStatus.VERIFIED),
            'partial': sum(1 for r in self.report.table_results if r.status == RollbackStatus.PARTIAL),
            'failed': sum(1 for r in self.report.table_results if r.status == RollbackStatus.FAILED),
            'overall_status': self.report.overall_status.value,
            'verification_duration_seconds': (
                self.report.end_time - self.report.start_time
            ).total_seconds()
        }
        
        logger.info(
            f"Rollback verification report generated: "
            f"{self.report.summary['verified']}/{self.report.summary['total_tables']} tables verified"
        )
        
        return self.report
    
    def is_rollback_verified(self) -> bool:
        """Check if rollback was fully verified for all tables."""
        return all(
            r.status == RollbackStatus.VERIFIED 
            for r in self.report.table_results
        )
    
    def get_failed_tables(self) -> List[str]:
        """Get list of tables where rollback verification failed."""
        return [
            r.table_name for r in self.report.table_results 
            if r.status in (RollbackStatus.FAILED, RollbackStatus.PARTIAL)
        ]