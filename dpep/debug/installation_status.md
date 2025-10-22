# pplx-kernels Installation Status

## Summary

Installation on both worker nodes is **95% complete** with a minor import issue.

### ✅ Successfully Installed
- **NVSHMEM 3.2.5** with EFA/libfabric support
  - Location: `/tmp/pplx_workspace/nvshmem_install`
  - Built with libfabric support for EFA networking
- **pplx-kernels C++/CUDA libraries**
  - Location: `/tmp/pplx_workspace/pplx-kernels`
  - All CUDA kernels compiled successfully
  - Libraries: `libpplx_kernels.so` built

### ⚠️ Remaining Issue
The pplx-kernels Python module imports `nvshmem.core` which is not available in NVSHMEM 3.2.5.
- **nvshmem4py** (Python bindings) were introduced in NVSHMEM 3.4+
- pplx-kernels code expects this module for initialization

### Solutions

**Option 1: Use NVSHMEM 3.4.5 with nvshmem4py** (Recommended)
- Rebuild NVSHMEM 3.4.5 WITH nvshmem4py enabled
- Install python3.10-venv and python3.11-venv system packages first
- This is the cleanest solution

**Option 2: Modify pplx-kernels to skip nvshmem Python import**
- The nvshmem Python module is only used in `nvshmem.py` for initialization
- Could potentially modify to use C++ libraries directly
- Less clean but would work

**Option 3: Use older pplx-kernels commit**
- Try commit that doesn't require nvshmem Python package
- May have different features/bugs

## Environment Setup

Once resolved, source this file on worker nodes:
```bash
source /tmp/pplx_workspace/setup_env.sh
```

Contains:
```bash
export NVSHMEM_HOME=/tmp/pplx_workspace/nvshmem_install
export LD_LIBRARY_PATH=$NVSHMEM_HOME/lib:$LD_LIBRARY_PATH
export CMAKE_PREFIX_PATH=$NVSHMEM_HOME:$CMAKE_PREFIX_PATH
export NVSHMEM_REMOTE_TRANSPORT=libfabric
export NVSHMEM_LIBFABRIC_PROVIDER=efa
```

## Next Steps for Benchmarking

Once pplx-kernels is fully working, we need to:
1. Create benchmark scripts for:
   - Intra-node (NVLink): EP8, 1 & 128 tokens
   - Inter-node (EFA): EP8, 1 & 128 tokens  
   - Inter-node (EFA): EP16, 1 & 128 tokens
2. Run benchmarks and collect results
3. Compare against published numbers

##

 Nodes
- Worker 1: 172.25.105.98 (8x H100)
- Worker 2: 172.25.105.130 (8x H100)
- Head: 172.25.101.40 (CPU only)

