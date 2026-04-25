"""
Incremental, Reversible Data Migration Framework

This module provides a robust system for database migrations that supports:
- Incremental migrations (can be applied in small batches)
- Reversible migrations (rollback support)
- Online migrations (minimal locking)
- Migration verification and validation
- Progress tracking and resumption
"""

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from abc import ABC, abstractmethod
import hashlib
import json

from sqlalchemy import text, Table, Column, MetaData, select, update, insert, delete
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
import redis.asyncio as redis

from app.core.config import settings
from app.db.base import Base
from app.core.metrics import MIGRATION_DURATION, MIGRATION_RECORDS

logger = logging.getLogger(__name__)


class MigrationStatus(str, Enum):
    """Status of a migration execution."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLING_BACK = "rolling_back"
    ROLLED_BACK = "rolled_back"
    PARTIAL = "partial"  # Some batches completed


class MigrationType(str, Enum):
    """Types of migrations."""
    SCHEMA = "schema"           # DDL changes
    DATA = "data"              # DML changes
    INDEX = "index"            # Index operations
    CONSTRAINT = "constraint"  # Constraint changes
    PARTITION = "partition"    # Partitioning changes


@dataclass
class MigrationBatch:
    """A batch of records to migrate."""
    batch_number: int
    start_id: Any
    end_id: Any
    estimated_records: int
    status: MigrationStatus = MigrationStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    records_processed: int = 0
    error_message: Optional[str] = None


@dataclass
class MigrationResult:
    """Result of a migration execution."""
    success: bool
    records_processed: int
    batches_completed: int
    total_batches: int
    duration_seconds: float
    errors: List[str] = field(default_factory=list)
    can_resume: bool = True


class Migration(ABC):
    """Base class for all migrations."""
    
    def __init__(
        self,
        migration_id: str,
        name: str,
        description: str = "",
        migration_type: MigrationType = MigrationType.DATA,
        dependencies: Optional[List[str]] = None,
        is_reversible: bool = True
    ):
        self.migration_id = migration_id
        self.name = name
        self.description = description
        self.migration_type = migration_type
        self.dependencies = dependencies or []
        self.is_reversible = is_reversible
        self.created_at = datetime.now(timezone.utc)
        
        # Execution state
        self.status = MigrationStatus.PENDING
        self.batches: List[MigrationBatch] = []
        self.current_batch = 0
        self.total_records = 0
        self.processed_records = 0
        self.errors: List[str] = []
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
    
    @abstractmethod
    async def get_total_records(self, session: AsyncSession) -> int:
        """Get total number of records to migrate."""
        pass
    
    @abstractmethod
    async def get_batch_boundaries(
        self,
        session: AsyncSession,
        batch_size: int
    ) -> List[Tuple[Any, Any]]:
        """Get (start_id, end_id) tuples for each batch."""
        pass
    
    @abstractmethod
    async def migrate_batch(
        self,
        session: AsyncSession,
        batch: MigrationBatch
    ) -> int:
        """
        Migrate a single batch. Returns number of records processed.
        """
        pass
    
    async def rollback_batch(
        self,
        session: AsyncSession,
        batch: MigrationBatch
    ) -> int:
        """
        Rollback a single batch. Returns number of records rolled back.
        Override if migration is reversible.
        """
        raise NotImplementedError("Rollback not implemented for this migration")
    
    @abstractmethod
    async def verify_migration(
        self,
        session: AsyncSession
    ) -> Tuple[bool, List[str]]:
        """
        Verify migration was applied correctly.
        Returns (is_valid, list_of_issues).
        """
        pass
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize migration state."""
        return {
            "migration_id": self.migration_id,
            "name": self.name,
            "description": self.description,
            "migration_type": self.migration_type.value,
            "status": self.status.value,
            "dependencies": self.dependencies,
            "is_reversible": self.is_reversible,
            "total_records": self.total_records,
            "processed_records": self.processed_records,
            "current_batch": self.current_batch,
            "total_batches": len(self.batches),
            "errors": self.errors,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class BatchDataMigration(Migration):
    """
    Migration for batch data updates with progress tracking.
    
    Example:
        class UpdateTaskPriorityMigration(BatchDataMigration):
            def __init__(self):
                super().__init__(
                    migration_id="2024_01_update_task_priority",
                    name="Update Task Priority Enum",
                    description="Migrate task priority from string to enum"
                )
                self.table_name = "tasks"
                self.id_column = "id"
            
            async def migrate_batch(self, session, batch):
                query = text('''
                    UPDATE tasks 
                    SET priority = CASE 
                        WHEN priority = 'high' THEN '3'
                        WHEN priority = 'medium' THEN '2'
                        WHEN priority = 'low' THEN '1'
                    END
                    WHERE id BETWEEN :start_id AND :end_id
                ''')
                result = await session.execute(query, {
                    "start_id": batch.start_id,
                    "end_id": batch.end_id
                })
                return result.rowcount
    """
    
    def __init__(
        self,
        migration_id: str,
        name: str,
        description: str = "",
        table_name: str = "",
        id_column: str = "id",
        batch_size: int = 1000,
        **kwargs
    ):
        super().__init__(
            migration_id=migration_id,
            name=name,
            description=description,
            migration_type=MigrationType.DATA,
            **kwargs
        )
        self.table_name = table_name
        self.id_column = id_column
        self.batch_size = batch_size
    
    async def get_total_records(self, session: AsyncSession) -> int:
        """Get total record count."""
        query = text(f"SELECT COUNT(*) FROM {self.table_name}")
        result = await session.execute(query)
        return result.scalar()
    
    async def get_batch_boundaries(
        self,
        session: AsyncSession,
        batch_size: int
    ) -> List[Tuple[Any, Any]]:
        """Get batch boundaries using window functions."""
        query = text(f"""
            SELECT 
                MIN({self.id_column}) as start_id,
                MAX({self.id_column}) as end_id
            FROM (
                SELECT {self.id_column},
                       NTILE((SELECT CEIL(COUNT(*)::float / :batch_size) FROM {self.table_name})) 
                       OVER (ORDER BY {self.id_column}) as batch_num
                FROM {self.table_name}
            ) batches
            GROUP BY batch_num
            ORDER BY start_id
        """)
        
        result = await session.execute(query, {"batch_size": batch_size})
        return [(row.start_id, row.end_id) for row in result]


class OnlineIndexMigration(Migration):
    """
    Migration for creating indexes with CONCURRENTLY option.
    Prevents table locking during index creation.
    """
    
    def __init__(
        self,
        migration_id: str,
        name: str,
        table_name: str,
        index_columns: List[str],
        index_name: Optional[str] = None,
        unique: bool = False,
        where_clause: Optional[str] = None,
        **kwargs
    ):
        super().__init__(
            migration_id=migration_id,
            name=name,
            description=f"Create index on {table_name}({', '.join(index_columns)})",
            migration_type=MigrationType.INDEX,
            is_reversible=True,
            **kwargs
        )
        self.table_name = table_name
        self.index_columns = index_columns
        self.index_name = index_name or f"idx_{table_name}_{'_'.join(index_columns)}"
        self.unique = unique
        self.where_clause = where_clause
    
    async def get_total_records(self, session: AsyncSession) -> int:
        return 1  # Index creation is atomic
    
    async def get_batch_boundaries(self, session, batch_size):
        return [(1, 1)]  # Single operation
    
    async def migrate_batch(self, session, batch):
        """Create index concurrently."""
        unique_str = "UNIQUE" if self.unique else ""
        where_str = f"WHERE {self.where_clause}" if self.where_clause else ""
        
        # Use CONCURRENTLY to avoid locking
        query = text(f"""
            CREATE {unique_str} INDEX CONCURRENTLY IF NOT EXISTS {self.index_name}
            ON {self.table_name} ({', '.join(self.index_columns)})
            {where_str}
        """)
        
        await session.execute(query)
        return 1
    
    async def rollback_batch(self, session, batch):
        """Drop index."""
        query = text(f"DROP INDEX CONCURRENTLY IF EXISTS {self.index_name}")
        await session.execute(query)
        return 1
    
    async def verify_migration(self, session):
        """Verify index exists."""
        query = text("""
            SELECT 1 FROM pg_indexes 
            WHERE indexname = :index_name
        """)
        result = await session.execute(query, {"index_name": self.index_name})
        exists = result.scalar() is not None
        return exists, [] if exists else [f"Index {self.index_name} not found"]


class ColumnBackfillMigration(BatchDataMigration):
    """
    Migration to backfill a new column with computed values.
    """
    
    def __init__(
        self,
        migration_id: str,
        name: str,
        table_name: str,
        column_name: str,
        compute_value_fn: Callable[[Any], Any],
        **kwargs
    ):
        super().__init__(
            migration_id=migration_id,
            name=name,
            table_name=table_name,
            **kwargs
        )
        self.column_name = column_name
        self.compute_value_fn = compute_value_fn
    
    async def migrate_batch(self, session, batch):
        """Backfill column for batch."""
        # Fetch records
        query = text(f"""
            SELECT * FROM {self.table_name}
            WHERE {self.id_column} BETWEEN :start_id AND :end_id
        """)
        result = await session.execute(query, {
            "start_id": batch.start_id,
            "end_id": batch.end_id
        })
        records = result.mappings().all()
        
        # Update each record
        update_query = text(f"""
            UPDATE {self.table_name}
            SET {self.column_name} = :value
            WHERE {self.id_column} = :id
        """)
        
        for record in records:
            value = self.compute_value_fn(dict(record))
            await session.execute(update_query, {
                "value": value,
                "id": record[self.id_column]
            })
        
        return len(records)


class MigrationManager:
    """Manages execution of migrations."""
    
    def __init__(
        self,
        db_url: str,
        redis_client: Optional[redis.Redis] = None,
        default_batch_size: int = 1000
    ):
        self.engine = create_async_engine(db_url)
        self.async_session = sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )
        self.redis = redis_client
        self.default_batch_size = default_batch_size
        self._migrations: Dict[str, Migration] = {}
    
    def register_migration(self, migration: Migration):
        """Register a migration."""
        self._migrations[migration.migration_id] = migration
        logger.info(f"Registered migration: {migration.migration_id}")
    
    async def get_migration(self, migration_id: str) -> Optional[Migration]:
        """Get migration by ID."""
        # Check local registry
        if migration_id in self._migrations:
            return self._migrations[migration_id]
        
        # Check Redis for state
        if self.redis:
            state = await self.redis.get(f"migration:{migration_id}")
            if state:
                # Deserialize and recreate migration
                pass
        
        return None
    
    async def run_migration(
        self,
        migration_id: str,
        batch_size: Optional[int] = None,
        resume: bool = True
    ) -> MigrationResult:
        """
        Run a migration.
        
        Args:
            migration_id: ID of migration to run
            batch_size: Number of records per batch
            resume: Whether to resume from previous state
            
        Returns:
            MigrationResult with execution details
        """
        migration = await self.get_migration(migration_id)
        if not migration:
            return MigrationResult(
                success=False,
                records_processed=0,
                batches_completed=0,
                total_batches=0,
                duration_seconds=0,
                errors=[f"Migration {migration_id} not found"],
                can_resume=False
            )
        
        batch_size = batch_size or self.default_batch_size
        start_time = datetime.now(timezone.utc)
        
        async with self.async_session() as session:
            try:
                # Check dependencies
                for dep_id in migration.dependencies:
                    dep = await self.get_migration(dep_id)
                    if not dep or dep.status != MigrationStatus.COMPLETED:
                        return MigrationResult(
                            success=False,
                            records_processed=0,
                            batches_completed=0,
                            total_batches=0,
                            duration_seconds=0,
                            errors=[f"Dependency {dep_id} not completed"],
                            can_resume=False
                        )
                
                # Initialize migration
                if not resume or migration.status == MigrationStatus.PENDING:
                    migration.total_records = await migration.get_total_records(session)
                    boundaries = await migration.get_batch_boundaries(session, batch_size)
                    migration.batches = [
                        MigrationBatch(
                            batch_number=i,
                            start_id=start_id,
                            end_id=end_id,
                            estimated_records=batch_size
                        )
                        for i, (start_id, end_id) in enumerate(boundaries)
                    ]
                    migration.current_batch = 0
                
                migration.status = MigrationStatus.RUNNING
                migration.started_at = start_time
                
                # Execute batches
                for i, batch in enumerate(migration.batches[migration.current_batch:], 
                                          start=migration.current_batch):
                    batch.status = MigrationStatus.RUNNING
                    batch.started_at = datetime.now(timezone.utc)
                    
                    try:
                        records = await migration.migrate_batch(session, batch)
                        await session.commit()
                        
                        batch.records_processed = records
                        batch.status = MigrationStatus.COMPLETED
                        batch.completed_at = datetime.now(timezone.utc)
                        
                        migration.processed_records += records
                        migration.current_batch = i + 1
                        
                        MIGRATION_RECORDS.inc(records)
                        
                        # Save state
                        await self._save_migration_state(migration)
                        
                        logger.info(
                            f"Migration {migration_id}: Completed batch {i+1}/"
                            f"{len(migration.batches)} ({records} records)"
                        )
                        
                    except Exception as e:
                        await session.rollback()
                        batch.status = MigrationStatus.FAILED
                        batch.error_message = str(e)
                        migration.errors.append(f"Batch {i}: {str(e)}")
                        migration.status = MigrationStatus.PARTIAL
                        
                        await self._save_migration_state(migration)
                        
                        return MigrationResult(
                            success=False,
                            records_processed=migration.processed_records,
                            batches_completed=i,
                            total_batches=len(migration.batches),
                            duration_seconds=(datetime.now(timezone.utc) - start_time).total_seconds(),
                            errors=migration.errors,
                            can_resume=True
                        )
                
                # Migration completed
                migration.status = MigrationStatus.COMPLETED
                migration.completed_at = datetime.now(timezone.utc)
                await self._save_migration_state(migration)
                
                duration = (migration.completed_at - start_time).total_seconds()
                MIGRATION_DURATION.observe(duration)
                
                # Verify
                is_valid, issues = await migration.verify_migration(session)
                
                return MigrationResult(
                    success=is_valid,
                    records_processed=migration.processed_records,
                    batches_completed=len(migration.batches),
                    total_batches=len(migration.batches),
                    duration_seconds=duration,
                    errors=issues,
                    can_resume=False
                )
                
            except Exception as e:
                migration.status = MigrationStatus.FAILED
                migration.errors.append(str(e))
                await self._save_migration_state(migration)
                
                return MigrationResult(
                    success=False,
                    records_processed=migration.processed_records,
                    batches_completed=migration.current_batch,
                    total_batches=len(migration.batches),
                    duration_seconds=(datetime.now(timezone.utc) - start_time).total_seconds(),
                    errors=migration.errors + [str(e)],
                    can_resume=True
                )
    
    async def rollback_migration(self, migration_id: str) -> MigrationResult:
        """Rollback a migration."""
        migration = await self.get_migration(migration_id)
        if not migration:
            return MigrationResult(
                success=False,
                records_processed=0,
                batches_completed=0,
                total_batches=0,
                duration_seconds=0,
                errors=[f"Migration {migration_id} not found"],
                can_resume=False
            )
        
        if not migration.is_reversible:
            return MigrationResult(
                success=False,
                records_processed=0,
                batches_completed=0,
                total_batches=0,
                duration_seconds=0,
                errors=["Migration is not reversible"],
                can_resume=False
            )
        
        start_time = datetime.now(timezone.utc)
        migration.status = MigrationStatus.ROLLING_BACK
        
        async with self.async_session() as session:
            try:
                # Rollback batches in reverse order
                total_rolled_back = 0
                for batch in reversed(migration.batches):
                    if batch.status == MigrationStatus.COMPLETED:
                        rolled_back = await migration.rollback_batch(session, batch)
                        await session.commit()
                        total_rolled_back += rolled_back
                
                migration.status = MigrationStatus.ROLLED_BACK
                migration.completed_at = datetime.now(timezone.utc)
                await self._save_migration_state(migration)
                
                return MigrationResult(
                    success=True,
                    records_processed=total_rolled_back,
                    batches_completed=len(migration.batches),
                    total_batches=len(migration.batches),
                    duration_seconds=(datetime.now(timezone.utc) - start_time).total_seconds(),
                    errors=[],
                    can_resume=False
                )
                
            except Exception as e:
                migration.errors.append(f"Rollback failed: {str(e)}")
                await self._save_migration_state(migration)
                
                return MigrationResult(
                    success=False,
                    records_processed=0,
                    batches_completed=0,
                    total_batches=len(migration.batches),
                    duration_seconds=(datetime.now(timezone.utc) - start_time).total_seconds(),
                    errors=migration.errors,
                    can_resume=False
                )
    
    async def _save_migration_state(self, migration: Migration):
        """Save migration state to Redis."""
        if self.redis:
            await self.redis.setex(
                f"migration:{migration.migration_id}",
                86400 * 30,  # 30 days
                json.dumps(migration.to_dict(), default=str)
            )
    
    async def get_migration_status(self, migration_id: str) -> Optional[Dict[str, Any]]:
        """Get current status of a migration."""
        migration = await self.get_migration(migration_id)
        if migration:
            return migration.to_dict()
        return None
    
    async def list_migrations(self) -> List[Dict[str, Any]]:
        """List all registered migrations."""
        return [m.to_dict() for m in self._migrations.values()]


# TaskFlow Pro specific migrations

class TaskPriorityMigration(BatchDataMigration):
    """Migrate task priority from string to integer enum."""
    
    def __init__(self):
        super().__init__(
            migration_id="2024_01_migrate_task_priority",
            name="Migrate Task Priority to Enum",
            description="Convert task priority from string values to integer enum",
            table_name="tasks",
            id_column="id",
            batch_size=5000,
            is_reversible=True
        )
    
    async def migrate_batch(self, session, batch):
        """Migrate priority values."""
        query = text("""
            UPDATE tasks 
            SET priority = CASE priority
                WHEN 'low' THEN 1
                WHEN 'medium' THEN 2
                WHEN 'high' THEN 3
                WHEN 'urgent' THEN 4
                ELSE 2  -- default to medium
            END::task_priority
            WHERE id BETWEEN :start_id AND :end_id
            AND priority IN ('low', 'medium', 'high', 'urgent')
        """)
        result = await session.execute(query, {
            "start_id": batch.start_id,
            "end_id": batch.end_id
        })
        return result.rowcount
    
    async def rollback_batch(self, session, batch):
        """Rollback to string values."""
        query = text("""
            UPDATE tasks 
            SET priority = CASE priority::int
                WHEN 1 THEN 'low'
                WHEN 2 THEN 'medium'
                WHEN 3 THEN 'high'
                WHEN 4 THEN 'urgent'
                ELSE 'medium'
            END
            WHERE id BETWEEN :start_id AND :end_id
        """)
        result = await session.execute(query, {
            "start_id": batch.start_id,
            "end_id": batch.end_id
        })
        return result.rowcount
    
    async def verify_migration(self, session):
        """Verify no string priorities remain."""
        query = text("""
            SELECT COUNT(*) FROM tasks 
            WHERE priority IN ('low', 'medium', 'high', 'urgent')
        """)
        result = await session.execute(query)
        count = result.scalar()
        
        if count == 0:
            return True, []
        return False, [f"{count} tasks still have string priority values"]


class AddTaskSearchVectorMigration(BatchDataMigration):
    """Backfill search vector for existing tasks."""
    
    def __init__(self):
        super().__init__(
            migration_id="2024_02_backfill_task_search",
            name="Backfill Task Search Vector",
            description="Compute and store search vector for existing tasks",
            table_name="tasks",
            id_column="id",
            batch_size=1000,
            is_reversible=True
        )
    
    async def migrate_batch(self, session, batch):
        """Compute search vector for batch."""
        query = text("""
            UPDATE tasks 
            SET search_vector = (
                setweight(to_tsvector('english', COALESCE(title, '')), 'A') ||
                setweight(to_tsvector('english', COALESCE(description, '')), 'B') ||
                setweight(to_tsvector('english', COALESCE(tags::text, '')), 'C')
            )
            WHERE id BETWEEN :start_id AND :end_id
            AND search_vector IS NULL
        """)
        result = await session.execute(query, {
            "start_id": batch.start_id,
            "end_id": batch.end_id
        })
        return result.rowcount
    
    async def rollback_batch(self, session, batch):
        """Clear search vectors."""
        query = text("""
            UPDATE tasks 
            SET search_vector = NULL
            WHERE id BETWEEN :start_id AND :end_id
        """)
        result = await session.execute(query, {
            "start_id": batch.start_id,
            "end_id": batch.end_id
        })
        return result.rowcount


# Global migration manager
migration_manager: Optional[MigrationManager] = None


async def initialize_migrations(db_url: str, redis_url: Optional[str] = None):
    """Initialize migration manager."""
    global migration_manager
    
    redis_client = None
    if redis_url:
        redis_client = redis.from_url(redis_url, decode_responses=True)
    
    migration_manager = MigrationManager(db_url, redis_client)
    
    # Register default migrations
    migration_manager.register_migration(TaskPriorityMigration())
    migration_manager.register_migration(AddTaskSearchVectorMigration())
    
    logger.info("Migration manager initialized")
