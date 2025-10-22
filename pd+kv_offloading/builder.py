import ray
from ray.serve.llm import LLMConfig, build_openai_app, build_pd_openai_app
from ray.llm._internal.common.dict_utils import deep_merge_dicts


def collocated_builder(config: dict):
    
    llm_config = LLMConfig(**config["llm_config"])
    ingress_deployment_config = config.get("ingress_deployment_config", {})
    
    
    app = build_openai_app({
        "llm_configs": [llm_config],
        "ingress_deployment_config": ingress_deployment_config,
    })
    return app


def pd_builder(config: dict):
    """Build PD disaggregation app with dynamic node placement."""
    
    # Get worker nodes with GPUs
    worker_nodes = [node for node in ray.nodes() 
                    if node["Alive"] and "GPU" in node["Resources"]]
    
    if len(worker_nodes) < 2:
        raise ValueError("At least 2 worker nodes are required for PD spread mode")
    
    p_node = worker_nodes[0]
    d_node = worker_nodes[1]
    
    # Build prefill config with node placement
    prefill_base = config["prefill_config"]
    p_tp_size = prefill_base["engine_kwargs"]["tensor_parallel_size"]
    prefill_config_dict = deep_merge_dicts(
        prefill_base,
        {
            "placement_group_config": {
                "bundles": [{"GPU": 1, f"node:{p_node['NodeName']}": 0.001} 
                           for _ in range(p_tp_size)],
            }
        }
    )
    prefill_config = LLMConfig(**prefill_config_dict)
    
    # Build decode config with node placement
    decode_base = config["decode_config"]
    d_tp_size = decode_base["engine_kwargs"]["tensor_parallel_size"]
    decode_config_dict = deep_merge_dicts(
        decode_base,
        {
            "placement_group_config": {
                "bundles": [{"GPU": 1, f"node:{d_node['NodeName']}": 0.001} 
                           for _ in range(d_tp_size)],
            }
        }
    )
    decode_config = LLMConfig(**decode_config_dict)
    
    # Build PD app
    pd_serving_args = {
        "prefill_config": prefill_config,
        "decode_config": decode_config,
        "proxy_deployment_config": config.get("proxy_deployment_config", {}),
        "ingress_deployment_config": config.get("ingress_deployment_config", {}),
    }
    
    return build_pd_openai_app(pd_serving_args)