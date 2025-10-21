#!/usr/bin/env python3
"""
Visualization script for benchmark results.
Analyzes and plots metrics from benchmark JSON files across experiments.
"""

import argparse
import json
from pathlib import Path
from typing import Dict, Any, Optional
import sys
import re

import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

# Set style for better-looking plots
sns.set_style("whitegrid")
plt.rcParams['figure.figsize'] = (10, 6)

# Configuration: Number of GPUs per node (baseline for normalization)
NUM_GPUS_PER_NODE = 8

# Default chunk size for chunk interactivity calculation
DEFAULT_CHUNK_SIZE = 16


def parse_experiment_config(exp_name: str) -> Optional[Dict[str, Any]]:
    """
    Parse experiment name to extract configuration parameters.
    
    Patterns supported:
    1. Prefill-Decode: itl<ITL>_otl<OTL>...<NP>x(tp|tpep)<PTP>-<ND>x(tp|tpep)<DTP>_
    2. Simple: itl<ITL>_otl<OTL>...<N>x(tp|tpep)<TP>
    
    Args:
        exp_name: Name of the experiment folder
        
    Returns:
        Dictionary with parsed config or None if parsing fails
    """
    config = {}
    
    # Extract ITL (input token length)
    itl_match = re.search(r'itl(\d+)', exp_name)
    if itl_match:
        config['itl'] = int(itl_match.group(1))
    
    # Extract OTL (output token length)
    otl_match = re.search(r'otl(\d+)', exp_name)
    if otl_match:
        config['otl'] = int(otl_match.group(1))
    
    # Try to extract prefill-decode configuration first: <NP>x(tp|tpep)<PTP>-<ND>x(tp|tpep)<DTP>
    # Pattern: 2xtp2-2xtp2 or p1xtp4-d1xtp4, etc. (optional letter prefix before numbers)
    pd_pattern = r'[a-z]?(\d+)x(tp|tpep)(\d+)-[a-z]?(\d+)x(tp|tpep)(\d+)'
    pd_match = re.search(pd_pattern, exp_name)
    
    if pd_match:
        config['num_prefill'] = int(pd_match.group(1))
        config['prefill_type'] = pd_match.group(2)
        config['prefill_tp'] = int(pd_match.group(3))
        config['num_decode'] = int(pd_match.group(4))
        config['decode_type'] = pd_match.group(5)
        config['decode_tp'] = int(pd_match.group(6))
        
        # Calculate total GPUs
        config['num_gpus'] = (config['num_prefill'] * config['prefill_tp'] + 
                              config['num_decode'] * config['decode_tp'])
    else:
        # Try simple pattern: <N>x(tp|tpep)<TP>
        # Pattern: 4xtp2, 8xtpep1, etc.
        simple_pattern = r'(\d+)x(tp|tpep)(\d+)'
        simple_match = re.search(simple_pattern, exp_name)
        
        if simple_match:
            num_replicas = int(simple_match.group(1))
            tp_type = simple_match.group(2)
            tp_degree = int(simple_match.group(3))
            
            config['num_replicas'] = num_replicas
            config['tp_type'] = tp_type
            config['tp_degree'] = tp_degree
            
            # Calculate total GPUs
            config['num_gpus'] = num_replicas * tp_degree
    
    return config if config else None


def format_config_summary(config: Optional[Dict[str, Any]]) -> str:
    """
    Format configuration dictionary into a readable summary string.
    
    Args:
        config: Configuration dictionary from parse_experiment_config
        
    Returns:
        Formatted string summary
    """
    if not config:
        return "N/A"
    
    lines = []
    if 'itl' in config:
        lines.append(f"ITL: {config['itl']}")
    if 'otl' in config:
        lines.append(f"OTL: {config['otl']}")
    
    # Prefill-decode configuration
    if 'num_prefill' in config:
        lines.append(f"Prefill: {config['num_prefill']}x{config['prefill_type']}{config['prefill_tp']}")
    if 'num_decode' in config:
        lines.append(f"Decode: {config['num_decode']}x{config['decode_type']}{config['decode_tp']}")
    
    # Simple configuration
    if 'num_replicas' in config:
        lines.append(f"Replicas: {config['num_replicas']}x{config['tp_type']}{config['tp_degree']}")
    
    if 'num_gpus' in config:
        lines.append(f"Total GPUs: {config['num_gpus']}")
    
    return " | ".join(lines)


def load_experiment_data(exp_folder: str) -> Dict[int, Dict[str, Any]]:
    """
    Load all JSON files from an experiment folder.
    
    Args:
        exp_folder: Path to experiment folder containing JSON result files
        
    Returns:
        Dictionary mapping concurrency levels to their metrics
    """
    exp_path = Path(exp_folder)
    if not exp_path.exists():
        print(f"Warning: Experiment folder '{exp_folder}' does not exist")
        return {}
    
    data = {}
    json_files = list(exp_path.glob("*.json"))
    
    if not json_files:
        print(f"Warning: No JSON files found in '{exp_folder}'")
        return {}
    
    for json_file in json_files:
        try:
            with open(json_file, 'r') as f:
                result = json.load(f)
                concurrency = result.get('max_concurrency')
                if concurrency is not None:
                    data[concurrency] = result
        except Exception as e:
            print(f"Error loading {json_file}: {e}")
    
    return data


def extract_metric(data: Dict[int, Dict[str, Any]], metric: str) -> Dict[int, float]:
    """
    Extract a specific metric from experiment data.
    
    Args:
        data: Dictionary mapping concurrency to metrics
        metric: Name of the metric to extract
        
    Returns:
        Dictionary mapping concurrency to metric value
    """
    result = {}
    for concurrency, metrics in data.items():
        if metric in metrics and metrics[metric] is not None:
            result[concurrency] = metrics[metric]
        else:
            print(f"Warning: Metric '{metric}' not found for concurrency {concurrency}")
    return result


def create_comparison_table(exp_data: Dict[str, Dict[int, Dict[str, Any]]], 
                            metric: str) -> pd.DataFrame:
    """
    Create a comparison table with concurrency as rows and experiments as columns.
    
    Args:
        exp_data: Dictionary mapping experiment names to their data
        metric: Metric to display in the table
        
    Returns:
        DataFrame with the comparison table
    """
    # Collect all unique concurrency levels
    all_concurrencies = set()
    for data in exp_data.values():
        all_concurrencies.update(data.keys())
    all_concurrencies = sorted(all_concurrencies)
    
    # Build the table
    table_data = {}
    for exp_name, data in exp_data.items():
        metric_values = extract_metric(data, metric)
        table_data[exp_name] = [metric_values.get(c, None) for c in all_concurrencies]
    
    df = pd.DataFrame(table_data, index=all_concurrencies)
    df.index.name = 'Concurrency'
    
    return df


def calculate_input_throughput(data: Dict[int, Dict[str, Any]]) -> Dict[int, float]:
    """
    Calculate input throughput (total_input_tokens / duration) for each concurrency.
    
    Args:
        data: Dictionary mapping concurrency to metrics
        
    Returns:
        Dictionary mapping concurrency to input throughput
    """
    result = {}
    for concurrency, metrics in data.items():
        total_input_tokens = metrics.get('total_input_tokens')
        duration = metrics.get('duration')
        if total_input_tokens is not None and duration is not None and duration > 0:
            result[concurrency] = total_input_tokens / duration
    return result


def calculate_latency(median_tpot_ms: float, 
                     median_ttft_ms: Optional[float] = None,
                     mode: str = 'chunk',
                     chunk_size: int = DEFAULT_CHUNK_SIZE) -> Optional[float]:
    """
    Calculate latency based on the specified mode.
    
    Args:
        median_tpot_ms: Median time per output token in milliseconds
        median_ttft_ms: Median time to first token in milliseconds (optional, needed for some modes)
        mode: Latency calculation mode ('chunk', 'first_token', 'token')
        chunk_size: Chunk size for chunk latency mode
        
    Returns:
        Latency in milliseconds, or None if calculation not possible
    """
    if mode == 'token':
        # Token latency: TPOT
        if median_tpot_ms <= 0:
            return None
        return median_tpot_ms
    
    elif mode == 'first_token':
        # First token latency: TTFT
        if median_ttft_ms is None or median_ttft_ms <= 0:
            return None
        return median_ttft_ms
    
    elif mode == 'chunk':
        # Chunk latency: (chunk_size - 1) * TPOT + TTFT
        if median_tpot_ms <= 0:
            return None
        if median_ttft_ms is None or median_ttft_ms <= 0:
            return None
        
        return (chunk_size - 1) * median_tpot_ms + median_ttft_ms
    
    return None


def normalize_throughput_to_node(value: float, num_gpus: int) -> float:
    """
    Normalize throughput value to single node baseline.
    
    Args:
        value: Original throughput value
        num_gpus: Number of GPUs used in the experiment
        
    Returns:
        Normalized throughput value (as if running on a single node)
    """
    if num_gpus <= 0:
        return value
    return value * (NUM_GPUS_PER_NODE / num_gpus)


def add_normalized_metrics(exp_data: Dict[str, Dict[int, Dict[str, Any]]],
                           exp_configs: Dict[str, Optional[Dict[str, Any]]]):
    """
    Add normalized throughput metrics to experiment data based on num_gpus.
    Normalizes to single node baseline for fair comparison.
    
    Args:
        exp_data: Dictionary mapping experiment names to their data
        exp_configs: Dictionary mapping experiment names to their parsed configs
    """
    for exp_name, data in exp_data.items():
        config = exp_configs.get(exp_name)
        if not config or 'num_gpus' not in config:
            continue
        
        num_gpus = config['num_gpus']
        
        for concurrency, metrics in data.items():
            # Normalize output_throughput
            if 'output_throughput' in metrics and metrics['output_throughput'] is not None:
                metrics['output_throughput_norm'] = normalize_throughput_to_node(
                    metrics['output_throughput'], num_gpus)
            
            # Normalize request_throughput
            if 'request_throughput' in metrics and metrics['request_throughput'] is not None:
                metrics['request_throughput_norm'] = normalize_throughput_to_node(
                    metrics['request_throughput'], num_gpus)
            
            # Calculate and normalize input_throughput if possible
            total_input_tokens = metrics.get('total_input_tokens')
            duration = metrics.get('duration')
            if total_input_tokens is not None and duration is not None and duration > 0:
                input_throughput = total_input_tokens / duration
                metrics['input_throughput_norm'] = normalize_throughput_to_node(
                    input_throughput, num_gpus)


def create_comprehensive_plot(exp_data: Dict[str, Dict[int, Dict[str, Any]]], 
                              exp_configs: Dict[str, Optional[Dict[str, Any]]],
                              save_path: str = None,
                              use_normalized: bool = True,
                              latency_mode: str = 'chunk',
                              chunk_size: int = DEFAULT_CHUNK_SIZE,
                              log_latency: bool = True,
                              log_concurrency: bool = True,
                              use_interactivity: bool = False,
                              throughput_metric: str = 'output'):
    """
    Create a comprehensive 1x3 subplot figure with:
    - Left: median_tpot_ms vs. concurrency
    - Middle: median_ttft_ms vs. concurrency
    - Right: throughput vs. latency/interactivity
    
    Args:
        exp_data: Dictionary mapping experiment names to their data
        exp_configs: Dictionary mapping experiment names to their parsed configs
        save_path: Path to save the plot (optional)
        use_normalized: If True, use normalized throughput metrics (default: True)
        latency_mode: Mode for calculating latency ('chunk', 'first_token', 'token')
        chunk_size: Chunk size for chunk latency mode
        log_latency: If True, use logarithmic scale for latency/interactivity x-axis on throughput plot
        log_concurrency: If True, use logarithmic scale for latency y-axis on latency-concurrency plots
        use_interactivity: If True, use interactivity (1000/tpot) instead of latency on x-axis for throughput plot
        throughput_metric: Which throughput to plot ('input', 'output', 'total')
    """
    fig, axes = plt.subplots(1, 3, figsize=(20, 6))
    
    # Color palette for experiments
    colors = plt.cm.tab10(range(len(exp_data)))
    
    # Left: median_tpot_ms vs. concurrency
    ax1 = axes[0]
    for (exp_name, data), color in zip(exp_data.items(), colors):
        metric_values = extract_metric(data, 'median_tpot_ms')
        if metric_values:
            concurrencies = sorted(metric_values.keys())
            values = [metric_values[c] for c in concurrencies]
            ax1.plot(concurrencies, values, marker='o', linewidth=2, 
                    markersize=8, label=exp_name, color=color)
    
    ax1.set_xlabel('Concurrency', fontsize=11, fontweight='bold')
    ax1.set_ylabel('TPOT Median (ms)', fontsize=11, fontweight='bold')
    ax1.set_title('TPOT Median vs Concurrency', fontsize=12, fontweight='bold')
    ax1.legend(fontsize=9, framealpha=0.9)
    ax1.grid(True, alpha=0.3)
    if log_concurrency:
        ax1.set_yscale('log')
    
    # Middle: median_ttft_ms vs. concurrency
    ax2 = axes[1]
    for (exp_name, data), color in zip(exp_data.items(), colors):
        metric_values = extract_metric(data, 'median_ttft_ms')
        if metric_values:
            concurrencies = sorted(metric_values.keys())
            values = [metric_values[c] for c in concurrencies]
            ax2.plot(concurrencies, values, marker='o', linewidth=2, 
                    markersize=8, label=exp_name, color=color)
    
    ax2.set_xlabel('Concurrency', fontsize=11, fontweight='bold')
    ax2.set_ylabel('TTFT Median (ms)', fontsize=11, fontweight='bold')
    ax2.set_title('TTFT Median vs Concurrency', fontsize=12, fontweight='bold')
    ax2.legend(fontsize=9, framealpha=0.9)
    ax2.grid(True, alpha=0.3)
    if log_concurrency:
        ax2.set_yscale('log')
    
    # Right: throughput vs. latency/interactivity
    ax3 = axes[2]
    req_throughput_metric = 'request_throughput_norm' if use_normalized else 'request_throughput'
    
    # Determine which throughput metric to use
    if throughput_metric == 'output':
        metric_name = 'output_throughput_norm' if use_normalized else 'output_throughput'
        ylabel_name = 'Output Throughput'
    elif throughput_metric == 'input':
        metric_name = 'input_throughput_norm' if use_normalized else 'input_throughput'
        ylabel_name = 'Input Throughput'
    elif throughput_metric == 'total':
        metric_name = None  # Will calculate as input + output
        ylabel_name = 'Total Throughput'
    else:
        raise ValueError(f"Invalid throughput_metric: {throughput_metric}. Must be 'input', 'output', or 'total'")
    
    for (exp_name, data), color in zip(exp_data.items(), colors):
        # Get or calculate throughput values
        if metric_name and metric_name.endswith('_norm'):
            # Use pre-calculated normalized metric
            throughput_values = extract_metric(data, metric_name)
        elif throughput_metric == 'output':
            throughput_values = extract_metric(data, 'output_throughput')
        elif throughput_metric == 'input':
            if use_normalized:
                throughput_values = extract_metric(data, 'input_throughput_norm')
            else:
                throughput_values = calculate_input_throughput(data)
        elif throughput_metric == 'total':
            # Calculate total as input + output
            output_metric = 'output_throughput_norm' if use_normalized else 'output_throughput'
            input_metric = 'input_throughput_norm' if use_normalized else 'input_throughput'
            
            output_values = extract_metric(data, output_metric)
            if use_normalized:
                input_values = extract_metric(data, input_metric)
            else:
                input_values = calculate_input_throughput(data)
            
            # Combine input and output
            throughput_values = {}
            for c in set(output_values.keys()) & set(input_values.keys()):
                throughput_values[c] = output_values[c] + input_values[c]
        
        median_tpot = extract_metric(data, 'median_tpot_ms')
        median_ttft = extract_metric(data, 'median_ttft_ms')
        request_throughput = extract_metric(data, req_throughput_metric)
        
        if throughput_values and median_tpot:
            common_concurrencies = set(throughput_values.keys()) & set(median_tpot.keys())
            common_concurrencies = sorted(common_concurrencies)
            
            x_values = []
            values = []
            req_throughputs = []
            
            for c in common_concurrencies:
                if use_interactivity:
                    # Use interactivity: 1000 / tpot
                    if median_tpot[c] > 0:
                        x_val = 1000.0 / median_tpot[c]
                    else:
                        continue
                else:
                    # Use latency
                    ttft = median_ttft.get(c) if median_ttft else None
                    x_val = calculate_latency(
                        median_tpot[c], ttft, latency_mode, chunk_size)
                    
                    if x_val is None:
                        continue
                
                x_values.append(x_val)
                values.append(throughput_values[c])
                req_throughputs.append(request_throughput.get(c, 0))
            
            if x_values and values:
                ax3.plot(x_values, values, marker='o', linewidth=2, 
                        markersize=8, label=exp_name, color=color)
                
                # Annotate with request_throughput
                for x, y, rps in zip(x_values, values, req_throughputs):
                    ax3.annotate(f'{rps:.1f}', 
                               xy=(x, y), 
                               xytext=(5, 5), 
                               textcoords='offset points',
                               fontsize=8,
                               alpha=0.7)
    
    # Set axis labels based on mode
    if use_interactivity:
        xlabel = 'Interactivity (token/s/usr)'
        title_suffix = 'Interactivity'
    elif latency_mode == 'token':
        xlabel = 'TPOT (ms)'
        title_suffix = 'TPOT'
    elif latency_mode == 'first_token':
        xlabel = 'TTFT (ms)'
        title_suffix = 'TTFT'
    else:  # chunk
        xlabel = f'Chunk Latency (ms, size={chunk_size})'
        title_suffix = 'Chunk Latency'
    
    ax3.set_xlabel(xlabel, fontsize=11, fontweight='bold')
    ylabel = f'{ylabel_name} (token/s/node)' if use_normalized else f'{ylabel_name} (token/s)'
    ax3.set_ylabel(ylabel, fontsize=11, fontweight='bold')
    ax3.set_title(f'{ylabel_name} vs {title_suffix}', fontsize=12, fontweight='bold')
    ax3.legend(fontsize=9, framealpha=0.9)
    ax3.grid(True, alpha=0.3)
    if log_latency:
        ax3.set_xscale('log')
    
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        print(f"Saved comprehensive plot to: {save_path}")
    else:
        plt.show()
    
    plt.close()


def main():
    parser = argparse.ArgumentParser(
        description='Visualize and compare benchmark results across experiments',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    parser.add_argument(
        '--exps',
        nargs='+',
        required=True,
        help='List of experiment folders to compare'
    )
    
    parser.add_argument(
        '--show-tables',
        action=argparse.BooleanOptionalAction,
        default=True,
        help='Show comparison tables (use --no-show-tables to disable)'
    )
    
    parser.add_argument(
        '--plot',
        action=argparse.BooleanOptionalAction,
        default=True,
        help='Create comprehensive plot (use --no-plot to disable)'
    )
    
    parser.add_argument(
        '--plot-path',
        type=str,
        default='plots',
        help='Folder where plots will be saved'
    )
    
    parser.add_argument(
        '--use-normalized',
        action=argparse.BooleanOptionalAction,
        default=True,
        help='Use normalized throughput metrics (single node baseline) in plots (use --no-use-normalized to disable)'
    )
    
    parser.add_argument(
        '--latency-mode',
        type=str,
        choices=['chunk', 'first_token', 'token'],
        default='token',
        help='Mode for calculating latency: chunk ((chunk_size-1)*tpot+ttft), first_token (ttft), token (tpot)'
    )
    
    parser.add_argument(
        '--chunk-size',
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        help=f'Chunk size for chunk latency mode (default: {DEFAULT_CHUNK_SIZE})'
    )
    
    parser.add_argument(
        '--log-latency',
        action=argparse.BooleanOptionalAction,
        default=True,
        help='Use logarithmic scale for latency x-axis on throughput-latency plots (use --no-log-latency to disable)'
    )
    
    parser.add_argument(
        '--log-concurrency',
        action=argparse.BooleanOptionalAction,
        default=True,
        help='Use logarithmic scale for latency y-axis on latency-concurrency plots (use --no-log-concurrency to disable)'
    )
    
    parser.add_argument(
        '--use-interactivity',
        action=argparse.BooleanOptionalAction,
        default=False,
        help='Use interactivity (1000/tpot) instead of latency on x-axis for throughput plot (use --use-interactivity to enable)'
    )
    
    parser.add_argument(
        '--throughput-metric',
        type=str,
        choices=['input', 'output', 'total'],
        default='output',
        help='Which throughput metric to plot: input (prefill), output (decode), or total (input+output)'
    )
    
    args = parser.parse_args()
    
    # Load data from all experiments
    print("Loading experiment data...")
    exp_data = {}
    for exp_folder in args.exps:
        exp_name = Path(exp_folder).name
        data = load_experiment_data(exp_folder)
        if data:
            exp_data[exp_name] = data
            print(f"  Loaded {len(data)} concurrency levels from '{exp_name}'")
        else:
            print(f"  Warning: No data loaded from '{exp_folder}'")
    
    if not exp_data:
        print("Error: No experiment data loaded. Exiting.")
        sys.exit(1)
    
    print(f"\nNumber of experiments: {len(exp_data)}")
    
    # Parse and display experiment configurations
    print("\n" + "="*80)
    print("EXPERIMENT CONFIGURATIONS")
    print("="*80)
    exp_configs = {}
    for exp_name in exp_data.keys():
        config = parse_experiment_config(exp_name)
        exp_configs[exp_name] = config
        print(f"\n{exp_name}:")
        if config:
            for key, value in config.items():
                print(f"  {key}: {value}")
        else:
            print("  Could not parse configuration")
    print()
    
    # Add normalized metrics to experiment data
    print(f"Normalizing throughput metrics to single node ({NUM_GPUS_PER_NODE} GPUs) baseline...")
    add_normalized_metrics(exp_data, exp_configs)
    print("Done.")
    
    # Show comparison tables for key metrics
    if args.show_tables:
        print("\n" + "="*80)
        print("COMPARISON TABLES - ORIGINAL METRICS")
        print("="*80)
        
        metrics_to_show = [
            ('median_tpot_ms', 'TPOT Median (ms)'),
            ('median_ttft_ms', 'TTFT Median (ms)'),
            ('output_throughput', 'Output Throughput (token/s)'),
            ('request_throughput', 'Request Throughput (req/s)')
        ]
        
        for metric, title in metrics_to_show:
            print(f"\n{title}:")
            print("-" * 80)
            table = create_comparison_table(exp_data, metric)
            print(table.to_string())
        
        print("\n" + "="*80)
        print("COMPARISON TABLES - NORMALIZED TO SINGLE NODE BASELINE")
        print("="*80)
        
        normalized_metrics = [
            ('output_throughput_norm', 'Output Throughput Normalized (token/s/node)'),
            ('request_throughput_norm', 'Request Throughput Normalized (req/s/node)'),
            ('input_throughput_norm', 'Input Throughput Normalized (token/s/node)')
        ]
        
        for metric, title in normalized_metrics:
            print(f"\n{title}:")
            print("-" * 80)
            table = create_comparison_table(exp_data, metric)
            print(table.to_string())
        print()
    
    # Create comprehensive plot
    if args.plot:
        plot_dir = Path(args.plot_path)
        plot_dir.mkdir(parents=True, exist_ok=True)
        print(f"\nPlots will be saved to: {plot_dir.absolute()}")
        
        norm_text = "with normalized metrics" if args.use_normalized else "with raw metrics"
        print(f"\nGenerating comprehensive plot {norm_text}...")
        
        if args.use_interactivity:
            print(f"X-axis mode: Interactivity (1000/tpot)")
        else:
            print(f"X-axis mode: Latency ({args.latency_mode}" + 
                  (f", chunk_size={args.chunk_size})" if args.latency_mode == 'chunk' else ")"))
        
        print(f"Log scale - latency/interactivity: {args.log_latency}, concurrency: {args.log_concurrency}")
        print(f"Throughput metric: {args.throughput_metric}")
        plot_path = plot_dir / "comprehensive_analysis.png"
        create_comprehensive_plot(
            exp_data,
            exp_configs,
            str(plot_path), 
            use_normalized=args.use_normalized,
            latency_mode=args.latency_mode,
            chunk_size=args.chunk_size,
            log_latency=args.log_latency,
            log_concurrency=args.log_concurrency,
            use_interactivity=args.use_interactivity,
            throughput_metric=args.throughput_metric
        )
    
    print("\n" + "="*80)
    print("Analysis complete!")
    print("="*80)


if __name__ == "__main__":
    main()

