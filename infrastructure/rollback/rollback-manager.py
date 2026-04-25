#!/usr/bin/env python3
"""
TaskFlow Pro Rollback Manager
=============================
Central orchestration for deployment rollbacks across all components.

Author: Release Safety Engineer
Version: 1.0.0
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
import yaml

import asyncpg
import kubernetes_asyncio as k8s
from kubernetes_asyncio import client, config
import boto3
from botocore.exceptions import ClientError


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('/var/log/rollback-manager.log')
    ]
)
logger = logging.getLogger('rollback-manager')


class DeploymentState(Enum):
    """Deployment state machine states."""
    IDLE = auto()
    DEPLOYING = auto()
    CANARY = auto()
    STABLE = auto()
    ROLLING_BACK = auto()
    ROLLED_BACK = auto()
    FAILED = auto()


class RollbackTrigger(Enum):
    """Automated rollback trigger types."""
    HEALTH_CHECK_FAILURE = "health_check_failure"
    ERROR_RATE_THRESHOLD = "error_rate_threshold"
    LATENCY_THRESHOLD = "latency_threshold"
    MANUAL = "manual"
    CANARY_REJECTION = "canary_rejection"
    DATABASE_MIGRATION_FAILURE = "database_migration_failure"
    INFRASTRUCTURE_FAILURE = "infrastructure_failure"


@dataclass
class RollbackContext:
    """Context for rollback operations."""
    deployment_id: str
    version_from: str
    version_to: str
    environment: str
    namespace: str
    triggered_by: RollbackTrigger
    triggered_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RollbackResult:
    """Result of rollback operation."""
    success: bool
    component: str
    duration_seconds: float
    error_message: Optional[str] = None
    artifacts: Dict[str, Any] = field(default_factory=dict)


class StateMachine:
    """Deployment state machine with persistence."""
    
    VALID_TRANSITIONS = {
        DeploymentState.IDLE: [DeploymentState.DEPLOYING],
        DeploymentState.DEPLOYING: [DeploymentState.CANARY, DeploymentState.FAILED],
        DeploymentState.CANARY: [DeploymentState.STABLE, DeploymentState.ROLLING_BACK, DeploymentState.FAILED],
        DeploymentState.STABLE: [DeploymentState.DEPLOYING, DeploymentState.ROLLING_BACK],
        DeploymentState.ROLLING_BACK: [DeploymentState.ROLLED_BACK, DeploymentState.FAILED],
        DeploymentState.ROLLED_BACK: [DeploymentState.DEPLOYING],
        DeploymentState.FAILED: [DeploymentState.ROLLING_BACK, DeploymentState.IDLE]
    }
    
    def __init__(self, deployment_id: str, state_file: str = "/var/lib/rollback/state.json"):
        self.deployment_id = deployment_id
        self.state_file = Path(state_file)
        self._state = DeploymentState.IDLE
        self._history: List[Dict] = []
        self._lock = asyncio.Lock()
        self._load_state()
    
    def _load_state(self):
        """Load state from persistent storage."""
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text())
                self._state = DeploymentState[data.get('state', 'IDLE')]
                self._history = data.get('history', [])
                logger.info(f"Loaded state: {self._state.name} for deployment {self.deployment_id}")
            except Exception as e:
                logger.error(f"Failed to load state: {e}")
    
    async def _save_state(self):
        """Persist state to storage."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            'deployment_id': self.deployment_id,
            'state': self._state.name,
            'timestamp': datetime.utcnow().isoformat(),
            'history': self._history[-100:]  # Keep last 100 transitions
        }
        self.state_file.write_text(json.dumps(data, indent=2))
    
    async def transition(self, new_state: DeploymentState, reason: str = "") -> bool:
        """Attempt state transition."""
        async with self._lock:
            if new_state not in self.VALID_TRANSITIONS.get(self._state, []):
                logger.error(
                    f"Invalid transition: {self._state.name} -> {new_state.name}"
                )
                return False
            
            old_state = self._state
            self._state = new_state
            self._history.append({
                'from': old_state.name,
                'to': new_state.name,
                'timestamp': datetime.utcnow().isoformat(),
                'reason': reason
            })
            
            await self._save_state()
            logger.info(f"State transition: {old_state.name} -> {new_state.name} ({reason})")
            return True
    
    @property
    def current_state(self) -> DeploymentState:
        return self._state
    
    def get_history(self) -> List[Dict]:
        return self._history.copy()


class KubernetesRollback:
    """Kubernetes deployment rollback handler."""
    
    def __init__(self, namespace: str):
        self.namespace = namespace
        self._k8s_client = None
    
    async def _get_client(self):
        """Initialize Kubernetes client."""
        if self._k8s_client is None:
            await config.load_kube_config()
            self._k8s_client = client.AppsV1Api()
        return self._k8s_client
    
    async def rollback_deployment(
        self, 
        deployment_name: str, 
        revision: Optional[int] = None
    ) -> RollbackResult:
        """Rollback a Kubernetes deployment."""
        start_time = datetime.utcnow()
        
        try:
            k8s_client = await self._get_client()
            
            # Get current deployment
            deployment = await k8s_client.read_namespaced_deployment(
                name=deployment_name,
                namespace=self.namespace
            )
            
            if revision:
                # Rollback to specific revision
                rollback_request = client.AppsV1beta1DeploymentRollback(
                    api_version="apps/v1",
                    kind="Deployment",
                    name=deployment_name,
                    rollback_to=client.AppsV1beta1RollbackConfig(revision=revision)
                )
                await k8s_client.create_namespaced_deployment_rollback(
                    name=deployment_name,
                    namespace=self.namespace,
                    body=rollback_request
                )
            else:
                # Restore previous replica set
                replica_sets = await k8s_client.list_namespaced_replica_set(
                    namespace=self.namespace,
                    label_selector=f"app={deployment_name}"
                )
                
                # Find previous RS (not the current one)
                current_revision = deployment.metadata.annotations.get(
                    'deployment.kubernetes.io/revision', '0'
                )
                
                previous_rs = None
                for rs in replica_sets.items:
                    rs_revision = rs.metadata.annotations.get(
                        'deployment.kubernetes.io/revision', '0'
                    )
                    if int(rs_revision) < int(current_revision):
                        if previous_rs is None or int(rs_revision) > int(
                            previous_rs.metadata.annotations.get(
                                'deployment.kubernetes.io/revision', '0'
                            )
                        ):
                            previous_rs = rs
                
                if previous_rs:
                    # Scale current deployment to 0
                    deployment.spec.replicas = 0
                    await k8s_client.patch_namespaced_deployment_scale(
                        name=deployment_name,
                        namespace=self.namespace,
                        body={'spec': {'replicas': 0}}
                    )
                    
                    # Scale previous RS to desired replicas
                    await k8s_client.patch_namespaced_replica_set_scale(
                        name=previous_rs.metadata.name,
                        namespace=self.namespace,
                        body={'spec': {'replicas': deployment.spec.replicas}}
                    )
            
            duration = (datetime.utcnow() - start_time).total_seconds()
            
            return RollbackResult(
                success=True,
                component=f"k8s/{deployment_name}",
                duration_seconds=duration,
                artifacts={
                    'revision': revision,
                    'namespace': self.namespace,
                    'deployment': deployment_name
                }
            )
            
        except Exception as e:
            duration = (datetime.utcnow() - start_time).total_seconds()
            logger.error(f"K8s rollback failed for {deployment_name}: {e}")
            return RollbackResult(
                success=False,
                component=f"k8s/{deployment_name}",
                duration_seconds=duration,
                error_message=str(e)
            )


class DatabaseRollback:
    """Database rollback handler for PostgreSQL."""
    
    def __init__(self, dsn: str):
        self.dsn = dsn
        self._pool: Optional[asyncpg.Pool] = None
    
    async def _get_pool(self) -> asyncpg.Pool:
        """Get database connection pool."""
        if self._pool is None:
            self._pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=5)
        return self._pool
    
    async def rollback_migration(
        self, 
        migration_version: str,
        backup_path: Optional[str] = None
    ) -> RollbackResult:
        """Rollback database migration."""
        start_time = datetime.utcnow()
        
        try:
            pool = await self._get_pool()
            
            async with pool.acquire() as conn:
                # Check if migration is reversible
                migration_record = await conn.fetchrow(
                    """
                    SELECT version, name, is_reversible, rollback_script 
                    FROM schema_migrations 
                    WHERE version = $1
                    """,
                    migration_version
                )
                
                if not migration_record:
                    raise ValueError(f"Migration {migration_version} not found")
                
                if not migration_record['is_reversible']:
                    # Must use backup restore
                    if not backup_path:
                        raise ValueError(
                            f"Migration {migration_version} is not reversible and no backup provided"
                        )
                    return await self._restore_from_backup(backup_path)
                
                # Execute rollback script
                rollback_script = migration_record['rollback_script']
                
                # Start transaction
                async with conn.transaction():
                    # Execute rollback script
                    await conn.execute(rollback_script)
                    
                    # Update migration record
                    await conn.execute(
                        """
                        DELETE FROM schema_migrations 
                        WHERE version = $1
                        """,
                        migration_version
                    )
                    
                    # Log rollback
                    await conn.execute(
                        """
                        INSERT INTO migration_rollbacks 
                        (version, rolled_back_at, rollback_method)
                        VALUES ($1, NOW(), 'script')
                        """,
                        migration_version
                    )
            
            duration = (datetime.utcnow() - start_time).total_seconds()
            
            return RollbackResult(
                success=True,
                component="database",
                duration_seconds=duration,
                artifacts={
                    'migration_version': migration_version,
                    'method': 'script_rollback'
                }
            )
            
        except Exception as e:
            duration = (datetime.utcnow() - start_time).total_seconds()
            logger.error(f"Database rollback failed: {e}")
            return RollbackResult(
                success=False,
                component="database",
                duration_seconds=duration,
                error_message=str(e)
            )
    
    async def _restore_from_backup(self, backup_path: str) -> RollbackResult:
        """Restore database from backup file."""
        start_time = datetime.utcnow()
        
        try:
            # Parse DSN for connection parameters
            import urllib.parse
            parsed = urllib.parse.urlparse(self.dsn)
            
            env = os.environ.copy()
            env['PGPASSWORD'] = parsed.password or ''
            
            # Terminate existing connections
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    SELECT pg_terminate_backend(pid) 
                    FROM pg_stat_activity 
                    WHERE datname = current_database() 
                    AND pid <> pg_backend_pid()
                    """
                )
            
            # Restore from backup using pg_restore
            cmd = [
                'pg_restore',
                '--clean',
                '--if-exists',
                '--no-owner',
                '--no-privileges',
                '-h', parsed.hostname or 'localhost',
                '-p', str(parsed.port or 5432),
                '-U', parsed.username or 'postgres',
                '-d', parsed.path.lstrip('/'),
                backup_path
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env=env
            )
            
            if result.returncode not in [0, 1]:  # 1 = warnings, still OK
                raise RuntimeError(f"pg_restore failed: {result.stderr}")
            
            duration = (datetime.utcnow() - start_time).total_seconds()
            
            return RollbackResult(
                success=True,
                component="database",
                duration_seconds=duration,
                artifacts={
                    'method': 'backup_restore',
                    'backup_path': backup_path
                }
            )
            
        except Exception as e:
            duration = (datetime.utcnow() - start_time).total_seconds()
            logger.error(f"Database restore failed: {e}")
            return RollbackResult(
                success=False,
                component="database",
                duration_seconds=duration,
                error_message=str(e)
            )
    
    async def close(self):
        """Close database connections."""
        if self._pool:
            await self._pool.close()
            self._pool = None


class ConfigRollback:
    """Configuration rollback handler."""
    
    def __init__(self, config_backend: str = "kubernetes"):
        self.config_backend = config_backend
        self._s3_client = None
    
    def _get_s3_client(self):
        """Get S3 client for config storage."""
        if self._s3_client is None:
            self._s3_client = boto3.client('s3')
        return self._s3_client
    
    async def rollback_config(
        self,
        config_key: str,
        version_id: Optional[str] = None,
        environment: str = "production"
    ) -> RollbackResult:
        """Rollback configuration to previous version."""
        start_time = datetime.utcnow()
        
        try:
            s3 = self._get_s3_client()
            bucket = f"taskflow-pro-configs-{environment}"
            
            if version_id:
                # Restore specific version
                s3.copy_object(
                    Bucket=bucket,
                    Key=config_key,
                    CopySource={
                        'Bucket': bucket,
                        'Key': config_key,
                        'VersionId': version_id
                    }
                )
            else:
                # Get previous version
                versions = s3.list_object_versions(
                    Bucket=bucket,
                    Prefix=config_key,
                    MaxKeys=2
                )
                
                if len(versions.get('Versions', [])) < 2:
                    raise ValueError(f"No previous version found for {config_key}")
                
                # Versions are sorted by LastModified descending
                previous_version = versions['Versions'][1]
                
                s3.copy_object(
                    Bucket=bucket,
                    Key=config_key,
                    CopySource={
                        'Bucket': bucket,
                        'Key': config_key,
                        'VersionId': previous_version['VersionId']
                    }
                )
            
            # Update Kubernetes ConfigMap if applicable
            if config_key.endswith('.yaml') or config_key.endswith('.yml'):
                await self._update_configmap(config_key, environment)
            
            duration = (datetime.utcnow() - start_time).total_seconds()
            
            return RollbackResult(
                success=True,
                component=f"config/{config_key}",
                duration_seconds=duration,
                artifacts={
                    'config_key': config_key,
                    'version_id': version_id
                }
            )
            
        except Exception as e:
            duration = (datetime.utcnow() - start_time).total_seconds()
            logger.error(f"Config rollback failed: {e}")
            return RollbackResult(
                success=False,
                component=f"config/{config_key}",
                duration_seconds=duration,
                error_message=str(e)
            )
    
    async def _update_configmap(self, config_key: str, environment: str):
        """Update Kubernetes ConfigMap with rolled back config."""
        # Implementation depends on your ConfigMap structure
        pass


class RollbackOrchestrator:
    """Main rollback orchestration class."""
    
    def __init__(self, context: RollbackContext):
        self.context = context
        self.state_machine = StateMachine(context.deployment_id)
        self.k8s_rollback = KubernetesRollback(context.namespace)
        self.db_rollback = DatabaseRollback(
            os.getenv('DATABASE_URL', 'postgresql://localhost/taskflow')
        )
        self.config_rollback = ConfigRollback()
        self._handlers: Dict[str, Callable] = {
            'backend': self._rollback_backend,
            'frontend': self._rollback_frontend,
            'worker': self._rollback_worker,
            'websocket': self._rollback_websocket,
            'database': self._rollback_database,
            'config': self._rollback_config,
        }
    
    async def execute_rollback(
        self, 
        components: Optional[List[str]] = None
    ) -> Dict[str, RollbackResult]:
        """Execute rollback for specified components."""
        logger.info(f"Initiating rollback for deployment {self.context.deployment_id}")
        
        # Transition to rolling back state
        if not await self.state_machine.transition(
            DeploymentState.ROLLING_BACK,
            f"Triggered by {self.context.triggered_by.value}"
        ):
            raise RuntimeError("Failed to transition to ROLLING_BACK state")
        
        components = components or ['backend', 'frontend', 'worker', 'websocket']
        results = {}
        
        # Phase 1: Stop traffic (if not already done)
        await self._stop_traffic()
        
        # Phase 2: Rollback components in order
        rollback_order = self._determine_rollback_order(components)
        
        for component in rollback_order:
            handler = self._handlers.get(component)
            if handler:
                try:
                    result = await handler()
                    results[component] = result
                    
                    if not result.success:
                        logger.error(f"Rollback failed for {component}")
                        # Continue with other components but mark overall as failed
                except Exception as e:
                    logger.exception(f"Exception during {component} rollback")
                    results[component] = RollbackResult(
                        success=False,
                        component=component,
                        duration_seconds=0,
                        error_message=str(e)
                    )
        
        # Phase 3: Verify rollback
        all_success = all(r.success for r in results.values())
        
        if all_success:
            await self.state_machine.transition(
                DeploymentState.ROLLED_BACK,
                "All components rolled back successfully"
            )
            await self._resume_traffic()
        else:
            await self.state_machine.transition(
                DeploymentState.FAILED,
                "One or more components failed to rollback"
            )
        
        # Generate report
        await self._generate_report(results)
        
        return results
    
    def _determine_rollback_order(self, components: List[str]) -> List[str]:
        """Determine safe rollback order (reverse of deployment)."""
        # Order: websocket -> worker -> backend -> frontend -> config -> database
        priority = {
            'websocket': 1,
            'worker': 2,
            'backend': 3,
            'frontend': 4,
            'config': 5,
            'database': 6,
        }
        return sorted(components, key=lambda c: priority.get(c, 99))
    
    async def _stop_traffic(self):
        """Stop incoming traffic during rollback."""
        logger.info("Stopping traffic to application")
        # Implementation: set ingress to maintenance mode or scale to 0
        pass
    
    async def _resume_traffic(self):
        """Resume traffic after successful rollback."""
        logger.info("Resuming traffic to application")
        pass
    
    async def _rollback_backend(self) -> RollbackResult:
        """Rollback backend deployment."""
        return await self.k8s_rollback.rollback_deployment(
            'taskflow-backend',
            revision=None  # Auto-detect previous
        )
    
    async def _rollback_frontend(self) -> RollbackResult:
        """Rollback frontend deployment."""
        return await self.k8s_rollback.rollback_deployment(
            'taskflow-frontend',
            revision=None
        )
    
    async def _rollback_worker(self) -> RollbackResult:
        """Rollback worker deployment."""
        return await self.k8s_rollback.rollback_deployment(
            'taskflow-worker',
            revision=None
        )
    
    async def _rollback_websocket(self) -> RollbackResult:
        """Rollback WebSocket deployment."""
        return await self.k8s_rollback.rollback_deployment(
            'taskflow-websocket',
            revision=None
        )
    
    async def _rollback_database(self) -> RollbackResult:
        """Rollback database migrations."""
        # Get last migration to rollback
        # This should be passed in context or determined from deployment
        migration_version = self.context.metadata.get('migration_version')
        if migration_version:
            return await self.db_rollback.rollback_migration(migration_version)
        
        return RollbackResult(
            success=True,
            component="database",
            duration_seconds=0,
            error_message="No migration to rollback"
        )
    
    async def _rollback_config(self) -> RollbackResult:
        """Rollback configuration."""
        config_key = self.context.metadata.get('config_key', 'app-config.yaml')
        return await self.config_rollback.rollback_config(
            config_key,
            environment=self.context.environment
        )
    
    async def _generate_report(self, results: Dict[str, RollbackResult]):
        """Generate rollback report."""
        report = {
            'deployment_id': self.context.deployment_id,
            'timestamp': datetime.utcnow().isoformat(),
            'triggered_by': self.context.triggered_by.value,
            'environment': self.context.environment,
            'results': {
                component: {
                    'success': r.success,
                    'duration_seconds': r.duration_seconds,
                    'error_message': r.error_message,
                    'artifacts': r.artifacts
                }
                for component, r in results.items()
            },
            'final_state': self.state_machine.current_state.name
        }
        
        # Save report
        report_path = Path(f"/var/lib/rollback/reports/{self.context.deployment_id}.json")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2))
        
        # Send notifications
        await self._send_notifications(report)
    
    async def _send_notifications(self, report: dict):
        """Send rollback notifications."""
        # Implementation: Slack, PagerDuty, email
        logger.info(f"Rollback report generated: {report}")
    
    async def cleanup(self):
        """Cleanup resources."""
        await self.db_rollback.close()


class AutoRollbackMonitor:
    """Monitor for automated rollback triggers."""
    
    def __init__(self, orchestrator: RollbackOrchestrator):
        self.orchestrator = orchestrator
        self._thresholds = {
            'error_rate': 0.05,  # 5%
            'latency_p99': 2000,  # 2 seconds
            'health_check_failures': 3,
        }
        self._running = False
    
    async def start_monitoring(self):
        """Start monitoring for rollback triggers."""
        self._running = True
        logger.info("Auto-rollback monitoring started")
        
        while self._running:
            try:
                await self._check_health_metrics()
                await asyncio.sleep(30)  # Check every 30 seconds
            except Exception as e:
                logger.error(f"Monitoring error: {e}")
                await asyncio.sleep(5)
    
    async def _check_health_metrics(self):
        """Check health metrics against thresholds."""
        # Fetch metrics from Prometheus/Grafana
        metrics = await self._fetch_metrics()
        
        triggers = []
        
        if metrics.get('error_rate', 0) > self._thresholds['error_rate']:
            triggers.append(RollbackTrigger.ERROR_RATE_THRESHOLD)
        
        if metrics.get('latency_p99', 0) > self._thresholds['latency_p99']:
            triggers.append(RollbackTrigger.LATENCY_THRESHOLD)
        
        if metrics.get('health_check_failures', 0) >= self._thresholds['health_check_failures']:
            triggers.append(RollbackTrigger.HEALTH_CHECK_FAILURE)
        
        if triggers:
            logger.warning(f"Rollback triggers detected: {triggers}")
            # Initiate rollback with highest priority trigger
            await self.orchestrator.execute_rollback()
    
    async def _fetch_metrics(self) -> dict:
        """Fetch metrics from monitoring system."""
        # Implementation depends on your monitoring stack
        return {
            'error_rate': 0.0,
            'latency_p99': 0,
            'health_check_failures': 0,
        }
    
    def stop(self):
        """Stop monitoring."""
        self._running = False


# CLI Interface
async def main():
    """Main entry point for CLI usage."""
    import argparse
    
    parser = argparse.ArgumentParser(description='TaskFlow Pro Rollback Manager')
    parser.add_argument('command', choices=['rollback', 'status', 'history'])
    parser.add_argument('--deployment-id', required=True)
    parser.add_argument('--environment', default='production')
    parser.add_argument('--namespace', default='taskflow-pro')
    parser.add_argument('--version-from')
    parser.add_argument('--version-to')
    parser.add_argument('--components', nargs='+', default=['backend', 'frontend', 'worker'])
    parser.add_argument('--trigger', default='manual')
    
    args = parser.parse_args()
    
    if args.command == 'rollback':
        context = RollbackContext(
            deployment_id=args.deployment_id,
            version_from=args.version_from or 'unknown',
            version_to=args.version_to or 'unknown',
            environment=args.environment,
            namespace=args.namespace,
            triggered_by=RollbackTrigger(args.trigger)
        )
        
        orchestrator = RollbackOrchestrator(context)
        
        try:
            results = await orchestrator.execute_rollback(args.components)
            
            print("\n=== Rollback Results ===")
            for component, result in results.items():
                status = "✓" if result.success else "✗"
                print(f"{status} {component}: {result.duration_seconds:.2f}s")
                if result.error_message:
                    print(f"  Error: {result.error_message}")
            
            all_success = all(r.success for r in results.values())
            sys.exit(0 if all_success else 1)
            
        finally:
            await orchestrator.cleanup()
    
    elif args.command == 'status':
        state_machine = StateMachine(args.deployment_id)
        print(f"Current state: {state_machine.current_state.name}")
        print(f"History: {len(state_machine.get_history())} transitions")
    
    elif args.command == 'history':
        state_machine = StateMachine(args.deployment_id)
        for entry in state_machine.get_history():
            print(f"{entry['timestamp']}: {entry['from']} -> {entry['to']} ({entry['reason']})")


if __name__ == '__main__':
    asyncio.run(main())
