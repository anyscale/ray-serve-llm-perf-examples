# Setup Guide

This guide documents hardware and software configurations that have been tested and verified to work for PD disaggregation experiments.

## Hardware Configuration

### Tested Setup

**Cluster**: 1 head node + 2 worker nodes
- **Worker nodes**: 2x p5.48xlarge instances (AWS)
  - 8x H100 GPUs per node (16 GPUs total)
  - EFA networking enabled
  - NVLink for intra-node GPU communication

**Model**: GPT-OSS-120B (openai/gpt-oss-120b)

## Software Stack

### Verified Versions

The following combination has been tested and works:

```
vllm==0.11.0
nixl==0.6.1 (built from source with UCX 1.20.0+)
flashinfer-python==0.2.14.post1
ray nightly (to be released as 2.51.0)
```

### Important Notes on Dependencies

**vLLM**
- Version 0.11.0 was the latest at the time of testing
- Newer versions may introduce API changes requiring adjustments
- Check Ray Serve documentation for currently supported vLLM versions

**NIXL**
- Release 0.6.1 is the first to support libfabric plugin
- **Known Issue**: libfabric plugin has issues on EFA (see [vllm#27055](https://github.com/vllm-project/vllm/issues/27055))
- **Working Solution**: Build NIXL against UCX 1.20.0+ with SRD backend support for EFA

## NIXL + UCX + EFA Setup

For multi-node PD experiments with EFA networking, you need to build NIXL with UCX support.

### Installation Procedure

The full installation script is available at `/debug/build_nixl_ucx_efa.sh`. Key steps:

1. Build UCX 1.20.0+ with EFA support
2. Build NIXL 0.6.1 against the custom UCX installation
3. Verify the installation using the test script

See [DEBUGGING.md](DEBUGGING.md) for verification procedures.

### Why UCX?

UCX with SRD (Scalable Reliable Datagram) backend provides:
- Proper EFA support on AWS p5 instances
- Significantly better performance than misconfigured libfabric
- Correct rdma/verbs usage

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

### Model Configuration

The model configuration uses `max_model_len: 16000` to accommodate TP=1 deployments. With the full model length, even a single request would exceed available KV cache on one GPU.

## Validation

Before running experiments, validate your setup:

1. **Smoke test**: Run `./run_bm.sh --smoke` to verify basic deployment
2. **NIXL connectivity**: Use `debug/test_nixl_connector_ray.py` to verify network layer
3. **GPU detection**: Check that all GPUs are visible to Ray

## Adaptability

This setup has been validated on the hardware configuration above. Adaptation to other setups may require:
- Adjusting parallelism degrees (TP, PP, EP) based on available GPUs
- Different NIXL/UCX configuration for non-EFA networks
- Model selection based on GPU memory
- Workload parameters based on use case

## Related Documentation

- [DEBUGGING.md](DEBUGGING.md): Troubleshooting NIXL and networking issues
- [METHODOLOGY.md](METHODOLOGY.md): How to use the experiment tools
- Ray Serve PD Setup: [docs.ray.io](https://docs.ray.io/en/master/serve/llm/user-guides/prefill-decode.html)

