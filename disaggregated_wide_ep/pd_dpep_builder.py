"""
Builder for combining prefill and decode configs when both are data parallel deployments.

This builder handles:
- Data parallel prefill deployments
- Data parallel decode deployments  
- DPRankAssigner setup for both prefill and decode
- Automatic node partitioning between prefill and decode
"""

import logging
from typing import Dict, Any, List

import ray
from ray import serve
from ray.serve.deployment import Application
from ray.llm._internal.common.dict_utils import deep_merge_dicts
from ray.llm._internal.serve.serving_patterns.prefill_decode.builder import PDServingArgs
from ray.llm._internal.serve.serving_patterns.data_parallel.dp_server import build_dp_deployment
from ray.llm._internal.serve.serving_patterns.data_parallel.dp_rank_assigner import DPRankAssigner
from ray.llm._internal.serve.core.ingress.ingress import make_fastapi_ingress
from ray.llm._internal.serve.core.server.builder import build_llm_deployment
from ray.serve.llm import LLMConfig

# Import custom classes from builder.py
from builder import DPServerWithPDInfo

logger = logging.getLogger(__name__)



def build_pd_dp_openai_app(config: Dict[str, Any]) -> Application:
    """
    Build a prefill-decode OpenAI app where both prefill and decode are data parallel.
    
    NOTE: Automatic node partitioning is currently disabled by default because
    Ray Serve doesn't support label_selector in ray_actor_options. To enable
    experimental node partitioning using custom resources, set 
    enable_auto_node_partition: true (requires manual node setup).
    
    Args:
        config: Dict containing:
            - prefill_config: LLM config with data_parallel_size > 1
            - decode_config: LLM config with data_parallel_size > 1
            - proxy_cls_config: Proxy server configuration
            - proxy_deployment_config: Optional proxy deployment overrides
            - ingress_deployment_config: Optional ingress deployment overrides
            - enable_auto_node_partition: Enable experimental node partitioning (default: False)
            - nodes_per_deployment: Number of nodes per deployment if auto-partition enabled
            - prefill_node_constraints: Manual node constraints (requires custom resources)
            - decode_node_constraints: Manual node constraints (requires custom resources)
    
    Returns:
        Ray Serve Application with prefill/decode data parallel deployments
    """
    
    # Validate and parse config
    pd_config = PDServingArgs.model_validate(config)
    
    # Build prefill deployment with DP using official builder
    # We use DPServerWithPDInfo to add pd_info() method for P2P NCCL connector
    prefill_deployment = _build_dp_deployment_with_pd_info(
        config=pd_config.prefill_config,
        deployment_name="Prefill",
    )
    
    # Build decode deployment with DP using official builder
    decode_deployment = _build_dp_deployment_with_pd_info(
        config=pd_config.decode_config,
        deployment_name="Decode",
    )
    
    # Build PDProxyServer
    proxy_cls_config = pd_config.proxy_cls_config
    proxy_options = proxy_cls_config.proxy_cls.get_deployment_options(
        pd_config.prefill_config, 
        pd_config.decode_config
    )
    
    if pd_config.proxy_deployment_config:
        proxy_options = deep_merge_dicts(
            proxy_options, 
            pd_config.proxy_deployment_config
        )
    
    proxy_deployment = (
        serve.deployment(proxy_cls_config.proxy_cls)
        .options(**proxy_options)
        .bind(
            prefill_server=prefill_deployment,
            decode_server=decode_deployment,
            **proxy_cls_config.proxy_extra_kwargs,
        )
    )
    
    # Build ingress
    ingress_cls_config = pd_config.ingress_cls_config
    ingress_options = ingress_cls_config.ingress_cls.get_deployment_options(
        [pd_config.prefill_config, pd_config.decode_config]
    )
    
    if pd_config.ingress_deployment_config:
        ingress_options = deep_merge_dicts(
            ingress_options, 
            pd_config.ingress_deployment_config
        )
    
    ingress_cls = make_fastapi_ingress(ingress_cls_config.ingress_cls)
    
    return serve.deployment(ingress_cls, **ingress_options).bind(
        llm_deployments=[proxy_deployment],
        **ingress_cls_config.ingress_extra_kwargs,
    )


def _build_dp_deployment_with_pd_info(
    config: LLMConfig,
    deployment_name: str,
) -> Application:
    """
    Build a DP deployment using DPServerWithPDInfo (thin wrapper around official build_dp_deployment).
    
    This is identical to ray.llm._internal.serve.serving_patterns.data_parallel.dp_server.build_dp_deployment
    except it uses DPServerWithPDInfo instead of DPServer to add pd_info() method for P2P NCCL.
    
    Args:
        config: LLM config with DP settings (must NOT have autoscaling_config in deployment_config)
        deployment_name: "Prefill" or "Decode" for logging
    
    Returns:
        Configured deployment
    """
    dp_size = config.engine_kwargs.get("data_parallel_size", 1)
    if dp_size == 1:
        raise ValueError(
            f"{deployment_name} requires data_parallel_size > 1 for DP deployment."
        )

    # Get dp_size_per_node from experimental_configs (official pattern)
    dp_size_per_node = config.experimental_configs.get("dp_size_per_node", None)

    # Create DPRankAssigner (official pattern)
    dp_rank_assigner = DPRankAssigner.bind(
        dp_size=dp_size, dp_size_per_node=dp_size_per_node
    )

    # Build deployment with DPServerWithPDInfo
    # Note: SessionAwareRequestRouter should be configured in the YAML deployment_config
    return build_llm_deployment(
        config,
        name_prefix=f"{deployment_name}:",
        bind_kwargs=dict(dp_rank_assigner=dp_rank_assigner),
        deployment_cls=DPServerWithPDInfo,
    )


