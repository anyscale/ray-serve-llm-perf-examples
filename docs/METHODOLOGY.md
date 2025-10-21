# Methodology

This document explains how to design and run PD disaggregation experiments using the tools in this repository.

## Experimental Design Philosophy

The goal is to systematically explore how different configurations affect the throughput vs latency trade-off for specific workloads. Key dimensions to explore:

1. **Deployment modes**: Collocated vs PD-pack vs PD-spread
2. **Parallelism**: Tensor Parallelism (TP) degrees for prefill and decode
3. **Replica ratios**: P:D ratio (e.g., 1:1, 1:2, 2:1)
4. **Workloads**: ITL (Input Token Length) and OTL (Output Token Length) combinations
5. **Network backends**: UCX vs libfabric (for multi-node)

## Tools Overview

### `launch_gptoss.py`

Unified launcher for deploying GPT-OSS-120B in different modes.

**Deployment Modes:**

- `--mode collocated`: Traditional unified prefill+decode on same replicas
- `--mode pd-pack`: PD with prefill and decode scheduled on same node (single-node PD)
- `--mode pd-spread`: PD with prefill and decode on different nodes (multi-node PD)

**Key Parameters:**

- `--tp <N>`: Tensor parallelism degree for collocated mode
- `--p-num <N>`: Number of prefill replicas (PD modes)
- `--p-tp <N>`: TP degree for prefill replicas
- `--d-num <N>`: Number of decode replicas (PD modes)
- `--d-tp <N>`: TP degree for decode replicas
- `--use-ucx`: Use UCX backend for NIXL
- `--use-libfabric`: Use libfabric backend for NIXL

**Example:**

```bash
# Collocated baseline with TP=2, 4 replicas
python launch_gptoss.py --mode collocated --tp 2 --num-replicas 4

# PD single-node: 2 prefill (TP=1) + 4 decode (TP=2)
python launch_gptoss.py --mode pd-pack --p-num 2 --p-tp 1 --d-num 4 --d-tp 2 --use-ucx

# PD multi-node: spread prefill and decode across nodes
python launch_gptoss.py --mode pd-spread --p-num 1 --p-tp 4 --d-num 1 --d-tp 4 --use-ucx
```

### `run_bm.sh`

Benchmark runner that executes concurrency or request rate sweeps.

**Key Parameters:**

- `-e|--exp-name <NAME>`: Experiment identifier
- `-t|--type <concurrency|request-rate>`: Benchmark sweep type
- `-c|--concurrency <LIST>`: Concurrency values (e.g., "4,8,16" or "all")
- `-r|--request-rate <LIST>`: Request rate values (e.g., "1,2,4" or "all")
- `--itl <N>`: Input token length
- `--otl <N>`: Output token length
- `--mode <mixed|prefill-only|decode-only>`: Benchmark mode
- `-s|--smoke`: Run smoke test only

**Benchmark Modes:**

- `mixed`: Standard ITL:OTL workload (default)
- `prefill-only`: ITL:1 (measure prefill performance)
- `decode-only`: 1:OTL (approximation, see limitations below)

**Example:**

```bash
# Run concurrency sweep for ITL=5000, OTL=250
./run_bm.sh -e my_experiment -t concurrency --itl 5000 --otl 250

# Run request rate sweep with custom rates
./run_bm.sh -e rate_test -t request-rate -r "1,2,4,8" --itl 5000 --otl 250

# Smoke test to verify deployment
./run_bm.sh --smoke
```

**Results Location:**

Benchmarks save results to `bm_results/<auto_generated_name>_<exp_name>/`

### `viz.py`

Visualization tool for analyzing and plotting benchmark results.

**Usage:**

```bash
# Analyze a single experiment
python viz.py --result-dir bm_results/gptoss_itl5000_otl250_mixed_4xtp2

# Compare multiple experiments
python viz.py --compare-dirs bm_results/exp1 bm_results/exp2 bm_results/exp3

# Generate specific plot types
python viz.py --result-dir bm_results/exp1 --plot-type throughput-vs-tpot
```

**Key Metrics:**

- **TTFT** (Time to First Token): Prefill latency
- **TPOT** (Time per Output Token): Decode latency
- **Throughput**: Tokens/sec (input, output, or total)
- **Normalized throughput**: Per-node or per-GPU basis

## Designing a Systematic Experiment

### Step 1: Define Your Baseline

Start with collocated deployments to establish baseline performance:

```bash
# Test different TP degrees
python launch_gptoss.py --mode collocated --tp 1 --num-replicas 8
./run_bm.sh -e baseline_tp1 -t concurrency --itl 5000 --otl 250

python launch_gptoss.py --mode collocated --tp 2 --num-replicas 4
./run_bm.sh -e baseline_tp2 -t concurrency --itl 5000 --otl 250

# Continue for TP=4, TP=8...
```

### Step 2: Explore PD Configurations

Test PD with different P:D ratios and TP combinations:

```bash
# Single-node: 1 prefill (TP=2) + 2 decode (TP=2)
python launch_gptoss.py --mode pd-pack --p-num 1 --p-tp 2 --d-num 2 --d-tp 2
./run_bm.sh -e pd_1p2-2d2 -t concurrency --itl 5000 --otl 250

# Vary the ratio
python launch_gptoss.py --mode pd-pack --p-num 2 --p-tp 2 --d-num 2 --d-tp 2
./run_bm.sh -e pd_2p2-2d2 -t concurrency --itl 5000 --otl 250
```

### Step 3: Test Network Impact (Multi-Node)

Compare single-node vs multi-node PD:

```bash
# Pack (single-node)
python launch_gptoss.py --mode pd-pack --p-num 1 --p-tp 4 --d-num 1 --d-tp 4 --use-ucx
./run_bm.sh -e pd_pack_1p4-1d4 -t concurrency --itl 5000 --otl 250

# Spread (multi-node)
python launch_gptoss.py --mode pd-spread --p-num 1 --p-tp 4 --d-num 1 --d-tp 4 --use-ucx
./run_bm.sh -e pd_spread_1p4-1d4 -t concurrency --itl 5000 --otl 250
```

### Step 4: Analyze and Compare

```bash
# Generate comparison plots
python viz.py --compare-dirs \
  bm_results/baseline_tp2 \
  bm_results/pd_1p2-2d2 \
  bm_results/pd_2p2-2d2
```

## Reproducibility Checklist

When documenting an experiment, include:

- [ ] Exact command used for deployment (`launch_gptoss.py`)
- [ ] Exact command used for benchmarking (`run_bm.sh`)
- [ ] Hardware configuration (node count, GPU type, networking)
- [ ] Software versions (vLLM, NIXL, Ray)
- [ ] Workload parameters (ITL, OTL, concurrency/rate values)
- [ ] Result location in `bm_results/`
- [ ] Generated figures
- [ ] Any environment variables or special configuration

## Important Notes

### Decode-Only Benchmarking Limitation

The current `decode-only` mode (1:OTL) doesn't realistically model decode-only performance because it doesn't account for the impact of input token length on generation speed. Proper decode-only benchmarking is being developed in [vllm#25986](https://github.com/vllm-project/vllm/pull/25986).

### Current vLLM Constraint

vLLM doesn't currently allow P:TPN, D:TPM where N > M. This means prefill can't have a higher TP degree than decode. This limitation may be removed in future versions.

### Batching Configuration

The base configuration sets `stream_batching_interval_ms: 0` to reduce latency variance during benchmarking. Increasing this value would improve average latency but introduce more variance.

## Next Steps

After running experiments, document your findings in `results/findings/` following the template in that directory.

