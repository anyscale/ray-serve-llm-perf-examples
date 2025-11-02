#!/usr/bin/env python3
"""
Simple plotting script for benchmark results.
Plots throughput vs concurrency for aggregated results.
"""

import json
import sys
import os
import re
from pathlib import Path
import matplotlib.pyplot as plt


def extract_node_count(exp_name):
    """Extract node count from experiment name (e.g., 'rayoss251-x8' -> 8)."""
    match = re.search(r'-x(\d+)$', exp_name)
    if match:
        return int(match.group(1))
    return None


def load_results(exp_dir):
    """Load all concurrency results from an experiment directory."""
    all_parts_dir = None
    
    # Find all-parts directory (could be named all-parts, all-parts-*xtp4, etc.)
    for item in os.listdir(exp_dir):
        item_path = os.path.join(exp_dir, item)
        if os.path.isdir(item_path) and 'all-parts' in item:
            all_parts_dir = item_path
            break
    
    if not all_parts_dir:
        return None
    
    results = {}
    for json_file in Path(all_parts_dir).glob('conc*.json'):
        try:
            with open(json_file, 'r') as f:
                data = json.load(f)
                # Extract concurrency from filename (e.g., conc32.json -> 32)
                conc_match = re.search(r'conc(\d+)', json_file.name)
                if conc_match:
                    conc = int(conc_match.group(1))
                    # Use request_throughput as the throughput metric
                    throughput = data.get('request_throughput')
                    if throughput is not None:
                        results[conc] = throughput
        except Exception as e:
            print(f"Warning: Failed to load {json_file}: {e}", file=sys.stderr)
    
    return results if results else None


def plot_results(exp_names, output_file=None):
    """Plot throughput vs concurrency for multiple experiments, normalized per replica."""
    data_by_exp = {}
    
    for exp_name in exp_names:
        exp_path = os.path.join('bm_results', exp_name)
        if not os.path.isdir(exp_path):
            print(f"Warning: Experiment directory not found: {exp_path}", file=sys.stderr)
            continue
        
        results = load_results(exp_path)
        if results:
            node_count = extract_node_count(exp_name)
            # Normalize throughput by node count
            normalized_results = {}
            for conc, throughput in results.items():
                if node_count and node_count > 0:
                    normalized_results[conc] = throughput / node_count
                else:
                    normalized_results[conc] = throughput
            
            label = f"{exp_name} ({node_count}x nodes)" if node_count else exp_name
            data_by_exp[label] = normalized_results
    
    if not data_by_exp:
        print("Error: No valid results found to plot", file=sys.stderr)
        return False
    
    # Create plot
    plt.figure(figsize=(10, 6))
    
    for label, results in sorted(data_by_exp.items()):
        concurrency = sorted(results.keys())
        throughput = [results[c] for c in concurrency]
        plt.plot(concurrency, throughput, marker='o', label=label, linewidth=2, markersize=6)
    
    plt.xlabel('Concurrency', fontsize=12)
    plt.ylabel('Throughput per Replica (requests/sec)', fontsize=12)
    plt.title('Throughput vs Concurrency (Normalized per Replica)', fontsize=14, fontweight='bold')
    plt.grid(True, alpha=0.3)
    plt.legend(loc='best')
    plt.tight_layout()
    
    if output_file:
        plt.savefig(output_file, dpi=150, bbox_inches='tight')
        print(f"Plot saved to: {output_file}")
    else:
        plt.show()
    
    return True


def main():
    if len(sys.argv) < 2:
        print("Usage: plot_results.py EXP_NAME [EXP_NAME2 ...] [--output OUTPUT_FILE]")
        print("Example: plot_results.py rayoss251-x2 rayoss251-x4 rayoss251-x8")
        sys.exit(1)
    
    exp_names = []
    output_file = None
    
    i = 1
    while i < len(sys.argv):
        if sys.argv[i] == '--output' or sys.argv[i] == '-o':
            if i + 1 < len(sys.argv):
                output_file = sys.argv[i + 1]
                i += 2
            else:
                print("Error: --output requires a filename", file=sys.stderr)
                sys.exit(1)
        else:
            exp_names.append(sys.argv[i])
            i += 1
    
    if not exp_names:
        print("Error: No experiment names provided", file=sys.stderr)
        sys.exit(1)
    
    success = plot_results(exp_names, output_file)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()

