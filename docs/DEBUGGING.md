# Debugging Guide

This guide consolidates lessons learned while setting up and troubleshooting NIXL, UCX, and EFA for PD disaggregation experiments.

## Critical Lessons Learned

### 1. Use UCX Backend, Not libfabric

**TL;DR**: The libfabric backend has data corruption issues in vLLM. Always use UCX.

**Symptoms with libfabric:**
- **Homogeneous TP** (P-TP == D-TP): KV cache blocks contain all zeros, model outputs gibberish
- **Heterogeneous TP** (P-TP != D-TP): Transfers hang indefinitely or crash with RKEY errors

**The Puzzle:**
- The micro benchmark (`test_nixl_connector_ray.py`) passes with libfabric
- vLLM fails with the same configuration
- This indicates an integration issue between vLLM's PagedAttention/CUDA graphs and NIXL's libfabric backend

**Solution:**
```python
kv_transfer_config = {
    "kv_connector": "NixlConnector",
    "kv_role": "kv_both",
    "kv_connector_extra_config": {
        "backends": ["UCX"]  # Always use UCX
    }
}
```

**Expected UCX Performance:**
- Cross-node: ~178 MB/s (slower than libfabric, but **correct**)
- Same-node: ~4.2 GB/s (CUDA IPC)
- All TP configurations: Works correctly

### 2. NIXL Logging Severely Impacts Performance

Setting `NIXL_LOGGING_LEVEL=DEBUG` can reduce performance by 5-10x.

**Recommendation:**
- Only use `DEBUG` logging when actively troubleshooting
- Use `INFO` or `WARNING` for benchmarking
- Turn off NIXL logging entirely for production workloads

### 3. Verify UCX Backend Selection

UCX can use different transport backends. On EFA, you need the SRD (Scalable Reliable Datagram) backend for good performance.

**Bad backends on EFA:**
- `ud_verbs` (older, slower)
- Generic RDMA without EFA-specific optimizations

**How to verify:**
```bash
# Run the NIXL test with UCX
python debug/test_nixl_connector_ray.py --backend UCX

# Check for "Using transport: srd" in output
```

**Expected bandwidth:**
- Cross-node with SRD: 10-12 GB/s
- Cross-node without SRD: < 1 GB/s

## Debugging Utilities

### `test_nixl_connector_ray.py`

Tests NIXL connectivity and bandwidth independent of vLLM.

**Usage:**
```bash
# Test UCX backend cross-node
python debug/test_nixl_connector_ray.py --backend UCX --cross-node

# Test with different KV cache sizes
python debug/test_nixl_connector_ray.py --backend UCX --kv-size 8192

# Test libfabric (for comparison, not for production)
python debug/test_nixl_connector_ray.py --backend LIBFABRIC
```

**What it tests:**
- NIXL initialization and setup
- Point-to-point transfers between Ray actors
- Bandwidth measurement at different KV cache sizes
- Transport backend selection

**Interpreting results:**
- **Good**: 10-12 GB/s cross-node with UCX on EFA
- **Bad**: < 1 GB/s indicates wrong transport backend
- **Weird**: libfabric shows 12 GB/s but vLLM fails → integration issue

### `build_nixl_ucx_efa.sh`

Builds NIXL from source with UCX 1.20.0+ for EFA support.

**When to use:**
- Setting up a new cluster
- The pre-built wheel doesn't work with your UCX version
- You need UCX SRD backend support

**What it does:**
1. Downloads and builds UCX 1.20.0+ with EFA support
2. Builds NIXL against the custom UCX installation
3. Installs both to `/opt/nixl-ucx/`

**Time required:** ~30-45 minutes per node

### `deploy_nixl_all_nodes.sh`

Deploys NIXL+UCX to all nodes in a Ray cluster.

**Usage:**
```bash
# Build on head node first
./debug/build_nixl_ucx_efa.sh

# Deploy to all worker nodes
./debug/deploy_nixl_all_nodes.sh
```

### `get_node_info.py`

Quick utility to get Ray cluster node information.

```bash
python debug/get_node_info.py
```

Outputs node IDs, IP addresses, and resource availability.

## Common Issues and Solutions

### Issue: vLLM deployment fails with NIXL errors

**Symptoms:**
```
Error initializing NIXL
Failed to create connector
```

**Checklist:**
1. Is NIXL installed on all nodes?
2. Is the correct backend specified in config?
3. Are environment variables set correctly?
4. Check Ray logs for detailed error messages

### Issue: Performance is much slower than expected

**Symptoms:**
- Multi-node PD is slower than single-node
- Throughput lower than collocated baseline

**Debugging steps:**

1. **Verify network transport:**
   ```bash
   python debug/test_nixl_connector_ray.py --backend UCX
   ```
   Should show 10-12 GB/s cross-node.

2. **Check NIXL logging level:**
   ```bash
   echo $NIXL_LOGGING_LEVEL
   ```
   Should be `INFO` or unset, not `DEBUG`.

3. **Verify UCX backend:**
   Check deployment logs for "Using transport: srd".

4. **Test with pack mode:**
   Try `--mode pd-pack` to isolate network vs other issues.

### Issue: Model outputs are wrong/gibberish

**Symptoms:**
- Completions don't make sense
- Output is random characters

**Most likely cause:** Using libfabric backend

**Solution:**
Switch to UCX backend in your deployment configuration.

### Issue: Deployment hangs during startup

**Symptoms:**
- Deployment doesn't complete
- Some replicas stuck initializing

**Possible causes:**
1. Resource constraints (not enough GPUs available)
2. NIXL initialization failure
3. Network connectivity issues between nodes

**Debugging:**
1. Check Ray dashboard for replica status
2. Check Ray logs on worker nodes
3. Verify network connectivity: `ray get-node-info`
4. Check GPU availability: `nvidia-smi`

## Performance Verification Checklist

Before trusting your benchmark results:

- [ ] UCX backend is being used (not libfabric)
- [ ] NIXL logging is at INFO or disabled
- [ ] Network test shows 10-12 GB/s cross-node bandwidth
- [ ] Smoke test (`./run_bm.sh --smoke`) passes
- [ ] Model outputs are coherent (not gibberish)
- [ ] TTFT and TPOT values are reasonable for the workload

## Environment Variables

Key environment variables for debugging:

```bash
# NIXL logging
export NIXL_LOGGING_LEVEL=INFO  # or DEBUG for troubleshooting

# UCX tuning (usually not needed, but documented for reference)
export UCX_TLS=rc_x,tcp,cuda_copy,cuda_ipc,srd_x  # Transport selection
export UCX_NET_DEVICES=efa0  # EFA device

# Ray logging
export RAY_BACKEND_LOG_LEVEL=debug  # For Ray-specific issues
```

## When to File Issues

If you encounter problems:

1. **vLLM integration issues**: [vllm-project/vllm](https://github.com/vllm-project/vllm/issues)
2. **NIXL issues**: [NVIDIA NIXL repository](https://github.com/NVIDIA/NIXL)
3. **Ray Serve issues**: [ray-project/ray](https://github.com/ray-project/ray/issues)

Include:
- Hardware configuration
- Software versions
- Output from `test_nixl_connector_ray.py`
- Ray logs
- Minimal reproduction steps

## Additional Resources

- Full debug README: [../debug/README.md](../debug/README.md)
- NIXL+UCX build script: [../debug/build_nixl_ucx_efa.sh](../debug/build_nixl_ucx_efa.sh)
- vLLM NIXL issues: [vllm#27055](https://github.com/vllm-project/vllm/issues/27055)

