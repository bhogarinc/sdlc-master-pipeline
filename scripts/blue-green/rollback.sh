#!/bin/bash
# Instant Rollback Script for TaskFlow Pro Blue-Green Deployment
# Usage: ./rollback.sh [--reason="..."] [--notify]

set -euo pipefail

# Configuration
NAMESPACE_SHARED="taskflow-shared"
INGRESS_ACTIVE="taskflow-api-active"
INGRESS_CANARY="taskflow-api-canary"
KUBECTL="kubectl"
SLACK_WEBHOOK="${SLACK_WEBHOOK_URL:-}"
PAGERDUTY_KEY="${PAGERDUTY_INTEGRATION_KEY:-}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Get current and previous environments
get_environments() {
    local current
    current=$($KUBECTL get ingress "$INGRESS_ACTIVE" -n "$NAMESPACE_SHARED" -o jsonpath='{.spec.rules[0].http.paths[0].backend.service.name}' 2>/dev/null || echo "")
    
    if [[ "$current" == *"blue"* ]]; then
        echo "blue green"
    elif [[ "$current" == *"green"* ]]; then
        echo "green blue"
    else
        echo "unknown unknown"
    fi
}

# Send Slack notification
notify_slack() {
    local message=$1
    local severity=$2
    
    if [[ -z "$SLACK_WEBHOOK" ]]; then
        return 0
    fi
    
    local color="danger"
    [[ "$severity" == "warning" ]] && color="warning"
    
    curl -s -X POST "$SLACK_WEBHOOK" \
        -H 'Content-type: application/json' \
        --data "{
            \"attachments\": [{
                \"color\": \"$color\",
                \"title\": \"TaskFlow Pro Rollback Alert\",
                \"text\": \"$message\",
                \"footer\": \"Blue-Green Deployer\",
                \"ts\": $(date +%s)
            }]
        }" > /dev/null || true
}

# Trigger PagerDuty incident
trigger_pagerduty() {
    local reason=$1
    
    if [[ -z "$PAGERDUTY_KEY" ]]; then
        return 0
    fi
    
    curl -s -X POST https://events.pagerduty.com/v2/enqueue \
        -H 'Content-Type: application/json' \
        --data "{
            \"routing_key\": \"$PAGERDUTY_KEY\",
            \"event_action\": \"trigger\",
            \"dedup_key\": \"taskflow-rollback-$(date +%Y%m%d)\",
            \"payload\": {
                \"summary\": \"TaskFlow Pro Emergency Rollback: $reason\",
                \"severity\": \"critical\",
                \"source\": \"blue-green-deployer\",
                \"component\": \"api\",
                \"group\": \"production\",
                \"class\": \"rollback\"
            }
        }" > /dev/null || true
}

# Perform instant rollback
perform_rollback() {
    local reason=$1
    local notify=$2
    
    log_error "EMERGENCY ROLLBACK INITIATED"
    log_error "Reason: $reason"
    
    read -r current previous <<< "$(get_environments)"
    
    log_info "Current active: $current"
    log_info "Rolling back to: $previous"
    
    if [[ "$current" == "unknown" || "$previous" == "unknown" ]]; then
        log_error "Cannot determine environments for rollback"
        exit 1
    fi
    
    # Instant switch - no validation, no canary
    log_info "Executing instant traffic switch..."
    
    $KUBECTL annotate ingress "$INGRESS_CANARY" -n "$NAMESPACE_SHARED" \
        nginx.ingress.kubernetes.io/canary-weight="0" --overwrite
    
    local previous_service="taskflow-api-$previous"
    
    $KUBECTL patch ingress "$INGRESS_ACTIVE" -n "$NAMESPACE_SHARED" --type='json' -p="[{
        \"op\": \"replace\",
        \"path\": \"/spec/rules/0/http/paths/0/backend/service/name\",
        \"value\": \"$previous_service\"
    }]"
    
    # Verify rollback
    log_info "Verifying rollback..."
    sleep 5
    
    local new_current
    new_current=$($KUBECTL get ingress "$INGRESS_ACTIVE" -n "$NAMESPACE_SHARED" -o jsonpath='{.spec.rules[0].http.paths[0].backend.service.name}')
    
    if [[ "$new_current" == *"$previous"* ]]; then
        log_success "ROLLBACK COMPLETED - Traffic now on $previous environment"
        
        # Create rollback marker
        $KUBECTL create configmap rollback-marker \
            -n "$NAMESPACE_SHARED" \
            --from-literal=timestamp="$(date -Iseconds)" \
            --from-literal=from="$current" \
            --from-literal=to="$previous" \
            --from-literal=reason="$reason" \
            --dry-run=client -o yaml | $KUBECTL apply -f -
        
        # Notifications
        if [[ "$notify" == "true" ]]; then
            notify_slack "🚨 ROLLBACK EXECUTED: Switched from $current to $previous. Reason: $reason" "critical"
            trigger_pagerduty "$reason"
        fi
        
        return 0
    else
        log_error "ROLLBACK VERIFICATION FAILED"
        exit 1
    fi
}

# Main
main() {
    local reason="Manual rollback triggered"
    local notify=false
    
    while [[ $# -gt 0 ]]; do
        case $1 in
            --reason=*)
                reason="${1#*=}"
                shift
                ;;
            --notify)
                notify=true
                shift
                ;;
            --help)
                echo "Usage: $0 [--reason=...] [--notify]"
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                exit 1
                ;;
        esac
    done
    
    # Confirm rollback
    echo -e "${RED}WARNING: This will perform an INSTANT rollback!${NC}"
    read -p "Are you sure? (yes/no): " confirm
    
    if [[ "$confirm" != "yes" ]]; then
        log_info "Rollback cancelled"
        exit 0
    fi
    
    perform_rollback "$reason" "$notify"
}

main "$@"
