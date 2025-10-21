# Experiments and Findings

This directory contains experiment scripts and documented observations from PD disaggregation exploration.

## Quick Start

1. Set up environment: [../docs/SETUP.md](../docs/SETUP.md)
2. Run an experiment: `bash <experiment-name>.sh`
3. Results saved to `../bm_results/`
4. Visualize: `python ../viz.py --compare-dirs <dirs>`

## Available Experiments

- `collocated-tp-sweep.sh`: Test TP1, TP2, TP4 in collocated mode (baseline, 8 GPUs)
- `pd-ratio-sweep.sh`: Test different P:D ratios (3:1, 2:1, 1:1, 1:2, 1:3)
- `pack-vs-spread.sh`: Compare single-node vs multi-node PD (network impact)
- `network-bandwidth-test.sh`: Validate NIXL+UCX configuration

**Note on TP selection**: We focus on TP1, TP2, TP4 for baselines because they provide flexibility for both single-node and cross-node PD experiments with limited resources. TP8 would require all 8 GPUs per replica, making it expensive to explore various P:D ratios across multiple nodes.

## Key Findings

### 1. P:D Ratio Impact is Counter-Intuitive

**Question**: Does ITL:OTL ratio determine optimal P:D ratio?

**Observation**: No. Despite ITL:OTL = 5000:250 (20:1), decode-heavy ratios (1:2, 1:3) outperformed prefill-heavy ratios (2:1, 3:1).

**Details**:
- Prefill-heavy ratios (3:1, 2:1) were dominated by collocated baseline
- Decode-heavy ratios showed regime-dependent performance:
  - Low latency (TPOT < 50ms): 1:3 is optimal
  - Mid throughput (50-65k tokens/s): 1:2 reaches 12.7 RPS
  - High throughput (65-70k tokens/s): 1:1 reaches 13.1 RPS
  - Very high (>70k tokens/s): Collocated 4xTP2 wins

**Reproduce**: `bash pd-ratio-sweep.sh`

**Data**: `bm_results/gptoss_itl5000_otl250_mixed_*xtp2-*xtp2_*`

**Implications**:
- ITL:OTL doesn't predict P:D ratio
- Optimal ratio shifts with throughput/latency target
- Need dynamic scaling for different SLAs
- Decode becomes bottleneck despite prefill-heavy workload

---

### 2. TP Configurations: Prefill and Decode Have Different Optima

**Question**: How does TP degree affect prefill vs decode performance?

**Observation**: Decode improves monotonically with higher TP (TP4 > TP2 > TP1), but prefill has non-monotonic behavior (TP2 or TP1 optimal depending on concurrency).

**Details**:
- **Decode (TPOT)**: Higher TP is better (memory-bandwidth limited, benefits from spreading KV cache)
- **Prefill (TTFT)**: TP2 optimal at some concurrencies, TP1 at others (compute vs communication trade-off)
- **Overall efficiency**: Follows decode performance for this workload (TP4 > TP2 > TP1 in collocated)

**Reproduce**: `bash collocated-tp-sweep.sh`

**Data**: `bm_results/gptoss_itl5000_otl250_mixed_*xtp*_baseline_*`

**Implications**:
- Conflicting TP optima justify PD disaggregation
- Can't predict optimal PD config from collocated results
- TP1/TP2/TP4 provide flexibility for exploring various single-node and cross-node PD combinations
- With 16 GPUs (2 nodes), can test: 1P-TP2 + 1D-TP4, 4P-TP2 + 2D-TP4, 8P-TP1 + 4D-TP2, etc.
- Workload-dependent: This workload is decode-dominated

---

### 3. Network Layer Configuration is Critical

**Question**: How much does network layer affect multi-node PD?

**Observation**: Network configuration can make 5-10x performance difference. Proper UCX/SRD setup is essential.

**Details**:
- **Good config** (UCX with SRD): 70-90% of single-node performance
- **Bad config** (wrong transport): 5-10x slower
- **libfabric**: Data corruption in vLLM (despite passing micro-benchmarks)
- **DEBUG logging**: 5-10x slowdown

Network bandwidth (from micro-benchmark):
- Cross-node with SRD: 10-12 GB/s
- Cross-node with ud_verbs: < 1 GB/s
- Same-node (CUDA IPC): 4-5 GB/s

**Reproduce**: 
```bash
bash network-bandwidth-test.sh  # Validate setup
bash pack-vs-spread.sh          # Measure impact
```

**Data**: `bm_results/gptoss_itl5000_otl250_mixed_1xtp4-1xtp4_*`

**Implications**:
- Must validate network before benchmarking
- Use UCX, not libfabric (despite it being "official")
- Ensure SRD backend on EFA (check with network test)
- Never benchmark with DEBUG logging
- Micro-benchmarks insufficient - always validate with vLLM

---

### 4. When PD Doesn't Help

**Observation**: PD isn't universally better. At very high throughput (>70k tokens/s), collocated can outperform PD.

**Possible reasons**:
- PD overhead becomes significant
- Resource fragmentation hurts efficiency
- Simple scaling more effective at extreme scales
- KV cache transfer cost accumulates

**Implication**: PD is most beneficial for specific latency/throughput regimes, not a universal win.

---

## Experimental Design Considerations

### TP Selection Strategy

We focus on **TP1, TP2, TP4** for collocated baselines (using 8 GPUs per node) because:

1. **Flexibility for PD exploration**: With 16 total GPUs (2 nodes), these TP degrees enable numerous single-node and cross-node PD configurations:
   - **Single node**: 1P-TP2 + 1D-TP4, 2P-TP2 + 2D-TP2, 4P-TP1 + 2D-TP2
   - **Cross node**: 4P-TP2 + 2D-TP4, 8P-TP1 + 4D-TP2, 2P-TP4 + 2D-TP4

2. **Resource efficiency**: TP8 uses all 8 GPUs for a single replica, making it expensive to explore various P:D ratios (would need 16 GPUs per P or D instance).

3. **Coverage of key trade-offs**:
   - TP1: Maximum replica parallelism, lowest per-model memory
   - TP2: Balanced compute/communication
   - TP4: Higher memory bandwidth for decode, still allows 2 replicas per node

### Possible PD Configurations to Explore

With TP1/TP2/TP4 baselines and 16 GPUs, we can test:

**Single-node PD (8 GPUs):**
- 4P-TP1 + 2D-TP2 (4 + 4 GPUs)
- 2P-TP2 + 2D-TP2 (4 + 4 GPUs)
- 1P-TP2 + 1D-TP4 (2 + 4 GPUs, asymmetric)
- 1P-TP4 + 1D-TP4 (4 + 4 GPUs)

**Cross-node PD (16 GPUs):**
- 8P-TP1 (node 1) + 4D-TP2 (node 2)
- 4P-TP2 (node 1) + 4D-TP2 (node 2)
- 4P-TP2 (node 1) + 2D-TP4 (node 2)
- 2P-TP4 (node 1) + 2D-TP4 (node 2)

---

## Important Notes

### Current Constraints

- **vLLM limitation**: P:TPN, D:TPM requires N ≤ M (prefill TP can't exceed decode TP)
- **Decode-only benchmarking**: Using 1:OTL doesn't accurately model decode (see [vllm#25986](https://github.com/vllm-project/vllm/pull/25986))

### Setup-Specific

All findings from:
- **Hardware**: 2x p5.48xlarge (16x H100, EFA)
- **Model**: GPT-OSS-120B
- **Workload**: ITL:OTL = 5000:250
- **Software**: vLLM 0.11.0, NIXL 0.6.1+UCX, Ray 2.51.0

Different setups may show different patterns.

## Figures

Visualization files stored in `figures/` subdirectory. Generate with:

```bash
python viz.py --compare-dirs <dirs> --output experiments/figures/<name>.png
```

## Adding New Findings

When you discover something interesting:

1. Add a new section to this README with:
   - Question
   - Observation
   - Details
   - How to reproduce
   - Data location
   - Implications

2. Create a `.sh` script if it's a new experiment pattern

3. Generate supporting figures in `figures/`

Keep it simple - this is a living document that grows with exploration.
