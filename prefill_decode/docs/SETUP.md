# Setup Guide

This guide documents the hardware and software stack that has been tested and works for PD disaggregation experiments.

## Hardware Configuration

**Cluster**: 1 head node + 2 worker nodes
- **Worker nodes**: 2x p5.48xlarge instances (AWS)
  - 8x H100 GPUs per node (16 GPUs total)
  - EFA networking enabled for cross-node communication
  - NVLink for intra-node GPU communication

**Model**: GPT-OSS-120B (openai/gpt-oss-120b)

This hardware enables testing:
- **Single-node configs**: Up to 8 GPUs (TP2-8, various PD ratios)
- **Cross-node configs**: All 16 GPUs for PD spread experiments

## Software Stack

### Tested Versions

```
vllm==0.11.0
nixl==0.6.1 (built from source with UCX 1.20.0+)
flashinfer-python==0.2.14.post1
ray==2.51.0 (nightly at time of testing)
```

### Key Dependencies

**NIXL 0.6.1 with UCX**
- **Critical**: Must build from source with UCX 1.20.0+ for EFA support
- **libfabric had issues**: At time of writing, had data corruption issues with vLLM (tracked in [vllm#27055](https://github.com/vllm-project/vllm/issues/27055))
- **UCX with SRD backend**: Provides correct performance on EFA
- See installation procedure below

## NIXL + UCX + EFA Setup

For multi-node PD experiments with EFA networking, you need to build NIXL with UCX support.

### Installation Procedure

The full installation script is available at `/debug/build_nixl_ucx_efa.sh`. Key steps:

1. Build UCX 1.20.0+ with EFA support
2. Build NIXL 0.6.1 against the custom UCX installation
3. Verify the installation using the test script


### Why UCX with SRD?

- **Correct functionality**: libfabric had data corruption issues with vLLM at time of writing
- **Performance**: 10-12 GB/s cross-node bandwidth on EFA
- **EFA support**: SRD backend optimized for AWS EFA

Without proper UCX configuration, network can be 5-10x slower or have correctness issues.

## Environment Setup

### Ray Cluster

Ensure Ray is running with proper GPU detection:

```bash
ray start --head  # On head node
ray start --address=<head-ip>:6379  # On worker nodes
```

Verify cluster status:
```bash
ray status
```

## Validation

Before running experiments:

1. **Verify Ray cluster**: `ray status` should show all GPUs
2. **Test network layer**:
   ```bash
   RAY_DEDUP_LOGS=0 python debug/test_nixl_connector_ray.py \
     --strategy spread --backends UCX \
     --num-blocks 3750 --num-layers 50 --blocks 512
   ```
   - Expected: 10-12 GB/s cross-node bandwidth
   - Should show "transport: srd" or "srd_x"
3. **Smoke test**: `./run_bm.sh --smoke` to verify deployment works

## Adapting to Other Hardware

This setup is specific to 2x p5.48xlarge with EFA. For other configurations:

- **Non-EFA networks**: May need different UCX or libfabric configuration
- **Different workloads**: Changes in ITL/OTL, and model might change the optimal setup and pareto curves.
