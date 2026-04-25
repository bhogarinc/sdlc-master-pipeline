#!/usr/bin/env python3
"""
Data Migration Validation CLI

Command-line interface for running migration validations.

Usage:
    python -m app.validation.cli validate-all --migration-id MIGRATION_001
    python -m app.validation.cli row-count --source-url ... --dest-url ...
    python -m app.validation.cli checksum --tables users teams
    python -m app.validation.cli report --migration-id MIGRATION_001 --format json
"""

import asyncio
import argparse
import json
import logging
import sys
from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from .migration_validator import MigrationValidator
from .row_count_validator import RowCountValidator
from .checksum_validator import ChecksumValidator
from .referential_integrity_validator import ReferentialIntegrityValidator
from .business_rule_validator import BusinessRuleValidator
from .performance_monitor import PerformanceMonitor

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def create_async_session(database_url: str) -> AsyncSession:
    """Create an async database session."""
    engine = create_async_engine(database_url, echo=False)
    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    return async_session()


async def validate_all(args):
    """Run complete migration validation."""
    logger.info(f"Starting full validation for migration: {args.migration_id}")
    
    source_session = create_async_session(args.source_url)
    dest_session = create_async_session(args.dest_url)
    
    try:
        validator = MigrationValidator(
            migration_id=args.migration_id,
            source_session=source_session,
            destination_session=dest_session
        )
        
        # Pre-migration validation
        if args.pre_validation:
            logger.info("Running pre-migration validation...")
            pre_results = await validator.run_pre_migration_validation()
            print("\n=== Pre-Migration Validation Results ===")
            print(json.dumps(pre_results, indent=2, default=str))
        
        # Post-migration validation
        logger.info("Running post-migration validation...")
        report = await validator.run_post_migration_validation(
            validate_checksums=not args.skip_checksums,
            validate_referential=not args.skip_referential,
            validate_business_rules=not args.skip_business_rules
        )
        
        # Output report
        print("\n=== Migration Validation Report ===")
        print(json.dumps(report.to_dict(), indent=2, default=str))
        
        # Summary
        summary = report.summary
        print(f"\n=== Summary ===")
        print(f"Total Issues: {summary.get('total_issues', 0)}")
        print(f"Total Warnings: {summary.get('total_warnings', 0)}")
        print(f"Overall Status: {report._determine_overall_status().upper()}")
        
        # Exit with appropriate code
        if report._determine_overall_status() == 'fail':
            sys.exit(1)
        elif report._determine_overall_status() == 'warning':
            sys.exit(2)
        else:
            sys.exit(0)
            
    finally:
        await source_session.close()
        await dest_session.close()


async def validate_row_count(args):
    """Validate row counts only."""
    source_session = create_async_session(args.source_url)
    dest_session = create_async_session(args.dest_url)
    
    try:
        validator = RowCountValidator(source_session, dest_session)
        
        tables = args.tables or validator.TABLE_CATEGORIES['critical']['tables']
        
        results = await validator.validate_all_tables(tables)
        
        print("\n=== Row Count Validation Results ===")
        for result in results:
            status_icon = "✓" if result.status == 'PASS' else "⚠" if result.status == 'WARNING' else "✗"
            print(f"{status_icon} {result.table_name}: {result.source_count} → {result.destination_count} "
                  f"(diff: {result.difference:+d}, {result.percentage_diff:.4f}%) [{result.status}]")
        
        summary = validator.get_summary()
        print(f"\nSummary: {summary['passed']}/{summary['total']} passed, "
              f"{summary['failed']} failed, {summary['warnings']} warnings")
        
        if validator.has_failures():
            sys.exit(1)
            
    finally:
        await source_session.close()
        await dest_session.close()


async def validate_checksum(args):
    """Validate checksums only."""
    source_session = create_async_session(args.source_url)
    dest_session = create_async_session(args.dest_url)
    
    try:
        validator = ChecksumValidator(source_session, dest_session)
        
        tables = args.tables or ['users', 'teams', 'tasks']
        
        for table in tables:
            result = await validator.validate_table(
                table, 
                use_partitioning=args.use_partitioning
            )
            
            status_icon = "✓" if result.status == 'MATCH' else "✗"
            print(f"{status_icon} {result.table_name}: {result.status}")
            if result.status == 'MISMATCH':
                print(f"  Source: {result.source_checksum[:32]}...")
                print(f"  Dest:   {result.destination_checksum[:32]}...")
        
        if validator.has_mismatches():
            sys.exit(1)
            
    finally:
        await source_session.close()
        await dest_session.close()


async def validate_referential(args):
    """Validate referential integrity only."""
    source_session = create_async_session(args.source_url)
    dest_session = create_async_session(args.dest_url)
    
    try:
        validator = ReferentialIntegrityValidator(source_session, dest_session)
        
        results = await validator.validate_all_relationships()
        
        print("\n=== Referential Integrity Validation Results ===")
        for result in results:
            status_icon = "✓" if result.status == 'PASS' else "⚠" if result.status == 'WARNING' else "✗"
            print(f"{status_icon} {result.relationship_name}")
            if result.orphaned_count > 0:
                print(f"  Orphaned records: {result.orphaned_count}/{result.total_children} "
                      f"({result.orphaned_percentage:.4f}%)")
        
        summary = validator.get_summary()
        print(f"\nSummary: {summary['passed']}/{summary['total']} passed, "
              f"{summary['failed']} failed, {summary['total_orphaned_records']} total orphaned")
        
        if validator.has_failures():
            sys.exit(1)
            
    finally:
        await source_session.close()
        await dest_session.close()


async def validate_business_rules(args):
    """Validate business rules only."""
    dest_session = create_async_session(args.dest_url)
    
    try:
        validator = BusinessRuleValidator(dest_session)
        
        results = await validator.validate_all_rules()
        
        print("\n=== Business Rule Validation Results ===")
        for result in results:
            status_icon = "✓" if result.status == 'PASS' else "⚠" if result.status == 'WARNING' else "✗"
            print(f"{status_icon} {result.rule_name} [{result.severity.value}]")
            if result.violation_count > 0:
                print(f"  Violations: {result.violation_count}/{result.total_checked} "
                      f"({result.violation_percentage:.4f}%)")
        
        summary = validator.get_summary()
        print(f"\nSummary: {summary['passed']}/{summary['total']} passed, "
              f"{summary['failed']} failed, {summary['critical_violations']} critical violations")
        
        if validator.has_failures():
            sys.exit(1)
            
    finally:
        await dest_session.close()


async def verify_rollback(args):
    """Verify rollback procedure."""
    dest_session = create_async_session(args.dest_url)
    
    try:
        from .rollback_verifier import RollbackVerifier
        
        verifier = RollbackVerifier(
            session=dest_session,
            migration_id=args.migration_id
        )
        
        # Load pre-migration snapshots from file if provided
        if args.snapshot_file:
            with open(args.snapshot_file, 'r') as f:
                snapshots = json.load(f)
                verifier._snapshots = snapshots
        
        tables = args.tables or MigrationValidator.CORE_TABLES
        
        results = await verifier.verify_all_tables(tables)
        
        print("\n=== Rollback Verification Results ===")
        for result in results:
            status_icon = "✓" if result.status.value == 'verified' else "⚠" if result.status.value == 'partial' else "✗"
            print(f"{status_icon} {result.table_name}: {result.status.value}")
            print(f"  Pre-migration: {result.row_count_pre} rows")
            print(f"  Post-rollback: {result.row_count_rollback} rows")
        
        report = verifier.generate_report()
        print(f"\nOverall Status: {report.overall_status.value}")
        
        if not verifier.is_rollback_verified():
            sys.exit(1)
            
    finally:
        await dest_session.close()


def main():
    parser = argparse.ArgumentParser(
        description='TaskFlow Pro Data Migration Validation CLI'
    )
    subparsers = parser.add_subparsers(dest='command', help='Validation command')
    
    # Common arguments
    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument('--source-url', required=True, help='Source database URL')
    common_parser.add_argument('--dest-url', required=True, help='Destination database URL')
    
    # Validate all command
    all_parser = subparsers.add_parser(
        'validate-all', 
        parents=[common_parser],
        help='Run complete migration validation'
    )
    all_parser.add_argument('--migration-id', required=True, help='Migration identifier')
    all_parser.add_argument('--pre-validation', action='store_true', help='Run pre-migration checks')
    all_parser.add_argument('--skip-checksums', action='store_true', help='Skip checksum validation')
    all_parser.add_argument('--skip-referential', action='store_true', help='Skip referential integrity')
    all_parser.add_argument('--skip-business-rules', action='store_true', help='Skip business rules')
    
    # Row count command
    row_parser = subparsers.add_parser(
        'row-count',
        parents=[common_parser],
        help='Validate row counts only'
    )
    row_parser.add_argument('--tables', nargs='+', help='Tables to validate')
    
    # Checksum command
    checksum_parser = subparsers.add_parser(
        'checksum',
        parents=[common_parser],
        help='Validate checksums only'
    )
    checksum_parser.add_argument('--tables', nargs='+', help='Tables to validate')
    checksum_parser.add_argument('--use-partitioning', action='store_true', help='Use partitioned validation')
    
    # Referential integrity command
    ref_parser = subparsers.add_parser(
        'referential',
        parents=[common_parser],
        help='Validate referential integrity only'
    )
    
    # Business rules command
    rules_parser = subparsers.add_parser(
        'business-rules',
        parents=[common_parser],
        help='Validate business rules only'
    )
    
    # Rollback verification command
    rollback_parser = subparsers.add_parser(
        'verify-rollback',
        help='Verify rollback procedure'
    )
    rollback_parser.add_argument('--migration-id', required=True, help='Migration identifier')
    rollback_parser.add_argument('--dest-url', required=True, help='Destination database URL')
    rollback_parser.add_argument('--tables', nargs='+', help='Tables to verify')
    rollback_parser.add_argument('--snapshot-file', help='Pre-migration snapshots JSON file')
    
    args = parser.parse_args()
    
    if args.command is None:
        parser.print_help()
        sys.exit(1)
    
    # Run appropriate command
    commands = {
        'validate-all': validate_all,
        'row-count': validate_row_count,
        'checksum': validate_checksum,
        'referential': validate_referential,
        'business-rules': validate_business_rules,
        'verify-rollback': verify_rollback,
    }
    
    command_func = commands.get(args.command)
    if command_func:
        asyncio.run(command_func(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()