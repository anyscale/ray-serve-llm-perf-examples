"""
Simple Qwen decode-only deployment with DP=8 and EP=8.
No prefill-decode disaggregation - just DP+EP decode.
"""

from ray.serve.llm import LLMConfig
from ray.llm._internal.serve.serving_patterns.data_parallel.dp_server import (
    build_openai_dp_app,
)
from ray import serve


# Qwen decode configuration with DP=8 and EP=8
decode_config = LLMConfig(
    model_loading_config={
        "model_id": "qwen",
        "model_source": "/hf_models/Qwen/Qwen3-235B-A22B-Instruct-2507-FP8/",
    },
    deployment_config={
        "ray_actor_options": {
            "resources": {"decode": 1},
        },
    },
    engine_kwargs={
        "max_model_len": 10000,
        "data_parallel_size": 8,
        "tensor_parallel_size": 1,
        "load_format": "dummy",
        "enable_expert_parallel": True,
        "compilation_config": {
            "cudagraph_mode": "PIECEWISE",
            "cudagraph_capture_sizes": [1],
        },
    },
    experimental_configs={
        "dp_size_per_node": 8,  # All 8 DP ranks on same node
        "stream_batching_interval_ms": 0,
    },
)

# Build the DP + OpenAI app
app = build_openai_dp_app(decode_config)
serve.run(app, blocking=True)