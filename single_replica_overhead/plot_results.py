#!/usr/bin/env python3
"""
Plotting script for single replica overhead benchmark results.
Plots tpot, ttft, and output throughput vs concurrency for baseline, oss, and turbo.
"""

import json
import sys
import os
import re
from pathlib import Path
import matplotlib.pyplot as plt


def load_results(results_dir):
    """Load all concurrency results from a results directory."""
    results = {}
    
    # Look for part1 subdirectory
    part1_dir = os.path.join(results_dir, 'part1')
    if not os.path.isdir(part1_dir):
        print(f"Warning: part1 directory not found in {results_dir}", file=sys.stderr)
        return None
    
    for json_file in Path(part1_dir).glob('conc*.json'):
        try:
            with open(json_file, 'r') as f:
                data = json.load(f)
                # Extract concurrency from filename (e.g., conc32.json -> 32)
                conc_match = re.search(r'conc(\d+)', json_file.name)
                if conc_match:
                    conc = int(conc_match.group(1))
                    results[conc] = {
                        'tpot_ms': data.get('mean_tpot_ms'),
                        'ttft_ms': data.get('mean_ttft_ms'),
                        'output_throughput': data.get('output_throughput'),
                    }
        except Exception as e:
            print(f"Warning: Failed to load {json_file}: {e}", file=sys.stderr)
    
    return results if results else None


def plot_results(results_base_dir='results', output_file=None):
    """Plot tpot, ttft, and output throughput vs concurrency for baseline, oss, and turbo."""
    
    # Load results from each configuration
    configs = {
        'baseline': os.path.join(results_base_dir, 'vllm-baseline'),
        'oss': os.path.join(results_base_dir, 'oss'),
        'turbo': os.path.join(results_base_dir, 'turbo'),
    }
    
    data_by_config = {}
    for config_name, config_path in configs.items():
        if not os.path.isdir(config_path):
            print(f"Warning: Configuration directory not found: {config_path}", file=sys.stderr)
            continue
        
        results = load_results(config_path)
        if results:
            data_by_config[config_name] = results
    
    if not data_by_config:
        print("Error: No valid results found to plot", file=sys.stderr)
        return False
    
    # Create figure with three subplots
    fig, axes = plt.subplots(1, 3, figsize=(18, 5))
    
    # Define colors and markers for each configuration
    style_map = {
        'baseline': {'color': 'blue', 'marker': 'o', 'label': 'vLLM Baseline'},
        'oss': {'color': 'green', 'marker': 's', 'label': 'OSS'},
        'turbo': {'color': 'red', 'marker': '^', 'label': 'Turbo'},
    }
    
    # Plot 1: TPOT (Time Per Output Token) vs Concurrency
    ax1 = axes[0]
    for config_name, results in data_by_config.items():
        if config_name not in style_map:
            continue
        style = style_map[config_name]
        concurrency = sorted(results.keys())
        tpot_values = [results[c]['tpot_ms'] for c in concurrency if results[c]['tpot_ms'] is not None]
        concurrency_filtered = [c for c in concurrency if results[c]['tpot_ms'] is not None]
        if tpot_values:
            ax1.plot(concurrency_filtered, tpot_values, 
                    marker=style['marker'], label=style['label'], 
                    color=style['color'], linewidth=2, markersize=6)
    
    ax1.set_xlabel('Concurrency', fontsize=12)
    ax1.set_ylabel('Mean TPOT (ms)', fontsize=12)
    ax1.set_title('Time Per Output Token vs Concurrency', fontsize=14, fontweight='bold')
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc='best')
    
    # Plot 2: TTFT (Time To First Token) vs Concurrency
    ax2 = axes[1]
    for config_name, results in data_by_config.items():
        if config_name not in style_map:
            continue
        style = style_map[config_name]
        concurrency = sorted(results.keys())
        ttft_values = [results[c]['ttft_ms'] for c in concurrency if results[c]['ttft_ms'] is not None]
        concurrency_filtered = [c for c in concurrency if results[c]['ttft_ms'] is not None]
        if ttft_values:
            ax2.plot(concurrency_filtered, ttft_values, 
                    marker=style['marker'], label=style['label'], 
                    color=style['color'], linewidth=2, markersize=6)
    
    ax2.set_xlabel('Concurrency', fontsize=12)
    ax2.set_ylabel('Mean TTFT (ms)', fontsize=12)
    ax2.set_title('Time To First Token vs Concurrency', fontsize=14, fontweight='bold')
    ax2.grid(True, alpha=0.3)
    ax2.legend(loc='best')
    
    # Plot 3: Output Throughput vs Concurrency
    ax3 = axes[2]
    for config_name, results in data_by_config.items():
        if config_name not in style_map:
            continue
        style = style_map[config_name]
        concurrency = sorted(results.keys())
        throughput_values = [results[c]['output_throughput'] for c in concurrency if results[c]['output_throughput'] is not None]
        concurrency_filtered = [c for c in concurrency if results[c]['output_throughput'] is not None]
        if throughput_values:
            ax3.plot(concurrency_filtered, throughput_values, 
                    marker=style['marker'], label=style['label'], 
                    color=style['color'], linewidth=2, markersize=6)
    
    ax3.set_xlabel('Concurrency', fontsize=12)
    ax3.set_ylabel('Output Throughput (tokens/sec)', fontsize=12)
    ax3.set_title('Output Throughput vs Concurrency', fontsize=14, fontweight='bold')
    ax3.grid(True, alpha=0.3)
    ax3.legend(loc='best')
    
    plt.tight_layout()
    
    if output_file:
        plt.savefig(output_file, dpi=150, bbox_inches='tight')
        print(f"Plot saved to: {output_file}")
    else:
        plt.show()
    
    return True


def main():
    if len(sys.argv) > 1 and (sys.argv[1] == '--help' or sys.argv[1] == '-h'):
        print("Usage: plot_results.py [RESULTS_DIR] [--output OUTPUT_FILE]")
        print("  RESULTS_DIR: Base directory containing vllm-baseline, oss, and turbo subdirectories")
        print("               (default: 'results')")
        print("  --output, -o: Output file path for the plot (default: display interactively)")
        print("")
        print("Example: plot_results.py results --output comparison.png")
        sys.exit(0)
    
    results_dir = 'results'
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
            results_dir = sys.argv[i]
            i += 1
    
    success = plot_results(results_dir, output_file)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()

