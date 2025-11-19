"""
DeepSeek-V3 decode-only deployment with DP=16 and EP.

Run: `python decode.py`
"""

from ray.serve.llm import LLMConfig
from ray.llm._internal.serve.serving_patterns.data_parallel.dp_server import (
    build_openai_dp_app,
)
from ray import serve


decode_config = LLMConfig(
    model_loading_config={
        "model_id": "dsv3",
        "model_source": "deepseek-ai/DeepSeek-V3-0324",
    },
    engine_kwargs={
        "max_model_len": 10000,
        "data_parallel_size": 16,
        "tensor_parallel_size": 1,
        "enable_expert_parallel": True,
    },
    experimental_configs={
        "dp_size_per_node": 8,
    },
    runtime_env={
        "env_vars": {
            "VLLM_USE_DEEP_GEMM": "1",
            "VLLM_ALL2ALL_BACKEND": "deepep_low_latency",
        }
    },
)

app = build_openai_dp_app(decode_config)
serve.run(app, blocking=True)