import argparse
import os
import sys
from ray import serve
from ray.serve.llm import LLMConfig, build_openai_app
from ray.llm._internal.common.callbacks.base import CallbackConfig
from clear_cache import clear_caches

MODEL_TO_TENSOR_PARALLEL_SIZE = {
    "llama-3-8b": 1,
    "llama-3-70b": 4,
    "qwen-3-235b": 8,
}

EXPERIMENT_NAME_TO_MODEL_SOURCE = {
    "llama-3-8b": {
        "baseline": "meta-llama/Meta-Llama-3-8B",
        "runai_streamer": "s3://ahao-runai-east1/Meta-Llama-3-8B/",
        "compile_cache": "meta-llama/Meta-Llama-3-8B",
        "all": "s3://ahao-runai-east1/Meta-Llama-3-8B/"
    },
    "llama-3-70b": {
        "baseline": "meta-llama/Meta-Llama-3-70B",
        "runai_streamer": "s3://ahao-runai-east1/Meta-Llama-3-70B/",
        "runai_streamer_sharded": "s3://ahao-runai-east1/Meta-Llama-3-70B-sharded/",
        "compile_cache": "meta-llama/Meta-Llama-3-70B",
        "all": "s3://ahao-runai-east1/Meta-Llama-3-70B-sharded/"
    },
    "qwen-3-235b": {
        "baseline": "Qwen/Qwen3-235B-A22B",
        "runai_streamer": "s3://ahao-runai-east1/Qwen3-235B-A22B/",
        "runai_streamer_sharded": "s3://ahao-runai-east1/Qwen3-235B-A22B-sharded/",
        "compile_cache": "Qwen/Qwen3-235B-A22B",
        "all": "s3://ahao-runai-east1/Qwen3-235B-A22B-sharded/"
    }
}

MODEL_TO_CALLBACK_KWARGS = {
    "llama-3-8b": {"paths": [("s3://ahao-runai-east1/llama-3-8b-cache", "/home/ray/.cache/vllm/torch_compile_cache/s3_cache")]},
    "llama-3-70b": {"paths": [("s3://ahao-runai-east1/llama-3-70b-cache", "/home/ray/.cache/vllm/torch_compile_cache/s3_cache")]},
    "qwen-3-235b": {"paths": [("s3://ahao-runai-east1/Qwen3-235B-A22B-cache", "/home/ray/.cache/vllm/torch_compile_cache/s3_cache")]},
}

EXPERIMENT_TO_LOAD_FORMAT = {
    "baseline": None,
    "runai_streamer": "runai_streamer",
    "runai_streamer_sharded": "runai_streamer_sharded",
    "compile_cache": None,
    "all": "runai_streamer_sharded",
}

def run_experiment(model_name, experiment_name):
    clear_caches()
    callback_config = {
        "callback_class": "ray.llm._internal.common.callbacks.cloud_downloader.CloudDownloader",
        "callback_kwargs": MODEL_TO_CALLBACK_KWARGS[model_name],
    } if experiment_name in ["compile_cache", "all"] else CallbackConfig()

    llm_config = LLMConfig(
        model_loading_config={
            "model_id": "model",
            "model_source": EXPERIMENT_NAME_TO_MODEL_SOURCE[model_name][experiment_name],
        },
        deployment_config={
            "autoscaling_config": {
                "target_ongoing_requests": 1,
                "min_replicas": 0,
                "initial_replicas": 0,
                "max_replicas": 1,
            }
        },
        callback_config=callback_config,
        accelerator_type="H100",
        engine_kwargs={
            "tensor_parallel_size": MODEL_TO_TENSOR_PARALLEL_SIZE[model_name],
            "compilation_config": {
                "cache_dir": "/home/ray/.cache/vllm/torch_compile_cache/s3_cache",
            }
        },
        load_format = EXPERIMENT_TO_LOAD_FORMAT[experiment_name]
        if load_format:
            engine_kwargs["load_format"] = load_format
        runtime_env={"env_vars": {
            # "AWS_ACCESS_KEY_ID": os.environ["AWS_ACCESS_KEY_ID"],
            # "AWS_SECRET_ACCESS_KEY": os.environ["AWS_SECRET_ACCESS_KEY"],
            # "AWS_SESSION_TOKEN": os.environ["AWS_SESSION_TOKEN"],
        }},
    )

    app = build_openai_app({"llm_configs": [llm_config]})
    serve.run(app, blocking=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run Ray Serve LLM experiments with different model configurations"
    )
    parser.add_argument(
        "model_name",
        choices=list(MODEL_TO_TENSOR_PARALLEL_SIZE.keys()),
        help="Model name to use for the experiment"
    )
    parser.add_argument(
        "experiment_name",
        help="Experiment name to run (e.g., baseline, runai_streamer, compile_cache, all)"
    )
    
    args = parser.parse_args()
    
    # Validate that the experiment_name is valid for the given model_name
    valid_experiments = list(EXPERIMENT_NAME_TO_MODEL_SOURCE[args.model_name].keys())
    if args.experiment_name not in valid_experiments:
        print(f"Error: '{args.experiment_name}' is not a valid experiment for model '{args.model_name}'")
        print(f"Valid experiments for {args.model_name}: {', '.join(valid_experiments)}")
        sys.exit(1)
    
    run_experiment(args.model_name, args.experiment_name)
