"""
Row Count Validation Module

Validates that row counts match between source and destination databases
within acceptable tolerance thresholds.
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass
class RowCountResult:
    """Result of row count validation for a single table."""
    table_name: str
    source_count: int
    destination_count: int
    difference: int
    percentage_diff: float
    tolerance_percent: float
    status: str  # 'PASS', 'FAIL', 'WARNING'
    validated_at: datetime
    details: Optional[str] = None


class RowCountValidator:
    """
    Validates row counts between source and destination databases.
    
    Supports configurable tolerance thresholds for different table types:
    - Critical tables: 0% tolerance (exact match required)
    - Standard tables: 0.1% tolerance
    - Audit tables: 1% tolerance (may have concurrent inserts)
    """
    
    # Table categories with their tolerance thresholds
    TABLE_CATEGORIES = {
        'critical': {
            'tables': ['users', 'teams', 'tasks', 'boards'],
            'tolerance_percent': 0.0,  # Exact match required
        },
        'standard': {
            'tables': ['team_members', 'columns', 'task_assignees', 'comments', 'attachments'],
            'tolerance_percent': 0.1,
        },
        'audit': {
            'tables': ['notifications', 'user_preferences', 'password_reset_tokens'],
            'tolerance_percent': 1.0,
        }
    }
    
    def __init__(
        self,
        source_session: AsyncSession,
        destination_session: AsyncSession,
        custom_tolerances: Optional[Dict[str, float]] = None
    ):
        self.source_session = source_session
        self.destination_session = destination_session
        self.custom_tolerances = custom_tolerances or {}
        self.results: List[RowCountResult] = []
        
    def _get_tolerance(self, table_name: str) -> float:
        """Get tolerance threshold for a table."""
        # Check custom tolerances first
        if table_name in self.custom_tolerances:
            return self.custom_tolerances[table_name]
        
        # Check category tolerances
        for category, config in self.TABLE_CATEGORIES.items():
            if table_name in config['tables']:
                return config['tolerance_percent']
        
        # Default tolerance
        return 0.1
    
    async def _get_row_count(
        self,
        session: AsyncSession,
        table_name: str,
        condition: Optional[str] = None
    ) -> int:
        """Get row count for a table with optional condition."""
        query = f"SELECT COUNT(*) FROM {table_name}"
        if condition:
            query += f" WHERE {condition}"
        
        result = await session.execute(text(query))
        return result.scalar()
    
    async def validate_table(
        self,
        table_name: str,
        source_condition: Optional[str] = None,
        destination_condition: Optional[str] = None
    ) -> RowCountResult:
        """
        Validate row count for a single table.
        
        Args:
            table_name: Name of the table to validate
            source_condition: Optional WHERE clause for source
            destination_condition: Optional WHERE clause for destination
            
        Returns:
            RowCountResult with validation details
        """
        logger.info(f"Validating row count for table: {table_name}")
        
        source_count = await self._get_row_count(
            self.source_session, table_name, source_condition
        )
        destination_count = await self._get_row_count(
            self.destination_session, table_name, destination_condition
        )
        
        difference = destination_count - source_count
        
        # Calculate percentage difference
        if source_count > 0:
            percentage_diff = abs(difference) / source_count * 100
        else:
            percentage_diff = 0.0 if destination_count == 0 else 100.0
        
        tolerance = self._get_tolerance(table_name)
        
        # Determine status
        if percentage_diff <= tolerance:
            status = 'PASS'
        elif percentage_diff <= tolerance * 2:
            status = 'WARNING'
        else:
            status = 'FAIL'
        
        result = RowCountResult(
            table_name=table_name,
            source_count=source_count,
            destination_count=destination_count,
            difference=difference,
            percentage_diff=round(percentage_diff, 4),
            tolerance_percent=tolerance,
            status=status,
            validated_at=datetime.utcnow(),
            details=self._generate_details(
                table_name, source_count, destination_count, difference, tolerance
            )
        )
        
        self.results.append(result)
        
        logger.info(
            f"Row count validation for {table_name}: {status} "
            f"(source={source_count}, dest={destination_count}, diff={difference})"
        )
        
        return result
    
    def _generate_details(
        self,
        table_name: str,
        source_count: int,
        destination_count: int,
        difference: int,
        tolerance: float
    ) -> str:
        """Generate detailed description of the validation result."""
        if difference == 0:
            return f"Exact match: {source_count} rows"
        elif difference > 0:
            return (
                f"Destination has {difference} more rows than source "
                f"({abs(difference)/source_count*100:.4f}% increase). "
                f"Tolerance: {tolerance}%"
            )
        else:
            return (
                f"Destination has {abs(difference)} fewer rows than source "
                f"({abs(difference)/source_count*100:.4f}% decrease). "
                f"Tolerance: {tolerance}%"
            )
    
    async def validate_all_tables(
        self,
        tables: Optional[List[str]] = None,
        exclude_tables: Optional[List[str]] = None
    ) -> List[RowCountResult]:
        """
        Validate row counts for all tables or specified subset.
        
        Args:
            tables: Optional list of tables to validate (default: all known tables)
            exclude_tables: Optional list of tables to exclude
            
        Returns:
            List of RowCountResult for all validated tables
        """
        if tables is None:
            # Collect all tables from categories
            tables = []
            for category in self.TABLE_CATEGORIES.values():
                tables.extend(category['tables'])
        
        if exclude_tables:
            tables = [t for t in tables if t not in exclude_tables]
        
        logger.info(f"Starting row count validation for {len(tables)} tables")
        
        for table_name in tables:
            try:
                await self.validate_table(table_name)
            except Exception as e:
                logger.error(f"Failed to validate {table_name}: {e}")
                # Add failed result
                self.results.append(RowCountResult(
                    table_name=table_name,
                    source_count=-1,
                    destination_count=-1,
                    difference=0,
                    percentage_diff=0.0,
                    tolerance_percent=0.0,
                    status='ERROR',
                    validated_at=datetime.utcnow(),
                    details=f"Validation failed: {str(e)}"
                ))
        
        return self.results
    
    def get_summary(self) -> Dict:
        """Get summary of all validation results."""
        if not self.results:
            return {'total': 0, 'passed': 0, 'failed': 0, 'warnings': 0, 'errors': 0}
        
        return {
            'total': len(self.results),
            'passed': sum(1 for r in self.results if r.status == 'PASS'),
            'failed': sum(1 for r in self.results if r.status == 'FAIL'),
            'warnings': sum(1 for r in self.results if r.status == 'WARNING'),
            'errors': sum(1 for r in self.results if r.status == 'ERROR'),
            'tables_with_issues': [
                r.table_name for r in self.results if r.status in ('FAIL', 'ERROR')
            ]
        }
    
    def has_failures(self) -> bool:
        """Check if any validations failed."""
        return any(r.status in ('FAIL', 'ERROR') for r in self.results)
    
    def get_failed_tables(self) -> List[str]:
        """Get list of tables with failed validation."""
        return [r.table_name for r in self.results if r.status in ('FAIL', 'ERROR')]