"""
Referential Integrity Validation Module

Validates that all foreign key relationships are preserved after migration.
Detects orphaned records and dangling references.
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass
class ReferentialIntegrityResult:
    """Result of referential integrity validation."""
    relationship_name: str
    parent_table: str
    child_table: str
    parent_column: str
    child_column: str
    orphaned_count: int
    total_children: int
    orphaned_percentage: float
    status: str  # 'PASS', 'FAIL', 'WARNING'
    sample_orphans: Optional[List[Dict]] = None
    validated_at: datetime = None
    
    def __post_init__(self):
        if self.validated_at is None:
            self.validated_at = datetime.utcnow()


class ReferentialIntegrityValidator:
    """
    Validates referential integrity between related tables.
    
    Checks all foreign key relationships to ensure:
    - No orphaned child records (child without matching parent)
    - No dangling references (parent deleted but children remain)
    - Cascade deletes work correctly
    """
    
    # Foreign key relationships in TaskFlow Pro schema
    # Format: (parent_table, parent_column, child_table, child_column)
    FOREIGN_KEY_RELATIONSHIPS: List[Tuple[str, str, str, str]] = [
        # User relationships
        ('users', 'id', 'teams', 'owner_id'),
        ('users', 'id', 'team_members', 'user_id'),
        ('users', 'id', 'boards', 'created_by'),
        ('users', 'id', 'tasks', 'created_by'),
        ('users', 'id', 'comments', 'user_id'),
        ('users', 'id', 'attachments', 'uploaded_by'),
        ('users', 'id', 'notifications', 'user_id'),
        ('users', 'id', 'user_preferences', 'user_id'),
        ('users', 'id', 'password_reset_tokens', 'user_id'),
        
        # Team relationships
        ('teams', 'id', 'team_members', 'team_id'),
        ('teams', 'id', 'boards', 'team_id'),
        
        # Board relationships
        ('boards', 'id', 'columns', 'board_id'),
        ('boards', 'id', 'tasks', 'board_id'),
        
        # Column relationships
        ('columns', 'id', 'tasks', 'column_id'),
        
        # Task relationships
        ('tasks', 'id', 'task_assignees', 'task_id'),
        ('tasks', 'id', 'comments', 'task_id'),
        ('tasks', 'id', 'attachments', 'task_id'),
    ]
    
    # Tables that allow soft deletes (check is_deleted flag)
    SOFT_DELETE_TABLES = ['users', 'teams', 'tasks', 'boards']
    
    def __init__(
        self,
        source_session: AsyncSession,
        destination_session: AsyncSession,
        max_sample_orphans: int = 10
    ):
        self.source_session = source_session
        self.destination_session = destination_session
        self.max_sample_orphans = max_sample_orphans
        self.results: List[ReferentialIntegrityResult] = []
        
    async def _get_orphaned_count(
        self,
        session: AsyncSession,
        parent_table: str,
        parent_column: str,
        child_table: str,
        child_column: str,
        use_soft_delete: bool = False
    ) -> Tuple[int, int, List[Dict]]:
        """
        Get count of orphaned records and sample orphans.
        
        Returns:
            Tuple of (orphaned_count, total_children, sample_orphans)
        """
        # Build query to find orphans
        soft_delete_filter = ""
        if use_soft_delete and parent_table in self.SOFT_DELETE_TABLES:
            soft_delete_filter = f" AND p.is_deleted = false"
        
        # Count orphaned records
        count_query = f"""
            SELECT COUNT(*) 
            FROM {child_table} c
            LEFT JOIN {parent_table} p ON c.{child_column} = p.{parent_column}
            WHERE p.{parent_column} IS NULL{soft_delete_filter}
        """
        
        count_result = await session.execute(text(count_query))
        orphaned_count = count_result.scalar()
        
        # Get total children count
        total_query = f"SELECT COUNT(*) FROM {child_table}"
        total_result = await session.execute(text(total_query))
        total_children = total_result.scalar()
        
        # Get sample orphans if any
        sample_orphans = []
        if orphaned_count > 0:
            sample_query = f"""
                SELECT c.*
                FROM {child_table} c
                LEFT JOIN {parent_table} p ON c.{child_column} = p.{parent_column}
                WHERE p.{parent_column} IS NULL{soft_delete_filter}
                LIMIT {self.max_sample_orphans}
            """
            sample_result = await session.execute(text(sample_query))
            sample_orphans = [dict(row) for row in sample_result.mappings().all()]
        
        return orphaned_count, total_children, sample_orphans
    
    async def validate_relationship(
        self,
        parent_table: str,
        parent_column: str,
        child_table: str,
        child_column: str,
        relationship_name: Optional[str] = None
    ) -> ReferentialIntegrityResult:
        """
        Validate a single foreign key relationship.
        
        Args:
            parent_table: Parent table name
            parent_column: Parent column name
            child_table: Child table name
            child_column: Child column name
            relationship_name: Optional name for this relationship
            
        Returns:
            ReferentialIntegrityResult with validation details
        """
        if relationship_name is None:
            relationship_name = f"{child_table}.{child_column} -> {parent_table}.{parent_column}"
        
        logger.info(f"Validating referential integrity: {relationship_name}")
        
        use_soft_delete = parent_table in self.SOFT_DELETE_TABLES
        
        # Check source database (baseline)
        source_orphans, source_total, _ = await self._get_orphaned_count(
            self.source_session,
            parent_table, parent_column,
            child_table, child_column,
            use_soft_delete
        )
        
        # Check destination database
        dest_orphans, dest_total, sample_orphans = await self._get_orphaned_count(
            self.destination_session,
            parent_table, parent_column,
            child_table, child_column,
            use_soft_delete
        )
        
        # Calculate percentage
        if dest_total > 0:
            orphaned_percentage = (dest_orphans / dest_total) * 100
        else:
            orphaned_percentage = 0.0
        
        # Determine status
        # Allow same number of orphans as source (may be pre-existing)
        if dest_orphans <= source_orphans:
            status = 'PASS'
        elif orphaned_percentage < 0.1:  # Less than 0.1% orphaned
            status = 'WARNING'
        else:
            status = 'FAIL'
        
        result = ReferentialIntegrityResult(
            relationship_name=relationship_name,
            parent_table=parent_table,
            child_table=child_table,
            parent_column=parent_column,
            child_column=child_column,
            orphaned_count=dest_orphans,
            total_children=dest_total,
            orphaned_percentage=round(orphaned_percentage, 4),
            status=status,
            sample_orphans=sample_orphans if dest_orphans > 0 else None
        )
        
        self.results.append(result)
        
        logger.info(
            f"Referential integrity check for {relationship_name}: {status} "
            f"({dest_orphans} orphans out of {dest_total} children)"
        )
        
        return result
    
    async def validate_all_relationships(
        self,
        relationships: Optional[List[Tuple[str, str, str, str]]] = None
    ) -> List[ReferentialIntegrityResult]:
        """
        Validate all configured foreign key relationships.
        
        Args:
            relationships: Optional list of relationships to validate
                          (default: all configured relationships)
                          
        Returns:
            List of ReferentialIntegrityResult for all relationships
        """
        if relationships is None:
            relationships = self.FOREIGN_KEY_RELATIONSHIPS
        
        logger.info(f"Starting referential integrity validation for {len(relationships)} relationships")
        
        for parent_table, parent_column, child_table, child_column in relationships:
            try:
                await self.validate_relationship(
                    parent_table, parent_column,
                    child_table, child_column
                )
            except Exception as e:
                logger.error(f"Failed to validate relationship {child_table}.{child_column}: {e}")
                # Add failed result
                self.results.append(ReferentialIntegrityResult(
                    relationship_name=f"{child_table}.{child_column} -> {parent_table}.{parent_column}",
                    parent_table=parent_table,
                    child_table=child_table,
                    parent_column=parent_column,
                    child_column=child_column,
                    orphaned_count=-1,
                    total_children=-1,
                    orphaned_percentage=0.0,
                    status='ERROR'
                ))
        
        return self.results
    
    async def validate_circular_references(
        self,
        table1: str,
        column1: str,
        table2: str,
        column2: str
    ) -> ReferentialIntegrityResult:
        """
        Validate circular references between two tables.
        
        Example: team_members references users, and users may reference teams
        """
        relationship_name = f"Circular: {table1}.{column1} <-> {table2}.{column2}"
        
        # Find records in table1 referencing non-existent table2 records
        query1 = f"""
            SELECT COUNT(*) 
            FROM {table1} t1
            LEFT JOIN {table2} t2 ON t1.{column1} = t2.{column2}
            WHERE t2.{column2} IS NULL
        """
        
        result1 = await self.destination_session.execute(text(query1))
        orphans1 = result1.scalar()
        
        # Find records in table2 referencing non-existent table1 records
        query2 = f"""
            SELECT COUNT(*) 
            FROM {table2} t2
            LEFT JOIN {table1} t1 ON t2.{column2} = t1.{column1}
            WHERE t1.{column1} IS NULL
        """
        
        result2 = await self.destination_session.execute(text(query2))
        orphans2 = result2.scalar()
        
        total_orphans = orphans1 + orphans2
        
        # Get total record count
        count_query1 = f"SELECT COUNT(*) FROM {table1}"
        count_query2 = f"SELECT COUNT(*) FROM {table2}"
        
        total1 = (await self.destination_session.execute(text(count_query1))).scalar()
        total2 = (await self.destination_session.execute(text(count_query2))).scalar()
        total = total1 + total2
        
        if total > 0:
            orphaned_percentage = (total_orphans / total) * 100
        else:
            orphaned_percentage = 0.0
        
        status = 'PASS' if total_orphans == 0 else ('WARNING' if orphaned_percentage < 0.1 else 'FAIL')
        
        result = ReferentialIntegrityResult(
            relationship_name=relationship_name,
            parent_table=f"{table1}/{table2}",
            child_table=f"{table2}/{table1}",
            parent_column=column1,
            child_column=column2,
            orphaned_count=total_orphans,
            total_children=total,
            orphaned_percentage=round(orphaned_percentage, 4),
            status=status
        )
        
        self.results.append(result)
        return result
    
    def get_summary(self) -> Dict:
        """Get summary of all referential integrity checks."""
        if not self.results:
            return {'total': 0, 'passed': 0, 'failed': 0, 'warnings': 0, 'errors': 0}
        
        return {
            'total': len(self.results),
            'passed': sum(1 for r in self.results if r.status == 'PASS'),
            'failed': sum(1 for r in self.results if r.status == 'FAIL'),
            'warnings': sum(1 for r in self.results if r.status == 'WARNING'),
            'errors': sum(1 for r in self.results if r.status == 'ERROR'),
            'total_orphaned_records': sum(
                r.orphaned_count for r in self.results if r.orphaned_count > 0
            ),
            'relationships_with_issues': [
                r.relationship_name for r in self.results if r.status in ('FAIL', 'ERROR')
            ]
        }
    
    def has_failures(self) -> bool:
        """Check if any referential integrity checks failed."""
        return any(r.status in ('FAIL', 'ERROR') for r in self.results)
    
    def get_failed_relationships(self) -> List[str]:
        """Get list of relationships with failed validation."""
        return [r.relationship_name for r in self.results if r.status in ('FAIL', 'ERROR')]