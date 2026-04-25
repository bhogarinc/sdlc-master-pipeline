#!/usr/bin/env python3
"""
Canary Deployment Analysis Script

Performs comprehensive metric comparison between canary and baseline deployments
to validate canary health before promotion.

Usage:
    python canary_analysis.py --prometheus-url http://prometheus:9090 \\
                              --services taskflow-api,taskflow-web \\
                              --duration 30m
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict

import requests
import pandas as pd
from prometheus_api_client import PrometheusConnect
from prometheus_api_client.utils import parse_datetime


@dataclass
class MetricThresholds:
    """Thresholds for canary validation"""
    error_rate_max: float = 1.0  # percentage
    latency_p99_max: float = 2000  # milliseconds
    latency_regression_max: float = 1.5  # 1.5x baseline
    error_rate_regression_max: float = 2.0  # 2x baseline
    throughput_min_ratio: float = 0.9  # 90% of baseline


@dataclass
class ServiceMetrics:
    """Metrics for a single service"""
    service_name: str
    error_rate: float
    error_count: int
    total_requests: int
    p50_latency: float
    p95_latency: float
    p99_latency: float
    throughput: float
    cpu_usage: float
    memory_usage: float
    pod_restarts: int


@dataclass
class ComparisonResult:
    """Comparison between canary and baseline"""
    service_name: str
    canary: ServiceMetrics
    baseline: ServiceMetrics
    delta_error_rate: float
    delta_latency_p99: float
    delta_throughput: float
    status: str  # 'PASS', 'WARNING', 'FAIL'
    checks: Dict[str, bool]


class CanaryAnalyzer:
    """Analyzes canary deployment metrics"""
    
    def __init__(self, prometheus_url: str, thresholds: Optional[MetricThresholds] = None):
        self.prometheus = PrometheusConnect(url=prometheus_url)
        self.thresholds = thresholds or MetricThresholds()
        
    def query_metric(self, query: str, time: Optional[datetime] = None) -> List[dict]:
        """Execute Prometheus query"""
        try:
            result = self.prometheus.custom_query(query=query)
            return result
        except Exception as e:
            print(f"Error querying Prometheus: {e}", file=sys.stderr)
            return []
    
    def get_service_metrics(
        self, 
        service_name: str, 
        is_canary: bool,
        start_time: datetime,
        end_time: datetime
    ) -> ServiceMetrics:
        """Collect metrics for a service"""
        
        service_label = f'{service_name}-canary' if is_canary else service_name
        
        # Error rate
        error_query = f'''
            sum(rate(http_requests_total{{service="{service_label}",status=~"5.."}}[5m]))
            /
            sum(rate(http_requests_total{{service="{service_label}"}}[5m])) * 100
        '''
        error_result = self.query_metric(error_query)
        error_rate = float(error_result[0]['value'][1]) if error_result else 0.0
        
        # Request counts
        total_query = f'''
            sum(increase(http_requests_total{{service="{service_label}"}}[1h]))
        '''
        total_result = self.query_metric(total_query)
        total_requests = int(float(total_result[0]['value'][1])) if total_result else 0
        error_count = int(total_requests * error_rate / 100)
        
        # Latency percentiles
        latency_query = f'''
            histogram_quantile(0.50,
                sum(rate(http_request_duration_seconds_bucket{{service="{service_label}"}}[5m])) by (le)
            ) * 1000
        '''
        p50_result = self.query_metric(latency_query)
        p50_latency = float(p50_result[0]['value'][1]) if p50_result else 0.0
        
        latency_p95_query = f'''
            histogram_quantile(0.95,
                sum(rate(http_request_duration_seconds_bucket{{service="{service_label}"}}[5m])) by (le)
            ) * 1000
        '''
        p95_result = self.query_metric(latency_p95_query)
        p95_latency = float(p95_result[0]['value'][1]) if p95_result else 0.0
        
        latency_p99_query = f'''
            histogram_quantile(0.99,
                sum(rate(http_request_duration_seconds_bucket{{service="{service_label}"}}[5m])) by (le)
            ) * 1000
        '''
        p99_result = self.query_metric(latency_p99_query)
        p99_latency = float(p99_result[0]['value'][1]) if p99_result else 0.0
        
        # Throughput
        throughput_query = f'''
            sum(rate(http_requests_total{{service="{service_label}"}}[5m]))
        '''
        throughput_result = self.query_metric(throughput_query)
        throughput = float(throughput_result[0]['value'][1]) if throughput_result else 0.0
        
        # Resource usage
        cpu_query = f'''
            avg(rate(container_cpu_usage_seconds_total{{pod=~"{service_label}-.*",container!=""}}[5m])) * 100
        '''
        cpu_result = self.query_metric(cpu_query)
        cpu_usage = float(cpu_result[0]['value'][1]) if cpu_result else 0.0
        
        memory_query = f'''
            avg(container_memory_working_set_bytes{{pod=~"{service_label}-.*",container!=""}})
            /
            avg(container_spec_memory_limit_bytes{{pod=~"{service_label}-.*",container!=""}}) * 100
        '''
        memory_result = self.query_metric(memory_query)
        memory_usage = float(memory_result[0]['value'][1]) if memory_result else 0.0
        
        # Pod restarts
        restart_query = f'''
            sum(rate(kube_pod_container_status_restarts_total{{pod=~"{service_label}-.*"}}[1h]))
        '''
        restart_result = self.query_metric(restart_query)
        pod_restarts = int(float(restart_result[0]['value'][1])) if restart_result else 0
        
        return ServiceMetrics(
            service_name=service_name,
            error_rate=round(error_rate, 4),
            error_count=error_count,
            total_requests=total_requests,
            p50_latency=round(p50_latency, 2),
            p95_latency=round(p95_latency, 2),
            p99_latency=round(p99_latency, 2),
            throughput=round(throughput, 2),
            cpu_usage=round(cpu_usage, 2),
            memory_usage=round(memory_usage, 2),
            pod_restarts=pod_restarts
        )
    
    def compare_services(
        self, 
        service_name: str,
        start_time: datetime,
        end_time: datetime
    ) -> ComparisonResult:
        """Compare canary vs baseline metrics"""
        
        canary_metrics = self.get_service_metrics(service_name, True, start_time, end_time)
        baseline_metrics = self.get_service_metrics(service_name, False, start_time, end_time)
        
        # Calculate deltas
        delta_error_rate = canary_metrics.error_rate - baseline_metrics.error_rate
        delta_latency_p99 = (
            (canary_metrics.p99_latency / baseline_metrics.p99_latency - 1) * 100
            if baseline_metrics.p99_latency > 0 else 0
        )
        delta_throughput = (
            (canary_metrics.throughput / baseline_metrics.throughput - 1) * 100
            if baseline_metrics.throughput > 0 else 0
        )
        
        # Run checks
        checks = {
            'error_rate_acceptable': canary_metrics.error_rate <= self.thresholds.error_rate_max,
            'latency_p99_acceptable': canary_metrics.p99_latency <= self.thresholds.latency_p99_max,
            'latency_regression_ok': (
                canary_metrics.p99_latency / baseline_metrics.p99_latency <= self.thresholds.latency_regression_max
                if baseline_metrics.p99_latency > 0 else True
            ),
            'error_regression_ok': (
                canary_metrics.error_rate / max(baseline_metrics.error_rate, 0.01) <= self.thresholds.error_rate_regression_max
            ),
            'throughput_acceptable': (
                canary_metrics.throughput >= baseline_metrics.throughput * self.thresholds.throughput_min_ratio
                if baseline_metrics.throughput > 0 else True
            ),
            'no_pod_restarts': canary_metrics.pod_restarts == 0
        }
        
        # Determine status
        if all(checks.values()):
            status = 'PASS'
        elif sum(1 for v in checks.values() if not v) == 1 and not checks['no_pod_restarts']:
            status = 'WARNING'
        else:
            status = 'FAIL'
        
        return ComparisonResult(
            service_name=service_name,
            canary=canary_metrics,
            baseline=baseline_metrics,
            delta_error_rate=round(delta_error_rate, 4),
            delta_latency_p99=round(delta_latency_p99, 2),
            delta_throughput=round(delta_throughput, 2),
            status=status,
            checks=checks
        )
    
    def generate_report(self, results: List[ComparisonResult]) -> Dict:
        """Generate comprehensive analysis report"""
        
        overall_status = 'PASS' if all(r.status == 'PASS' for r in results) else \
                        'WARNING' if all(r.status in ['PASS', 'WARNING'] for r in results) else \
                        'FAIL'
        
        recommendations = []
        if overall_status == 'FAIL':
            recommendations.append("⚠️ Canary validation FAILED. Do not promote to production.")
            recommendations.append("Investigate failing metrics and fix issues before retrying.")
        elif overall_status == 'WARNING':
            recommendations.append("⚡ Canary validation WARNING. Review metrics carefully.")
            recommendations.append("Consider manual approval before promotion.")
        else:
            recommendations.append("✅ Canary validation PASSED. Safe to promote to production.")
        
        return {
            'timestamp': datetime.utcnow().isoformat(),
            'overall_status': overall_status,
            'thresholds': asdict(self.thresholds),
            'services': [
                {
                    'service_name': r.service_name,
                    'status': r.status,
                    'canary': asdict(r.canary),
                    'baseline': asdict(r.baseline),
                    'delta': {
                        'error_rate': r.delta_error_rate,
                        'latency_p99_percent': r.delta_latency_p99,
                        'throughput_percent': r.delta_throughput
                    },
                    'checks': r.checks
                }
                for r in results
            ],
            'recommendations': recommendations,
            'promotion_approved': overall_status == 'PASS'
        }


def main():
    parser = argparse.ArgumentParser(
        description='Analyze canary deployment metrics'
    )
    parser.add_argument(
        '--prometheus-url',
        required=True,
        help='Prometheus server URL'
    )
    parser.add_argument(
        '--services',
        required=True,
        help='Comma-separated list of service names'
    )
    parser.add_argument(
        '--start-time',
        help='Analysis start time (ISO format)'
    )
    parser.add_argument(
        '--duration',
        default='30m',
        help='Analysis duration (e.g., 30m, 1h)'
    )
    parser.add_argument(
        '--output',
        default='canary-analysis.json',
        help='Output file for results'
    )
    parser.add_argument(
        '--error-threshold',
        type=float,
        default=1.0,
        help='Maximum acceptable error rate (%)'
    )
    parser.add_argument(
        '--latency-threshold',
        type=float,
        default=2000,
        help='Maximum acceptable P99 latency (ms)'
    )
    
    args = parser.parse_args()
    
    # Parse time range
    end_time = datetime.utcnow()
    if args.start_time:
        start_time = parse_datetime(args.start_time)
    else:
        # Parse duration
        duration_str = args.duration
        if duration_str.endswith('m'):
            minutes = int(duration_str[:-1])
            start_time = end_time - timedelta(minutes=minutes)
        elif duration_str.endswith('h'):
            hours = int(duration_str[:-1])
            start_time = end_time - timedelta(hours=hours)
        else:
            start_time = end_time - timedelta(minutes=30)
    
    # Initialize thresholds
    thresholds = MetricThresholds(
        error_rate_max=args.error_threshold,
        latency_p99_max=args.latency_threshold
    )
    
    # Initialize analyzer
    analyzer = CanaryAnalyzer(args.prometheus_url, thresholds)
    
    # Analyze each service
    services = args.services.split(',')
    results = []
    
    print(f"Analyzing {len(services)} services from {start_time} to {end_time}")
    
    for service in services:
        print(f"\nAnalyzing service: {service}")
        try:
            result = analyzer.compare_services(service, start_time, end_time)
            results.append(result)
            print(f"  Status: {result.status}")
            print(f"  Error Rate: {result.canary.error_rate}% (baseline: {result.baseline.error_rate}%)")
            print(f"  P99 Latency: {result.canary.p99_latency}ms (baseline: {result.baseline.p99_latency}ms)")
        except Exception as e:
            print(f"  Error analyzing {service}: {e}", file=sys.stderr)
    
    # Generate report
    report = analyzer.generate_report(results)
    
    # Output results
    with open(args.output, 'w') as f:
        json.dump(report, f, indent=2)
    
    print(f"\n{'='*60}")
    print(f"Overall Status: {report['overall_status']}")
    print(f"Promotion Approved: {report['promotion_approved']}")
    print(f"\nRecommendations:")
    for rec in report['recommendations']:
        print(f"  - {rec}")
    print(f"\nReport saved to: {args.output}")
    
    # Exit with appropriate code
    if report['overall_status'] == 'FAIL':
        sys.exit(1)
    elif report['overall_status'] == 'WARNING':
        sys.exit(2)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()