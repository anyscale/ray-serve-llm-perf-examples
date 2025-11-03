In this benchmark our goal is to do a comparison between vllm and ray serve + vllm in a single replica case, to establish the overhead added from the orchestration layer. The idea is that the overhead should be small so that we get the benefits of optimizations from the engine, hardware, quanitization, etc. 


To do this effectively, we pick a small model on H100 gpus to make sure the latency and throughput numbers are high with the goal of pushing the limits of ray serve to keep up with this higher SLA and throughput requirements. Towards this mean this is our reference vllm run:

```
vllm serve openai/gpt-oss-20b --port 8192     --tensor-parallel-size 8    --disable-log-requests     --disable-uvicorn-access-log     --kv-cache-dtype "fp8" --async-scheduling  --no-enable-prefix-caching
```

We benchmark gptoss-20B, since it is small and can be very low latency on H100s. We make use of async scheduling, fp8 kv cache and TP8 to make sure the reference has very low latency performance (not caring about throughput).

In this benchmark we also compare Ray open source with Anyscale runtime optimizations to get a good understanding of the differences in this regimes of benchmarking. 


### Key benchmark considerations

To accurately measure horizontal scaling, you must account for several factors:

- **Disable prefix caching**: The engine's prefix caching capability can confound results. When prefix caching is enabled, request content and cache hit patterns can impact results in non-intuitive ways, even with randomly generated requests if the seed is shared across runs. These benchmarks pass `enable_prefix_caching=False` to the engine kwargs.


