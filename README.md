# Ray Serve LLM Performance Benchmarks

Reproducible benchmark snapshots exploring different aspects of Ray Serve LLM performance. Each benchmark includes experiments, tooling, and debugging utilities to help replicate the approach on different workloads, models, and hardware stacks.

## Benchmarks

### [Prefill-Decode Disaggregation](prefill_decode/)

Systematic exploration of PD disaggregation performance on real hardware (GPT-OSS-120B on 2× p5.48xlarge with H100s and EFA). Includes:

- Three narrative experiments showing when PD helps and configuration trade-offs
- Working NIXL + UCX + EFA setup for multi-node KV cache transfer
- Tools for benchmarking, visualization, and debugging

See [prefill_decode/README.md](prefill_decode/README.md) to get started.

### [Composing KV Connectors with MultiConnector](pd+kv_offloading/)

Demonstrates composing multiple KV transfer backends using `MultiConnector`. Shows how to combine NIXL (for GPU-to-GPU transfers) with LMCache (for local offloading) in PD deployments:

- Four configurations comparing baseline, LMCache-only, NIXL-only, and combined approaches
- Config-driven YAML deployment pattern with custom builders
- Performance analysis showing composability overhead

See [pd+kv_offloading/README.md](pd+kv_offloading/README.md) for details.

---

**Note**: This repository is actively evolving. Additional benchmark angles will be added as we explore different Ray Serve LLM optimization strategies.
