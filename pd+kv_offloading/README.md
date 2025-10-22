# Composing KV Connectors with MultiConnector

## Introduction

KV cache management is critical for efficient LLM inference, but it operates at multiple layers. During inference, KV caches consume significant GPU memory—[LMCache](https://docs.lmcache.ai/) addresses this by offloading caches to CPU RAM or local storage, reducing GPU memory pressure and enabling larger batch sizes. In disaggregated prefill-decode (PD) architectures, where prefill and decode run on separate GPU instances, KV caches must be transferred between instances—NIXL handles these GPU-to-GPU transfers efficiently over high-speed networks like EFA.

This example demonstrates how you can compose multiple KV transfer backends using Ray Serve and vLLM's `MultiConnector`: combining NIXL for inter-instance transfers with LMCache for local offloading. We compare four configurations to show the overhead and benefits of each approach in isolation and combination.

## Hardware Setup

2× p5.48xlarge (16× H100 GPUs with EFA per instance)

## Configurations

We test four configurations to demonstrate composability and measure overhead:

1. **Collocated baseline (TP=4)**: Standard single-instance deployment with tensor parallelism
2. **Collocated + LMCache (TP=4)**: Adds LMCache offloading to extend KV cache capacity
3. **PD + NIXL (1P1D, TP=4 each)**: Disaggregated prefill-decode with cross node GPU-to-GPU KV transfer via NIXL
4. **PD + MultiConnector (1P1D, TP=4 each)**: Combines both NIXL (for P↔D transfer) and LMCache (for local offloading)

These configurations isolate the performance characteristics of each connector and demonstrate their composition via `MultiConnector`.

## Performance Results

Benchmark configuration: 320 requests, 5000 input tokens, 250 output tokens per request, concurrency=64. This uses random inputs to avoid cache hits—the goal is to measure baseline overhead when connectors don't provide caching benefits, establishing a performance floor.

| Configuration | Request Throughput (req/s) | Output Token Throughput (tok/s) | Mean TTFT (ms) | Mean TPOT (ms) |
|---------------|----------------------------|----------------------------------|----------------|----------------|
| Collocated baseline | 3.09 | 3092.52 | 1858.70 | 18.78 |
| Collocated + LMCache | 2.76 | 2759.43 | 2603.58 | 20.53 |
| PD + NIXL | 4.35 | 4354.03 | 1217.11 | 12.83 |
| PD + MultiConnector (NIXL + LMCache) | 3.70 | 3697.97 | 1481.06 | 15.20 |

**Key observations**: 
- PD disaggregation improves throughput and TTFT by specializing prefill and decode
- LMCache adds modest overhead (~10-15%) in this no-cache-hit scenario
- MultiConnector successfully composes both backends with acceptable overhead
- In real workloads with cache hits, LMCache's benefits outweigh this overhead by eliminating redundant prefill computation. For example, in multi-turn conversations where users return after minutes of inactivity, LMCache retrieves the conversation history from CPU rather than recomputing it, significantly reducing TTFT for follow-up requests

## Files in this Example

- **`builder.py`**: Custom builder functions (`collocated_builder`, `pd_builder`) that map YAML configs to Ray Serve applications. The PD builder dynamically discovers GPU nodes and pins prefill/decode to separate nodes.
- **`collocated_baseline.yaml`**: Baseline TP=4 deployment with no KV transfer
- **`collocated_lmcache.yaml`**: TP=4 deployment with LMCache for local offloading
- **`pd_nixl.yaml`**: PD disaggregation (1P1D, TP=4 each) with NIXL for GPU-to-GPU transfer
- **`pd_multiconnector.yaml`**: PD disaggregation with MultiConnector (NIXL + LMCache combined)
- **`bm_results/`**: Benchmark data for all configurations

## How to Run

Each configuration is defined in a YAML file using Ray Serve's config-driven deployment pattern with a custom builder.

**Deploy a configuration:**
```bash
# Collocated baseline
serve run collocated_baseline.yaml

# Collocated + LMCache
serve run collocated_lmcache.yaml

# PD + NIXL
serve run pd_nixl.yaml

# PD + MultiConnector (NIXL + LMCache)
serve run pd_multiconnector.yaml
```

**Run smoke test to verify deployment:**
```bash
bash ../prefill_decode/run_bm.sh -c 64 -e <experiment_name> --smoke
```

**Run full benchmark:**
```bash
bash ../prefill_decode/run_bm.sh -c 64 -e <experiment_name>
```

The benchmark uses `vllm bench serve` with 5000 input tokens and 250 output tokens per request.

## Key Takeaway

`MultiConnector` enables composing multiple KV transfer backends seamlessly. This allows combining NIXL's efficient inter-instance transfers with LMCache's capacity extension through offloading. The overhead is modest in worst-case scenarios (no cache hits), while real workloads with prefix reuse see substantial benefits from LMCache's caching capabilities combined with PD's throughput advantages.

<details>
<summary><b>Detailed Benchmark Results</b></summary>

### NIXL only (PD baseline)

```
============ Serving Benchmark Result ============
Successful requests:                     320       
Failed requests:                         0         
Maximum request concurrency:             64        
Request rate configured (RPS):           1000000000.00
Benchmark duration (s):                  73.50     
Total input tokens:                      2560000   
Total generated tokens:                  320000    
Request throughput (req/s):              4.35      
Output token throughput (tok/s):         4354.03   
Peak output token throughput (tok/s):    5196.00   
Peak concurrent requests:                71.00     
Total Token throughput (tok/s):          39186.31  
---------------Time to First Token----------------
Mean TTFT (ms):                          1217.11   
Median TTFT (ms):                        385.96    
P99 TTFT (ms):                           8162.56   
-----Time per Output Token (excl. 1st token)------
Mean TPOT (ms):                          12.83     
Median TPOT (ms):                        13.16     
P99 TPOT (ms):                           13.40     
---------------Inter-token Latency----------------
Mean ITL (ms):                           12.91     
Median ITL (ms):                         13.07     
P99 ITL (ms):                            23.72     
==================================================
```

### NIXL + LMCache (MultiConnector)

```
============ Serving Benchmark Result ============
Successful requests:                     320       
Failed requests:                         0         
Maximum request concurrency:             64        
Request rate configured (RPS):           1000000000.00
Benchmark duration (s):                  86.53     
Total input tokens:                      2560000   
Total generated tokens:                  320000    
Request throughput (req/s):              3.70      
Output token throughput (tok/s):         3697.97   
Peak output token throughput (tok/s):    5156.00   
Peak concurrent requests:                71.00     
Total Token throughput (tok/s):          33281.70  
---------------Time to First Token----------------
Mean TTFT (ms):                          1481.06   
Median TTFT (ms):                        519.26    
P99 TTFT (ms):                           9656.32   
-----Time per Output Token (excl. 1st token)------
Mean TPOT (ms):                          15.20     
Median TPOT (ms):                        15.65     
P99 TPOT (ms):                           15.94     
---------------Inter-token Latency----------------
Mean ITL (ms):                           15.28     
Median ITL (ms):                         13.50     
P99 ITL (ms):                            53.68     
==================================================
```

### Collocated + LMCache

```
============ Serving Benchmark Result ============
Successful requests:                     320       
Failed requests:                         0         
Maximum request concurrency:             64        
Request rate configured (RPS):           1000000000.00
Benchmark duration (s):                  115.97    
Total input tokens:                      2560000   
Total generated tokens:                  320000    
Request throughput (req/s):              2.76      
Output token throughput (tok/s):         2759.43   
Peak output token throughput (tok/s):    5249.00   
Peak concurrent requests:                78.00     
Total Token throughput (tok/s):          24834.89  
---------------Time to First Token----------------
Mean TTFT (ms):                          2603.58   
Median TTFT (ms):                        1939.92   
P99 TTFT (ms):                           10506.51  
-----Time per Output Token (excl. 1st token)------
Mean TPOT (ms):                          20.53     
Median TPOT (ms):                        21.00     
P99 TPOT (ms):                           22.78     
---------------Inter-token Latency----------------
Mean ITL (ms):                           20.53     
Median ITL (ms):                         13.39     
P99 ITL (ms):                            178.27    
==================================================
```

### Collocated baseline

```
============ Serving Benchmark Result ============
Successful requests:                     320       
Failed requests:                         0         
Maximum request concurrency:             64        
Request rate configured (RPS):           1000000000.00
Benchmark duration (s):                  103.48    
Total input tokens:                      2560000   
Total generated tokens:                  320000    
Request throughput (req/s):              3.09      
Output token throughput (tok/s):         3092.52   
Peak output token throughput (tok/s):    5223.00   
Peak concurrent requests:                79.00     
Total Token throughput (tok/s):          27832.68  
---------------Time to First Token----------------
Mean TTFT (ms):                          1858.70   
Median TTFT (ms):                        1381.70   
P99 TTFT (ms):                           8109.22   
-----Time per Output Token (excl. 1st token)------
Mean TPOT (ms):                          18.78     
Median TPOT (ms):                        19.11     
P99 TPOT (ms):                           20.27     
---------------Inter-token Latency----------------
Mean ITL (ms):                           18.78     
Median ITL (ms):                         13.37     
P99 ITL (ms):                            139.65    
==================================================
```

</details>

