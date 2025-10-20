import argparse
import os
import ray
import pprint
from ray import serve
from ray.serve.llm import LLMConfig, build_openai_app, build_pd_openai_app
from ray.llm._internal.common.dict_utils import deep_merge_dicts


HEAD_NODE_RESOURCE_NAME = "node:__internal_head__"


# Help message for argument parser
DESC = """
Unified launcher for GPT-OSS in different deployment modes.

Examples:
  # Collocated mode with TP=2
  python launch_gptoss.py --mode collocated --tp 2
  
  # PD pack mode (single node) with UCX
  python launch_gptoss.py --mode pd-pack --p-num 4 --p-tp 1 --d-num 2 --d-tp 2 --use-ucx
  
  # PD spread mode (multi-node) with libfabric
  python launch_gptoss.py --mode pd-spread --p-num 4 --p-tp 1 --d-num 2 --d-tp 2 --use-libfabric
  
  # Use a different model
  python launch_gptoss.py --mode collocated --tp 2 --model-id llama3 --model-source meta-llama/Llama-3-70B
"""


# Base configuration shared across all modes
# We are setting `max_model_len` to 16000, because when we deploy this model in 
# TP=1, the full model length for even one request would exceed the kv-cache 
# size that is available on the GPU. 
BASE_ENGINE_KWARGS = {
    "max_model_len": 16000,
}

# We are setting `stream_batching_interval_ms` to 0, because we want to look at 
# the standard deviation in latency during our benchmark, and batching would 
# introduce additional variance. Turning up this value would improve latency a 
# bit, but we don't want to do that for now.
BASE_EXPERIMENTAL_CONFIGS = {
    "stream_batching_interval_ms": 0,
}

def get_libfabric_env_vars(verbose=False):
    """Return environment variables for libfabric/EFA configuration."""
    env_vars = {
        "LD_LIBRARY_PATH": "/opt/amazon/efa/lib:" + os.environ.get("LD_LIBRARY_PATH", ""),
        # "FI_PROVIDER": "efa",
        # "FI_EFA_USE_DEVICE_RDMA": "0",  # DISABLE GPU Direct - not available on this system
        # "FI_EFA_ENABLE_SHM_TRANSFER": "0",  # Disable shared memory for cross-node
        # "FI_EFA_MR_CACHE_ENABLE": "1",
        # "FI_EFA_MR_MAX_CACHED_COUNT": "0",  # Unlimited
        # "FI_MR_CACHE_MAX_COUNT": "0",  # Also set generic libfabric MR cache
    }
    if verbose:
        env_vars["FI_LOG_LEVEL"] = "debug"
        env_vars["FI_LOG_PROV"] = "efa"
    return env_vars


def get_ucx_env_vars(verbose=False):
    """Return environment variables for UCX configuration."""
    env_vars = {
        "UCX_TLS": "all"
    }
    if verbose:
        env_vars["UCX_LOG_LEVEL"] = "debug"
        env_vars["UCX_PROTO_INFO"] = "y"
    return env_vars



def build_llm_config(model_id, model_source, overrides):
    """Build LLMConfig from base configuration plus overrides."""
    config = {
        "model_loading_config": {
            "model_id": model_id,
            "model_source": model_source,
        },
        "engine_kwargs": BASE_ENGINE_KWARGS.copy(),
        "experimental_configs": BASE_EXPERIMENTAL_CONFIGS.copy(),
    }
    config = deep_merge_dicts(config, overrides)
    print(f"LLMConfig: {pprint.pformat(config)}")
    return LLMConfig(**config)


def get_kv_transfer_config(backends):
    """Build KV transfer configuration for PD modes."""
    return {
        "kv_connector": "NixlConnector",
        "kv_role": "kv_both",
        "kv_connector_extra_config": {
            "backends": backends
        }
    }


def get_base_env_vars(use_libfabric, verbose=False):
    """Get base environment variables based on backend choice."""
    env_vars = {}
    if verbose:
        env_vars["NIXL_LOG_LEVEL"] = "DEBUG"
        env_vars["VLLM_LOGGING_LEVEL"] = "DEBUG"
    if use_libfabric:
        env_vars.update(get_libfabric_env_vars(verbose))
    else:
        env_vars.update(get_ucx_env_vars(verbose))
    return env_vars    


def launch_collocated(pargs):
    """Launch collocated (tensor parallel only) deployment."""
    ray.init()
    print(f"Launching collocated deployment with \
        TP={pargs.tensor_parallel_size}...")
    print(f"Model: {pargs.model_source} (ID: {pargs.model_id})")
    print("="*80)
    
    
    worker_nodes = [node for node in ray.nodes() \
            if node["Alive"] and "GPU" in node["Resources"]]
    node = worker_nodes[0]
    node_resource = {f"node:{node['NodeName']}": 0.001}
    
    
    llm_config = build_llm_config(
        pargs.model_id,
        pargs.model_source,
        {
            "deployment_config": {
                "num_replicas": pargs.num,
            },
            "engine_kwargs": {
                "tensor_parallel_size": pargs.tensor_parallel_size,
            },
            "placement_group_config": {
                "bundles": [
                    {"GPU": 1, **node_resource} for _ in range(pargs.tensor_parallel_size)
                ],
            },
        }
    )
    
    # NOTE: HARDCODE to 16, to make our comparison fair.
    ingress_options_override = {
        "placement_group_bundles": [{"CPU": 1, **node_resource}],
        "autoscaling_config": {
            "min_replicas": 16,
            "max_replicas": 16,
        },
    }

    app = build_openai_app({
        "llm_configs": [llm_config],
        "ingress_deployment_config": ingress_options_override
    })

    serve.run(app, blocking=True)


def launch_pd(pargs):
    """Launch prefill-decode disaggregation across multiple nodes (spread)."""
    backends = ["LIBFABRIC"] if pargs.use_libfabric else ["UCX"]
    
    # Build ray runtime environment
    ray_env_vars = get_base_env_vars(pargs.use_libfabric, pargs.verbose)
    
    # Initialize Ray with runtime environment
    ray.init(runtime_env={"env_vars": ray_env_vars})
    is_packed = (pargs.mode == "pd-pack")
    
    worker_nodes = [node for node in ray.nodes() \
        if node["Alive"] and "GPU" in node["Resources"]]
    
    if not is_packed and len(worker_nodes) < 2:
        raise ValueError("At least 2 worker nodes are required for spread mode")
    
    if is_packed:
        p_node = worker_nodes[0]
        d_node = worker_nodes[0]
    else:
        # Use first two worker nodes for prefill and decode
        p_node = worker_nodes[0]
        d_node = worker_nodes[1]
    
    print(f"Launching PD {'packed' if is_packed else 'spread'} mode:")
    print(f"  Model: {pargs.model_source} (ID: {pargs.model_id})")
    print(f"  Prefill: {pargs.p_num} replicas with TP={pargs.p_tp} \
        on {p_node['NodeName']}")
    print(f"  Decode: {pargs.d_num} replicas with TP={pargs.d_tp} \
        on {d_node['NodeName']}")
    
    print("="*80)
    print("Prefill:")
    print("="*80)
    p_config = build_llm_config(
        pargs.model_id,
        pargs.model_source,
        {
            "deployment_config": {
                "autoscaling_config": {
                    "min_replicas": pargs.p_num,
                    "max_replicas": pargs.p_num,
                },
            },
            "placement_group_config": {
                "bundles": [{"GPU": 1, f"node:{p_node['NodeName']}": 0.001} for _ in range(pargs.p_tp)],
            },
            "engine_kwargs": {
                "tensor_parallel_size": pargs.p_tp,
                "kv_transfer_config": get_kv_transfer_config(backends),
            },
            "runtime_env": {
                "env_vars": {
                    "VLLM_IS_PREFILL": "1",
                }
            }
        }
    )
    
    print("="*80)
    print("Decode:")
    print("="*80)
    d_config = build_llm_config(
        pargs.model_id,
        pargs.model_source,
        {
            "deployment_config": {
                "autoscaling_config": {
                    "min_replicas": pargs.d_num,
                    "max_replicas": pargs.d_num,
                },
            },
            "placement_group_config": {
                "bundles": [{"GPU": 1, f"node:{d_node['NodeName']}": 0.001} for _ in range(pargs.d_tp)],
            },
            "engine_kwargs": {
                "tensor_parallel_size": pargs.d_tp,
                "kv_transfer_config": get_kv_transfer_config(backends),
            },
        }
    )
    print("="*80)
    
    # NOTE: HARDCODE to 16 and if pack they will be on the same node as P or D.
    proxy_deployment_config = {
        "autoscaling_config": {
            "min_replicas": 16,
            "max_replicas": 16,
        },
        "max_ongoing_requests": 1e5,
    }    

    # NOTE: HARDCODE to 16, to make our comparison fair.
    ingress_options = {
        "autoscaling_config": {
            "min_replicas": 16,
            "max_replicas": 16,
        },
    }
    
    # Make sure both Proxy and ingress map to the p node if packed
    if is_packed:
        proxy_deployment_config["placement_group_bundles"] = [
            {"CPU": 1, f"node:{p_node['NodeName']}": 0.001}]
        ingress_options["placement_group_bundles"] = [
            {"CPU": 1, f"node:{p_node['NodeName']}": 0.001}]
    
    pd_serving_args = {
        "prefill_config": p_config, 
        "decode_config": d_config,
        "proxy_deployment_config": proxy_deployment_config,
        "ingress_deployment_config": ingress_options,
    }

    app = build_pd_openai_app(pd_serving_args)
    
    serve.start(http_options={"host": "0.0.0.0"})
    serve.run(app, blocking=True)


def setup_arg_parser():
    """Setup and return the argument parser."""
    parser = argparse.ArgumentParser(
        description="Unified launcher for GPT-OSS in different deployment modes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=DESC
    )
    
    parser.add_argument(
        "--mode",
        type=str,
        required=True,
        choices=["collocated", "pd-pack", "pd-spread"],
        help="Deployment mode: collocated (TP only), pd-pack (single node PD), pd-spread (multi-node PD)"
    )
    
    # Model configuration
    parser.add_argument(
        "--model-id",
        type=str,
        default="gptoss",
        help="Model identifier for the deployment (default: gptoss)"
    )
    parser.add_argument(
        "--model-source",
        type=str,
        default="openai/gpt-oss-120b",
        help="Model source path or name (default: openai/gpt-oss-120b)"
    )
    
    
    # Collocated mode arguments
    parser.add_argument(
        "--num",
        type=int,
        default=1,
        help="Number of replicas for collocated mode (default: 1)"
    )
    
    parser.add_argument(
        "--tp", "--tensor-parallel-size",
        dest="tensor_parallel_size",
        type=int,
        default=2,
        help="Tensor parallel size for collocated mode (default: 2)"
    )
    
    # PD mode arguments
    parser.add_argument(
        "--p-num",
        type=int,
        default=2,
        help="Number of prefill replicas (default: 2)"
    )
    parser.add_argument(
        "--p-tp",
        type=int,
        default=1,
        help="Prefill tensor parallel size (default: 1)"
    )
    parser.add_argument(
        "--d-num",
        type=int,
        default=1,
        help="Number of decode replicas (default: 1)"
    )
    parser.add_argument(
        "--d-tp",
        type=int,
        default=2,
        help="Decode tensor parallel size (default: 2)"
    )
    
    # Backend selection (mutually exclusive)
    backend_group = parser.add_mutually_exclusive_group()
    backend_group.add_argument(
        "--use-ucx",
        action="store_true",
        default=True,
        help="Use UCX backend for KV transfer (default backend)"
    )
    backend_group.add_argument(
        "--use-libfabric",
        action="store_true",
        help="Use libfabric/EFA backend for KV transfer"
    )
    
    # Verbose logging
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose debug logging (NIXL, UCX, libfabric, VLLM)"
    )
    
    return parser


def main(pargs):
    """Main entry point for launching GPT-OSS deployments."""
        
    if pargs.mode == "collocated":
        launch_collocated(pargs)
    elif pargs.mode.startswith("pd"):
        if pargs.p_tp > pargs.d_tp:
            raise ValueError("Prefill tensor parallel size must be less than or equal to decode tensor parallel size. This is a constaint set by the NixlConnector in vLLM.")
        launch_pd(pargs)
    else:
        raise ValueError(f"Unknown mode: {pargs.mode}")


if __name__ == "__main__":
    parser = setup_arg_parser()
    pargs = parser.parse_args()
    
    # If neither backend is specified, default to UCX
    if not pargs.use_libfabric and not pargs.use_ucx:
        pargs.use_ucx = True
    
    main(pargs)
