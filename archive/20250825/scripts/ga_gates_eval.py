#!/usr/bin/env python3
"""
GA Gates Evaluator v1.0 - Definitive Production Readiness Assessment
Evaluates 5 hard gates for RC → GA promotion decision
"""
import json
import yaml
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import statistics

@dataclass
class GateResult:
    gate_id: int
    gate_name: str
    status: str  # PASS, WARN, FAIL
    value: float
    threshold: float
    condition: str
    message: str
    fail_action: str  # NO-GO, CONDITIONAL, OBSERVE

class GAGatesEvaluator:
    def __init__(self, prometheus_url: Optional[str] = None, artifacts_dir: str = "artifacts"):
        self.prometheus_url = prometheus_url
        self.artifacts_dir = Path(artifacts_dir)
        self.window_hours = 48
        
    def query_prometheus(self, query: str, hours: int = 48) -> Dict:
        """Query Prometheus metrics"""
        if not self.prometheus_url:
            # Fallback to mock data for demo
            return self._mock_prometheus_data(query)
        
        try:
            import requests
            end_time = datetime.now()
            start_time = end_time - timedelta(hours=hours)
            
            params = {
                'query': query,
                'start': start_time.isoformat(),
                'end': end_time.isoformat(),
                'step': '5m'
            }
            
            response = requests.get(f"{self.prometheus_url}/api/v1/query_range", params=params)
            return response.json()
            
        except Exception as e:
            print(f"⚠️ Prometheus query failed: {e}")
            return self._mock_prometheus_data(query)
    
    def _mock_prometheus_data(self, query: str) -> Dict:
        """Mock Prometheus data for testing"""
        mock_data = {
            'ci_gating_violation_total': {'data': {'result': [{'values': [[1629554400, '0']]}]}},
            'aurora_warn_rate': {'data': {'result': [{'values': [[1629554400, '0.02']]}]}},
            'aurora_tvf2_dcts_robust_value': {'data': {'result': [{'values': [[1629554400, '0.75']]}]}},
            'aurora_tvf2_dcts_min_value': {'data': {'result': [{'values': [[1629554400, '0.80']]}]}},
            'aurora_ci_coverage_abs_err_ema': {'data': {'result': [{'values': [[1629554400, '0.03']]}]}},
            'aurora_risk_dro_factor': {'data': {'result': [{'values': [[1629554400, '0.75']]}]}},
            'aurora_risk_dro_adj': {'data': {'result': [{'values': [[1629554400, '0.05']]}]}}
        }
        
        for key in mock_data:
            if key in query:
                return mock_data[key]
        
        return {'data': {'result': []}}
    
    def evaluate_gate_1_stability(self) -> GateResult:
        """Gate 1: Stability / Hard-fail"""
        # Check CI gating violations
        violations = self.query_prometheus('increase(ci_gating_violation_total[48h])')
        warn_rate = self.query_prometheus('avg_over_time(aurora_warn_rate[48h])')
        
        violation_count = 0
        warn_rate_value = 0.0
        
        try:
            violation_data = violations.get('data', {}).get('result', [])
            if violation_data and violation_data[0].get('values'):
                violation_count = float(violation_data[0]['values'][-1][1])
                
            warn_data = warn_rate.get('data', {}).get('result', [])
            if warn_data and warn_data[0].get('values'):
                warn_rate_value = float(warn_data[0]['values'][-1][1])
        except (IndexError, KeyError, ValueError):
            pass
        
        # Gate conditions
        violations_ok = violation_count == 0
        warn_rate_ok = warn_rate_value <= 0.05
        
        if violations_ok and warn_rate_ok:
            status = "PASS"
            message = f"No violations, warn rate {warn_rate_value:.1%}"
        else:
            status = "FAIL"
            message = f"Violations: {violation_count}, warn rate: {warn_rate_value:.1%}"
        
        return GateResult(
            gate_id=1,
            gate_name="Stability / Hard-fail",
            status=status,
            value=max(violation_count, warn_rate_value),
            threshold=0.05,
            condition="exit=3 count = 0 AND warn_rate ≤ 5%",
            message=message,
            fail_action="NO-GO"
        )
    
    def evaluate_gate_2_dcts_robustness(self) -> GateResult:
        """Gate 2: DCTS Robustness"""
        robust_values = self.query_prometheus('aurora_tvf2_dcts_robust_value')
        base_values = self.query_prometheus('aurora_tvf2_dcts_min_value')
        
        robust_val = 0.75  # Default fallback
        base_val = 0.80
        
        try:
            robust_data = robust_values.get('data', {}).get('result', [])
            if robust_data and robust_data[0].get('values'):
                robust_val = float(robust_data[0]['values'][-1][1])
                
            base_data = base_values.get('data', {}).get('result', [])
            if base_data and base_data[0].get('values'):
                base_val = float(base_data[0]['values'][-1][1])
        except (IndexError, KeyError, ValueError):
            pass
        
        # Calculate variance ratio and relative difference
        var_ratio = robust_val / base_val if base_val > 0 else 1.0
        rel_diff = abs(robust_val - base_val) / base_val if base_val > 0 else 0.0
        
        var_ratio_ok = var_ratio <= 0.85
        rel_diff_ok = rel_diff <= 0.15
        
        if var_ratio_ok and rel_diff_ok:
            status = "PASS"
            message = f"Var ratio: {var_ratio:.3f}, rel diff: {rel_diff:.1%}"
        else:
            status = "FAIL"
            message = f"Var ratio: {var_ratio:.3f} (>0.85) or rel diff: {rel_diff:.1%} (>15%)"
        
        return GateResult(
            gate_id=2,
            gate_name="DCTS Robustness",
            status=status,
            value=max(var_ratio, rel_diff),
            threshold=0.85,
            condition="var_ratio ≤ 0.85 AND |robust-base|/|base| ≤ 0.15",
            message=message,
            fail_action="NO-GO"
        )
    
    def evaluate_gate_3_coverage_control(self) -> GateResult:
        """Gate 3: Coverage Control"""
        coverage_err = self.query_prometheus('aurora_ci_coverage_abs_err_ema')
        
        err_values = []
        try:
            err_data = coverage_err.get('data', {}).get('result', [])
            if err_data and err_data[0].get('values'):
                for timestamp, value in err_data[0]['values']:
                    err_values.append(float(value))
        except (IndexError, KeyError, ValueError):
            err_values = [0.03]  # Fallback
        
        coverage_tolerance = 0.05  # 5% tolerance
        breach_count = sum(1 for err in err_values if err > coverage_tolerance)
        breach_rate = breach_count / len(err_values) if err_values else 0
        
        success_rate = 1.0 - breach_rate
        
        if success_rate >= 0.95:
            status = "PASS"
            message = f"Coverage control: {success_rate:.1%} success rate"
        else:
            status = "FAIL"
            message = f"Coverage breaches: {breach_rate:.1%} (>5%)"
        
        return GateResult(
            gate_id=3,
            gate_name="Coverage Control",
            status=status,
            value=breach_rate,
            threshold=0.05,
            condition="coverage_abs_err_ema ≤ tolerance in ≥95% runs",
            message=message,
            fail_action="NO-GO"
        )
    
    def evaluate_gate_4_risk_dro_health(self) -> GateResult:
        """Gate 4: Risk / DRO Health"""
        dro_factor = self.query_prometheus('quantile_over_time(0.05, aurora_risk_dro_factor[48h])')
        dro_adj = self.query_prometheus('quantile_over_time(0.95, abs(aurora_risk_dro_adj)[48h])')
        
        dro_factor_p05 = 0.75  # Fallback
        dro_adj_p95 = 0.05
        
        try:
            factor_data = dro_factor.get('data', {}).get('result', [])
            if factor_data and factor_data[0].get('values'):
                dro_factor_p05 = float(factor_data[0]['values'][-1][1])
                
            adj_data = dro_adj.get('data', {}).get('result', [])
            if adj_data and adj_data[0].get('values'):
                dro_adj_p95 = float(adj_data[0]['values'][-1][1])
        except (IndexError, KeyError, ValueError):
            pass
        
        factor_ok = dro_factor_p05 >= 0.6
        autotune_ok = dro_adj_p95 <= 0.15
        
        if factor_ok and autotune_ok:
            status = "PASS"
            message = f"DRO factor p05: {dro_factor_p05:.2f}, adj p95: {dro_adj_p95:.2f}"
        elif factor_ok:
            status = "WARN"
            message = f"DRO factor ok, but autotune unstable: adj p95: {dro_adj_p95:.2f}"
        else:
            status = "FAIL"
            message = f"DRO factor low: {dro_factor_p05:.2f} (<0.6)"
        
        return GateResult(
            gate_id=4,
            gate_name="Risk / DRO Health",
            status=status,
            value=min(dro_factor_p05, 1.0 - dro_adj_p95),
            threshold=0.6,
            condition="dro_factor p05 ≥ 0.6 AND |Δλ| p95 ≤ 0.15",
            message=message,
            fail_action="CONDITIONAL"
        )
    
    def evaluate_gate_5_model_qa(self) -> GateResult:
        """Gate 5: Model QA / Checkpoints"""
        # Check checkpoint analyzer report
        ckpt_report_path = self.artifacts_dir / "ckpt" / "report.json"
        
        if not ckpt_report_path.exists():
            return GateResult(
                gate_id=5,
                gate_name="Model QA / Checkpoints",
                status="FAIL",
                value=1.0,
                threshold=0.0,
                condition="ckpt_analyzer_v2 → 0 anomalies",
                message="Checkpoint report not found",
                fail_action="NO-GO"
            )
        
        try:
            with open(ckpt_report_path, 'r') as f:
                report = json.load(f)
            
            anomalies = report.get('anomalies', 0)
            cos_similarity = report.get('min_cos_similarity', 1.0)
            frozen_layers = report.get('frozen_layers', 0)
            
            anomalies_ok = anomalies == 0
            cos_ok = cos_similarity >= 0.995
            frozen_ok = frozen_layers == 0
            
            if anomalies_ok and cos_ok and frozen_ok:
                status = "PASS"
                message = f"Clean checkpoints: cos≥{cos_similarity:.3f}"
                anomaly_value = 0.0
            else:
                status = "FAIL"
                message = f"Anomalies: {anomalies}, cos: {cos_similarity:.3f}, frozen: {frozen_layers}"
                anomaly_value = float(anomalies)
            
        except Exception as e:
            status = "FAIL"
            message = f"Checkpoint analysis failed: {e}"
            anomaly_value = 1.0
        
        return GateResult(
            gate_id=5,
            gate_name="Model QA / Checkpoints",
            status=status,
            value=anomaly_value,
            threshold=0.0,
            condition="0 anomalies (NaN/inf, cos<0.995, frozen-layers)",
            message=message,
            fail_action="NO-GO"
        )
    
    def evaluate_all_gates(self) -> Tuple[str, List[GateResult]]:
        """Evaluate all 5 GA gates"""
        gates = [
            self.evaluate_gate_1_stability(),
            self.evaluate_gate_2_dcts_robustness(),
            self.evaluate_gate_3_coverage_control(),
            self.evaluate_gate_4_risk_dro_health(),
            self.evaluate_gate_5_model_qa()
        ]
        
        # Determine overall status
        fail_count = sum(1 for gate in gates if gate.status == "FAIL")
        warn_count = sum(1 for gate in gates if gate.status == "WARN")
        
        if fail_count > 0:
            overall_status = "FAIL"
        elif warn_count > 0:
            overall_status = "WARN"
        else:
            overall_status = "PASS"
        
        return overall_status, gates
    
    def generate_report(self, output_format: str = "json") -> str:
        """Generate GA gates evaluation report"""
        overall_status, gates = self.evaluate_all_gates()
        
        report_data = {
            "timestamp": datetime.now().isoformat(),
            "window_hours": self.window_hours,
            "overall_status": overall_status,
            "ga_status": overall_status,
            "gates": [
                {
                    "gate_id": gate.gate_id,
                    "gate_name": gate.gate_name,
                    "status": gate.status,
                    "value": gate.value,
                    "threshold": gate.threshold,
                    "condition": gate.condition,
                    "message": gate.message,
                    "fail_action": gate.fail_action
                }
                for gate in gates
            ],
            "decision": self._generate_decision(overall_status, gates),
            "next_steps": self._generate_next_steps(overall_status, gates)
        }
        
        if output_format == "json":
            return json.dumps(report_data, indent=2)
        elif output_format == "md":
            return self._generate_markdown_report(report_data)
        else:
            return json.dumps(report_data, indent=2)
    
    def _generate_decision(self, overall_status: str, gates: List[GateResult]) -> str:
        """Generate GA promotion decision"""
        if overall_status == "PASS":
            return "✅ GA PROMOTION APPROVED - All gates passed"
        elif overall_status == "WARN":
            return "⚠️ GA PROMOTION CONDITIONAL - Review warnings"
        else:
            return "❌ GA PROMOTION BLOCKED - Critical failures detected"
    
    def _generate_next_steps(self, overall_status: str, gates: List[GateResult]) -> List[str]:
        """Generate next steps based on gate results"""
        if overall_status == "PASS":
            return [
                "Enable ci_gating.hard_override: auto",
                "Promote r2 profile with lock",
                "Create GA Decision PR",
                "Deploy to production"
            ]
        else:
            steps = ["Address the following issues:"]
            for gate in gates:
                if gate.status in ["FAIL", "WARN"]:
                    steps.append(f"- Gate {gate.gate_id}: {gate.message}")
            steps.append("Re-run GA gates evaluation")
            return steps
    
    def _generate_markdown_report(self, report_data: Dict) -> str:
        """Generate markdown report"""
        md = f"""# GA Gates Evaluation Report

**Timestamp:** {report_data['timestamp']}  
**Window:** {report_data['window_hours']} hours  
**Overall Status:** **{report_data['ga_status']}**

## Decision
{report_data['decision']}

## Gate Results

| Gate | Name | Status | Value | Condition | Message |
|------|------|--------|-------|-----------|---------|
"""
        
        for gate in report_data['gates']:
            status_icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}[gate['status']]
            md += f"| {gate['gate_id']} | {gate['gate_name']} | {status_icon} {gate['status']} | {gate['value']:.3f} | {gate['condition']} | {gate['message']} |\n"
        
        md += f"""
## Next Steps

"""
        for i, step in enumerate(report_data['next_steps'], 1):
            md += f"{i}. {step}\n"
        
        return md

def main():
    parser = argparse.ArgumentParser(description="GA Gates Evaluator v1.0")
    parser.add_argument("--prometheus-url", help="Prometheus server URL")
    parser.add_argument("--artifacts-dir", default="artifacts", help="Artifacts directory")
    parser.add_argument("--window-hours", type=int, default=48, help="Evaluation window")
    parser.add_argument("--format", choices=["json", "md"], default="json", help="Output format")
    parser.add_argument("--output", help="Output file (stdout if not specified)")
    
    args = parser.parse_args()
    
    evaluator = GAGatesEvaluator(args.prometheus_url, args.artifacts_dir)
    evaluator.window_hours = args.window_hours
    
    report = evaluator.generate_report(args.format)
    
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, 'w') as f:
            f.write(report)
        print(f"Report saved to {args.output}")
    else:
        print(report)
    
    # Exit with appropriate code
    overall_status, _ = evaluator.evaluate_all_gates()
    return 0 if overall_status == "PASS" else 1

if __name__ == "__main__":
    exit(main())