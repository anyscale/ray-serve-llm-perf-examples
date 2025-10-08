import argparse
from ray import serve
from ray.serve.llm import LLMConfig, build_openai_app


def main(pargs):

    llm_config = LLMConfig(
        model_loading_config={
            "model_id": "gptoss",
            "model_source": "openai/gpt-oss-120b",
        },
        deployment_config={
            "num_replicas": 1,
        },
        engine_kwargs={
            "tensor_parallel_size": pargs.tensor_parallel_size,
            "kv_cache_dtype": "fp8",
            "enable_prefix_caching": False,
            "block_size": 128,
        },
        experimental_configs={
            "stream_batching_interval_ms": 0,
        },
        log_engine_metrics=True,
    )

    app = build_openai_app({"llm_configs": [llm_config]})
    serve.run(app, blocking=True)
    
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-tp", "--tensor-parallel-size", type=int, default=2)
    pargs = parser.parse_args()
    main(pargs)