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
from ray.llm._internal.serve.serving_patterns.data_parallel.dp_rank_assigner import DPRankAssigner
from ray.llm._internal.serve.core.ingress.ingress import make_fastapi_ingress
from ray.serve.llm import LLMConfig, build_llm_deployment

# Import custom classes from builder.py
from builder import DPServerWithPDInfo

logger = logging.getLogger(__name__)


def _get_available_nodes() -> List[str]:
    """
    Get list of available GPU-enabled node IDs in the cluster.
    
    Returns:
        List of node IDs that are alive and have GPUs
    """
    try:
        nodes = ray.nodes()
        gpu_nodes = []
        
        for node in nodes:
            if not node.get("Alive", False):
                continue
            
            resources = node.get("Resources", {})
            if resources.get("GPU", 0) > 0:
                node_id = node["NodeID"]
                gpu_nodes.append(node_id)
        
        logger.info(f"Found {len(gpu_nodes)} GPU-enabled nodes in cluster")
        return gpu_nodes
    
    except Exception as e:
        logger.warning(f"Failed to get node info: {e}. Node constraints will not be applied.")
        return []


def _partition_nodes_for_pd(
    prefill_dp_size: int,
    decode_dp_size: int,
    nodes_per_deployment: int = 2
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Automatically partition cluster nodes between prefill and decode deployments.
    
    Args:
        prefill_dp_size: Data parallel size for prefill
        decode_dp_size: Data parallel size for decode
        nodes_per_deployment: Number of nodes to allocate per deployment (default: 2)
    
    Returns:
        Tuple of (prefill_constraints, decode_constraints)
    """
    gpu_nodes = _get_available_nodes()
    
    if len(gpu_nodes) < nodes_per_deployment * 2:
        logger.warning(
            f"Not enough GPU nodes for partitioning. "
            f"Need {nodes_per_deployment * 2}, found {len(gpu_nodes)}. "
            f"Node constraints will not be applied."
        )
        return None, None
    
    # Split nodes: first N for prefill, next N for decode
    prefill_nodes = gpu_nodes[:nodes_per_deployment]
    decode_nodes = gpu_nodes[nodes_per_deployment:nodes_per_deployment * 2]
    
    logger.info(
        f"Partitioning nodes for PD deployment:\n"
        f"  Prefill ({prefill_dp_size} replicas) -> {len(prefill_nodes)} nodes: {prefill_nodes}\n"
        f"  Decode ({decode_dp_size} replicas) -> {len(decode_nodes)} nodes: {decode_nodes}"
    )
    
    prefill_constraints = {"node_ids": prefill_nodes}
    decode_constraints = {"node_ids": decode_nodes}
    
    return prefill_constraints, decode_constraints


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
    
    # Get DP sizes
    prefill_dp_size = pd_config.prefill_config.engine_kwargs.get("data_parallel_size", 1)
    decode_dp_size = pd_config.decode_config.engine_kwargs.get("data_parallel_size", 1)
    
    # Check for manual node constraints override
    prefill_node_constraints = config.get("prefill_node_constraints")
    decode_node_constraints = config.get("decode_node_constraints")
    
    # Automatic node partitioning is disabled because Ray Serve doesn't support
    # label_selector in ray_actor_options (only supports: num_cpus, num_gpus, 
    # resources, memory, runtime_env, accelerator_type)
    if prefill_node_constraints is None and decode_node_constraints is None:
        enable_auto_partition = config.get("enable_auto_node_partition", False)
        if enable_auto_partition:
            nodes_per_deployment = config.get("nodes_per_deployment", 2)
            logger.warning(
                f"Automatic node partitioning is EXPERIMENTAL and requires manual "
                f"node setup with custom resources. See documentation for details."
            )
            
            prefill_node_constraints, decode_node_constraints = _partition_nodes_for_pd(
                prefill_dp_size=prefill_dp_size,
                decode_dp_size=decode_dp_size,
                nodes_per_deployment=nodes_per_deployment
            )
        else:
            logger.info(
                "Node partitioning disabled. Replicas will be scheduled by Ray's default "
                "policy across all available GPU nodes."
            )
            prefill_node_constraints = None
            decode_node_constraints = None
    else:
        logger.info("Using manually specified node constraints (requires custom resources)")
    
    # Build prefill deployment with DP
    prefill_deployment = _build_dp_deployment(
        config=pd_config.prefill_config,
        deployment_name="Prefill",
        node_constraints=prefill_node_constraints
    )
    
    # Build decode deployment with DP
    decode_deployment = _build_dp_deployment(
        config=pd_config.decode_config,
        deployment_name="Decode",
        node_constraints=decode_node_constraints
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


def _build_dp_deployment(
    config: LLMConfig,
    deployment_name: str,
    node_constraints: Dict[str, Any] = None,
) -> Application:
    """
    Build a single DP deployment (prefill or decode).
    
    Args:
        config: LLM config with DP settings
        deployment_name: "Prefill" or "Decode"
        node_constraints: Optional dict with 'node_ips' or 'node_ids' to constrain scheduling
    
    Returns:
        Configured deployment
    """
    
    # Extract DP configuration
    dp_size = config.engine_kwargs.get("data_parallel_size", 1)
    dp_size_per_node = config.experimental_configs.get("dp_size_per_node")
    
    if dp_size <= 1:
        raise ValueError(
            f"{deployment_name} deployment requires data_parallel_size > 1, got {dp_size}"
        )
    
    # Validate dp_size_per_node if provided
    if dp_size_per_node is not None:
        if dp_size % dp_size_per_node != 0:
            raise ValueError(
                f"{deployment_name}: data_parallel_size ({dp_size}) must be divisible by "
                f"dp_size_per_node ({dp_size_per_node})"
            )
        logger.info(
            f"{deployment_name}: Using node-aware DP rank assignment with "
            f"dp_size={dp_size}, dp_size_per_node={dp_size_per_node}"
        )
    else:
        logger.warning(
            f"{deployment_name}: dp_size_per_node not set. Using random rank assignment. "
            f"For multi-node Expert Parallel deployments, this may cause NCCL hangs!"
        )
    
    # Remove autoscaling_config - DPServer uses num_replicas instead
    deployment_config = config.deployment_config.copy()
    if "autoscaling_config" in deployment_config:
        logger.info(f"Removing autoscaling_config from {deployment_name} for DP deployment")
        del deployment_config["autoscaling_config"]
        config.deployment_config = deployment_config
    
    # Apply node constraints if specified
    if node_constraints:
        _apply_node_constraints(config, deployment_name, node_constraints)
    
    # Create DPRankAssigner with dp_size_per_node for node-aware placement
    dp_rank_assigner = DPRankAssigner.bind(
        dp_size=dp_size, 
        dp_size_per_node=dp_size_per_node
    )
    
    # Build deployment
    deployment = build_llm_deployment(
        config,
        name_prefix=f"{deployment_name}:",
        deployment_cls=DPServerWithPDInfo,
        bind_kwargs={"dp_rank_assigner": dp_rank_assigner},
    )
    
    logger.info(f"{deployment_name} deployment built successfully")
    
    return deployment


def _apply_node_constraints(
    config: LLMConfig,
    deployment_name: str,
    node_constraints: Dict[str, Any]
):
    """
    Apply node scheduling constraints to the deployment config.
    
    Ray Serve doesn't support label_selector in ray_actor_options, so we use
    custom resources to constrain replicas to specific nodes.
    
    Args:
        config: LLM config to modify
        deployment_name: Name of deployment for logging
        node_constraints: Dict containing:
            - node_ids: List of node IDs to constrain to
            - resource_name: Custom resource name (optional, default: deployment-specific)
    """
    if "node_ids" not in node_constraints:
        raise ValueError(f"node_constraints must contain 'node_ids', got {node_constraints}")
    
    node_ids = node_constraints["node_ids"]
    if not isinstance(node_ids, list) or len(node_ids) == 0:
        raise ValueError(f"node_ids must be a non-empty list, got {node_ids}")
    
    # Create a custom resource name for this deployment
    # This resource should be set on the target nodes
    resource_name = node_constraints.get(
        "resource_name", 
        f"{deployment_name.lower()}_node"
    )
    
    if "ray_actor_options" not in config.deployment_config:
        config.deployment_config["ray_actor_options"] = {}
    
    if "resources" not in config.deployment_config["ray_actor_options"]:
        config.deployment_config["ray_actor_options"]["resources"] = {}
    
    # Require a small amount of the custom resource
    # This will constrain the replica to nodes that have this resource
    config.deployment_config["ray_actor_options"]["resources"][resource_name] = 0.001
    
    logger.info(
        f"{deployment_name}: Constraining to nodes {node_ids} "
        f"using custom resource '{resource_name}'. "
        f"NOTE: Nodes must be started with --resources '{{\"{resource_name}\": 1}}'"
    )
    logger.warning(
        f"{deployment_name}: Custom resource approach requires manual node setup. "
        f"For automatic node partitioning, nodes need to be pre-labeled with resources."
    )

