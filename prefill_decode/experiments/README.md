# Experiments and Findings

Three experiments that tell the PD disaggregation story with reproducible scripts and observations.

## Quick Start

1. **Setup**: Follow [../docs/SETUP.md](../docs/SETUP.md) to configure hardware and NIXL+UCX
2. **Run experiments**: Execute the three scripts in order
3. **Visualize**: `python ../viz.py --exps <experiment_dirs>`

## The Three Experiments

### 1. TP Baselines - Understanding TTFT vs TPOT Trade-offs

**Script**: `bash tp-baselines.sh`

**Purpose**: Establish collocated baselines to understand conflicting optimization needs.

**What it runs**:
- TP=1 (8 replicas)
- TP=2 (4 replicas)  
- TP=4 (2 replicas)

**Key observations**:
- **TPOT (decode)**: TP4 > TP2 > TP1 (monotonic improvement)
- **TTFT (prefill)**: Non-monotonic (TP2 best at low concurrency, TP1 at high)
- **Overall efficiency**: TP4 > TP2 > TP1 (workload is decode-dominated)

**Takeaway**: There's a fundamental trade-off between optimizing for prefill (TTFT) and decode (TPOT). This motivates PD disaggregation.

---

### 2. PD Ratio Exploration - Configuration Choices Matter

**Script**: `bash pd-ratio-sweep.sh`

**Purpose**: Explore how P:D ratios and TP combinations affect performance.

**What it runs**:

**Part 1: D:TP4 (highest decode performance)**
- 1P-TP4 : 1D-TP4 (symmetric)
- 1P-TP2 : 1D-TP4, 2P-TP2 : 1D-TP4 (asymmetric)

**Part 2: D:TP2 ratio exploration**
- P:TP2, D:TP2 with ratios: 3:1, 2:1, 1:1, 1:2, 1:3

**Part 3: P:TP1, D:TP2 (lower prefill TP)**
- 1P-TP1 : 1D-TP2, 2P-TP1 : 1D-TP2, 4P-TP1 : 1D-TP2

**Key observations**:

1. **P:D ratio matters more than ITL:OTL ratio**
   - Despite ITL:OTL = 5000:250 (20:1), decode-heavy ratios (1:2, 1:3) outperformed prefill-heavy (2:1, 3:1)
   - Prefill-heavy ratios were dominated by collocated baseline

2. **Optimal ratio shifts with throughput regime**
   - Low throughput/latency: 1:3 optimal
   - Mid throughput (50-65k tokens/s): 1:2 optimal
   - High throughput (65-70k tokens/s): 1:1 optimal

3. **TP4-TP4 can beat collocated in efficiency**
   - 1P-TP4 : 1D-TP4 beats the collocated variation

**Takeaways**:
- Need dynamic ratio adjustment for different SLAs
- Must sweep configurations empirically for your workload

---

### 3. Network Impact - Pack vs Spread

**Script**: `bash pack-vs-spread.sh`

**Purpose**: Demonstrate how network configuration affects multi-node PD.

**What it runs**:
- Pack mode (same node, CUDA IPC)
- Spread with SRD (cross-node, good network)
- Spread with TCP (cross-node, forced bad network)

All use 1P-TP4 : 1D-TP4 configuration.

**Key observations**:

1. **With good network (SRD): Pack ≈ Spread**
   - Proper UCX with SRD backend on EFA
   - Cross-node bandwidth: 10-12 GB/s
   - Performance comparable to single-node

2. **With bad network (TCP): Spread << Pack**
   - Forced TCP transport: ~100x slower
   - Shows critical importance of network config
