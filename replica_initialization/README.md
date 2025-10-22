# Replica Initialization: Measuring Autoscaling Performance

## What is this?

Experiments measuring how fast Ray Serve LLM replicas can cold-start and serve their first request. We're exploring optimization strategies like model streaming from S3 and torch compile caching across three models at different scales.

## What you'll find here

- **Completed experiments**: Results for 14 total experiments across three model sizes
- **Performance graphs**: Visualizations showing initialization time improvements from different optimizations
- **Terminal output**: Detailed timing breakdowns for model load and torch compile phases
- **Reproducible setup**: Code to run experiments yourself with `service.py` and `client.py`

## Models and Experiments

Three models tested with different optimization strategies:

**llama-3-8b** (TP=1) - 4 experiments
- `baseline`, `runai_streamer`, `compile_cache`, `all`

**llama-3-70b** (TP=4) - 5 experiments  
- `baseline`, `runai_streamer`, `runai_streamer_sharded`, `compile_cache`, `all`

**qwen-3-235b** (TP=8) - 5 experiments
- `baseline`, `runai_streamer`, `runai_streamer_sharded`, `compile_cache`, `all`

### What each experiment tests

- **baseline**: Standard model loading from Hugging Face
- **runai_streamer**: Model streaming from S3
- **runai_streamer_sharded**: Sharded model streaming from S3 (70B and 235B only)
- **compile_cache**: Torch compile cache from S3
- **all**: Combined optimizations (sharded streaming + compile cache)

## Running Experiments

**Note**: To run these experiments yourself, you'll need to configure your own AWS S3 bucket and update the bucket paths in `service.py`. The experiments use S3 for model storage and torch compile cache. You may also need to set AWS credentials as environment variables (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`) and uncomment the relevant lines in `LLMConfig`'s `runtime_env`.

Start a service with autoscaling from 0 replicas:

```bash
python service.py <model_name> <experiment_name>
```

The service scales up from 0 replicas on first request (`min_replicas=0`, `initial_replicas=0`, `max_replicas=1`), letting you measure cold-start time.

## Measuring Performance

**TTFT**: Run `client.py` after starting the service. This captures end-to-end time from request to first token, including replica initialization.

**Model load and torch compile metrics**: Check the terminal output where `service.py` is running, or see pre-captured logs in `experiment_terminal_output/`.

Key metrics:
- Model load time
- Torch compile time 

## Results

**Graphs**: `graphs/` directory contains performance comparisons
- Individual model charts: `llama8b.png`, `llama70b.png`, `Qwen235B.png`
- Cross-model overview: `all_models_comparison.png`

**Terminal logs**: `experiment_terminal_output/` has detailed timing breakdowns for each experiment run.

## Tools

- `service.py`: Start Ray Serve with configured model and experiment type
- `client.py`: Send timed requests to measure TTFT
- `clear_cache.py`: Clear local caches between experiments

## Hardware Configuration

- **EC2**: p5.48xlarge
    - **CPU**: 192 vCPU
    - **MEM**: 2048 GiB
    - **GPUs**: 8xH100
- **Model sources**: Hugging Face Hub (baseline) and S3 (same cloud and region)
- **Compile cache**: S3-backed torch compile cache in the same cloud and region

