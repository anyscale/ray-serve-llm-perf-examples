# Horizontal Scaling Benchmarks

The goal of this benchmark is to show that Ray serve scales horizontally. Meaning if you scale the number of replicas in a deployment from 1x -> 2x -> 4x you'll see a linear scaling in aggregate throughput. 

There are a few key factors when doing this benchmark: 

- The client should also scale with the server side, so that it does not become bottleneck at high concurrencies as the capacity of the throughput on the serving side increases.
- All components of the serving side should scale at the same rate, so that there is no asymetry on the serve side making one of the components the bottleneck. That means ingress deployment shoudl scale with the LLM deployment. 
- During this benchmark, prefix caching capability of the engine should be turned off, because it can confound our results. When prefix-caching is turned on, the content of requests and whether there is any hit repetion in them during benchmarking a service that has been up for a while can impact the results. Even if the request are randomly generated the seed might be shared across different runs and the results might show no intuitive pattern compared to expectations. Therefore during these benchmarks we pass `enable_prefix_caching=False` into our engine kwargs.

In this benchmark we also compare Ray vs. Anyscale runtime to see if there are any differences regarding the horizontal scaling angle of LLMs. To do this we build two sets of anyscale images, one where we explicity turn off the runtime optimizations and one where do not turn it off:

- rayoss-251 image: 

```
FROM anyscale/ray-llm:2.51.0-py311-cu128

ENV ANYSCALE_DISABLE_OPTIMIZED_RAY=1
ENV RAY_SERVE_THROUGHPUT_OPTIMIZED=1
```

- rayturbo-251 image:

```
FROM anyscale/ray-llm:2.51.0-py311-cu128

ENV ANYSCALE_RAY_SERVE_ENABLE_HA_PROXY=1
ENV RAY_SERVE_THROUGHPUT_OPTIMIZED=1
ENV ANYSCALE_RAY_SERVE_DIRECT_INGRESS_MIN_DRAINING_PERIOD_S=90
```

We have included the service yamls in oss_configs and turbo_configs respectively. For each yaml we deploy an Anyscale service: 

```
anyscale services deploy -f <config.yaml>
```

And then set the URL and API key in the following benchmarks for testing.

<include table of content>

## Quick Start

### Install Just

```bash
# Install using the official install script (recommended)
curl --proto '=https' --tlsv1.2 -sSf https://just.systems/install.sh | sudo bash -s -- --to /usr/local/bin

# Or download pre-built binary manually
# wget https://github.com/casey/just/releases/latest/download/just-x86_64-unknown-linux-musl.tar.gz
# tar -xzf just-*.tar.gz
# sudo mv just /usr/local/bin/

# Verify installation
just --version
```

### Configuration

Set environment variables for your API endpoint:

```bash
# Required: Set the API URL
export OPENAI_API_URL="http://127.0.0.1:8000"

# Optional: Set API key if authentication is required
export OPENAI_API_KEY="your-api-key-here"
```

### Basic Usage

```bash
# Set API URL (or use default http://127.0.0.1:8000)
export OPENAI_API_URL="http://your-server:8000"

# Run a benchmark with default settings (1 client, all concurrency values)
just bench my-experiment

# Run with 8 parallel clients
just bench my-experiment 8

# Run with custom concurrency values and 8 parallel clients
just bench-conc my-experiment 8 "4,8,16,32"

# Run smoke test to verify server connectivity
just smoke

# List all experiment results
just results

# Show results for a specific experiment
just results my-experiment

# Clean up zombie processes
just clean
```

For advanced options (request-rate, custom token lengths, etc.), use `run_bm.sh` directly:
```bash
./run_bm.sh -e my-experiment -t request-rate -r "1,2,4" -s 4 && \
python3 aggregate_results.py my-experiment
```

## Results Structure

Results are stored in:
- `bm_results/EXP_NAME/part1/`, `part2/`, etc. - Individual run results
- `bm_results/EXP_NAME/all-parts/` - Aggregated results (sum of throughputs, avg of latencies)

## Environment Variables

- `OPENAI_API_URL` - Base URL for the API endpoint (default: `http://127.0.0.1:8000`)
- `OPENAI_API_KEY` - API key for authentication (optional, can be empty)

These can be set in your shell or passed inline:
```bash
OPENAI_API_URL="http://your-server:8000" just bench my-experiment 8
```

## Advanced Usage

See `./run_bm.sh --help` for full options including:
- Custom input/output token lengths (`--itl`, `--otl`)
- Custom base URL (`-u` flag overrides `OPENAI_API_URL` env var)
- Request-rate benchmarking (`-t request-rate`)


# Results

