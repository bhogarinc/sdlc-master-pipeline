# TaskFlow Pro Manual Rollback Procedures

## Quick Reference

| Scenario | Command | Estimated Time | Approval Required |
|----------|---------|----------------|-------------------|
| Graceful Rollback | `rollback-manager rollback --deployment-id <id>` | 5-10 min | Release Engineer |
| Emergency Rollback | `rollback-manager rollback --deployment-id <id> --emergency` | 2-5 min | Senior SRE |
| Database Only | `rollback-manager rollback --components database` | 10-15 min | DBA + Release Engineer |
| Config Only | `rollback-manager rollback --components config` | 1-2 min | Release Engineer |

---

## Table of Contents

1. [Overview](#overview)
2. [Authorization](#authorization)
3. [Graceful Rollback Procedure](#graceful-rollback-procedure)
4. [Emergency Rollback Procedure](#emergency-rollback-procedure)
5. [Component-Specific Procedures](#component-specific-procedures)
6. [Database Rollback](#database-rollback)
7. [Post-Rollback Validation](#post-rollback-validation)
8. [Troubleshooting](#troubleshooting)
9. [Contact Information](#contact-information)

---

## Overview

This document provides step-by-step procedures for manually initiating rollbacks in TaskFlow Pro. Rollbacks should be initiated when:

- Automated rollback triggers fail to activate
- Human judgment determines a rollback is necessary
- Emergency situations require immediate action

### Rollback Types

1. **Graceful Rollback**: Standard procedure with full safety checks
2. **Emergency Rollback**: Fast rollback bypassing some safety checks
3. **Partial Rollback**: Rollback specific components only
4. **Full System Rollback**: Complete system restoration

---

## Authorization

### Required Roles

| Rollback Type | Required Role | MFA Required | Secondary Approval |
|--------------|---------------|--------------|-------------------|
| Graceful | Release Engineer | Yes | No |
| Emergency | Senior SRE | Yes | No* |
| Database | DBA + Release Engineer | Yes | Engineering Manager |
| Production Config | Release Engineer | Yes | No |
| Infrastructure | Senior SRE | Yes | Infrastructure Lead |

*Emergency rollbacks require post-incident review within 24 hours.

### Authentication

All rollback commands require:

```bash
# 1. Kubernetes access
kubectl auth can-i patch deployments -n taskflow-pro

# 2. Database access (for DB rollbacks)
psql $DATABASE_URL -c "SELECT 1"

# 3. Rollback manager authentication
rollback-manager auth verify
```

---

## Graceful Rollback Procedure

### When to Use

- Deployment is in CANARY state showing issues
- Error rates are elevated but below auto-rollback threshold
- Performance degradation detected
- Feature defects discovered post-deployment

### Prerequisites

- [ ] Current deployment ID
- [ ] Reason for rollback documented
- [ ] Rollback approval (if required)
- [ ] Incident channel opened

### Procedure

#### Step 1: Verify Current State

```bash
# Check deployment status
rollback-manager status --deployment-id <deployment-id>

# Expected output:
# Current state: CANARY
# History: 3 transitions
# Started: 2024-04-25T14:30:00Z
```

#### Step 2: Open Incident Communication

```bash
# Create incident channel
slack create-channel rollback-$(date +%Y%m%d-%H%M%S)

# Notify stakeholders
slack post-channel "Initiating graceful rollback for deployment <deployment-id>"
```

#### Step 3: Initiate Rollback

```bash
# Execute graceful rollback
rollback-manager rollback \
  --deployment-id <deployment-id> \
  --environment production \
  --namespace taskflow-pro \
  --trigger manual \
  --reason "Performance degradation detected in canary"
```

#### Step 4: Monitor Progress

```bash
# Watch rollback progress
rollback-manager watch --deployment-id <deployment-id>

# In another terminal, monitor pods
kubectl get pods -n taskflow-pro -w
```

#### Step 5: Verify Completion

```bash
# Check final state
rollback-manager status --deployment-id <deployment-id>

# Run validation tests
post-rollback-tests --base-url https://taskflow.pro
```

#### Step 6: Update Stakeholders

```bash
# Post completion message
slack post-channel "Rollback completed successfully. System stable."

# Update incident status
pagerduty resolve-incident --deployment-id <deployment-id>
```

### Timeline

| Phase | Duration | Action |
|-------|----------|--------|
| Preparation | 2 min | Verify state, open incident |
| Initiation | 1 min | Execute rollback command |
| Execution | 3-5 min | Component rollbacks |
| Validation | 2-3 min | Run health checks |
| Total | 8-11 min | |

---

## Emergency Rollback Procedure

### When to Use

- Critical system outage
- Data corruption detected
- Security incident
- Complete service failure
- Auto-rollback failed to activate

⚠️ **WARNING**: Emergency rollback bypasses some safety checks. Use only when system is critically compromised.

### Prerequisites

- [ ] Confirmed critical incident
- [ ] Senior SRE approval
- [ ] Incident commander assigned

### Procedure

#### Step 1: Declare Emergency

```bash
# Page on-call team
pagerduty trigger-emergency \
  --service taskflow-pro \
  --description "Emergency rollback required"

# Create war room
zoom create-meeting \
  --topic "TaskFlow Emergency Rollback" \
  --duration 60
```

#### Step 2: Execute Emergency Rollback

```bash
# Emergency rollback with bypass flags
rollback-manager rollback \
  --deployment-id <deployment-id> \
  --emergency \
  --bypass-health-checks \
  --bypass-backup-verification \
  --drain-connections-timeout 10 \
  --reason "CRITICAL: Complete service failure"
```

#### Step 3: Immediate Verification

```bash
# Quick health check
kubectl get pods -n taskflow-pro

curl -f https://taskflow.pro/api/v1/health || echo "HEALTH CHECK FAILED"
```

#### Step 4: Traffic Management

If rollback doesn't restore service immediately:

```bash
# Enable maintenance mode
kubectl apply -f infrastructure/k8s/maintenance-mode.yaml

# Or redirect to static page
kubectl patch ingress taskflow-ingress \
  --type merge \
  -p '{"spec":{"rules":[{"http":{"paths":[{"path":"/","pathType":"Prefix","backend":{"service":{"name":"maintenance-page","port":{"number":80}}}}]}}]}}'
```

#### Step 5: Post-Emergency Actions

Within 24 hours of emergency rollback:

```bash
# 1. Schedule post-incident review
calendar create-event \
  --title "Post-Incident Review: Emergency Rollback" \
  --attendees sre-team,engineering-leads \
  --duration 60

# 2. Document incident
confluence create-page \
  --space APH \
  --parent "Incident Reports" \
  --title "INC-$(date +%Y%m%d): Emergency Rollback"

# 3. Update runbooks
# Review and improve procedures based on lessons learned
```

### Emergency Contacts

| Role | Contact | Escalation |
|------|---------|------------|
| Senior SRE | #sre-oncall | +1-555-SRE-HELP |
| Engineering Manager | eng-manager@taskflow.pro | +1-555-ENG-MGR |
| CTO | cto@taskflow.pro | +1-555-CTO-911 |

---

## Component-Specific Procedures

### Backend Rollback Only

```bash
rollback-manager rollback \
  --deployment-id <deployment-id> \
  --components backend \
  --strategy rolling
```

**Use when:** Frontend and other components are healthy, only backend issues detected.

### Frontend Rollback Only

```bash
rollback-manager rollback \
  --deployment-id <deployment-id> \
  --components frontend \
  --strategy rolling
```

**Use when:** Backend APIs are healthy, only UI issues detected.

### WebSocket Service Rollback

```bash
# Graceful shutdown with connection migration
rollback-manager rollback \
  --deployment-id <deployment-id> \
  --components websocket \
  --graceful-shutdown 30
```

**Note:** WebSocket rollbacks require special handling to avoid dropping active connections.

### Worker Rollback

```bash
# Drain in-progress jobs before rollback
rollback-manager rollback \
  --deployment-id <deployment-id> \
  --components worker \
  --drain-jobs \
  --max-drain-time 300
```

---

## Database Rollback

### Prerequisites

⚠️ **CRITICAL**: Database rollbacks require explicit DBA approval and should only be performed during maintenance windows.

### Pre-Rollback Checks

```bash
# 1. Verify backup exists
aws s3 ls s3://taskflow-pro-backups/ | grep $(date +%Y%m%d)

# 2. Check migration reversibility
psql $DATABASE_URL -c "
  SELECT version, is_reversible 
  FROM schema_migrations 
  ORDER BY applied_at DESC 
  LIMIT 5;
"

# 3. Verify safety checks pass
psql $DATABASE_URL -c "
  SELECT * FROM can_rollback_safely('20240425_001');
"
```

### Reversible Migration Rollback

```bash
# Rollback specific migration
rollback-manager rollback \
  --deployment-id <deployment-id> \
  --components database \
  --migration-version 20240425_001
```

### Full Database Restore

```bash
# Only use when migration rollback is not possible
# Requires maintenance window

# 1. Announce maintenance
slack post-channel "DATABASE MAINTENANCE: Starting in 5 minutes"

# 2. Stop application traffic
kubectl scale deployment taskflow-backend --replicas=0 -n taskflow-pro

# 3. Execute restore
rollback-manager rollback \
  --deployment-id <deployment-id> \
  --components database \
  --restore-from-backup s3://taskflow-pro-backups/backup-$(date +%Y%m%d).sql

# 4. Verify restore
psql $DATABASE_URL -c "SELECT COUNT(*) FROM users;"

# 5. Restart application
kubectl scale deployment taskflow-backend --replicas=3 -n taskflow-pro
```

---

## Post-Rollback Validation

### Automated Validation

```bash
# Run full validation suite
post-rollback-tests \
  --base-url https://taskflow.pro \
  --db-dsn $DATABASE_URL \
  --output /tmp/rollback-validation-$(date +%Y%m%d-%H%M%S).json \
  --exit-code
```

### Manual Verification Checklist

- [ ] All pods in Running state
- [ ] No CrashLoopBackOff pods
- [ ] Health endpoints return 200
- [ ] Can log in to application
- [ ] Can create/view tasks
- [ ] Real-time notifications working
- [ ] Database connections healthy
- [ ] Error rates back to baseline
- [ ] Response times acceptable

### Sign-Off

```bash
# Mark rollback complete
rollback-manager complete \
  --deployment-id <deployment-id> \
  --validation-passed \
  --signed-off-by $(whoami)
```

---

## Troubleshooting

### Rollback Stuck in Progress

```bash
# Check component status
kubectl get deployments -n taskflow-pro

# Force rollout restart if stuck
kubectl rollout restart deployment/taskflow-backend -n taskflow-pro

# Check for resource constraints
kubectl describe pods -n taskflow-pro | grep -A 5 "Events:"
```

### Database Rollback Failed

```bash
# Check for active connections blocking rollback
psql $DATABASE_URL -c "
  SELECT pid, state, query_start, query 
  FROM pg_stat_activity 
  WHERE state = 'active' 
  AND query_start < NOW() - INTERVAL '1 minute';
"

# Terminate blocking connections if safe
psql $DATABASE_URL -c "
  SELECT pg_terminate_backend(pid) 
  FROM pg_stat_activity 
  WHERE state = 'active' 
  AND query_start < NOW() - INTERVAL '5 minutes';
"
```

### Post-Rollback Health Check Failures

```bash
# Check pod logs
kubectl logs -l app=taskflow-backend -n taskflow-pro --tail=100

# Check for configuration issues
kubectl get configmap taskflow-config -n taskflow-pro -o yaml

# Verify database connectivity
kubectl exec -it deployment/taskflow-backend -n taskflow-pro -- \
  python -c "from app.database import test_connection; test_connection()"
```

### Rollback Cannot Complete

If rollback cannot complete:

1. **Stop all traffic**: Enable maintenance mode
2. **Preserve evidence**: Collect logs before any restart
3. **Escalate**: Page Senior SRE and Engineering Manager
4. **Consider restore**: May need to restore from backup instead

---

## Contact Information

### Escalation Path

```
Release Engineer → Senior SRE → Engineering Manager → CTO
     (5 min)           (10 min)         (15 min)      (20 min)
```

### Communication Channels

- **Slack**: #sre-alerts, #incidents
- **PagerDuty**: TaskFlow Pro Critical Service
- **Email**: sre-oncall@taskflow.pro
- **Emergency Phone**: +1-555-TASKFLOW

### Documentation

- **Runbooks**: https://wiki.taskflow.pro/runbooks
- **Architecture**: https://wiki.taskflow.pro/architecture
- **Incident Reports**: https://wiki.taskflow.pro/incidents

---

## Appendix

### A. Rollback Decision Matrix

| Symptom | Severity | Recommended Action | Time Limit |
|---------|----------|-------------------|------------|
| Error rate > 5% | High | Auto-rollback | 2 min |
| Error rate 2-5% | Medium | Graceful rollback | 10 min |
| Latency P99 > 2s | Medium | Graceful rollback | 15 min |
| Feature bug | Low | Scheduled rollback | 1 hour |
| Data inconsistency | Critical | Emergency rollback | 5 min |
| Complete outage | Critical | Emergency rollback | 2 min |

### B. Rollback Checklist

Before any rollback:

- [ ] Deployment ID confirmed
- [ ] Current state verified
- [ ] Reason documented
- [ ] Approval obtained (if required)
- [ ] Incident channel opened
- [ ] Stakeholders notified
- [ ] Rollback command reviewed
- [ ] Post-rollback tests ready

After rollback:

- [ ] Validation tests passed
- [ ] Monitoring dashboards checked
- [ ] Stakeholders updated
- [ ] Incident documented
- [ ] Lessons learned captured

---

**Last Updated**: 2024-04-25  
**Version**: 1.0.0  
**Owner**: Release Safety Engineering Team  
**Review Schedule**: Quarterly
