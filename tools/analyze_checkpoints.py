#!/usr/bin/env python3
"""
AURORA Checkpoint Analyzer
Analyzes model checkpoints for anomalies and quality issues
"""

import argparse
import json
import sys
import torch
import numpy as np
from pathlib import Path
from datetime import datetime

def load_checkpoint_safely(ckpt_path):
    """Safely load checkpoint with error handling"""
    try:
        # Try CPU first to avoid GPU memory issues
        checkpoint = torch.load(ckpt_path, map_location='cpu')
        return True, checkpoint
    except Exception as e:
        return False, str(e)

def analyze_checkpoint_weights(checkpoint):
    """Analyze checkpoint weights for anomalies"""
    analysis = {
        "weight_stats": {},
        "anomalies": [],
        "health_score": 1.0
    }
    
    if 'model_state_dict' not in checkpoint:
        analysis["anomalies"].append("Missing model_state_dict")
        analysis["health_score"] = 0.0
        return analysis
    
    state_dict = checkpoint['model_state_dict']
    
    # Analyze each layer
    layer_stats = {}
    anomaly_count = 0
    
    for name, tensor in state_dict.items():
        if not isinstance(tensor, torch.Tensor):
            continue
        
        # Convert to numpy for analysis
        weights = tensor.detach().cpu().numpy()
        
        # Basic statistics
        stats = {
            "shape": list(weights.shape),
            "mean": float(np.mean(weights)),
            "std": float(np.std(weights)),
            "min": float(np.min(weights)),
            "max": float(np.max(weights)),
            "zeros_pct": float(np.mean(weights == 0) * 100),
            "inf_count": int(np.sum(np.isinf(weights))),
            "nan_count": int(np.sum(np.isnan(weights)))
        }
        
        # Check for anomalies
        anomalies = []
        
        # NaN/Inf check
        if stats["nan_count"] > 0:
            anomalies.append(f"Contains {stats['nan_count']} NaN values")
            anomaly_count += 1
        
        if stats["inf_count"] > 0:
            anomalies.append(f"Contains {stats['inf_count']} infinite values")
            anomaly_count += 1
        
        # Extreme values check
        if abs(stats["mean"]) > 10:
            anomalies.append(f"Extreme mean: {stats['mean']:.3f}")
            anomaly_count += 1
        
        if stats["std"] > 100:
            anomalies.append(f"Extreme std: {stats['std']:.3f}")
            anomaly_count += 1
        
        # Dead neurons (all zeros)
        if stats["zeros_pct"] > 50:
            anomalies.append(f"High zero percentage: {stats['zeros_pct']:.1f}%")
            anomaly_count += 1
        
        layer_stats[name] = {
            **stats,
            "anomalies": anomalies
        }
    
    analysis["weight_stats"] = layer_stats
    analysis["total_anomalies"] = anomaly_count
    
    # Calculate health score
    total_layers = len(layer_stats)
    if total_layers > 0:
        anomaly_ratio = anomaly_count / total_layers
        analysis["health_score"] = max(0.0, 1.0 - anomaly_ratio)
    
    return analysis

def compare_checkpoints(ckpt1_path, ckpt2_path):
    """Compare two checkpoints for similarity"""
    
    # Load both checkpoints
    success1, ckpt1 = load_checkpoint_safely(ckpt1_path)
    success2, ckpt2 = load_checkpoint_safely(ckpt2_path)
    
    if not success1 or not success2:
        return {
            "similarity": 0.0,
            "error": f"Failed to load checkpoints: {ckpt1 if not success1 else ''} {ckpt2 if not success2 else ''}"
        }
    
    # Extract state dicts
    state1 = ckpt1.get('model_state_dict', {})
    state2 = ckpt2.get('model_state_dict', {})
    
    if not state1 or not state2:
        return {
            "similarity": 0.0,
            "error": "Missing model_state_dict in one or both checkpoints"
        }
    
    # Calculate cosine similarity for matching layers
    similarities = []
    
    for name in state1.keys():
        if name not in state2:
            continue
        
        tensor1 = state1[name].detach().cpu().numpy().flatten()
        tensor2 = state2[name].detach().cpu().numpy().flatten()
        
        # Cosine similarity
        dot_product = np.dot(tensor1, tensor2)
        norm1 = np.linalg.norm(tensor1)
        norm2 = np.linalg.norm(tensor2)
        
        if norm1 > 0 and norm2 > 0:
            similarity = dot_product / (norm1 * norm2)
            similarities.append(similarity)
    
    overall_similarity = np.mean(similarities) if similarities else 0.0
    
    return {
        "similarity": float(overall_similarity),
        "layer_count": len(similarities),
        "min_similarity": float(np.min(similarities)) if similarities else 0.0,
        "max_similarity": float(np.max(similarities)) if similarities else 0.0
    }

def main():
    parser = argparse.ArgumentParser(description="Analyze AURORA model checkpoints")
    parser.add_argument('--ckpt-dir', default='checkpoints/', help="Checkpoints directory")
    parser.add_argument('--ref', help="Reference checkpoint for comparison (e.g., 'latest-1')")
    parser.add_argument('--jsonl', help="Output JSONL file for detailed analysis")
    parser.add_argument('--report', help="Output JSON file for summary report")
    parser.add_argument('--exit-on-anomaly', action='store_true', help="Exit with code 1 if anomalies found")
    
    args = parser.parse_args()
    
    ckpt_dir = Path(args.ckpt_dir)
    if not ckpt_dir.exists():
        print(f"❌ Checkpoint directory not found: {ckpt_dir}")
        sys.exit(1)
    
    # Find checkpoint files
    checkpoint_files = list(ckpt_dir.glob("*.pt"))
    if not checkpoint_files:
        print(f"❌ No checkpoint files found in {ckpt_dir}")
        sys.exit(1)
    
    # Sort by modification time (newest first)
    checkpoint_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    
    print(f"🔍 Analyzing {len(checkpoint_files)} checkpoints...")
    
    results = []
    anomaly_count = 0
    
    # Analyze each checkpoint
    for i, ckpt_path in enumerate(checkpoint_files):
        print(f"   Analyzing {ckpt_path.name}...")
        
        success, checkpoint = load_checkpoint_safely(ckpt_path)
        if not success:
            result = {
                "checkpoint": ckpt_path.name,
                "success": False,
                "error": checkpoint,
                "timestamp": datetime.now().isoformat()
            }
        else:
            analysis = analyze_checkpoint_weights(checkpoint)
            
            result = {
                "checkpoint": ckpt_path.name,
                "success": True,
                "analysis": analysis,
                "file_size_mb": ckpt_path.stat().st_size / (1024*1024),
                "modified_time": datetime.fromtimestamp(ckpt_path.stat().st_mtime).isoformat(),
                "timestamp": datetime.now().isoformat()
            }
            
            if analysis.get("total_anomalies", 0) > 0:
                anomaly_count += 1
        
        results.append(result)
        
        # Write to JSONL if requested
        if args.jsonl:
            jsonl_path = Path(args.jsonl)
            jsonl_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(jsonl_path, 'a') as f:
                f.write(json.dumps(result) + '\n')
    
    # Generate summary report
    summary = {
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "analyzer": "analyze_checkpoints.py",
            "checkpoints_analyzed": len(checkpoint_files)
        },
        "summary": {
            "total_checkpoints": len(checkpoint_files),
            "successful_analysis": sum(1 for r in results if r["success"]),
            "checkpoints_with_anomalies": anomaly_count,
            "overall_health": "HEALTHY" if anomaly_count == 0 else "ANOMALIES_DETECTED"
        },
        "checkpoints": results
    }
    
    # Compare with reference if specified
    if args.ref and len(checkpoint_files) >= 2:
        if args.ref == "latest-1" and len(checkpoint_files) >= 2:
            ref_ckpt = checkpoint_files[1]  # Second newest
            current_ckpt = checkpoint_files[0]  # Newest
        else:
            # Try to find reference by name
            ref_ckpt = None
            for ckpt in checkpoint_files:
                if args.ref in ckpt.name:
                    ref_ckpt = ckpt
                    break
            current_ckpt = checkpoint_files[0]
        
        if ref_ckpt:
            comparison = compare_checkpoints(current_ckpt, ref_ckpt)
            summary["comparison"] = {
                "current": current_ckpt.name,
                "reference": ref_ckpt.name,
                **comparison
            }
            
            # Check for significant drift
            if comparison.get("similarity", 0) < 0.995:
                summary["summary"]["overall_health"] = "DRIFT_DETECTED"
                print(f"⚠️  Model drift detected: similarity = {comparison['similarity']:.4f}")
    
    # Write report
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(report_path, 'w') as f:
            json.dump(summary, f, indent=2)
        
        print(f"📄 Report written to {report_path}")
    
    # Print summary
    print(f"\n📊 Analysis Summary:")
    print(f"   Total checkpoints: {summary['summary']['total_checkpoints']}")
    print(f"   Successful analysis: {summary['summary']['successful_analysis']}")
    print(f"   Anomalies detected: {anomaly_count}")
    print(f"   Overall health: {summary['summary']['overall_health']}")
    
    if 'comparison' in summary:
        comp = summary['comparison']
        print(f"   Similarity to reference: {comp.get('similarity', 0):.4f}")
    
    # Exit with error if anomalies found and flag set
    if args.exit_on_anomaly and anomaly_count > 0:
        print(f"\n❌ Exiting due to anomalies detected")
        sys.exit(1)
    
    print(f"\n✅ Checkpoint analysis complete")
    sys.exit(0)

if __name__ == "__main__":
    main()