import argparse
from ray import serve
from ray.serve.llm import LLMConfig
from ray.llm._internal.serve.deployments.prefill_decode_disagg.prefill_decode_disagg import build_pd_openai_app


def main(pargs):
    
    print(f"Starting prefill deployment with {pargs.p_num} replicas of tp {pargs.p_tp}")
    print(f"Starting decode deployment with {pargs.d_num} replicas of tp {pargs.d_tp}")

    p_config = LLMConfig(
        model_loading_config={
            "model_id": "gptoss",
            "model_source": "openai/gpt-oss-120b",
        },
        deployment_config={
            "autoscaling_config": {
                "min_replicas": pargs.p_num,
                "max_replicas": pargs.p_num,
            },
        },
        engine_kwargs={
            "tensor_parallel_size": pargs.p_tp,
            "kv_cache_dtype": "fp8",
            "enable_prefix_caching": False,
            "kv_transfer_config": {
                "kv_connector": "NixlConnector",
                "kv_role": "kv_both",
            },
            "block_size": 128,
        },
        experimental_configs={
            "stream_batching_interval_ms": 0,
        },
        log_engine_metrics=True,
        runtime_env={
            "env_vars": {
                "VLLM_IS_PREFILL": "1",
                "NIXL_LOG_LEVEL": "DEBUG",
                # "UCX_LOG_LEVEL": "debug",
                "UCX_PROTO_INFO": "y",
                "UCX_TLS": "self,cuda_ipc,cuda_copy,cma,tcp",
            }
        }
    )
    
    d_config = LLMConfig(
        model_loading_config={
            "model_id": "gptoss",
            "model_source": "openai/gpt-oss-120b",
        },
        deployment_config={
            "autoscaling_config": {
                "min_replicas": pargs.d_num,
                "max_replicas": pargs.d_num,
            },
        },
        engine_kwargs={
            "tensor_parallel_size": pargs.d_tp,
            "kv_cache_dtype": "fp8",
            "enable_prefix_caching": False,
            "kv_transfer_config": {
                "kv_connector": "NixlConnector",
                "kv_role": "kv_both",
            },
            "block_size": 128,
        },
        experimental_configs={
            "stream_batching_interval_ms": 0,
        },
        runtime_env={
            "env_vars": {
                "NIXL_LOG_LEVEL": "DEBUG",
                # "UCX_LOG_LEVEL": "debug",
                "UCX_PROTO_INFO": "y",
                "UCX_TLS": "self,cuda_ipc,cuda_copy,cma,tcp",
            }
        },
        log_engine_metrics=True,
    )

    app = build_pd_openai_app({
        "prefill_config": p_config, 
        "decode_config": d_config,
        "proxy_deployment_config": {
            "autoscaling_config": {
                "min_replicas": pargs.p_num + pargs.d_num,
                "max_replicas": pargs.p_num + pargs.d_num,
            },
            "max_ongoing_requests": 1e5,
        }
    })
    
    serve.start(http_options={"host": "0.0.0.0"})
    serve.run(app, blocking=True)
    
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-ptp", "--p-tp", type=int, default=1)
    parser.add_argument("-pnum", "--p-num", type=int, default=4)
    parser.add_argument("-dtp", "--d-tp", type=int, default=2)
    parser.add_argument("-dnum", "--d-num", type=int, default=2)
    pargs = parser.parse_args()
    main(pargs)