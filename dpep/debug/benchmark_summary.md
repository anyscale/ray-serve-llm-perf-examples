# pplx-kernels Benchmark Plan

## ✅ Installation Complete!

**pplx-kernels with NVSHMEM 3.4.5** successfully installed on:
- Node 1: 172.25.105.98 (8x H100)
- Node 2: 172.25.105.130 (8x H100)

Location: `/tmp/pplx_workspace/pplx-kernels`

## Benchmarks to Run

We'll compare **intra-node (NVLink)** vs **inter-node (EFA)** performance:

### Test Matrix

| Scenario | EP Size | Tokens/GPU | Transport | Expected Latency |
|----------|---------|------------|-----------|------------------|
| Intra-node | EP8 | 1 | NVLink | ~41-60μs |
| Intra-node | EP8 | 128 | NVLink | ~83-102μs |
| Inter-node | EP8 | 1 | EFA | ? (to measure) |
| Inter-node | EP8 | 128 | EFA | ? (to measure) |
| Inter-node | EP16 | 1 | EFA | ? (to measure) |
| Inter-node | EP16 | 128 | EFA | ? (to measure) |

### Environment Setup

Before running benchmarks, source this on both nodes:
```bash
source /tmp/pplx_workspace/setup_env.sh
```

This sets:
- `NVSHMEM_HOME=/tmp/pplx_workspace/nvshmem_install`
- `LD_LIBRARY_PATH` includes NVSHMEM libs
- `NVSHMEM_REMOTE_TRANSPORT=libfabric` (for EFA)
- `NVSHMEM_LIBFABRIC_PROVIDER=efa`

For single-node tests, override with:
```bash
export NVSHMEM_REMOTE_TRANSPORT=none
```

## Next Steps

1. Create Python benchmark script using pplx-kernels test framework
2. Run benchmarks for each scenario
3. Compare against published results
4. Document findings

