# Debugging Guide

Troubleshooting guide for NIXL, UCX, and EFA issues in PD disaggregation experiments.

## Known Issue: libfabric Backend

**At the time of writing, libfabric backend had correctness and functionality issues with vLLM.**

**Observed symptoms:**
- **Homogeneous TP** (P-TP == D-TP): KV cache blocks contain all zeros, model outputs gibberish
- **Heterogeneous TP** (P-TP != D-TP): Transfers hang indefinitely or crash with RKEY errors

**The puzzle:**
- Micro-benchmark (`test_nixl_connector_ray.py`) passes with libfabric showing 12 GB/s
- vLLM fails with the same configuration
- Indicates integration issue with vLLM's PagedAttention/CUDA graphs and NIXL's libfabric backend

**Working configuration:**
Use UCX backend with `--use-ucx`:
```bash
python launch_gptoss.py --mode pd-spread --p-num 1 --p-tp 4 --d-num 1 --d-tp 4 --use-ucx
```

**UCX Performance on EFA:**
- Cross-node with SRD: 4-5 GB/s
- Same-node (CUDA IPC): 4-5 GB/s
- All TP configurations: Works correctly

### NIXL Logging Impact

`NIXL_LOGGING_LEVEL=DEBUG` reduces performance by 5-10x. Only use for active troubleshooting.

### UCX Transport Backend

On EFA, UCX should use SRD (Scalable Reliable Datagram) backend for good performance.

**Verify transport:**
```bash
# Cross-node test (emulating realistic kv-cache size xfer)
RAY_DEDUP_LOGS=0 python debug/test_nixl_connector_ray.py \
  --strategy spread --backends UCX \
  --num-blocks 3750 --num-layers 50 --blocks 512

# Quick test (fewer blocks for faster validation)
python debug/test_nixl_connector_ray.py --strategy spread --backends UCX --blocks 10
```

**Expected:**
- Cross-node bandwidth: 10-12 GB/s
- Transport in logs: "srd" or "srd_x"
- Same-node: 4-5 GB/s (CUDA IPC)

**If < 1 GB/s:** Wrong transport (e.g., ud_verbs). Rebuild UCX/NIXL with proper EFA support.

## Debugging Utilities

### `test_nixl_connector_ray.py`

Tests NIXL bandwidth independently of vLLM, following the same transfer flow as vLLM.

**Usage:**
```bash
# Cross-node test with UCX (realistic workload size)
RAY_DEDUP_LOGS=0 python debug/test_nixl_connector_ray.py \
  --strategy spread --backends UCX \
  --num-blocks 3750 --num-layers 50 --blocks 512

# Same-node test
RAY_DEDUP_LOGS=0 python debug/test_nixl_connector_ray.py \
  --strategy pack --backends UCX \
  --num-blocks 3750 --num-layers 50 --blocks 512

# Quick test with fewer blocks
python debug/test_nixl_connector_ray.py --strategy spread --backends UCX --blocks 10

# Test with different backends (for debugging)
python debug/test_nixl_connector_ray.py --strategy spread --backends LIBFABRIC
python debug/test_nixl_connector_ray.py --strategy spread --backends UCX,LIBFABRIC

# Test heterogeneous TP
python debug/test_nixl_connector_ray.py --strategy spread --backends UCX \
  --prefill-tp 1 --decode-tp 2 --num-blocks 3750 --num-layers 50 --blocks 512
```

**Good result (UCX on EFA):**
- Cross-node: 10-12 GB/s
- Logs show "transport: srd" or "srd_x"
- Transfer validation passes

**Bad result:**
- < 1 GB/s → Wrong transport (ud_verbs instead of SRD), rebuild UCX
- Errors → NIXL not installed correctly
- Validation fails → Data corruption (e.g., with libfabric)

### `build_nixl_ucx_efa.sh`

Builds NIXL from source with UCX 1.20.0+ for EFA support.

```bash
./debug/build_nixl_ucx_efa.sh
```

## Common Issues

### Deployment Fails with NIXL Errors

**Check:**
1. NIXL installed on all nodes?
2. Check Ray logs for details in debug mode

### Performance Much Slower Than Expected

**Debug steps:**

1. **Test network:**
   ```bash
   RAY_DEDUP_LOGS=0 python debug/test_nixl_connector_ray.py --strategy spread --backends UCX --num-blocks 3750 --num-layers 50 --blocks 512
   ```
   Expected: 10-12 GB/s with SRD transport.

2. **Check logging level:**
   ```bash
   echo $NIXL_LOG_LEVEL
   ```
   Should be unset or `INFO`, not `DEBUG` (DEBUG reduces performance 5-10x).

3. **Try pack mode:**
   Isolate network vs other issues:
   ```bash
   python launch_gptoss.py --mode pd-pack --p-num 1 --p-tp 4 --d-num 1 --d-tp 4 --use-ucx
   ```

4. **Check UCX transport in logs:**
   Look for "transport: srd" or "srd_x" in NIXL output.

### Model Outputs Are Gibberish

**Likely causes:**
- Using libfabric backend (had known correctness issues at time of writing)
- Data corruption during KV cache transfer

**Solution:** 
Use `--use-ucx` in launch command:
```bash
python launch_gptoss.py --mode pd-spread --p-num 1 --p-tp 4 --d-num 1 --d-tp 4 --use-ucx
```

## Useful Environment Variables

```bash
# NIXL logging (for debugging only - reduces performance 5-10x)
export NIXL_LOG_LEVEL=DEBUG

# Force TCP (for testing network impact, see pack-vs-spread.sh)
export UCX_TLS="tcp"

# UCX transport selection (usually auto-detected correctly)
export UCX_TLS="rc_x,tcp,cuda_copy,cuda_ipc,srd_x"
# SHOWS the xfer protocol
export UCX_PROTO_INFO="y"

# Ray debugging (reduces log deduplication)
export RAY_DEDUP_LOGS=0
export RAY_BACKEND_LOG_LEVEL=debug

# Enable NIXL telemetry
export NIXL_TELEMETRY_ENABLE=1
```
