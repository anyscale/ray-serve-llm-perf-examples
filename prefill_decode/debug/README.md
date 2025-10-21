# NIXL Debugging Tools

This directory contains scripts for installing, fixing, and testing NIXL with AWS EFA on Ray clusters.

## Overview

There are two approaches to get NIXL working with AWS EFA:

1. **Wheel + Fix** (Recommended for testing): Install the official nixl wheel and apply a compatibility fix
2. **Source Build** (Recommended for production): Build nixl from source with proper EFA support

---

## ⚠️ CRITICAL KNOWN ISSUES WITH LIBFABRIC

**TL;DR: Even after fixing the segfault, LIBFABRIC backend has DATA CORRUPTION issues in vLLM. Use UCX backend instead.**

### Issue Summary

After applying the EFA compatibility fix (or building from source), NIXL with LIBFABRIC will:
- ✅ **Pass the micro benchmark** (`test_nixl_connector_ray.py`) 
- ❌ **FAIL in vLLM** with silent data corruption or hangs

### Symptoms in vLLM vs Micro Benchmark

| TP Configuration | Inter/Intra-node | UCX | LIBFABRIC (vLLM) | LIBFABRIC (Micro Benchmark) |
|------------------|------------------|-----|------------------|-----------------------------|
| 1P-TP1 → 1D-TP1 (Homogeneous) | Both | ✅ Works | ❌ Gibberish | ✅ Passes (12 GB/s) |
| 4P-TP1 → 2D-TP1 (Homogeneous) | Both | ✅ Works | ❌ Gibberish | ✅ Passes (12 GB/s) |
| 1P-TP2 → 1D-TP2 (Homogeneous) | Both | ✅ Works | ❌ Gibberish | ✅ Passes (12 GB/s) |
| 1P-TP1 → 2D-TP2 (Heterogeneous) | Both | ✅ Works | ❌ **HANGS** | ✅ Passes (12 GB/s) |
| 4P-TP4 → 8D-TP8 (Heterogeneous) | Both | ✅ Works | ❌ **HANGS** | ✅ Passes (12 GB/s) |

**P** = Prefill engine, **D** = Decode engine, **TP** = Tensor Parallelism size

**Key Insight:** The micro benchmark passes in ALL configurations, proving the issue is specific to vLLM's integration, not NIXL or EFA hardware.

### What Happens

**Homogeneous TP (P-TP == D-TP):**
- KV cache blocks transferred via LIBFABRIC contain **all zeros**
- Model output is **gibberish** due to corrupted KV cache
- Example: `Block 1 K sample mean: 0.0, sum: 0.0` (should be ~0.019)

**Heterogeneous TP (P-TP != D-TP):**
- Transfer **hangs indefinitely** or crashes with x-rail errors:
  ```
  libfabric:1242394:1760404169::efa:cq:efa_cq_handle_error():103<warn> 
  err: 22, message: Remote key (RKEY) not registered or does not match remote IOVA
  libfabric_rail.cpp:712] CQ read failed on rail 28 with error: Invalid argument
  ```

### Why Micro Benchmark Passes but vLLM Fails

The `test_nixl_connector_ray.py` micro benchmark **passes** (even with heterogeneous TP) because:
- Simple synchronous transfer pattern
- No PagedAttention integration
- No CUDA graph capture/replay
- No complex block table management
- Transfers complete before next operation

vLLM **fails** because:
- Complex PagedAttention block management
- CUDA graph capture with NIXL operations
- Asynchronous stream synchronization issues
- Multi-layer concurrent transfers
- Block table updates during transfers
- Potential race conditions with block reuse

**This indicates an issue in either:**
1. vLLM's NIXL integration (nixl_connector.py) - missing synchronization or memory barriers
2. NIXL's LIBFABRIC backend - incompatibility with CUDA graphs or async operations
3. PagedAttention + NIXL interaction - memory ordering issues during block updates

**Key Finding:** The heterogeneous TP configuration alone doesn't trigger the issue - it requires vLLM's specific memory access patterns and synchronization model.

### Recommended Solution

**Use UCX backend instead:**

```python
kv_transfer_config = {
    "kv_connector": "NixlConnector",
    "kv_role": "kv_both",
    "kv_connector_extra_config": {
        "backends": ["UCX"]  # Use UCX instead of LIBFABRIC
    }
}
```

**Expected UCX performance:**
- Cross-node: ~178 MB/s (slower than LIBFABRIC, but **correct**)
- Same-node: ~4.2 GB/s (CUDA IPC)
- All TP configurations: ✅ Works correctly

### Status

This issue has been reported to NVIDIA/NIXL maintainers. Until resolved:
- ❌ **DO NOT use LIBFABRIC backend with vLLM**
- ✅ `test_nixl_connector_ray.py` still useful for testing EFA setup

---

## Scripts

### 1. `install_nixl_wheel.sh` - Install Official Wheel

Installs the official nixl 0.6.1 wheel from PyPI on all cluster nodes.

**Usage:**
```bash
cd /home/ray/default/ray-serve-pd-example/debug
./install_nixl_wheel.sh
```

**What it does:**
- Detects all GPU nodes and head node in the Ray cluster
- Completely uninstalls any existing nixl installations
- Installs `nixl==0.6.1` using `uv pip install --system`
- Verifies the installation on each node

**When to use:**
- Quick testing with the official release
- Must be followed by `fix_nixl_wheel_efa.sh` for EFA to work

**Note:** The bundled libfabric (1.29.0) is incompatible with AWS EFA and will cause segfaults. You MUST run `fix_nixl_wheel_efa.sh` after this script.

---

### 2. `fix_nixl_wheel_efa.sh` - Fix EFA Compatibility

Fixes the nixl wheel to work with AWS EFA by replacing bundled libraries with system EFA libraries.

**Usage:**
```bash
cd /home/ray/default/ray-serve-pd-example/debug
./fix_nixl_wheel_efa.sh
```

**What it does:**
- Disables bundled libfabric/libefa/libibverbs (vanilla upstream 1.29.0)
- Creates symlinks to system AWS EFA libraries (2.1.0amzn3.0)
- Verifies the fix on both GPU nodes (172.25.105.35, 172.25.105.65)

**When to use:**
- After installing the nixl wheel with `install_nixl_wheel.sh`
- When you encounter "Segmentation fault" errors with LIBFABRIC backend

**Technical details:**
The bundled libfabric 1.29.0 is vanilla upstream and lacks AWS EFA-specific patches. This script replaces it with the system's AWS EFA libfabric (2.1.0amzn3.0).

See `../NIXL_WHEEL_EFA_FIX.md` for full technical explanation.

---

### 3. `deploy_nixl_all_nodes.sh` - Build from Source

Builds nixl from source on all cluster nodes with proper AWS EFA support.

**Usage:**
```bash
cd /home/ray/default/ray-serve-pd-example/debug
./deploy_nixl_all_nodes.sh
```

**What it does:**
- Detects all GPU nodes and head node in the Ray cluster
- Clones nixl repository from GitHub
- Builds with `meson` and `ninja`, explicitly linking against system EFA libfabric
- Installs to `/usr/local/nixl`
- Configures `ldconfig` for library paths
- Installs Python bindings with `pip install .`
- Verifies installation on each node
- It does not come with UCX

**When to use:**
- Production deployments requiring guaranteed EFA compatibility
- When you need the latest nixl features from the main branch
- When you want a permanent solution without manual symlink fixes
- When you do not need UCX 

**Advantages over wheel:**
- No real advantage, just easy to make sure NIXL is using systems libfabric and EFA instead of the bundled version

**Disadvantages:**
- Takes 2-3 minutes per node (build time)
- Requires build tools (meson, ninja, gcc)

---

### 4. `test_nixl_connector_ray.py` - Test NIXL Transfers

Tests NIXL KV-cache transfers using Ray actors, following vLLM's `nixl_connector.py` flow.

**Basic Usage:**

```bash
cd /home/ray/default/ray-serve-pd-example/debug

# Test cross-node transfer with LIBFABRIC (default)
RAY_DEDUP_LOGS=0 python test_nixl_connector_ray.py --strategy spread --random-blocks --backends LIBFABRIC --num-blocks 3750 --num-layers 50 --blocks 128

# Test same-node transfer
RAY_DEDUP_LOGS=0 python test_nixl_connector_ray.py --strategy pack --backends LIBFABRIC --blocks 50

# Test with UCX backend
RAY_DEDUP_LOGS=0 python test_nixl_connector_ray.py --strategy spread --backends UCX --blocks 50
```

**Options:**
- `--strategy spread|pack`: Cross-node (spread) or same-node (pack) placement
- `--backends LIBFABRIC|UCX`: Which NIXL backend to test (comma-separated)
- `--blocks N`: Number of blocks to transfer (default: 10)
- `--num-blocks N`: Total KV-cache blocks (default: 100)
- `--num-layers N`: Number of transformer layers (default: 2)
- `--random-blocks`: Use random non-contiguous block selection
- `--verbose`: Enable detailed logging (reduces performance)
- `--seed N`: Random seed for block selection (default: 42)
- `--prefill-tp N`: Tensor parallelism size for prefill engine (default: 1)
- `--decode-tp N`: Tensor parallelism size for decode engine (default: 1)

**What it tests:**
1. Creates Ray actors for prefill and decode engines (supports multiple TP ranks)
2. Registers GPU memory with NIXL
3. Performs agent handshake (metadata exchange)
4. Transfers KV-cache blocks from prefill to decode
5. Validates data correctness
6. Reports throughput and telemetry
7. **NEW:** Tests heterogeneous TP configurations (e.g., 4 prefill → 8 decode) to replicate cross-rail issues

**Expected Results:**
- **Homogeneous TP (1→1, 2→2, 4→4):** ✅ TEST PASSED (11-12 GB/s cross-node)
- **Heterogeneous TP (4→8, 1→2) with LIBFABRIC:** ✅ TEST PASSED in micro benchmark, but ❌ FAILS in vLLM
- **Same-node (CUDA IPC):** 40-50+ GB/s throughput

**Heterogeneous TP Examples:**

```bash
# Test 4 prefill → 8 decode (attempts to replicate TP4-TP8 issue)
# Cross-node (spread)
RAY_DEDUP_LOGS=0 python test_nixl_connector_ray.py \
    --strategy spread --backends LIBFABRIC \
    --prefill-tp 4 --decode-tp 8 \
    --num-blocks 1000 --blocks 50

# Same-node (pack) - tested configuration that PASSES
RAY_DEDUP_LOGS=0 python test_nixl_connector_ray.py \
    --strategy pack --backends LIBFABRIC \
    --num-blocks 3750 --num-layers 50 --blocks 128 \
    --prefill-tp 4 --decode-tp 8

# Test 1 prefill → 2 decode  
RAY_DEDUP_LOGS=0 python test_nixl_connector_ray.py \
    --strategy spread --backends LIBFABRIC \
    --prefill-tp 1 --decode-tp 2 \
    --num-blocks 1000 --blocks 50

# Test homogeneous TP
RAY_DEDUP_LOGS=0 python test_nixl_connector_ray.py \
    --strategy spread --backends LIBFABRIC \
    --prefill-tp 4 --decode-tp 4 \
    --num-blocks 1000 --blocks 50
```

**Important Finding:** Even with heterogeneous TP configurations (including 4P-TP4 → 8D-TP8), the micro benchmark **PASSES** while vLLM **FAILS**. 

**Tested Configuration:**
- ✅ `--prefill-tp 4 --decode-tp 8` with 3750 blocks, 50 layers, 128 block transfer
- ✅ Both same-node (pack) and cross-node (spread) strategies pass
- ✅ Achieves ~12 GB/s throughput with LIBFABRIC
- ❌ **Same configuration fails in vLLM with gibberish or hangs**

This proves the issue is not simply about heterogeneous TP mapping, but something deeper in vLLM's integration:
- PagedAttention's memory access patterns
- CUDA graph capture and replay
- Stream synchronization 
- Multi-layer concurrent transfers
- Block table management

The micro benchmark is still useful for verifying EFA hardware and basic NIXL functionality, but cannot fully replicate the vLLM failure modes.

**What it emulates:**
This script follows the exact same NIXL API flow as vLLM's `nixl_connector.py`:
- `register_kv_caches()` → registration phase
- `add_remote_agent()` → handshake phase
- `_read_blocks()` → transfer phase
- `_pop_done_transfers()` → completion phase

---

## Complete Workflows

⚠️ **IMPORTANT:** These workflows are for testing and debugging the EFA setup only. For vLLM production use, configure `backends: ["UCX"]` instead of LIBFABRIC.

### Workflow 1: Quick Testing (Wheel + Fix) - For EFA Verification Only

```bash
cd /home/ray/default/ray-serve-pd-example/debug

# Step 1: Install wheel on all nodes
./install_nixl_wheel.sh

# Step 2: Apply EFA compatibility fix
./fix_nixl_wheel_efa.sh

# Step 3: Test cross-node transfer (micro benchmark only)
RAY_DEDUP_LOGS=0 python test_nixl_connector_ray.py \
    --strategy spread --random-blocks --backends LIBFABRIC \
    --num-blocks 3750 --num-layers 50 --blocks 128
```

**Total time:** ~2 minutes (installation + fix)  
**Use case:** Verify EFA hardware and drivers are working  
**⚠️ DO NOT use LIBFABRIC with vLLM** - use UCX instead

---

### Workflow 2: Production Setup - Install with UCX Backend

```bash
cd /home/ray/default/ray-serve-pd-example/debug

# Step 1: Install wheel on all nodes
./install_nixl_wheel.sh

# Step 2: Configure vLLM to use UCX (in your vLLM config)
# kv_transfer_config = {
#     "kv_connector": "NixlConnector",
#     "kv_role": "kv_both",
#     "kv_connector_extra_config": {
#         "backends": ["UCX"]
#     }
# }

# Step 3: Test with UCX backend
RAY_DEDUP_LOGS=0 python test_nixl_connector_ray.py \
    --strategy spread --random-blocks --backends UCX \
    --num-blocks 3750 --num-layers 50 --blocks 128
```

**Total time:** ~2 minutes (installation only, no fix needed for UCX)  
**Use case:** Production vLLM deployment  
**Expected throughput:** ~178 MB/s (slow but correct)

---

### Workflow 3: Source Build (For Development/Testing)

```bash
cd /home/ray/default/ray-serve-pd-example/debug

# Step 1: Build and install on all nodes
./deploy_nixl_all_nodes.sh

# Step 2: Test LIBFABRIC (micro benchmark only)
RAY_DEDUP_LOGS=0 python test_nixl_connector_ray.py \
    --strategy spread --random-blocks --backends LIBFABRIC \
    --num-blocks 3750 --num-layers 50 --blocks 128

# Step 3: Test UCX (for vLLM)
RAY_DEDUP_LOGS=0 python test_nixl_connector_ray.py \
    --strategy spread --random-blocks --backends UCX \
    --num-blocks 3750 --num-layers 50 --blocks 128
```

**Total time:** ~5-10 minutes (build time on 3 nodes)  
**Note:** Source build does not include UCX. Bundled UCX from wheel is fine for production.

---

## Troubleshooting

### Problem: vLLM outputs gibberish with LIBFABRIC

**Symptoms:**
- KV cache blocks contain all zeros after transfer
- Model generates nonsensical output
- `test_nixl_connector_ray.py` passes but vLLM fails

**Cause:** Data corruption issue with NIXL LIBFABRIC backend in vLLM (see Critical Issues section above)

**Solution:**
```python
# Use UCX backend instead
kv_transfer_config = {
    "kv_connector": "NixlConnector",
    "kv_role": "kv_both",
    "kv_connector_extra_config": {
        "backends": ["UCX"]
    }
}
```

---

### Problem: Segmentation fault with LIBFABRIC

**Symptoms:**
```
Segmentation fault: invalid permissions for mapped object
```

**Cause:** Using bundled libfabric 1.29.0 (vanilla upstream) instead of AWS EFA libfabric 2.1.0

**Solution:**
```bash
./fix_nixl_wheel_efa.sh
```

**Note:** Even after fixing the segfault, LIBFABRIC has data corruption issues in vLLM. See Critical Issues section.

---

### Problem: Low throughput with UCX backend

**Symptoms:**
- Cross-node throughput: ~178 MB/s (expected: 10+ GB/s)
- Log shows: `using ud_verbs/ud_mlx5 transport`

**Cause:** Bundled UCX lacks EFA DC transport support

**Solution:**
- This is a known limitation of the bundled UCX
- For vLLM production use: **USE UCX ANYWAY** (178 MB/s is slow but correct)
- For LIBFABRIC testing only: Use the fix, but know that vLLM won't work correctly

---

### Problem: "nixl not found" on head node

**Symptoms:**
```
ModuleNotFoundError: No module named 'nixl'
```

**Cause:** Scripts only installed on GPU workers, not head node

**Solution:**
Both `install_nixl_wheel.sh` and `deploy_nixl_all_nodes.sh` automatically install on head node. If still missing, manually install:
```bash
# For wheel
uv pip install nixl==0.6.1 --system

# For source build
cd /tmp/nixl-build && pip install .
```

---

### Problem: "LD_LIBRARY_PATH affects performance"

**Symptoms:**
- With `--verbose`: throughput drops from 12 GB/s to 0.35 GB/s

**Cause:** Verbose logging (`FI_LOG_LEVEL=debug`) logs every packet

**Solution:**
- Don't use `--verbose` for performance testing
- Or edit `test_nixl_connector_ray.py` to use `info` level instead of `debug`

---

## Environment Requirements

All scripts assume:
- Ray cluster is running (`ray status`)
- SSH access to GPU nodes on port 2222
- GPU nodes: 172.25.105.35, 172.25.105.65
- AWS EFA installed at `/opt/amazon/efa/`
- CUDA installed at `/usr/local/cuda/`
- Build tools (for source build): `meson`, `ninja`, `gcc`, `git`
- Python environment: `torch`, `ray`, `nixl` (after installation)

---

## Files Reference

```
debug/
├── README.md                      # This file
├── install_nixl_wheel.sh          # Install official wheel
├── fix_nixl_wheel_efa.sh          # Fix EFA compatibility
├── deploy_nixl_all_nodes.sh       # Build from source
└── test_nixl_connector_ray.py     # Test NIXL transfers
```

Related documentation:
- `../NIXL_WHEEL_EFA_FIX.md` - Detailed technical explanation of the EFA fix

---

## Quick Reference Commands

```bash
# ========================================
# For vLLM Production (RECOMMENDED)
# ========================================
# Install wheel (UCX backend - no fix needed)
./install_nixl_wheel.sh

# Test UCX backend
RAY_DEDUP_LOGS=0 python test_nixl_connector_ray.py \
    --strategy spread --random-blocks --backends UCX \
    --num-blocks 3750 --num-layers 50 --blocks 128

# Configure vLLM to use UCX
# kv_transfer_config = {
#     "kv_connector": "NixlConnector",
#     "kv_role": "kv_both",
#     "kv_connector_extra_config": {
#         "backends": ["UCX"]
#     }
# }

# ========================================
# For EFA Hardware Testing Only
# ========================================
# Install wheel + fix (for LIBFABRIC testing)
./install_nixl_wheel.sh && ./fix_nixl_wheel_efa.sh

# Test LIBFABRIC (micro benchmark only - DO NOT use with vLLM)
RAY_DEDUP_LOGS=0 python test_nixl_connector_ray.py \
    --strategy spread --random-blocks --backends LIBFABRIC \
    --num-blocks 3750 --num-layers 50 --blocks 128

# Test same-node CUDA IPC
RAY_DEDUP_LOGS=0 python test_nixl_connector_ray.py \
    --strategy pack --backends LIBFABRIC --blocks 128

# Verify symlinks are active (wheel + fix approach)
ssh -p 2222 172.25.105.35 "ls -la /home/ray/anaconda3/lib/python3.11/site-packages/nixl.libs/libfabric*"
```

---

## Performance Benchmarks

### Micro Benchmark (`test_nixl_connector_ray.py`)

| Configuration | Backend | Strategy | Throughput | Status |
|---------------|---------|----------|------------|--------|
| Wheel (unfixed) | LIBFABRIC | Cross-node | SEGFAULT | ❌ |
| Wheel (fixed) | LIBFABRIC | Cross-node | 12.2 GB/s | ✅ (micro only) |
| Wheel (fixed) | LIBFABRIC | Same-node | 40+ GB/s | ✅ (micro only) |
| Source build | LIBFABRIC | Cross-node | 11.8 GB/s | ✅ (micro only) |
| Wheel (bundled) | UCX | Cross-node | 0.18 GB/s | ✅ (slow but correct) |
| Wheel (bundled) | UCX | Same-node | 4.2 GB/s | ✅ |

### vLLM Production Usage

| Configuration | Backend | Result | Recommendation |
|---------------|---------|--------|----------------|
| Any | LIBFABRIC | ❌ Data corruption / Hangs | **DO NOT USE** |
| Any | UCX | ✅ Correct outputs | **RECOMMENDED** |

**Hardware:** AWS P5.48xlarge (2 nodes, 32x EFA per node)  
**Transfer size:** 419 MB (128 blocks, 50 layers)

**Key Takeaway:** LIBFABRIC passes micro benchmarks but fails in vLLM. Use UCX for production.

---

## Additional Notes

### Why the fix is needed

The nixl 0.6.1 wheel bundles **vanilla upstream libfabric 1.29.0**, which lacks AWS-specific patches required by the EFA kernel driver (2.17.2g). AWS EFA requires their forked **libfabric 2.1.0amzn3.0** to work properly.

The fix works by using symlinks to intercept RPATH-based library loading, redirecting to the correct AWS EFA libraries.

### Alternative: Use source build

Building from source is the cleanest solution as it links against AWS EFA libfabric from the start, avoiding any post-installation hacks. However, note that even with source build, LIBFABRIC has data corruption issues in vLLM.

### Reporting to NVIDIA

The LIBFABRIC data corruption issue has been documented and should be reported to NVIDIA/nixl maintainers. Key evidence:

1. **Micro benchmark passes:** `test_nixl_connector_ray.py` achieves 12 GB/s with LIBFABRIC (even with heterogeneous TP)
2. **vLLM fails:** All TP configurations (homogeneous and heterogeneous) produce gibberish or hang
3. **UCX works:** Same vLLM setup works correctly with UCX backend
4. **Hardware verified:** EFA drivers and hardware are working (micro benchmark confirms)
5. **Not a simple TP mapping issue:** Heterogeneous TP works in micro benchmark but fails in vLLM

This suggests either:
- A bug in NIXL's LIBFABRIC backend with CUDA graphs or async stream operations
- Missing synchronization/memory barriers when used with PagedAttention
- Race conditions triggered by vLLM's block reuse patterns
- Incompatibility with CUDA graph capture/replay

**Recommended Investigation:**
- Test NIXL LIBFABRIC with CUDA graph capture enabled
- Profile memory synchronization between NIXL transfers and PagedAttention kernels
- Check if LIBFABRIC backend properly integrates with CUDA stream ordering

Use `../NIXL_WHEEL_EFA_FIX.md` for technical details about the EFA compatibility fix.

