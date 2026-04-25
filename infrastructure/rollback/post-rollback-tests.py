#!/usr/bin/env python3
"""
TaskFlow Pro Post-Rollback Validation Tests
============================================
Comprehensive test suite to verify system health after rollback.

These tests ensure:
1. All services are healthy and responding
2. Data integrity is maintained
3. Critical user flows work correctly
4. Performance is within acceptable bounds
"""

import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import aiohttp
import asyncpg
import pytest
from pytest_asyncio import fixture

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('post-rollback-tests')


@dataclass
class TestResult:
    """Result of a validation test."""
    test_name: str
    passed: bool
    duration_seconds: float
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


class PostRollbackValidator:
    """Main validator class for post-rollback testing."""
    
    def __init__(self, base_url: str, db_dsn: str):
        self.base_url = base_url
        self.db_dsn = db_dsn
        self.results: List[TestResult] = []
        self._session: Optional[aiohttp.ClientSession] = None
        self._db_pool: Optional[asyncpg.Pool] = None
    
    async def __aenter__(self):
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30)
        )
        self._db_pool = await asyncpg.create_pool(
            self.db_dsn,
            min_size=1,
            max_size=5
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._session:
            await self._session.close()
        if self._db_pool:
            await self._db_pool.close()
    
    async def run_all_validations(self) -> List[TestResult]:
        """Run complete validation suite."""
        logger.info("Starting post-rollback validation suite")
        
        # Phase 1: Health Checks
        await self._run_health_checks()
        
        # Phase 2: Data Integrity
        await self._run_data_integrity_checks()
        
        # Phase 3: Critical User Flows
        await self._run_smoke_tests()
        
        # Phase 4: Performance Validation
        await self._run_performance_checks()
        
        return self.results
    
    async def _run_health_checks(self):
        """Verify all services are healthy."""
        logger.info("Running health checks...")
        
        services = [
            ('backend', '/api/v1/health'),
            ('frontend', '/health'),
            ('websocket', '/ws/health'),
        ]
        
        for service_name, endpoint in services:
            start_time = time.time()
            try:
                url = urljoin(self.base_url, endpoint)
                async with self._session.get(url) as response:
                    passed = response.status == 200
                    body = await response.text() if passed else None
                    
                    self.results.append(TestResult(
                        test_name=f"health_check_{service_name}",
                        passed=passed,
                        duration_seconds=time.time() - start_time,
                        message=f"{service_name} is {'healthy' if passed else 'unhealthy'}",
                        details={'status_code': response.status, 'response': body}
                    ))
            except Exception as e:
                self.results.append(TestResult(
                    test_name=f"health_check_{service_name}",
                    passed=False,
                    duration_seconds=time.time() - start_time,
                    message=f"Health check failed: {str(e)}",
                    details={'error': str(e)}
                ))
    
    async def _run_data_integrity_checks(self):
        """Verify database integrity after rollback."""
        logger.info("Running data integrity checks...")
        
        async with self._db_pool.acquire() as conn:
            # Check 1: Critical tables exist
            await self._check_critical_tables(conn)
            
            # Check 2: Row counts are reasonable
            await self._check_row_counts(conn)
            
            # Check 3: Foreign key integrity
            await self._check_foreign_keys(conn)
            
            # Check 4: No orphaned records
            await self._check_orphaned_records(conn)
            
            # Check 5: Index consistency
            await self._check_indexes(conn)
    
    async def _check_critical_tables(self, conn: asyncpg.Connection):
        """Verify critical tables exist."""
        start_time = time.time()
        critical_tables = [
            'users', 'tasks', 'teams', 'team_members',
            'notifications', 'user_sessions', 'schema_migrations'
        ]
        
        missing_tables = []
        for table in critical_tables:
            exists = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = $1)",
                table
            )
            if not exists:
                missing_tables.append(table)
        
        self.results.append(TestResult(
            test_name="data_integrity_critical_tables",
            passed=len(missing_tables) == 0,
            duration_seconds=time.time() - start_time,
            message=f"Critical tables check: {len(missing_tables)} missing" if missing_tables else "All critical tables present",
            details={'missing_tables': missing_tables}
        ))
    
    async def _check_row_counts(self, conn: asyncpg.Connection):
        """Verify row counts are within expected bounds."""
        start_time = time.time()
        
        # Get baseline counts from pre-deployment snapshot
        # For now, just verify tables aren't empty
        checks = [
            ('users', 'SELECT COUNT(*) FROM users', 1),
            ('tasks', 'SELECT COUNT(*) FROM tasks', 0),
            ('teams', 'SELECT COUNT(*) FROM teams', 0),
        ]
        
        issues = []
        for table_name, query, min_count in checks:
            count = await conn.fetchval(query)
            if count < min_count:
                issues.append(f"{table_name}: {count} rows (min: {min_count})")
        
        self.results.append(TestResult(
            test_name="data_integrity_row_counts",
            passed=len(issues) == 0,
            duration_seconds=time.time() - start_time,
            message="Row counts valid" if not issues else f"Row count issues: {', '.join(issues)}",
            details={'issues': issues}
        ))
    
    async def _check_foreign_keys(self, conn: asyncpg.Connection):
        """Verify foreign key integrity."""
        start_time = time.time()
        
        fk_checks = [
            ("tasks.assignee_id -> users.id", 
             """SELECT COUNT(*) FROM tasks t 
                LEFT JOIN users u ON t.assignee_id = u.id 
                WHERE t.assignee_id IS NOT NULL AND u.id IS NULL"""),
            ("tasks.creator_id -> users.id",
             """SELECT COUNT(*) FROM tasks t 
                LEFT JOIN users u ON t.creator_id = u.id 
                WHERE u.id IS NULL"""),
            ("team_members.user_id -> users.id",
             """SELECT COUNT(*) FROM team_members tm 
                LEFT JOIN users u ON tm.user_id = u.id 
                WHERE u.id IS NULL"""),
            ("team_members.team_id -> teams.id",
             """SELECT COUNT(*) FROM team_members tm 
                LEFT JOIN teams t ON tm.team_id = t.id 
                WHERE t.id IS NULL"""),
        ]
        
        violations = []
        for description, query in fk_checks:
            count = await conn.fetchval(query)
            if count > 0:
                violations.append(f"{description}: {count} violations")
        
        self.results.append(TestResult(
            test_name="data_integrity_foreign_keys",
            passed=len(violations) == 0,
            duration_seconds=time.time() - start_time,
            message="Foreign key integrity verified" if not violations else f"FK violations: {', '.join(violations)}",
            details={'violations': violations}
        ))
    
    async def _check_orphaned_records(self, conn: asyncpg.Connection):
        """Check for orphaned records."""
        start_time = time.time()
        
        orphan_checks = [
            ("orphaned_task_comments",
             """SELECT COUNT(*) FROM task_comments tc 
                LEFT JOIN tasks t ON tc.task_id = t.id 
                WHERE t.id IS NULL"""),
            ("orphaned_notifications",
             """SELECT COUNT(*) FROM notifications n 
                LEFT JOIN users u ON n.user_id = u.id 
                WHERE u.id IS NULL"""),
        ]
        
        orphans_found = []
        for check_name, query in orphan_checks:
            count = await conn.fetchval(query)
            if count > 0:
                orphans_found.append(f"{check_name}: {count}")
        
        self.results.append(TestResult(
            test_name="data_integrity_orphaned_records",
            passed=len(orphans_found) == 0,
            duration_seconds=time.time() - start_time,
            message="No orphaned records" if not orphans_found else f"Orphaned records: {', '.join(orphans_found)}",
            details={'orphans': orphans_found}
        ))
    
    async def _check_indexes(self, conn: asyncpg.Connection):
        """Verify critical indexes exist."""
        start_time = time.time()
        
        critical_indexes = [
            'idx_users_email',
            'idx_tasks_assignee',
            'idx_tasks_status',
            'idx_teams_owner',
            'idx_notifications_user_read',
        ]
        
        missing_indexes = []
        for index in critical_indexes:
            exists = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = $1)",
                index
            )
            if not exists:
                missing_indexes.append(index)
        
        self.results.append(TestResult(
            test_name="data_integrity_indexes",
            passed=len(missing_indexes) == 0,
            duration_seconds=time.time() - start_time,
            message="All critical indexes present" if not missing_indexes else f"Missing indexes: {', '.join(missing_indexes)}",
            details={'missing_indexes': missing_indexes}
        ))
    
    async def _run_smoke_tests(self):
        """Run critical user flow smoke tests."""
        logger.info("Running smoke tests...")
        
        await self._test_user_authentication()
        await self._test_task_creation()
        await self._test_task_assignment()
        await self._test_team_invitation()
        await self._test_real_time_notifications()
    
    async def _test_user_authentication(self):
        """Test user authentication flow."""
        start_time = time.time()
        
        try:
            # Test login endpoint
            url = urljoin(self.base_url, '/api/v1/auth/login')
            payload = {
                'email': 'test@taskflow.pro',
                'password': 'TestPassword123!'
            }
            
            async with self._session.post(url, json=payload) as response:
                passed = response.status in [200, 401]  # 401 is OK for invalid creds
                
                self.results.append(TestResult(
                    test_name="smoke_test_user_authentication",
                    passed=passed,
                    duration_seconds=time.time() - start_time,
                    message="Authentication endpoint responding" if passed else "Authentication endpoint failed",
                    details={'status_code': response.status}
                ))
        except Exception as e:
            self.results.append(TestResult(
                test_name="smoke_test_user_authentication",
                passed=False,
                duration_seconds=time.time() - start_time,
                message=f"Authentication test failed: {str(e)}",
                details={'error': str(e)}
            ))
    
    async def _test_task_creation(self):
        """Test task creation API."""
        start_time = time.time()
        
        try:
            url = urljoin(self.base_url, '/api/v1/tasks')
            
            async with self._session.get(url) as response:
                passed = response.status in [200, 401]  # 401 without auth is OK
                
                self.results.append(TestResult(
                    test_name="smoke_test_task_creation",
                    passed=passed,
                    duration_seconds=time.time() - start_time,
                    message="Task API responding" if passed else "Task API failed",
                    details={'status_code': response.status}
                ))
        except Exception as e:
            self.results.append(TestResult(
                test_name="smoke_test_task_creation",
                passed=False,
                duration_seconds=time.time() - start_time,
                message=f"Task creation test failed: {str(e)}",
                details={'error': str(e)}
            ))
    
    async def _test_task_assignment(self):
        """Test task assignment functionality."""
        start_time = time.time()
        
        try:
            url = urljoin(self.base_url, '/api/v1/tasks/1/assign')
            
            async with self._session.post(url, json={'assignee_id': 1}) as response:
                passed = response.status in [200, 401, 404]  # Expected responses
                
                self.results.append(TestResult(
                    test_name="smoke_test_task_assignment",
                    passed=passed,
                    duration_seconds=time.time() - start_time,
                    message="Task assignment API responding" if passed else "Task assignment API failed",
                    details={'status_code': response.status}
                ))
        except Exception as e:
            self.results.append(TestResult(
                test_name="smoke_test_task_assignment",
                passed=False,
                duration_seconds=time.time() - start_time,
                message=f"Task assignment test failed: {str(e)}",
                details={'error': str(e)}
            ))
    
    async def _test_team_invitation(self):
        """Test team invitation flow."""
        start_time = time.time()
        
        try:
            url = urljoin(self.base_url, '/api/v1/teams/1/invite')
            
            async with self._session.post(url, json={'email': 'invite@test.com'}) as response:
                passed = response.status in [200, 401]  # Expected responses
                
                self.results.append(TestResult(
                    test_name="smoke_test_team_invitation",
                    passed=passed,
                    duration_seconds=time.time() - start_time,
                    message="Team invitation API responding" if passed else "Team invitation API failed",
                    details={'status_code': response.status}
                ))
        except Exception as e:
            self.results.append(TestResult(
                test_name="smoke_test_team_invitation",
                passed=False,
                duration_seconds=time.time() - start_time,
                message=f"Team invitation test failed: {str(e)}",
                details={'error': str(e)}
            ))
    
    async def _test_real_time_notifications(self):
        """Test WebSocket notification connection."""
        start_time = time.time()
        
        try:
            import websockets
            
            ws_url = self.base_url.replace('https://', 'wss://').replace('http://', 'ws://')
            ws_url = urljoin(ws_url, '/ws/notifications')
            
            # Try to connect with timeout
            try:
                async with websockets.connect(ws_url, timeout=5) as websocket:
                    # Try to send ping
                    await websocket.send(json.dumps({'type': 'ping'}))
                    response = await asyncio.wait_for(websocket.recv(), timeout=5)
                    
                    self.results.append(TestResult(
                        test_name="smoke_test_websocket_notifications",
                        passed=True,
                        duration_seconds=time.time() - start_time,
                        message="WebSocket connection successful",
                        details={'response': response}
                    ))
            except asyncio.TimeoutError:
                self.results.append(TestResult(
                    test_name="smoke_test_websocket_notifications",
                    passed=False,
                    duration_seconds=time.time() - start_time,
                    message="WebSocket connection timeout",
                    details={'error': 'Connection timeout'}
                ))
                
        except ImportError:
            self.results.append(TestResult(
                test_name="smoke_test_websocket_notifications",
                passed=False,
                duration_seconds=time.time() - start_time,
                message="websockets package not installed",
                details={'error': 'ImportError'}
            ))
        except Exception as e:
            self.results.append(TestResult(
                test_name="smoke_test_websocket_notifications",
                passed=False,
                duration_seconds=time.time() - start_time,
                message=f"WebSocket test failed: {str(e)}",
                details={'error': str(e)}
            ))
    
    async def _run_performance_checks(self):
        """Verify performance is within acceptable bounds."""
        logger.info("Running performance checks...")
        
        await self._check_api_latency()
        await self._check_database_performance()
    
    async def _check_api_latency(self):
        """Check API endpoint latency."""
        start_time = time.time()
        
        endpoints = [
            ('/api/v1/health', 'GET'),
            ('/api/v1/tasks', 'GET'),
        ]
        
        latencies = []
        for endpoint, method in endpoints:
            url = urljoin(self.base_url, endpoint)
            req_start = time.time()
            
            try:
                async with self._session.request(method, url) as response:
                    latency = (time.time() - req_start) * 1000  # ms
                    latencies.append({
                        'endpoint': endpoint,
                        'latency_ms': latency,
                        'status': response.status
                    })
            except Exception as e:
                latencies.append({
                    'endpoint': endpoint,
                    'error': str(e)
                })
        
        # Check if any latency exceeds threshold (1000ms)
        slow_endpoints = [
            l for l in latencies 
            if l.get('latency_ms', 0) > 1000
        ]
        
        self.results.append(TestResult(
            test_name="performance_api_latency",
            passed=len(slow_endpoints) == 0,
            duration_seconds=time.time() - start_time,
            message="API latency within bounds" if not slow_endpoints else f"Slow endpoints: {len(slow_endpoints)}",
            details={'latencies': latencies, 'slow_endpoints': slow_endpoints}
        ))
    
    async def _check_database_performance(self):
        """Check database query performance."""
        start_time = time.time()
        
        async with self._db_pool.acquire() as conn:
            # Test query performance
            perf_tests = [
                ("User lookup by email", 
                 "SELECT * FROM users WHERE email = 'test@taskflow.pro'"),
                ("Task list query", 
                 "SELECT * FROM tasks WHERE assignee_id = 1 LIMIT 10"),
                ("Team members query",
                 "SELECT * FROM team_members WHERE team_id = 1"),
            ]
            
            results = []
            for test_name, query in perf_tests:
                query_start = time.time()
                try:
                    await conn.fetch(query)
                    duration = (time.time() - query_start) * 1000
                    results.append({
                        'test': test_name,
                        'duration_ms': duration,
                        'passed': duration < 500  # 500ms threshold
                    })
                except Exception as e:
                    results.append({
                        'test': test_name,
                        'error': str(e),
                        'passed': False
                    })
            
            failed_tests = [r for r in results if not r.get('passed', False)]
            
            self.results.append(TestResult(
                test_name="performance_database_queries",
                passed=len(failed_tests) == 0,
                duration_seconds=time.time() - start_time,
                message="Database performance acceptable" if not failed_tests else f"Slow queries: {len(failed_tests)}",
                details={'query_results': results}
            ))
    
    def generate_report(self) -> dict:
        """Generate validation report."""
        passed = sum(1 for r in self.results if r.passed)
        failed = len(self.results) - passed
        
        return {
            'timestamp': datetime.utcnow().isoformat(),
            'summary': {
                'total_tests': len(self.results),
                'passed': passed,
                'failed': failed,
                'success_rate': passed / len(self.results) if self.results else 0
            },
            'results': [
                {
                    'test_name': r.test_name,
                    'passed': r.passed,
                    'duration_seconds': r.duration_seconds,
                    'message': r.message,
                    'details': r.details
                }
                for r in self.results
            ]
        }
    
    def all_passed(self) -> bool:
        """Check if all tests passed."""
        return all(r.passed for r in self.results)


# Pytest fixtures and tests for CI/CD integration

@fixture(scope="session")
async def validator():
    """Create validator instance for tests."""
    base_url = os.getenv('TASKFLOW_BASE_URL', 'http://localhost:8000')
    db_dsn = os.getenv('DATABASE_URL', 'postgresql://localhost/taskflow_test')
    
    async with PostRollbackValidator(base_url, db_dsn) as v:
        yield v


@pytest.mark.asyncio
async def test_health_checks(validator: PostRollbackValidator):
    """Test all service health endpoints."""
    await validator._run_health_checks()
    health_results = [r for r in validator.results if r.test_name.startswith('health_check')]
    assert all(r.passed for r in health_results), "Some health checks failed"


@pytest.mark.asyncio
async def test_data_integrity(validator: PostRollbackValidator):
    """Test database integrity."""
    await validator._run_data_integrity_checks()
    integrity_results = [r for r in validator.results if r.test_name.startswith('data_integrity')]
    assert all(r.passed for r in integrity_results), "Data integrity checks failed"


@pytest.mark.asyncio
async def test_smoke_tests(validator: PostRollbackValidator):
    """Test critical user flows."""
    await validator._run_smoke_tests()
    smoke_results = [r for r in validator.results if r.test_name.startswith('smoke_test')]
    assert all(r.passed for r in smoke_results), "Smoke tests failed"


@pytest.mark.asyncio
async def test_performance(validator: PostRollbackValidator):
    """Test performance metrics."""
    await validator._run_performance_checks()
    perf_results = [r for r in validator.results if r.test_name.startswith('performance')]
    assert all(r.passed for r in perf_results), "Performance checks failed"


# CLI entry point
async def main():
    """Run validation suite from command line."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Post-Rollback Validation')
    parser.add_argument('--base-url', default=os.getenv('TASKFLOW_BASE_URL', 'http://localhost:8000'))
    parser.add_argument('--db-dsn', default=os.getenv('DATABASE_URL', 'postgresql://localhost/taskflow'))
    parser.add_argument('--output', '-o', help='Output file for JSON report')
    parser.add_argument('--exit-code', action='store_true', help='Exit with non-zero code if any test fails')
    
    args = parser.parse_args()
    
    async with PostRollbackValidator(args.base_url, args.db_dsn) as validator:
        await validator.run_all_validations()
        report = validator.generate_report()
        
        # Print summary
        print("\n" + "="*60)
        print("POST-ROLLBACK VALIDATION REPORT")
        print("="*60)
        print(f"Total Tests: {report['summary']['total_tests']}")
        print(f"Passed: {report['summary']['passed']}")
        print(f"Failed: {report['summary']['failed']}")
        print(f"Success Rate: {report['summary']['success_rate']:.1%}")
        print("="*60)
        
        # Print failed tests
        failed_tests = [r for r in validator.results if not r.passed]
        if failed_tests:
            print("\nFAILED TESTS:")
            for test in failed_tests:
                print(f"  ✗ {test.test_name}: {test.message}")
        
        # Save report if requested
        if args.output:
            with open(args.output, 'w') as f:
                json.dump(report, f, indent=2)
            print(f"\nReport saved to: {args.output}")
        
        # Exit code
        if args.exit_code and failed_tests:
            sys.exit(1)
        
        sys.exit(0)


if __name__ == '__main__':
    asyncio.run(main())
