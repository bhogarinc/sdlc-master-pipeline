# TaskFlow Pro Blue-Green Deployment Guide

## Overview

This document describes the blue-green deployment strategy implemented for TaskFlow Pro, enabling zero-downtime releases with instant rollback capability.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Production Traffic                        │
│                    (api.taskflow.pro)                           │
└───────────────────────┬─────────────────────────────────────────┘
                        │
            ┌───────────┴───────────┐
            │   Ingress Controller   │
            │  (NGINX with Canary)   │
            └───────────┬───────────┘
                        │
        ┌───────────────┼───────────────┐
        │               │               │
   100% Traffic    0% Traffic      Direct Access
        │               │               │
   ┌────▼────┐    ┌────▼────┐    ┌─────┴──────┐
   │  BLUE   │    │  GREEN  │    │  Testing   │
   │ (Active)│    │ (Standby│    │  Endpoints │
   └────┬────┘    └────┬────┘    └────────────┘
        │               │
   ┌────▼────┐    ┌────▼────┐
   │ taskflow│    │ taskflow│
   │  -blue  │    │  -green │
   └─────────┘    └─────────┘
```

## Environments

### Blue Environment
- **Namespace**: `taskflow-blue`
- **Direct URL**: https://api-blue.taskflow.pro
- **Purpose**: Production or standby environment

### Green Environment
- **Namespace**: `taskflow-green`
- **Direct URL**: https://api-green.taskflow.pro
- **Purpose**: Production or standby environment

### Shared Resources
- **Namespace**: `taskflow-shared`
- **Ingress**: Main traffic routing
- **Secrets**: Database credentials, JWT secrets

## Deployment Process

### 1. Pre-Deployment

```bash
# Check current active environment
kubectl get ingress taskflow-api-active -n taskflow-shared \
  -o jsonpath='{.spec.rules[0].http.paths[0].backend.service.name}'

# Verify target environment health
curl https://api-blue.taskflow.pro/health
curl https://api-green.taskflow.pro/health
```

### 2. Deploy to Inactive Environment

```bash
# Deploy new version to green (if blue is active)
kubectl apply -f k8s/blue-green/configmap-green.yaml
sed 's/{{VERSION}}/v2.0.0/g' k8s/blue-green/deployment-api-green.yaml | kubectl apply -f -

# Wait for rollout
kubectl rollout status deployment/taskflow-api -n taskflow-green --timeout=300s
```

### 3. Smoke Tests

```bash
# Run automated smoke tests
pytest tests/smoke/ --base-url=https://api-green.taskflow.pro

# Manual verification
curl https://api-green.taskflow.pro/health
curl https://api-green.taskflow.pro/ready
```

### 4. Traffic Switch

#### Option A: Immediate Switch
```bash
./scripts/blue-green/switch-traffic.sh green
```

#### Option B: Canary Deployment
```bash
# Start with 10% traffic
./scripts/blue-green/switch-traffic.sh green --canary-percentage=10

# Gradually increase
./scripts/blue-green/switch-traffic.sh green --canary-percentage=50

# Full switch
./scripts/blue-green/switch-traffic.sh green
```

### 5. Post-Deployment Verification

```bash
# Monitor production metrics
kubectl top pods -n taskflow-green

# Check error rates
# (Monitor via Grafana/Prometheus)

# Verify user traffic
kubectl logs -l app=taskflow-api -n taskflow-green --tail=100
```

## Rollback Procedures

### Automatic Rollback

The CI/CD pipeline automatically rolls back if smoke tests fail:

```yaml
# In .github/workflows/blue-green-deploy.yml
rollback:
  if: failure() && needs.smoke-test.result == 'failure'
  steps:
    - run: ./scripts/blue-green/rollback.sh --notify
```

### Manual Rollback

```bash
# Instant rollback to previous environment
./scripts/blue-green/rollback.sh --reason="Performance degradation" --notify

# Force rollback without confirmation
./scripts/blue-green/rollback.sh --reason="Critical bug" --force
```

### Emergency Rollback

```bash
# Direct kubectl commands for emergency
kubectl patch ingress taskflow-api-active -n taskflow-shared --type='json' \
  -p='[{"op": "replace", "path": "/spec/rules/0/http/paths/0/backend/service/name", "value": "taskflow-api-blue"}]'
```

## Switch Criteria Checklist

Before switching traffic, verify:

- [ ] All pods in target environment are ready
- [ ] Health checks pass consistently
- [ ] Smoke tests completed successfully
- [ ] Error rate < 0.1% in target environment
- [ ] Response time p95 < 500ms
- [ ] Database connections stable
- [ ] Memory usage < 80%
- [ ] CPU usage < 70%
- [ ] No critical alerts in target environment
- [ ] Rollback plan documented

## Data Synchronization

### Database
Both environments connect to the same PostgreSQL database:

```yaml
# Connection string (same for both environments)
postgres://taskflow:${DB_PASSWORD}@taskflow-db.postgres.database.azure.com:5432/taskflow
```

### Cache
Both environments share the same Redis cluster:

```yaml
# Redis URL (same for both environments)
redis://taskflow-redis.redis.cache.windows.net:6380/0
```

### Session Management
Sessions are stored in Redis, enabling seamless switching:

```python
# FastAPI session configuration
app.add_middleware(
    SessionMiddleware,
    secret_key=JWT_SECRET,
    session_cookie="session_id",
    max_age=1800,
    same_site="lax",
    https_only=True
)
```

## Monitoring

### Key Metrics

| Metric | Warning | Critical |
|--------|---------|----------|
| Error Rate | > 0.1% | > 1% |
| Response Time (p95) | > 500ms | > 1000ms |
| CPU Usage | > 70% | > 85% |
| Memory Usage | > 80% | > 90% |
| Pod Restarts | > 2/hour | > 5/hour |

### Grafana Dashboards

- **Blue-Green Overview**: https://grafana.taskflow.pro/d/blue-green
- **API Performance**: https://grafana.taskflow.pro/d/api-perf
- **Error Analysis**: https://grafana.taskflow.pro/d/errors

### Alerts

```yaml
# Example alert configuration
groups:
  - name: blue-green
    rules:
      - alert: HighErrorRate
        expr: rate(http_requests_total{status=~"5.."}[5m]) > 0.01
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "High error rate detected"
```

## Cleanup

### Automated Cleanup

Old environments are automatically scaled down after 24 hours:

```bash
# Scheduled cleanup job
kubectl apply -f k8s/blue-green/cleanup-job.yaml
```

### Manual Cleanup

```bash
# Scale down old environment
kubectl scale deployment taskflow-api -n taskflow-blue --replicas=0
kubectl scale deployment taskflow-frontend -n taskflow-blue --replicas=0

# (Keep configuration for quick rollback if needed)
```

## Troubleshooting

### Common Issues

#### Pods Not Ready
```bash
# Check pod status
kubectl get pods -n taskflow-green

# Check logs
kubectl logs -l app=taskflow-api -n taskflow-green

# Describe pod for events
kubectl describe pod <pod-name> -n taskflow-green
```

#### Health Check Failures
```bash
# Test health endpoint
kubectl exec -it <pod-name> -n taskflow-green -- curl localhost:8000/health

# Check database connectivity
kubectl exec -it <pod-name> -n taskflow-green -- python -c "from app.db import check_connection; check_connection()"
```

#### Traffic Not Switching
```bash
# Verify ingress configuration
kubectl get ingress taskflow-api-active -n taskflow-shared -o yaml

# Check ingress controller logs
kubectl logs -l app.kubernetes.io/name=ingress-nginx -n ingress-nginx
```

## Best Practices

1. **Always validate** the target environment before switching
2. **Use canary deployments** for high-risk releases
3. **Monitor metrics** for at least 30 minutes after switch
4. **Keep old environment** running for 24 hours minimum
5. **Document** all switches in deployment log
6. **Test rollback procedures** regularly
7. **Automate** as much as possible

## Security Considerations

- Both environments use the same secrets (stored in Azure Key Vault)
- Network policies restrict inter-environment communication
- Pod security policies enforce non-root containers
- Read-only root filesystems
- Resource limits prevent DoS

## Contact

For issues or questions:
- Slack: #deployments
- On-call: https://pagerduty.taskflow.pro
- Runbook: https://wiki.taskflow.pro/runbooks/blue-green
