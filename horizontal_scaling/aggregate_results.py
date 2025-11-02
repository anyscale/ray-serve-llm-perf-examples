#!/usr/bin/env python3
"""
Script to aggregate benchmark results from multiple part directories.
Aggregates results by summing throughput metrics and averaging latency metrics.
"""

import json
import sys
import os
import argparse
import re
from pathlib import Path
from statistics import mean


def aggregate_files(files, output_file):
    """Aggregate multiple JSON result files into a single result."""
    # Read all JSON files
    results = []
    for file_path in files:
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
                results.append(data)
        except Exception as e:
            print(f"Error reading {file_path}: {e}", file=sys.stderr)
            return False

    if not results:
        print("Error: No valid results to aggregate", file=sys.stderr)
        return False

    # Initialize aggregated result with metadata from first file
    aggregated = {
        'date': results[0].get('date'),
        'endpoint_type': results[0].get('endpoint_type'),
        'backend': results[0].get('backend'),
        'label': results[0].get('label'),
        'model_id': results[0].get('model_id'),
        'tokenizer_id': results[0].get('tokenizer_id'),
        'num_prompts': results[0].get('num_prompts'),
        'request_rate': results[0].get('request_rate'),
        'burstiness': results[0].get('burstiness'),
        'max_concurrency': results[0].get('max_concurrency'),
    }

    # Fields to sum (throughput and counts)
    sum_fields = [
        'completed',
        'total_input_tokens',
        'total_output_tokens',
        'request_throughput',
        'output_throughput',
        'total_token_throughput',
        'max_output_tokens_per_s',
        'max_concurrent_requests',
        'num_prompts',
    ]

    # Fields to average (latency and time metrics)
    avg_fields = [
        'duration',
        'mean_ttft_ms',
        'median_ttft_ms',
        'std_ttft_ms',
        'p99_ttft_ms',
        'mean_tpot_ms',
        'median_tpot_ms',
        'std_tpot_ms',
        'p99_tpot_ms',
        'mean_itl_ms',
        'median_itl_ms',
        'std_itl_ms',
        'p99_itl_ms',
    ]

    # Special fields (from first)
    special_fields = ['request_goodput']

    # Sum throughput and count fields
    for field in sum_fields:
        values = [r.get(field) for r in results if r.get(field) is not None]
        if values:
            aggregated[field] = sum(values)

    # Average latency and time fields
    for field in avg_fields:
        values = [r.get(field) for r in results if r.get(field) is not None]
        if values:
            aggregated[field] = mean(values)

    # Handle special fields
    for field in special_fields:
        # For other special fields, take from first file
        aggregated[field] = results[0].get(field)

    # Write aggregated result
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, 'w') as f:
        json.dump(aggregated, f, indent=2)

    print(f"  Aggregated {len(results)} files into {output_file}")
    return True


def detect_part_directories(exp_name):
    """Detect all partX directories in the experiment directory."""
    if not os.path.isdir(exp_name):
        return []
    
    part_dirs = []
    part_pattern = re.compile(r'^part(\d+)$')
    
    for item in os.listdir(exp_name):
        item_path = os.path.join(exp_name, item)
        if os.path.isdir(item_path):
            match = part_pattern.match(item)
            if match:
                part_num = int(match.group(1))
                part_dirs.append((part_num, item))
    
    # Sort by part number
    part_dirs.sort(key=lambda x: x[0])
    return [name for _, name in part_dirs]


def main():
    parser = argparse.ArgumentParser(
        description='Aggregate benchmark results from multiple part directories'
    )
    parser.add_argument('exp_name', help='Experiment name (directory path)')
    parser.add_argument('--num-runs', type=int, default=None,
                       help='Number of parallel runs (auto-detected if not specified)')
    
    args = parser.parse_args()
    
    exp_name = args.exp_name
    aggregated_dir = os.path.join(exp_name, 'all-parts')
    
    # Check if experiment directory exists
    if not os.path.isdir(exp_name):
        print(f"Error: Experiment directory '{exp_name}' does not exist", file=sys.stderr)
        sys.exit(1)
    
    # Detect part directories
    part_dirs = detect_part_directories(exp_name)
    
    if not part_dirs:
        print(f"Error: No part directories found in '{exp_name}'", file=sys.stderr)
        print("Expected directories in format: part1, part2, part3, ...", file=sys.stderr)
        sys.exit(1)
    
    # Use detected number of runs or override with command-line argument
    if args.num_runs is not None:
        num_runs = args.num_runs
        if num_runs > len(part_dirs):
            print(f"Warning: Specified {num_runs} runs but only {len(part_dirs)} part directories found", file=sys.stderr)
    else:
        num_runs = len(part_dirs)
    
    # Create aggregated results directory
    os.makedirs(aggregated_dir, exist_ok=True)
    
    print("==========================================")
    print(f"Aggregating results from {num_runs} runs")
    print(f"  Detected part directories: {', '.join(part_dirs[:num_runs])}")
    print(f"  Destination: {aggregated_dir}")
    print("==========================================")
    
    # Find all unique result files across all part directories
    # Use the first part directory to get the list of result files
    first_part_dir = os.path.join(exp_name, part_dirs[0])
    if not os.path.isdir(first_part_dir):
        print(f"Error: Part directory '{first_part_dir}' does not exist", file=sys.stderr)
        sys.exit(1)
    
    result_files = set()
    for file_path in Path(first_part_dir).glob('*.json'):
        result_files.add(file_path.name)
    
    if not result_files:
        print(f"Error: No result files found in {first_part_dir}", file=sys.stderr)
        sys.exit(1)
    
    # Process each result file
    success_count = 0
    for result_file in sorted(result_files):
        print(f"Aggregating {result_file}...")
        
        # Collect all matching files from all part directories
        files_to_aggregate = []
        for part_dir in part_dirs[:num_runs]:
            part_file = os.path.join(exp_name, part_dir, result_file)
            if os.path.isfile(part_file):
                files_to_aggregate.append(part_file)
        
        if not files_to_aggregate:
            print(f"  Warning: No files found for {result_file}, skipping...")
            continue
        
        output_file = os.path.join(aggregated_dir, result_file)
        if aggregate_files(files_to_aggregate, output_file):
            success_count += 1
        else:
            print(f"  Error: Failed to aggregate {result_file}")
    
    print("")
    print("==========================================")
    print("Aggregation completed!")
    print(f"Aggregated results saved to: {aggregated_dir}")
    print(f"Successfully aggregated {success_count} result files")
    print("==========================================")
    
    if success_count == 0:
        sys.exit(1)


if __name__ == '__main__':
    main()

