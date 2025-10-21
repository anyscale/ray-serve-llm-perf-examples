# Ray Serve Prefill-Decode Disaggregation: An Exploration Guide

**Living Document**: This repository is actively evolving as we explore PD disaggregation across different workloads, hardware, and network configurations.

## What is this repository?

A systematic exploration of Prefill-Decode (PD) disaggregation performance on real hardware using Ray Serve's LLM PD support. We demonstrate:

- **When PD helps**: Understanding the trade-offs between prefill and decode optimization
- **Configuration choices that matter**: P:D ratios, TP degrees, and their interactions
- **Network layer impact**: How network configuration affects multi-node PD performance

## What you'll find here

- **Reproducible experiments**: A set of reproducible experiments showing the value of prefill-decode dissagregation 
- **Working configurations**: Hardware and network setups validated on 2x p5.48xlarge (16x H100, EFA)
- **Evolving observations**: What we're learning as we explore different configurations

## What this is NOT

- Prescriptive recommendations (configurations are workload and hardware dependent)
- Complete (we're actively exploring and adding new findings)

## Quick Navigation

- **New to PD?** Read the [Ray Serve PD documentation](https://docs.ray.io/en/master/serve/llm/user-guides/prefill-decode.html)
- **Setup**: See [docs/SETUP.md](docs/SETUP.md) for tested configurations
- **Experiments and findings**: [experiments/README.md](experiments/README.md)
- **Debugging**: [docs/DEBUGGING.md](docs/DEBUGGING.md) for NIXL/UCX/EFA troubleshooting

## Experiments

Three experiments that tell the PD disaggregation story:

1. **[TP Baselines](experiments/tp-baselines.sh)**: Understanding TTFT vs TPOT trade-offs in collocated mode
2. **[PD Ratio Exploration](experiments/pd-ratio-sweep.sh)**: How P:D ratios and TP configurations affect performance
3. **[Network Impact](experiments/pack-vs-spread.sh)**: Pack vs spread placement and network layer effects

See [experiments/README.md](experiments/README.md) for detailed findings and how to run experiments.

## Tools

- `launch_gptoss.py`: Deploy GPT-OSS-120B in collocated, PD-pack, or PD-spread modes
- `run_bm.sh`: Benchmark runner with concurrency and request rate sweeps
- `viz.py`: Visualization tool for analyzing results
- `query_completion.py`: Smoke test utility

## Background

For architectural details and the theory behind PD disaggregation:
- [Ray Serve PD User Guide](https://docs.ray.io/en/master/serve/llm/user-guides/prefill-decode.html)
- [Ray Serve PD Architecture](https://docs.ray.io/en/master/serve/llm/architecture/serving-patterns/prefill-decode.html)

