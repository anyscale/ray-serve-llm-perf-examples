import argparse
from ray import serve
from ray.serve.llm import LLMConfig
from ray.llm._internal.serve.deployments.prefill_decode_disagg.prefill_decode_disagg import build_pd_openai_app
import ray
import pprint
import os

HEAD_NODE_RESOURCE_NAME = "node:__internal_head__"
BACKENDS = ["LIBFABRIC"]
# BACKENDS = ["UCX"]


def main(pargs):
    
    ray.init(
        runtime_env={
            "env_vars": {
                "LD_LIBRARY_PATH": "/opt/amazon/efa/lib:" + os.environ.get("LD_LIBRARY_PATH", ""),
                # "FI_PROVIDER": "efa",
                # "FI_EFA_USE_DEVICE_RDMA": "1",
                # "FI_EFA_ENABLE_SHM_TRANSFER": "0",  # Disable shared memory for cross-node
                # "FI_EFA_TX_SIZE": "16384",
                # "FI_EFA_RX_SIZE": "16384",
                # "FI_EFA_MR_CACHE_ENABLE": "0",
                # "FI_EFA_MR_MAX_CACHED_COUNT": "0",
                # "FI_LOG_LEVEL": "debug",  # Enable detailed libfabric logging
                # "FI_LOG_PROV": "efa",  # Enable EFA provider-specific logs
                # "NIXL_LOG_LEVEL": "DEBUG",
                # "UCX_LOG_LEVEL": "debug",
                # "UCX_PROTO_INFO": "y",
                # "UCX_TLS": "self,cuda_ipc,cuda_copy,cma,tcp",
                "VLLM_LOGGING_LEVEL": "DEBUG",
                "VLLM_ATTENTION_BACKEND": "FLASH_ATTN",
            }
        }
    )
    worker_nodes = [node for node in ray.nodes() if node["Alive"] and HEAD_NODE_RESOURCE_NAME not in node["Resources"]]
    
    if len(worker_nodes) < 2:
        raise ValueError("At least 2 worker nodes are required")
    
    p_node = worker_nodes[1]
    d_node = worker_nodes[1]
    # d_node = p_node
    
    
    print(f"Starting prefill deployment with {pargs.p_num} replicas of tp {pargs.p_tp} on {p_node['NodeName']}")
    print(f"Starting decode deployment with {pargs.d_num} replicas of tp {pargs.d_tp} on {d_node['NodeName']}")

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
        resources_per_bundle={"GPU": 1, f"node:{p_node['NodeName']}": 0.001},
        engine_kwargs={
            "tensor_parallel_size": pargs.p_tp,
            "enable_prefix_caching": False,
            "enforce_eager": True,
            "kv_transfer_config": {
                "kv_connector": "NixlConnector",
                "kv_role": "kv_both",
                "kv_connector_extra_config": {
                    "backends": BACKENDS
                }
            },
            "max_model_len": 16000,
            "block_size": 128,
        },
        experimental_configs={
            "stream_batching_interval_ms": 0,
        },
        log_engine_metrics=True,
        runtime_env={
            "env_vars": {
                "VLLM_IS_PREFILL": "1",
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
        resources_per_bundle={"GPU": 1, f"node:{d_node['NodeName']}": 0.001},
        engine_kwargs={
            "tensor_parallel_size": pargs.d_tp,
            "enforce_eager": True,
            "enable_prefix_caching": False,
            "kv_transfer_config": {
                "kv_connector": "NixlConnector",
                "kv_role": "kv_both",
                "kv_connector_extra_config": {
                    "backends": BACKENDS
                }
            },
            "max_model_len": 16000,
            "block_size": 128,
        },
        experimental_configs={
            "stream_batching_interval_ms": 0,
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