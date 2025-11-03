# Ray Serve LLM Performance Benchmarks

Reproducible benchmark snapshots exploring different aspects of Ray Serve LLM performance. Each benchmark includes experiments, tooling, and debugging utilities to help replicate the approach on different workloads, models, and hardware stacks.

## Table of Contents

- [Horizontal Scaling](#horizontal-scaling)
- [Prefill-Decode Disaggregation](#prefill-decode-disaggregation)
- [Composing KV Connectors with MultiConnector](#composing-kv-connectors-with-multiconnector)
- [Replica Initialization](#replica-initialization)

## Benchmarks


### [Horizontal Scaling](horizontal_scaling/)

Demonstrates that Ray Serve scales horizontally with linear throughput gains. When you scale the number of replicas in a deployment from 1x → 2x → 4x → 8x, you'll see proportional increases in aggregate throughput. Includes:

- Benchmark methodology accounting for client scaling, symmetric component scaling, and prefix caching considerations
- Comparison between Ray Serve with open-source Ray and Anyscale runtime optimizations
- Tools for running benchmarks at different replica counts and concurrency levels
- Visualization showing consistent per-replica throughput across scaling factors

See [horizontal_scaling/README.md](horizontal_scaling/README.md) to get started.


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

### [Replica Initialization](replica_initialization/)

Measures how fast Ray Serve LLM replicas can cold-start and serve their first request, exploring optimization strategies for autoscaling scenarios. Includes:

- Experiments across three model sizes (8B, 70B, 235B) testing different optimization strategies
- Model streaming from S3 to reduce initialization time
- Torch compile caching to accelerate model compilation
- Performance visualizations showing initialization time improvements
- Tools for measuring TTFT (time-to-first-token) including replica initialization overhead

See [replica_initialization/README.md](replica_initialization/README.md) for details.

---

**Note**: This repository is actively evolving. Additional benchmark angles will be added as we explore different Ray Serve LLM optimization strategies.
