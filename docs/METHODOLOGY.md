# Methodology

This guide explains how to use the tools in this repository to run PD disaggregation experiments.

## Overview

We provide three main experiment scripts that tell a coherent story:

1. **TP Baselines** (`experiments/tp-baselines.sh`): Understand TTFT vs TPOT trade-offs
2. **PD Ratio Exploration** (`experiments/pd-ratio-sweep.sh`): Test various P:D ratios and TP configs
3. **Network Impact** (`experiments/pack-vs-spread.sh`): Compare pack vs spread with network effects

Each script is self-contained with exact commands to reproduce results.

## Tools

### `launch_gptoss.py`

Deploys GPT-OSS-120B in different modes.

**Modes:**
- `--mode collocated`: Traditional serving (prefill + decode together)
- `--mode pd-pack`: PD with P and D on same node
- `--mode pd-spread`: PD with P and D on different nodes

**Key Parameters:**
```bash
# Collocated
--tp <N>              # Tensor parallelism degree
--num <N>             # Number of replicas

# PD modes
--p-num <N>           # Number of prefill replicas
--p-tp <N>            # Prefill TP degree
--d-num <N>           # Number of decode replicas
--d-tp <N>            # Decode TP degree
--use-ucx             # Use UCX backend (recommended)
--use-libfabric       # Use libfabric backend (had issues, see DEBUGGING.md)
```

**Examples:**
```bash
# Collocated TP=2, 4 replicas
python launch_gptoss.py --mode collocated --tp 2 --num 4

# PD pack: 1P-TP2, 2D-TP2
python launch_gptoss.py --mode pd-pack --p-num 1 --p-tp 2 --d-num 2 --d-tp 2 --use-ucx

# PD spread: 1P-TP4, 1D-TP4 (cross-node)
python launch_gptoss.py --mode pd-spread --p-num 1 --p-tp 4 --d-num 1 --d-tp 4 --use-ucx
```

### `run_bm.sh`

Runs benchmark sweeps against a deployed model.

**Parameters:**
```bash
-e|--exp-name <NAME>     # Experiment identifier
-t|--type <TYPE>         # concurrency or request-rate
-c|--concurrency <LIST>  # e.g., "4,8,16" or "all"
-r|--request-rate <LIST> # e.g., "1,2,4" or "all"
--itl <N>                # Input token length
--otl <N>                # Output token length
--mode <MODE>            # mixed, prefill-only, or decode-only
-s|--smoke               # Quick smoke test
```

**Examples:**
```bash
# Smoke test
./run_bm.sh --smoke

# Concurrency sweep (default: 4,8,16,32,48,64)
./run_bm.sh -e my_exp -t concurrency --itl 5000 --otl 250

# Request rate sweep with custom rates
./run_bm.sh -e rate_test -t request-rate -r "1,2,4,8" --itl 5000 --otl 250
```

**Benchmark Modes:**
- `mixed` (default): Standard ITL:OTL workload
- `prefill-only`: ITL:1 (isolate prefill)
- `decode-only`: 1:OTL (approximation, see limitations)

**Note**: Decode-only benchmarking via 1:OTL doesn't accurately model decode because it doesn't account for input length impact on generation speed. Proper decode-only support is tracked in [vllm#25986](https://github.com/vllm-project/vllm/pull/25986).

**Results Location:**
```
bm_results/{model}_itl{ITL}_otl{OTL}_{mode}_{config}_{exp_name}/
```

### `viz.py`

Visualizes and analyzes benchmark results.

**Usage:**
```bash
# Compare multiple experiments
python viz.py --exps bm_results/exp1 bm_results/exp2 bm_results/exp3

# Use normalized metrics (per-node throughput)
python viz.py --exps bm_results/exp1 bm_results/exp2 --use-normalized

# Change latency mode
python viz.py --exps bm_results/exp1 --latency-mode token  # Use TPOT
python viz.py --exps bm_results/exp1 --latency-mode first_token  # Use TTFT
python viz.py --exps bm_results/exp1 --latency-mode chunk --chunk-size 16  # Use chunk latency

# Use interactivity instead of latency
python viz.py --exps bm_results/exp1 --use-interactivity

# Show tables only (no plots)
python viz.py --exps bm_results/exp1 --no-plot

# Save plots to custom directory
python viz.py --exps bm_results/exp1 --plot-path custom_plots/
```

**Key Metrics:**
- **TTFT** (Time to First Token): Prefill latency
- **TPOT** (Time per Output Token): Decode latency
- **Throughput**: Tokens/sec (input, output, or total)
- **Normalized throughput**: Per-node or per-GPU for fair comparison

## Running the Three Main Experiments

### 1. TP Baselines

Establishes collocated baselines to understand TTFT vs TPOT trade-offs.

```bash
cd experiments
bash tp-baselines.sh
```

This runs:
- TP=1 (8 replicas)
- TP=2 (4 replicas)
- TP=4 (2 replicas)

**Expected observations:**
- TPOT: TP4 > TP2 > TP1 (decode improves with higher TP)
- TTFT: Non-monotonic (TP2 best at low concurrency, TP1 at high)
- Overall efficiency: TP4 > TP2 > TP1 (decode-dominated workload)

### 2. PD Ratio Exploration

Tests various P:D ratios and TP combinations.

```bash
cd experiments
bash pd-ratio-sweep.sh
```

This runs three parts:
- **Part 1**: D:TP4 configs (1P-TP4:1D-TP4, 1P-TP2:1D-TP4, 2P-TP2:1D-TP4)
- **Part 2**: D:TP2 ratios (3:1, 2:1, 1:1, 1:2, 1:3)
- **Part 3**: P:TP1, D:TP2 configs (1:1, 2:1, 4:1)

**Expected observations:**
- Optimal ratio shifts with throughput regime
- PD can beat collocated in token efficiency (especially TP4-TP4)
- Dynamic ratio adjustment matters

### 3. Network Impact

Compares pack vs spread with different network configurations.

```bash
cd experiments
bash pack-vs-spread.sh
```

This runs:
- Pack mode (same node, CUDA IPC)
- Spread with SRD (cross-node, good network)
- Spread with TCP (cross-node, forced bad network)

**Expected observations:**
- Pack ≈ Spread (SRD) when network is good
- Spread (TCP) << Pack shows network impact
- Proper network config is critical
