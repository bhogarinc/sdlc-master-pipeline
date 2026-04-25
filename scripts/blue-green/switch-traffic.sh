#!/bin/bash
# Blue-Green Traffic Switch Script for TaskFlow Pro
# Usage: ./switch-traffic.sh [blue|green] [--force] [--canary-percentage=N]

set -euo pipefail

# Configuration
NAMESPACE_SHARED="taskflow-shared"
INGRESS_ACTIVE="taskflow-api-active"
INGRESS_CANARY="taskflow-api-canary"
KUBECTL="kubectl"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Print usage
usage() {
    cat << EOF
Usage: $0 [blue|green] [OPTIONS]

Switch traffic between blue and green environments for TaskFlow Pro.

Arguments:
    blue|green    Target environment to receive 100% traffic

Options:
    --force                    Skip pre-switch validation
    --canary-percentage=N      Gradual switch with canary (0-100)
    --dry-run                  Show what would be done without executing
    --wait-timeout=SECONDS     Wait for rollout (default: 300)
    --help                     Show this help message

Examples:
    $0 green                          # Switch all traffic to green
    $0 green --canary-percentage=10   # Send 10% traffic to green
    $0 blue --force                   # Force switch to blue
    $0 green --dry-run                # Preview changes

EOF
}

# Validate environment
validate_environment() {
    local target=$1
    
    log_info "Validating $target environment..."
    
    # Check if target namespace exists
    if ! $KUBECTL get namespace "taskflow-$target" &>/dev/null; then
        log_error "Namespace taskflow-$target does not exist"
        exit 1
    fi
    
    # Check if deployment exists and is ready
    local ready_replicas
    ready_replicas=$($KUBECTL get deployment taskflow-api -n "taskflow-$target" -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
    
    if [[ "$ready_replicas" == "0" || -z "$ready_replicas" ]]; then
        log_error "No ready replicas found in $target environment"
        exit 1
    fi
    
    log_success "$target environment has $ready_replicas ready replicas"
    
    # Run health checks
    log_info "Running health checks on $target environment..."
    
    local endpoint
    if [[ "$target" == "blue" ]]; then
        endpoint="https://api-blue.taskflow.pro/health"
    else
        endpoint="https://api-green.taskflow.pro/health"
    fi
    
    local retries=5
    local count=0
    while [[ $count -lt $retries ]]; do
        if curl -sf "$endpoint" &>/dev/null; then
            log_success "Health check passed for $target"
            break
        fi
        count=$((count + 1))
        log_warn "Health check attempt $count/$retries failed, retrying..."
        sleep 5
    done
    
    if [[ $count -eq $retries ]]; then
        log_error "Health checks failed for $target environment"
        exit 1
    fi
    
    return 0
}

# Get current active environment
get_current_active() {
    local backend
    backend=$($KUBECTL get ingress "$INGRESS_ACTIVE" -n "$NAMESPACE_SHARED" -o jsonpath='{.spec.rules[0].http.paths[0].backend.service.name}' 2>/dev/null || echo "")
    
    if [[ "$backend" == *"blue"* ]]; then
        echo "blue"
    elif [[ "$backend" == *"green"* ]]; then
        echo "green"
    else
        echo "unknown"
    fi
}

# Switch traffic using canary weight
switch_traffic_canary() {
    local target=$1
    local percentage=$2
    local dry_run=$3
    
    log_info "Setting canary traffic: $target at $percentage%"
    
    if [[ "$dry_run" == "true" ]]; then
        log_info "[DRY RUN] Would set canary weight to $percentage%"
        return 0
    fi
    
    # Update canary ingress with weight
    $KUBECTL annotate ingress "$INGRESS_CANARY" -n "$NAMESPACE_SHARED" \
        nginx.ingress.kubernetes.io/canary-weight="$percentage" \
        --overwrite
    
    log_success "Canary weight set to $percentage%"
}

# Full traffic switch
switch_traffic_full() {
    local target=$1
    local source=$2
    local dry_run=$3
    
    log_info "Performing full traffic switch from $source to $target..."
    
    if [[ "$dry_run" == "true" ]]; then
        log_info "[DRY RUN] Would switch main ingress to $target"
        log_info "[DRY RUN] Would set canary weight to 0"
        return 0
    fi
    
    # First, set canary to 0 to drain traffic from canary
    $KUBECTL annotate ingress "$INGRESS_CANARY" -n "$NAMESPACE_SHARED" \
        nginx.ingress.kubernetes.io/canary-weight="0" \
        --overwrite
    
    # Patch the main ingress to point to target
    local target_service="taskflow-api-$target"
    
    $KUBECTL patch ingress "$INGRESS_ACTIVE" -n "$NAMESPACE_SHARED" --type='json' -p="[{
        \"op\": \"replace\",
        \"path\": \"/spec/rules/0/http/paths/0/backend/service/name\",
        \"value\": \"$target_service\"
    }]"
    
    log_success "Traffic switched to $target"
}

# Verify traffic switch
verify_switch() {
    local target=$1
    local timeout=${2:-300}
    
    log_info "Verifying traffic switch (timeout: ${timeout}s)..."
    
    local start_time
    start_time=$(date +%s)
    
    while true; do
        local current
        current=$(get_current_active)
        
        if [[ "$current" == "$target" ]]; then
            log_success "Traffic successfully switched to $target"
            return 0
        fi
        
        local elapsed
        elapsed=$(($(date +%s) - start_time))
        
        if [[ $elapsed -gt $timeout ]]; then
            log_error "Traffic switch verification timed out"
            return 1
        fi
        
        log_info "Waiting for traffic switch... ($elapsed/${timeout}s)"
        sleep 5
    done
}

# Main function
main() {
    local target=""
    local force=false
    local canary_percentage=""
    local dry_run=false
    local wait_timeout=300
    
    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            blue|green)
                target=$1
                shift
                ;;
            --force)
                force=true
                shift
                ;;
            --canary-percentage=*)
                canary_percentage="${1#*=}"
                shift
                ;;
            --dry-run)
                dry_run=true
                shift
                ;;
            --wait-timeout=*)
                wait_timeout="${1#*=}"
                shift
                ;;
            --help)
                usage
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                usage
                exit 1
                ;;
        esac
    done
    
    # Validate arguments
    if [[ -z "$target" ]]; then
        log_error "Target environment (blue or green) is required"
        usage
        exit 1
    fi
    
    if [[ "$target" != "blue" && "$target" != "green" ]]; then
        log_error "Invalid target: $target. Must be 'blue' or 'green'"
        exit 1
    fi
    
    # Get current active environment
    local current
    current=$(get_current_active)
    log_info "Current active environment: $current"
    
    if [[ "$current" == "$target" ]]; then
        log_warn "$target is already the active environment"
        exit 0
    fi
    
    # Validate target environment (unless --force)
    if [[ "$force" == "false" ]]; then
        validate_environment "$target"
    else
        log_warn "Skipping validation due to --force flag"
    fi
    
    # Perform traffic switch
    if [[ -n "$canary_percentage" ]]; then
        switch_traffic_canary "$target" "$canary_percentage" "$dry_run"
    else
        switch_traffic_full "$target" "$current" "$dry_run"
    fi
    
    # Verify switch (skip in dry-run mode)
    if [[ "$dry_run" == "false" && -z "$canary_percentage" ]]; then
        if verify_switch "$target" "$wait_timeout"; then
            log_success "Blue-green deployment switch completed successfully!"
            log_info "Active environment is now: $target"
            log_info "Previous environment ($current) can be safely decommissioned after validation period"
        else
            log_error "Traffic switch verification failed!"
            log_info "Consider rolling back with: $0 $current --force"
            exit 1
        fi
    fi
}

# Run main function
main "$@"
