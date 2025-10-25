import ray
from ray.serve.llm import LLMConfig, build_openai_app, build_pd_openai_app
from ray.llm._internal.common.dict_utils import deep_merge_dicts


def builder(config: dict):
    
    llm_config = LLMConfig(**config["llm_config"])
    # ingress_deployment_config = config.get("ingress_deployment_config", {})
    
    
    app = build_openai_app({
        "llm_configs": [llm_config],
        # "ingress_deployment_config": ingress_deployment_config,
    })
    return app