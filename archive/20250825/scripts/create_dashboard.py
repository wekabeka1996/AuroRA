#!/usr/bin/env python3
"""
AURORA Observability Dashboard Generator
Створює Grafana dashboard для моніторингу RC → GA
"""
import json
import argparse
from pathlib import Path
from datetime import datetime

def create_ga_gates_panel():
    """Панель GA Gates"""
    return {
        "id": 1,
        "title": "GA Gates Status",
        "type": "stat",
        "targets": [
            {
                "expr": "aurora_ga_gate_main_loop_started_ratio",
                "legendFormat": "Main Loop Started",
                "refId": "A"
            },
            {
                "expr": "aurora_ga_gate_decisions_per_run",
                "legendFormat": "Decisions/Run",
                "refId": "B"
            },
            {
                "expr": "aurora_ga_gate_preloop_exit_ratio", 
                "legendFormat": "Preloop Exit %",
                "refId": "C"
            },
            {
                "expr": "aurora_ga_gate_noop_ratio_mean",
                "legendFormat": "NOOP Ratio",
                "refId": "D"
            },
            {
                "expr": "aurora_ga_gate_zero_budget_count",
                "legendFormat": "Zero Budget",
                "refId": "E"
            }
        ],
        "fieldConfig": {
            "defaults": {
                "thresholds": {
                    "steps": [
                        {"color": "red", "value": 0},
                        {"color": "yellow", "value": 0.8},
                        {"color": "green", "value": 0.95}
                    ]
                },
                "unit": "percentunit"
            }
        },
        "gridPos": {"h": 8, "w": 24, "x": 0, "y": 0}
    }

def create_preloop_stats_panel():
    """Панель Preloop Statistics"""
    return {
        "id": 2,
        "title": "Preloop Statistics",
        "type": "timeseries",
        "targets": [
            {
                "expr": "aurora_preloop_runs_total",
                "legendFormat": "Total Runs",
                "refId": "A"
            },
            {
                "expr": "aurora_preloop_successful_runs",
                "legendFormat": "Successful Runs", 
                "refId": "B"
            },
            {
                "expr": "aurora_preloop_exit_rate_exit",
                "legendFormat": "Exit Rate",
                "refId": "C"
            },
            {
                "expr": "aurora_preloop_exit_rate_timeout",
                "legendFormat": "Timeout Rate",
                "refId": "D"
            }
        ],
        "fieldConfig": {
            "defaults": {
                "custom": {
                    "drawStyle": "line",
                    "lineInterpolation": "linear",
                    "lineWidth": 2,
                    "fillOpacity": 10
                }
            }
        },
        "gridPos": {"h": 8, "w": 12, "x": 0, "y": 8}
    }

def create_main_loop_panel():
    """Панель Main Loop Metrics"""
    return {
        "id": 3,
        "title": "Main Loop Performance",
        "type": "timeseries",
        "targets": [
            {
                "expr": "aurora_main_loop_decisions_total",
                "legendFormat": "Total Decisions",
                "refId": "A"
            },
            {
                "expr": "aurora_main_loop_execution_decisions",
                "legendFormat": "Execution Decisions",
                "refId": "B"
            },
            {
                "expr": "aurora_main_loop_noop_ratio",
                "legendFormat": "NOOP Ratio",
                "refId": "C"
            }
        ],
        "fieldConfig": {
            "defaults": {
                "custom": {
                    "drawStyle": "line",
                    "lineInterpolation": "linear"
                }
            }
        },
        "gridPos": {"h": 8, "w": 12, "x": 12, "y": 8}
    }

def create_canary_health_panel():
    """Панель Canary Health"""
    return {
        "id": 4,
        "title": "Canary Deployment Health",
        "type": "table",
        "targets": [
            {
                "expr": "aurora_canary_test_success_rate",
                "legendFormat": "Success Rate",
                "refId": "A"
            },
            {
                "expr": "aurora_canary_test_health_rate", 
                "legendFormat": "Health Rate",
                "refId": "B"
            },
            {
                "expr": "aurora_canary_tests_total",
                "legendFormat": "Total Tests",
                "refId": "C"
            }
        ],
        "fieldConfig": {
            "defaults": {
                "custom": {
                    "displayMode": "basic",
                    "inspect": False
                },
                "thresholds": {
                    "steps": [
                        {"color": "red", "value": 0},
                        {"color": "yellow", "value": 0.67},
                        {"color": "green", "value": 0.9}
                    ]
                }
            }
        },
        "gridPos": {"h": 6, "w": 24, "x": 0, "y": 16}
    }

def create_system_resources_panel():
    """Панель System Resources"""
    return {
        "id": 5,
        "title": "System Resources",
        "type": "timeseries",
        "targets": [
            {
                "expr": "aurora_memory_usage_mb",
                "legendFormat": "Memory (MB)",
                "refId": "A"
            },
            {
                "expr": "aurora_cpu_usage_percent",
                "legendFormat": "CPU %",
                "refId": "B"
            },
            {
                "expr": "aurora_run_duration_seconds",
                "legendFormat": "Run Duration (s)",
                "refId": "C"
            }
        ],
        "fieldConfig": {
            "defaults": {
                "custom": {
                    "drawStyle": "line",
                    "lineInterpolation": "linear"
                },
                "unit": "short"
            }
        },
        "gridPos": {"h": 6, "w": 12, "x": 0, "y": 22}
    }

def create_error_tracking_panel():
    """Панель Error Tracking"""
    return {
        "id": 6,
        "title": "Error & Warning Tracking",
        "type": "logs",
        "targets": [
            {
                "expr": '{job="aurora"} |= "ERROR"',
                "legendFormat": "Errors",
                "refId": "A"
            },
            {
                "expr": '{job="aurora"} |= "WARNING"',
                "legendFormat": "Warnings", 
                "refId": "B"
            }
        ],
        "options": {
            "showTime": True,
            "showLabels": False,
            "showCommonLabels": False,
            "wrapLogMessage": False,
            "prettifyLogMessage": False,
            "enableLogDetails": True,
            "dedupStrategy": "none",
            "sortOrder": "Descending"
        },
        "gridPos": {"h": 6, "w": 12, "x": 12, "y": 22}
    }

def create_dashboard_template():
    """Створити повний dashboard template"""
    dashboard = {
        "id": None,
        "title": "AURORA RC → GA Monitoring",
        "description": "Observability dashboard for AURORA RC to GA transition",
        "tags": ["aurora", "rc", "ga", "monitoring"],
        "timezone": "browser",
        "editable": True,
        "graphTooltip": 1,
        "time": {
            "from": "now-24h",
            "to": "now"
        },
        "timepicker": {
            "refresh_intervals": ["5s", "10s", "30s", "1m", "5m", "15m", "30m", "1h", "2h", "1d"],
            "time_options": ["5m", "15m", "1h", "6h", "12h", "24h", "2d", "7d", "30d"]
        },
        "templating": {
            "list": [
                {
                    "name": "environment",
                    "type": "custom",
                    "options": [
                        {"text": "staging", "value": "staging", "selected": True},
                        {"text": "production", "value": "production", "selected": False},
                        {"text": "canary", "value": "canary", "selected": False}
                    ],
                    "current": {"text": "staging", "value": "staging"}
                },
                {
                    "name": "config_profile",
                    "type": "custom", 
                    "options": [
                        {"text": "r2", "value": "r2", "selected": True},
                        {"text": "smoke", "value": "smoke", "selected": False}
                    ],
                    "current": {"text": "r2", "value": "r2"}
                }
            ]
        },
        "annotations": {
            "list": [
                {
                    "name": "Deployments",
                    "datasource": "prometheus",
                    "expr": "aurora_deployment_event",
                    "iconColor": "green",
                    "textFormat": "Deployment: {{version}}"
                },
                {
                    "name": "Canary Tests",
                    "datasource": "prometheus", 
                    "expr": "aurora_canary_test_started",
                    "iconColor": "blue",
                    "textFormat": "Canary: {{test_id}}"
                }
            ]
        },
        "panels": [
            create_ga_gates_panel(),
            create_preloop_stats_panel(),
            create_main_loop_panel(),
            create_canary_health_panel(),
            create_system_resources_panel(),
            create_error_tracking_panel()
        ],
        "refresh": "30s",
        "schemaVersion": 30,
        "version": 1
    }
    
    return dashboard

def create_prometheus_alerts():
    """Створити Prometheus alerts для AURORA"""
    alerts = {
        "groups": [
            {
                "name": "aurora_ga_gates",
                "rules": [
                    {
                        "alert": "AuroraMainLoopStartedRateLow",
                        "expr": "aurora_ga_gate_main_loop_started_ratio < 0.95",
                        "for": "5m",
                        "labels": {
                            "severity": "critical",
                            "component": "aurora-ga-gates"
                        },
                        "annotations": {
                            "summary": "AURORA main loop started ratio below threshold",
                            "description": "Main loop started ratio is {{ $value }} (threshold: 0.95)"
                        }
                    },
                    {
                        "alert": "AuroraZeroBudgetDetected",
                        "expr": "aurora_ga_gate_zero_budget_count > 0",
                        "for": "1m",
                        "labels": {
                            "severity": "warning",
                            "component": "aurora-ga-gates"
                        },
                        "annotations": {
                            "summary": "AURORA zero budget events detected",
                            "description": "{{ $value }} zero budget events in recent runs"
                        }
                    },
                    {
                        "alert": "AuroraNoopRatioHigh",
                        "expr": "aurora_ga_gate_noop_ratio_mean > 0.85",
                        "for": "10m",
                        "labels": {
                            "severity": "warning",
                            "component": "aurora-ga-gates"
                        },
                        "annotations": {
                            "summary": "AURORA NOOP ratio is high",
                            "description": "Mean NOOP ratio is {{ $value }} (threshold: 0.85)"
                        }
                    }
                ]
            },
            {
                "name": "aurora_canary",
                "rules": [
                    {
                        "alert": "AuroraCanaryTestsFailing",
                        "expr": "aurora_canary_test_success_rate < 0.67",
                        "for": "5m",
                        "labels": {
                            "severity": "critical",
                            "component": "aurora-canary"
                        },
                        "annotations": {
                            "summary": "AURORA canary tests failing",
                            "description": "Canary success rate is {{ $value }} (threshold: 0.67)"
                        }
                    }
                ]
            }
        ]
    }
    
    return alerts

def main():
    parser = argparse.ArgumentParser(description="Generate AURORA observability dashboard")
    parser.add_argument("--output-dashboard", default="monitoring/aurora_dashboard.json",
                       help="Output dashboard JSON file")
    parser.add_argument("--output-alerts", default="monitoring/aurora_alerts.yml", 
                       help="Output alerts YAML file")
    parser.add_argument("--grafana-api", help="Grafana API endpoint for direct upload")
    parser.add_argument("--grafana-token", help="Grafana API token")
    
    args = parser.parse_args()
    
    # Ensure monitoring directory exists
    Path("monitoring").mkdir(exist_ok=True)
    
    print(f"📊 AURORA Observability Dashboard Generator")
    
    # Generate dashboard
    dashboard = create_dashboard_template()
    
    with open(args.output_dashboard, 'w') as f:
        json.dump(dashboard, f, indent=2)
    
    print(f"✅ Dashboard saved to {args.output_dashboard}")
    
    # Generate alerts
    alerts = create_prometheus_alerts()
    
    import yaml
    with open(args.output_alerts, 'w') as f:
        yaml.dump(alerts, f, default_flow_style=False)
    
    print(f"✅ Alerts saved to {args.output_alerts}")
    
    # Optionally upload to Grafana
    if args.grafana_api and args.grafana_token:
        try:
            import requests
            
            headers = {
                "Authorization": f"Bearer {args.grafana_token}",
                "Content-Type": "application/json"
            }
            
            response = requests.post(
                f"{args.grafana_api}/api/dashboards/db",
                headers=headers,
                json={"dashboard": dashboard, "overwrite": True}
            )
            
            if response.status_code == 200:
                print(f"✅ Dashboard uploaded to Grafana")
            else:
                print(f"⚠️ Failed to upload dashboard: {response.status_code}")
                
        except ImportError:
            print("⚠️ requests library not available for Grafana upload")
        except Exception as e:
            print(f"⚠️ Grafana upload failed: {e}")
    
    print(f"\n🎯 Dashboard Features:")
    print(f"  • GA Gates monitoring with thresholds")
    print(f"  • Preloop and main loop statistics")
    print(f"  • Canary deployment health tracking")
    print(f"  • System resource monitoring")
    print(f"  • Error and warning log tracking")
    print(f"  • Prometheus alerts for critical conditions")
    
    return 0

if __name__ == "__main__":
    exit(main())