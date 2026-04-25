# TaskFlow Pro Canary Deployment Strategy

## Overview

This document describes the comprehensive canary deployment strategy for TaskFlow Pro, utilizing Flagger with NGINX ingress for progressive traffic shifting and automated rollback capabilities.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Production Cluster                        │
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │   Ingress    │───▶│   NGINX      │───▶│   Services   │      │
│  │   Controller │    │   Gateway    │    │              │      │
│  └──────────────┘    └──────────────┘    └──────┬───────┘      │
│                                                  │               │
│                    Traffic Split                 │               │
│                         │                        │               │
│              ┌──────────┴──────────┐             │               │
│              │                     │             │               │
│              ▼                     ▼             │               │
│  ┌──────────────────┐  ┌──────────────────┐     │               │
│  │   Baseline       │  │   Canary         │     │               │
│  │   (Stable)       │  │   (New Version)  │     │               │
│  │   99% → 0%       │  │   1% → 100%      │     │               │
│  └──────────────────┘  └──────────────────┘     │               │
│                                                  │               │
│  ┌───────────────────────────────────────────────┘               │
│  │   Prometheus / Grafana Monitoring                             │
│  │   - Real-time metrics collection                              │
│  │   - Automated health analysis                                 │
│  │   - Alertmanager notifications                                │
│  └───────────────────────────────────────────────────────────────┘
└─────────────────────────────────────────────────────────────────┘
```

## Traffic Progression Schedule

### Backend (taskflow-api)

| Step | Traffic % | Duration | Total Time | Gates |
|------|-----------|----------|------------|-------|
| 1 | 1% | 10 min | 10 min | Health check, Smoke test |
| 2 | 5% | 15 min | 25 min | Error rate, Latency check |
| 3 | 25% | 20 min | 45 min | Full metric comparison |
| 4 | 50% | 30 min | 75 min | Extended stability |
| 5 | 100% | 0 min | 75 min | Full promotion |

### Frontend (taskflow-web)

| Step | Traffic % | Duration | Total Time | Gates |
|------|-----------|----------|------------|-------|
| 1 | 5% | 10 min | 10 min | Lighthouse, Visual regression |
| 2 | 25% | 15 min | 25 min | Web vitals, Error tracking |
| 3 | 50% | 20 min | 45 min | UX validation |
| 4 | 100% | 0 min | 45 min | Full promotion |

## Health Check Endpoints

### Kubernetes Probes

```yaml
# Liveness Probe
GET /health/live
Response: 200 OK
Purpose: Determine if container should be restarted

# Readiness Probe  
GET /health/ready
Response: 200 OK
Purpose: Determine if container should receive traffic

# Startup Probe
GET /health/startup
Response: 200 OK
Purpose: Allow slow-starting containers time to initialize
```

### Application Health Checks

```yaml
# Database Connectivity
GET /health/db
Response: {"status": "healthy", "database": "connected"}

# Cache Connectivity
GET /health/cache
Response: {"status": "healthy", "redis": "connected"}

# External Services
GET /health/external
Response: {"status": "healthy", "services": [...]}
```

## Metric Thresholds

### Primary Metrics

| Metric | Threshold | Window | Action on Breach |
|--------|-----------|--------|------------------|
| Error Rate | < 1% | 5m | Rollback |
| P99 Latency | < 2000ms | 5m | Rollback |
| P95 Latency | < 1000ms | 5m | Warning |
| Success Rate | > 99% | 1m | Rollback |

### Regression Criteria

| Comparison | Threshold | Action |
|------------|-----------|--------|
| Latency vs Baseline | < 1.5x | Rollback |
| Error Rate vs Baseline | < 2x | Rollback |
| Throughput vs Baseline | > 90% | Warning |

### Web Vitals (Frontend)

| Metric | Threshold | Tool |
|--------|-----------|------|
| LCP (Largest Contentful Paint) | < 2.5s | Lighthouse |
| FID (First Input Delay) | < 100ms | Lighthouse |
| CLS (Cumulative Layout Shift) | < 0.1 | Lighthouse |

## Auto-Rollback Rules

### Immediate Rollback (Critical)

```yaml
- name: critical_error_rate
  condition: error_rate > 5%
  action: immediate_rollback
  
- name: pod_crash_loop
  condition: pod_restarts > 0 for 5m
  action: immediate_rollback
  
- name: health_check_failure
  condition: readiness_probe_failures > 3 consecutive
  action: immediate_rollback
```

### Standard Rollback

```yaml
- name: high_error_rate
  condition: error_rate > 1% for 5m
  action: rollback
  
- name: latency_regression
  condition: p99_latency > 2x baseline for 3m
  action: rollback
  
- name: error_rate_regression
  condition: error_rate > 2x baseline for 3m
  action: rollback
```

## Feature Flag Coordination

### Canary-Specific Flags

```yaml
flags:
  - name: new-task-ui
    canary_override:
      target: canary_only
      percentage: 100
      
  - name: websocket-notifications
    canary_override:
      target: canary_only
      percentage: 100
      
  - name: enhanced-search
    canary_override:
      target: canary_only
      percentage: 100
```

### Flag Lifecycle

1. **Pre-Canary**: Enable flags for canary pods only
2. **During Canary**: Monitor feature-specific metrics
3. **Post-Promotion**: Enable flags for all pods
4. **Post-Rollback**: Reset all flags to baseline

## Notification Plan

### Event Triggers

| Event | Severity | Channels | Recipients |
|-------|----------|----------|------------|
| Canary Started | Info | Slack, Webhook | #deployments |
| Progression (1%, 5%, 25%, 50%, 100%) | Info | Slack | #deployments |
| Warning | Warning | Slack, Email | #deployments, Platform Team |
| Rollback | Critical | All | #alerts, PagerDuty, On-Call |
| Promotion Complete | Info | All | #deployments, Platform Team |

### Notification Templates

#### Slack - Canary Started
```json
{
  "text": "🚀 Canary deployment started",
  "attachments": [{
    "color": "good",
    "fields": [
      {"title": "Version", "value": "v1.2.3", "short": true},
      {"title": "Environment", "value": "Production", "short": true}
    ]
  }]
}
```

#### PagerDuty - Rollback
```json
{
  "routing_key": "...",
  "event_action": "trigger",
  "payload": {
    "summary": "Canary deployment rolled back",
    "severity": "critical",
    "source": "flagger"
  }
}
```

## Deployment Commands

### Manual Canary Trigger

```bash
# Update image and trigger canary
kubectl set image deployment/taskflow-api \
  api=bhogarinc/taskflow-api:v1.2.3 \
  -n production

# Monitor canary progress
kubectl get canaries -n production -w

# View canary events
kubectl describe canary taskflow-api -n production
```

### Manual Rollback

```bash
# Rollback to previous version
kubectl rollout undo deployment/taskflow-api -n production

# Verify rollback
kubectl rollout status deployment/taskflow-api -n production
```

### Force Promotion

```bash
# Manually promote canary (use with caution)
kubectl patch canary taskflow-api -n production \
  --type merge \
  -p '{"spec":{"skipAnalysis":true}}'
```

## Monitoring & Observability

### Grafana Dashboards

- **Canary Overview**: `https://grafana.taskflow.pro/d/canary`
- **API Metrics**: `https://grafana.taskflow.pro/d/taskflow-api`
- **Web Metrics**: `https://grafana.taskflow.pro/d/taskflow-web`

### Key Metrics to Watch

```promql
# Canary traffic split
flagger_canary_weight{name=~"taskflow-.*"}

# Error rate comparison
sum(rate(http_requests_total{service=~"taskflow-.*-canary",status=~"5.."}[5m]))
/
sum(rate(http_requests_total{service=~"taskflow-.*-canary"}[5m]))

# Latency comparison (P99)
histogram_quantile(0.99,
  sum(rate(http_request_duration_seconds_bucket{service=~"taskflow-.*-canary"}[5m])) by (le)
)
```

### Alertmanager Rules

See `k8s/canary/canary-monitoring.yaml` for complete alert definitions.

## Troubleshooting

### Common Issues

#### Canary Stuck in Progressing

```bash
# Check canary status
kubectl get canary taskflow-api -n production -o yaml

# Check events
kubectl describe canary taskflow-api -n production

# Check webhook status
kubectl get canaries taskflow-api -n production -o jsonpath='{.status.conditions}'
```

#### Webhook Failures

```bash
# Test webhook manually
curl -X POST http://flagger-loadtester.production/gate/check \
  -H "Content-Type: application/json" \
  -d '{"name":"taskflow-api","namespace":"production"}'
```

#### Metric Collection Issues

```bash
# Verify Prometheus targets
kubectl get servicemonitors -n monitoring

# Check metric availability
curl "http://prometheus:9090/api/v1/query?query=flagger_canary_weight"
```

## Best Practices

### 1. Pre-Deployment Checklist

- [ ] All tests passing in CI/CD
- [ ] Security scans completed
- [ ] Database migrations tested
- [ ] Feature flags configured
- [ ] Runbook updated
- [ ] On-call engineer notified

### 2. During Canary

- [ ] Monitor Grafana dashboard continuously
- [ ] Watch for error spikes in real-time
- [ ] Verify feature flags working correctly
- [ ] Check customer-facing metrics

### 3. Post-Promotion

- [ ] Verify all pods running new version
- [ ] Run smoke tests on production
- [ ] Monitor for 30 minutes post-promotion
- [ ] Update deployment documentation

## Configuration Files

| File | Purpose |
|------|---------|
| `taskflow-api-canary.yaml` | Backend canary configuration |
| `taskflow-web-canary.yaml` | Frontend canary configuration |
| `canary-monitoring.yaml` | Prometheus rules and alerts |
| `canary-config.json` | Complete configuration specification |
| `canary-deployment.yaml` | GitHub Actions workflow |
| `canary_analysis.py` | Metric analysis script |

## References

- [Flagger Documentation](https://flagger.app/)
- [NGINX Ingress Controller](https://kubernetes.github.io/ingress-nginx/)
- [Prometheus Query Language](https://prometheus.io/docs/prometheus/latest/querying/basics/)
- [Google SRE - Canary Releases](https://sre.google/workbook/canarying-releases/)