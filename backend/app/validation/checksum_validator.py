"""
Checksum Validation Module

Provides hash-based data integrity verification using SHA256.
Validates that data content matches between source and destination.
"""

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass
class ChecksumResult:
    """Result of checksum validation for a table or partition."""
    table_name: str
    partition_key: Optional[str]
    source_checksum: str
    destination_checksum: str
    status: str  # 'MATCH', 'MISMATCH', 'ERROR'
    row_count: int
    validated_at: datetime
    mismatched_rows: Optional[List[Dict]] = None
    details: Optional[str] = None


class ChecksumValidator:
    """
    Validates data integrity using SHA256 checksums.
    
    Supports:
    - Full table checksums
    - Partition-based checksums for large tables
    - Column-level checksums for specific validation
    - Incremental checksums for delta validation
    """
    
    # Tables that should use partition-based validation
    LARGE_TABLES = ['tasks', 'comments', 'notifications', 'attachments']
    
    # Default partition column for large tables
    PARTITION_COLUMNS = {
        'tasks': 'created_at',
        'comments': 'created_at',
        'notifications': 'created_at',
        'attachments': 'uploaded_at',
    }
    
    def __init__(
        self,
        source_session: AsyncSession,
        destination_session: AsyncSession,
        batch_size: int = 10000
    ):
        self.source_session = source_session
        self.destination_session = destination_session
        self.batch_size = batch_size
        self.results: List[ChecksumResult] = []
        
    def _serialize_value(self, value: Any) -> str:
        """Serialize a value for hashing, handling special types."""
        if value is None:
            return 'NULL'
        elif isinstance(value, datetime):
            return value.isoformat()
        elif isinstance(value, Decimal):
            return str(value)
        elif isinstance(value, (dict, list)):
            return json.dumps(value, sort_keys=True, default=str)
        else:
            return str(value)
    
    def _compute_row_hash(self, row: Dict[str, Any]) -> str:
        """Compute SHA256 hash for a single row."""
        # Sort keys for consistent ordering
        sorted_items = sorted(row.items())
        
        # Serialize values
        serialized = '|'.join(
            f"{k}={self._serialize_value(v)}" for k, v in sorted_items
        )
        
        return hashlib.sha256(serialized.encode('utf-8')).hexdigest()
    
    def _compute_aggregate_hash(self, row_hashes: List[str]) -> str:
        """Compute aggregate hash from individual row hashes."""
        # Sort hashes for consistent ordering
        sorted_hashes = sorted(row_hashes)
        combined = ''.join(sorted_hashes)
        return hashlib.sha256(combined.encode('utf-8')).hexdigest()
    
    async def _fetch_rows(
        self,
        session: AsyncSession,
        table_name: str,
        columns: Optional[List[str]] = None,
        where_clause: Optional[str] = None,
        order_by: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Fetch rows from database."""
        if columns:
            col_str = ', '.join(columns)
        else:
            col_str = '*'
        
        query = f"SELECT {col_str} FROM {table_name}"
        
        if where_clause:
            query += f" WHERE {where_clause}"
        
        if order_by:
            query += f" ORDER BY {order_by}"
        
        if limit:
            query += f" LIMIT {limit}"
        
        if offset:
            query += f" OFFSET {offset}"
        
        result = await session.execute(text(query))
        rows = result.mappings().all()
        return [dict(row) for row in rows]
    
    async def validate_table(
        self,
        table_name: str,
        columns: Optional[List[str]] = None,
        where_clause: Optional[str] = None,
        use_partitioning: Optional[bool] = None
    ) -> ChecksumResult:
        """
        Validate checksum for a table.
        
        Args:
            table_name: Table to validate
            columns: Specific columns to validate (default: all)
            where_clause: Optional filter condition
            use_partitioning: Force partitioning on/off (default: auto-detect)
            
        Returns:
            ChecksumResult with validation details
        """
        logger.info(f"Computing checksum for table: {table_name}")
        
        # Determine if we should use partitioning
        if use_partitioning is None:
            use_partitioning = table_name in self.LARGE_TABLES
        
        if use_partitioning and table_name in self.PARTITION_COLUMNS:
            return await self._validate_partitioned(
                table_name, columns, where_clause
            )
        else:
            return await self._validate_full_table(
                table_name, columns, where_clause
            )
    
    async def _validate_full_table(
        self,
        table_name: str,
        columns: Optional[List[str]] = None,
        where_clause: Optional[str] = None
    ) -> ChecksumResult:
        """Validate entire table checksum."""
        # Get row count first
        count_query = f"SELECT COUNT(*) FROM {table_name}"
        if where_clause:
            count_query += f" WHERE {where_clause}"
        
        count_result = await self.source_session.execute(text(count_query))
        row_count = count_result.scalar()
        
        logger.info(f"Validating {row_count} rows in {table_name}")
        
        # Compute source checksum
        source_rows = await self._fetch_rows(
            self.source_session, table_name, columns, where_clause
        )
        source_hashes = [self._compute_row_hash(row) for row in source_rows]
        source_checksum = self._compute_aggregate_hash(source_hashes)
        
        # Compute destination checksum
        dest_rows = await self._fetch_rows(
            self.destination_session, table_name, columns, where_clause
        )
        dest_hashes = [self._compute_row_hash(row) for row in dest_rows]
        dest_checksum = self._compute_aggregate_hash(dest_hashes)
        
        # Find mismatches if any
        mismatched = None
        if source_checksum != dest_checksum:
            mismatched = self._find_mismatched_rows(source_rows, dest_rows)
        
        result = ChecksumResult(
            table_name=table_name,
            partition_key=None,
            source_checksum=source_checksum,
            destination_checksum=dest_checksum,
            status='MATCH' if source_checksum == dest_checksum else 'MISMATCH',
            row_count=row_count,
            validated_at=datetime.utcnow(),
            mismatched_rows=mismatched[:100] if mismatched else None,  # Limit to 100
            details=f"Full table checksum computed over {row_count} rows"
        )
        
        self.results.append(result)
        return result
    
    async def _validate_partitioned(
        self,
        table_name: str,
        columns: Optional[List[str]] = None,
        where_clause: Optional[str] = None
    ) -> ChecksumResult:
        """Validate table using time-based partitioning."""
        partition_col = self.PARTITION_COLUMNS.get(table_name, 'created_at')
        
        # Get date range
        range_query = f"""
            SELECT 
                MIN({partition_col}) as min_date,
                MAX({partition_col}) as max_date,
                COUNT(*) as total_count
            FROM {table_name}
        """
        if where_clause:
            range_query += f" WHERE {where_clause}"
        
        range_result = await self.source_session.execute(text(range_query))
        range_row = range_result.mappings().first()
        
        if not range_row or range_row['total_count'] == 0:
            return ChecksumResult(
                table_name=table_name,
                partition_key=partition_col,
                source_checksum='',
                destination_checksum='',
                status='MATCH',
                row_count=0,
                validated_at=datetime.utcnow(),
                details="Empty table"
            )
        
        # Compute checksums for each partition
        partition_checksums_source = []
        partition_checksums_dest = []
        total_rows = 0
        
        # For simplicity, use monthly partitions
        # In production, this could be configurable
        partitions = self._generate_partitions(
            range_row['min_date'], range_row['max_date']
        )
        
        for partition_start, partition_end in partitions:
            partition_where = f"{partition_col} >= '{partition_start}' AND {partition_col} < '{partition_end}'"
            if where_clause:
                partition_where = f"({where_clause}) AND ({partition_where})"
            
            # Source partition checksum
            source_rows = await self._fetch_rows(
                self.source_session, table_name, columns, partition_where
            )
            source_hashes = [self._compute_row_hash(row) for row in source_rows]
            partition_checksums_source.extend(source_hashes)
            
            # Destination partition checksum
            dest_rows = await self._fetch_rows(
                self.destination_session, table_name, columns, partition_where
            )
            dest_hashes = [self._compute_row_hash(row) for row in dest_rows]
            partition_checksums_dest.extend(dest_hashes)
            
            total_rows += len(source_rows)
        
        source_checksum = self._compute_aggregate_hash(partition_checksums_source)
        dest_checksum = self._compute_aggregate_hash(partition_checksums_dest)
        
        result = ChecksumResult(
            table_name=table_name,
            partition_key=partition_col,
            source_checksum=source_checksum,
            destination_checksum=dest_checksum,
            status='MATCH' if source_checksum == dest_checksum else 'MISMATCH',
            row_count=total_rows,
            validated_at=datetime.utcnow(),
            details=f"Partitioned checksum over {len(partitions)} partitions"
        )
        
        self.results.append(result)
        return result
    
    def _generate_partitions(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> List[tuple]:
        """Generate monthly partition ranges."""
        from dateutil.relativedelta import relativedelta
        
        partitions = []
        current = start_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        while current < end_date:
            next_month = current + relativedelta(months=1)
            partitions.append((current.isoformat(), next_month.isoformat()))
            current = next_month
        
        return partitions
    
    def _find_mismatched_rows(
        self,
        source_rows: List[Dict],
        dest_rows: List[Dict],
        key_column: str = 'id'
    ) -> List[Dict]:
        """Find specific rows that don't match."""
        # Build lookup by key
        source_by_key = {row.get(key_column): row for row in source_rows}
        dest_by_key = {row.get(key_column): row for row in dest_rows}
        
        mismatched = []
        all_keys = set(source_by_key.keys()) | set(dest_by_key.keys())
        
        for key in all_keys:
            source_row = source_by_key.get(key)
            dest_row = dest_by_key.get(key)
            
            if source_row is None:
                mismatched.append({
                    'key': key,
                    'issue': 'MISSING_IN_SOURCE',
                    'destination_row': dest_row
                })
            elif dest_row is None:
                mismatched.append({
                    'key': key,
                    'issue': 'MISSING_IN_DESTINATION',
                    'source_row': source_row
                })
            elif self._compute_row_hash(source_row) != self._compute_row_hash(dest_row):
                mismatched.append({
                    'key': key,
                    'issue': 'CONTENT_MISMATCH',
                    'source_row': source_row,
                    'destination_row': dest_row
                })
        
        return mismatched
    
    async def validate_column(
        self,
        table_name: str,
        column_name: str,
        aggregation: str = 'SUM'  # SUM, COUNT, AVG, etc.
    ) -> ChecksumResult:
        """
        Validate a specific column using aggregation.
        
        Useful for numeric columns where exact row match isn't required
        but aggregate values must match.
        """
        query = f"SELECT {aggregation}({column_name}) FROM {table_name}"
        
        source_result = await self.source_session.execute(text(query))
        source_value = source_result.scalar()
        
        dest_result = await self.destination_session.execute(text(query))
        dest_value = dest_result.scalar()
        
        # Convert to string for consistent comparison
        source_str = str(source_value) if source_value is not None else 'NULL'
        dest_str = str(dest_value) if dest_value is not None else 'NULL'
        
        source_checksum = hashlib.sha256(source_str.encode()).hexdigest()
        dest_checksum = hashlib.sha256(dest_str.encode()).hexdigest()
        
        result = ChecksumResult(
            table_name=f"{table_name}.{column_name}",
            partition_key=None,
            source_checksum=source_checksum,
            destination_checksum=dest_checksum,
            status='MATCH' if source_checksum == dest_checksum else 'MISMATCH',
            row_count=-1,  # Not applicable for aggregates
            validated_at=datetime.utcnow(),
            details=f"{aggregation}({column_name}): source={source_value}, dest={dest_value}"
        )
        
        self.results.append(result)
        return result
    
    def get_summary(self) -> Dict:
        """Get summary of all checksum validations."""
        if not self.results:
            return {'total': 0, 'matched': 0, 'mismatched': 0, 'errors': 0}
        
        return {
            'total': len(self.results),
            'matched': sum(1 for r in self.results if r.status == 'MATCH'),
            'mismatched': sum(1 for r in self.results if r.status == 'MISMATCH'),
            'errors': sum(1 for r in self.results if r.status == 'ERROR'),
            'tables_with_mismatches': [
                r.table_name for r in self.results if r.status == 'MISMATCH'
            ]
        }
    
    def has_mismatches(self) -> bool:
        """Check if any checksums don't match."""
        return any(r.status == 'MISMATCH' for r in self.results)