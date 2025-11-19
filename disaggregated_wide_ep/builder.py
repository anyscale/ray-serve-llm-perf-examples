import random
import re
from typing import AsyncGenerator, Optional, Union
import ray
from ray.llm._internal.serve.engines.vllm.kv_transfer.base import BaseConnectorBackend
from ray.llm._internal.serve.core.protocol import LLMServerProtocol
from ray.llm._internal.serve.core.configs.openai_api_models import ChatCompletionRequest, ChatCompletionResponse, CompletionRequest, CompletionResponse, ErrorResponse
from ray.llm._internal.serve.serving_patterns.prefill_decode.pd_server import RequestType
from ray.llm._internal.serve.core.ingress.ingress import make_fastapi_ingress
from ray.llm._internal.serve.serving_patterns.prefill_decode.builder import PDServingArgs
from ray.serve.llm import build_llm_deployment
from ray.serve.llm.deployment import PDProxyServer
from ray.serve.handle import DeploymentHandle
from ray.serve.llm import LLMConfig, build_openai_app, build_pd_openai_app
from ray.llm._internal.common.dict_utils import deep_merge_dicts
from ray.llm._internal.serve.engines.vllm.kv_transfer.base import BaseConnectorBackend
from ray.llm._internal.serve.engines.vllm.kv_transfer.factory import KVConnectorBackendFactory
from ray import serve

from ray.serve._private.request_router.common import PendingRequest
from ray.serve._private.request_router.replica_wrapper import RunningReplica
from ray.serve._private.request_router.pow_2_router import PowerOfTwoChoicesRequestRouter

from typing import List, Optional

import os
import socket
import sys
import threading
import time
import uuid
from typing import Any

import aiohttp
import msgpack
import zmq

import logging
logger = logging.getLogger(__name__)

from ray.serve.llm import LLMConfig, LLMRouter, LLMServer
from ray.serve.config import RequestRouterConfig
from ray.serve.context import _get_internal_replica_context
from ray.serve.deployment import Application
from ray.serve._private.common import ReplicaID
from ray.serve.handle import ReplicaResult

from typing import Dict, Any

# Import DP-related classes
from ray.llm._internal.serve.serving_patterns.data_parallel.dp_server import DPServer as _DPServer
from ray.llm._internal.serve.serving_patterns.data_parallel.dp_rank_assigner import DPRankAssigner

@ray.remote
class SessionManager:
    def __init__(self):
        self._request_session_mappings: Dict[str, str] = {}
        self._session_replica_mappings_prefill: Dict[str, str] = {}
        self._session_replica_mappings_decode: Dict[str, str] = {}
    
    def store_mapping(self, request_id: str, session_id: str) -> None:
        """Store a request ID to session ID mapping."""
        self._request_session_mappings[request_id] = session_id
    
    def get_mapping(self, request_id: str) -> Optional[str]:
        """Get session ID for a given request ID."""
        return self._request_session_mappings.get(request_id)
    
    def delete_mapping(self, request_id: str) -> None:
        """Delete a request ID to session ID mapping."""
        self._request_session_mappings.pop(request_id, None)
    
    def get_replica_for_session(self, session_id: str, is_prefill: bool) -> Optional[str]:
        """Get replica ID for a given session ID."""
        if is_prefill:
            return self._session_replica_mappings_prefill.get(session_id)
        else:
            return self._session_replica_mappings_decode.get(session_id)
    
    def associate_session_with_replica(self, session_id: str, replica_id: str, is_prefill: bool) -> None:
        """Associate a session ID with a replica ID."""
        if is_prefill:
            self._session_replica_mappings_prefill[session_id] = replica_id
        else:
            self._session_replica_mappings_decode[session_id] = replica_id

    # We also need to handle the case where the replica handling a session dies
    

SESSION_MANAGER_ACTOR_NAME = "session_manager"

def get_session_manager():
    """Get or create the detached session manager actor."""
    try:
        # Try to get existing detached actor
        return ray.get_actor(SESSION_MANAGER_ACTOR_NAME)
    except ValueError:
        # Actor doesn't exist, create a new detached one
        return SessionManager.options(name=SESSION_MANAGER_ACTOR_NAME, lifetime="detached").remote()


def store_request_session_mapping(request_id: str, session_id: str) -> None:
    """Store a request ID to session ID mapping."""
    manager = get_session_manager()
    ray.get(manager.store_mapping.remote(request_id, session_id))


def get_request_session_mapping(request_id: str) -> Optional[str]:
    """Get session ID for a given request ID."""
    manager = get_session_manager()
    return ray.get(manager.get_mapping.remote(request_id))


def delete_request_session_mapping(request_id: str) -> None:
    """Delete a request ID to session ID mapping."""
    manager = get_session_manager()
    ray.get(manager.delete_mapping.remote(request_id))


def get_replica_for_session(session_id: str, is_prefill: bool) -> Optional[str]:
    """Get replica ID for a given session ID."""
    manager = get_session_manager()
    return ray.get(manager.get_replica_for_session.remote(session_id, is_prefill))


def associate_session_with_replica(session_id: str, replica_id: str, is_prefill: bool) -> None:
    """Associate a session ID with a replica ID."""
    manager = get_session_manager()
    ray.get(manager.associate_session_with_replica.remote(session_id, replica_id, is_prefill))


class SesssionAwareMixin:
    
    async def __init__(self):
        
        context = _get_internal_replica_context()
        self.replica_id: ReplicaID = context.replica_id
        
        # TODO: Make this a Capped set of size 1000 or sth that has LRU eviction
        self.hot_sessions = set()
        
    def _parse_session_id(self, request):
        # Extra args from request
        xargs = getattr(request, "vllm_xargs", {}) or {}
        return xargs.get("session_id")
    
    def record_routing_stats(self) -> Dict[str, Any]:
        return {
            "hot_sessions": self.hot_sessions
        }

class PDInfoMixin:
    """Mixin for LLMServer to get PD info."""
    async def pd_info(self):
        replica_id = serve.get_replica_context().replica_id.unique_id
        from vllm import utils as vllm_utils
        ip = vllm_utils.get_ip()
        port = None
        if self.engine.llm_config.engine_kwargs["kv_transfer_config"]["kv_connector"] == "P2pNcclConnector":
            port = self.engine.llm_config.engine_kwargs["kv_transfer_config"]["kv_port"]
        elif self.engine.llm_config.engine_kwargs["kv_transfer_config"]["kv_connector"] == "MultiConnector":
            for connector in self.engine.llm_config.engine_kwargs["kv_transfer_config"]["kv_connector_extra_config"]["connectors"]:
                if connector["kv_connector"] == "P2pNcclConnector":
                    port = connector["kv_port"]
                    break
        if port is None:
            raise ValueError("P2pNcclConnector or MultiConnector not found in the engine kwargs")
        
        # vLLM's P2pNcclEngine handles port offsetting via get_world_group().rank (which equals dp_rank)
        # so we just return the base port from config
        dp_rank = self.engine.llm_config.engine_kwargs.get("data_parallel_rank", 0)
        logger.info(f"pd_info: replica_id={replica_id}, base_port={port}, dp_rank={dp_rank}")
        
        return replica_id, f"{ip}:{port}", dp_rank

class SessionAwareLLMServer(LLMServer, SesssionAwareMixin, PDInfoMixin):
    
    async def __init__(self, llm_config: LLMConfig):
        await LLMServer.__init__(self, llm_config)
        await SesssionAwareMixin.__init__(self)
        
    async def _run_request(
        self,
        request,
        *,
        engine_method: str,
        batch_output_stream: bool = False,
    ):
        # from session aware mixin
        session_id = self._parse_session_id(request)
        if session_id:
            self.hot_sessions.add(session_id)
        
        return await super()._run_request(
            request,
            engine_method=engine_method,
            batch_output_stream=batch_output_stream,
        )
        
    
    async def completions(self, request):
        # NOTE: Making the batch_output_stream=False to see if it affects the TPOT performance. 
        return await self._run_request(
            request,
            engine_method="completions",
            batch_output_stream=False,
        )
        
    async def chat(self, request):
        # NOTE: Making the batch_output_stream=False to see if it affects the TPOT performance. 
        return await self._run_request(
            request,
            engine_method="chat",
            batch_output_stream=False,
        )

class DPServerWithPDInfo(_DPServer, PDInfoMixin):
    """DPServer with PD info support (no session awareness)."""
    
    async def __init__(self, llm_config: LLMConfig, dp_rank_assigner):
        logger.info(f"DPServerWithPDInfo.__init__ called with dp_rank_assigner={dp_rank_assigner}")
        await _DPServer.__init__(self, llm_config, dp_rank_assigner)
        logger.info(f"DPServerWithPDInfo.__init__ completed successfully")
    
    
def build(serving_config_dict: Dict[str, Any]) -> Application:
    
    llm_configs = serving_config_dict["llm_configs"]
    
    if len(llm_configs) != 1:
        raise ValueError("Only one LLM config is supported")
    
    
    llm_config = LLMConfig(**llm_configs[0])
    # TODO: Builder of LLM Deployment is not generic enough for custom LLMServers. 
    # llm_deployment = build_llm_deployment(llm_config)
    deployment_options = llm_config.get_serve_options(
        name_prefix="LLMServer:",
    )
    
    # Update the deployment option with the session aware request router
    deployment_options["request_router_config"] = RequestRouterConfig(
        request_router_class=SessionAwareRequestRouter,
        request_routing_stats_period_s=2,
        request_routing_stats_timeout_s=1,
    )

    llm_deployment = serve.deployment(SessionAwareLLMServer).options(**deployment_options).bind(llm_config=llm_config)
    app = LLMRouter.as_deployment(
        llm_configs=[llm_config]).bind(
        llm_deployments=[llm_deployment])
    return app

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
        "proxy_cls_config": config.get("proxy_cls_config", {}),
        "proxy_deployment_config": config.get("proxy_deployment_config", {}),
        "ingress_deployment_config": config.get("ingress_deployment_config", {}),
    }
    
    return build_pd_openai_app(pd_serving_args)

def pd_builder_1node(config: dict):
    """Build PD disaggregation app on a single node."""
    
    # Build prefill config with node placement
    prefill_base = config["prefill_config"]
    p_tp_size = prefill_base["engine_kwargs"]["tensor_parallel_size"]
    prefill_config_dict = deep_merge_dicts(
        prefill_base,
        {
            "placement_group_config": {
                "bundles": [{"GPU": 1} 
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
                "bundles": [{"GPU": 1} 
                           for _ in range(d_tp_size)],
            }
        }
    )
    decode_config = LLMConfig(**decode_config_dict)

    # if "proxy_cls_config" in config and "proxy_extra_kwargs" in config["proxy_cls_config"] \
    #     and config["proxy_cls_config"]["proxy_extra_kwargs"].get("proxy_ip", None) == "0.0.0.0":
    #     config["proxy_cls_config"]["proxy_extra_kwargs"]["proxy_ip"] = socket.gethostname()
    
    # Build PD app
    pd_serving_args = {
        "prefill_config": prefill_config,
        "decode_config": decode_config,
        "proxy_cls_config": config.get("proxy_cls_config", {}),
        "proxy_deployment_config": config.get("proxy_deployment_config", {}),
        "ingress_deployment_config": config.get("ingress_deployment_config", {}),
    }
    
    return build_pd_openai_app(pd_serving_args)

def pd_builder_multi_nodes(config: dict):
    """Build PD disaggregation app with multiple nodes.
    
    For DP deployments, explicitly assigns prefill and decode to separate node pairs
    to ensure they don't compete for the same nodes.
    """
    
    pd_config = PDServingArgs.model_validate(config)

    # Get worker nodes with GPUs for explicit node placement
    worker_nodes = [node for node in ray.nodes() 
                    if node["Alive"] and "GPU" in node["Resources"]]
    
    if len(worker_nodes) < 4:
        logger.warning(f"Only {len(worker_nodes)} worker nodes available. For optimal PD+DP, 4+ nodes recommended.")
    
    # Check if DP is enabled for prefill
    prefill_dp_size = pd_config.prefill_config.engine_kwargs.get("data_parallel_size", 1)
    logger.info(f"Prefill DP size: {prefill_dp_size}")
    if prefill_dp_size > 1:
        # Build DP deployment for prefill
        prefill_dp_size_per_node = pd_config.prefill_config.experimental_configs.get("dp_size_per_node")
        if prefill_dp_size_per_node is None:
            raise ValueError(
                "dp_size_per_node must be set in experimental_configs for DP deployment."
            )
        
        num_prefill_nodes = prefill_dp_size // prefill_dp_size_per_node
        logger.info(f"Building DP prefill deployment with dp_size={prefill_dp_size}, dp_size_per_node={prefill_dp_size_per_node}, num_nodes={num_prefill_nodes}")
        
        # Assign prefill to first num_prefill_nodes
        prefill_nodes = worker_nodes[:num_prefill_nodes]
        logger.info(f"Prefill will use nodes: {[n['NodeName'] for n in prefill_nodes]}")
        
        # Create placement_group_config with node hints for prefill
        # For TP=1, we just need one GPU bundle per replica, with node hints
        # Use PACK strategy (not STRICT_PACK) since we're spreading across multiple nodes
        prefill_placement_config = {
            "bundles": [{"GPU": 1, f"node:{node['NodeName']}": 0.001} 
                       for node in prefill_nodes 
                       for _ in range(prefill_dp_size_per_node)],
            "strategy": "PACK"
        }
        
        # Merge placement_group_config into prefill config
        prefill_config_dict = deep_merge_dicts(
            pd_config.prefill_config.model_dump(),
            {"placement_group_config": prefill_placement_config}
        )
        pd_config.prefill_config = LLMConfig(**prefill_config_dict)
        
        # Remove autoscaling_config for DP deployment (DPServer.get_deployment_options will set num_replicas)
        prefill_deployment_config = pd_config.prefill_config.deployment_config.copy()
        if "autoscaling_config" in prefill_deployment_config:
            logger.info("Removing autoscaling_config from prefill deployment_config for DP deployment")
            del prefill_deployment_config["autoscaling_config"]
            pd_config.prefill_config.deployment_config = prefill_deployment_config
        
        logger.info(f"Creating DPRankAssigner for prefill with dp_size={prefill_dp_size}, dp_size_per_node={prefill_dp_size_per_node}")
        prefill_dp_rank_assigner = DPRankAssigner.bind(
            dp_size=prefill_dp_size, dp_size_per_node=prefill_dp_size_per_node
        )
        logger.info(f"DPRankAssigner for prefill created: {prefill_dp_rank_assigner}, type: {type(prefill_dp_rank_assigner)}")
        prefill_deployment = build_llm_deployment(
            pd_config.prefill_config,
            name_prefix="Prefill:",
            deployment_cls=DPServerWithPDInfo,
            bind_kwargs={"dp_rank_assigner": prefill_dp_rank_assigner},
        )
        logger.info(f"Prefill deployment created with DPRankAssigner: {prefill_deployment}")
    else:
        logger.info("Building non-DP prefill deployment with SessionAwareLLMServer")
        prefill_deployment = build_llm_deployment(
            pd_config.prefill_config, name_prefix="Prefill:", deployment_cls=SessionAwareLLMServer
        )

    # Check if DP is enabled for decode
    decode_dp_size = pd_config.decode_config.engine_kwargs.get("data_parallel_size", 1)
    logger.info(f"Decode DP size: {decode_dp_size}")
    if decode_dp_size > 1:
        # Build DP deployment for decode
        decode_dp_size_per_node = pd_config.decode_config.experimental_configs.get("dp_size_per_node")
        if decode_dp_size_per_node is None:
            raise ValueError(
                "dp_size_per_node must be set in experimental_configs for DP deployment."
            )
        
        num_decode_nodes = decode_dp_size // decode_dp_size_per_node
        num_prefill_nodes = prefill_dp_size // pd_config.prefill_config.experimental_configs.get("dp_size_per_node", 1) if prefill_dp_size > 1 else 0
        logger.info(f"Building DP decode deployment with dp_size={decode_dp_size}, dp_size_per_node={decode_dp_size_per_node}, num_nodes={num_decode_nodes}")
        
        # Assign decode to next num_decode_nodes (after prefill nodes)
        decode_nodes = worker_nodes[num_prefill_nodes:num_prefill_nodes + num_decode_nodes]
        logger.info(f"Decode will use nodes: {[n['NodeName'] for n in decode_nodes]}")
        
        # Create placement_group_config with node hints for decode
        # Use PACK strategy (not STRICT_PACK) since we're spreading across multiple nodes
        decode_placement_config = {
            "bundles": [{"GPU": 1, f"node:{node['NodeName']}": 0.001} 
                       for node in decode_nodes 
                       for _ in range(decode_dp_size_per_node)],
            "strategy": "PACK"
        }
        
        # Merge placement_group_config into decode config
        decode_config_dict = deep_merge_dicts(
            pd_config.decode_config.model_dump(),
            {"placement_group_config": decode_placement_config}
        )
        pd_config.decode_config = LLMConfig(**decode_config_dict)
        
        # Remove autoscaling_config for DP deployment (DPServer.get_deployment_options will set num_replicas)
        decode_deployment_config = pd_config.decode_config.deployment_config.copy()
        if "autoscaling_config" in decode_deployment_config:
            logger.info("Removing autoscaling_config from decode deployment_config for DP deployment")
            del decode_deployment_config["autoscaling_config"]
            pd_config.decode_config.deployment_config = decode_deployment_config
        
        logger.info(f"Creating DPRankAssigner for decode with dp_size={decode_dp_size}, dp_size_per_node={decode_dp_size_per_node}")
        decode_dp_rank_assigner = DPRankAssigner.bind(
            dp_size=decode_dp_size, dp_size_per_node=decode_dp_size_per_node
        )
        logger.info(f"DPRankAssigner for decode created: {decode_dp_rank_assigner}, type: {type(decode_dp_rank_assigner)}")
        decode_deployment = build_llm_deployment(
            pd_config.decode_config,
            name_prefix="Decode:",
            deployment_cls=DPServerWithPDInfo,
            bind_kwargs={"dp_rank_assigner": decode_dp_rank_assigner},
        )
        logger.info(f"Decode deployment created with DPRankAssigner: {decode_deployment}")
    else:
        logger.info("Building non-DP decode deployment with SessionAwareLLMServer")
        decode_deployment = build_llm_deployment(
            pd_config.decode_config, name_prefix="Decode:", deployment_cls=SessionAwareLLMServer
        )

    # Get the default deployment options from the PDProxyServer class based on the prefill and decode configs.
    proxy_cls_config = pd_config.proxy_cls_config

    pd_proxy_server_options = proxy_cls_config.proxy_cls.get_deployment_options(
        pd_config.prefill_config, pd_config.decode_config
    )

    # Override if the proxy deployment config is provided.
    if pd_config.proxy_deployment_config:
        pd_proxy_server_options = deep_merge_dicts(
            pd_proxy_server_options, pd_config.proxy_deployment_config
        )

    proxy_server_deployment = (
        serve.deployment(proxy_cls_config.proxy_cls)
        .options(**pd_proxy_server_options)
        .bind(
            prefill_server=prefill_deployment,
            decode_server=decode_deployment,
            **proxy_cls_config.proxy_extra_kwargs,
        )
    )

    ingress_cls_config = pd_config.ingress_cls_config
    ingress_options = ingress_cls_config.ingress_cls.get_deployment_options(
        [pd_config.prefill_config, pd_config.decode_config]
    )

    if pd_config.ingress_deployment_config:
        ingress_options = deep_merge_dicts(
            ingress_options, pd_config.ingress_deployment_config
        )

    ingress_cls = make_fastapi_ingress(ingress_cls_config.ingress_cls)
    return serve.deployment(ingress_cls, **ingress_options).bind(
        llm_deployments=[proxy_server_deployment],
        **ingress_cls_config.ingress_extra_kwargs,
    )

count = 0
prefill_instances: dict[str, Any] = {}  # http_address: (zmq_address, stamp)
decode_instances: dict[str, Any] = {}  # http_address: (zmq_address, stamp)

prefill_cv = threading.Condition()
decode_cv = threading.Condition()

DEFAULT_PING_SECONDS = 5

def random_uuid() -> str:
    return str(uuid.uuid4().hex)

def _remove_oldest_instances(instances: dict[str, Any]) -> None:
    oldest_key = next(iter(instances), None)
    while oldest_key is not None:
        value = instances[oldest_key]
        if value[1] > time.time():
            break
        print(f"🔴Remove [HTTP:{oldest_key}, ZMQ:{value[0]}, stamp:{value[1]}]")
        instances.pop(oldest_key, None)
        oldest_key = next(iter(instances), None)


def _listen_for_register(poller, router_socket):
    print("🎧 Service discovery listener thread started")
    sys.stdout.flush()
    while True:
        socks = dict(poller.poll())
        if router_socket in socks:
            remote_address, message = router_socket.recv_multipart()
            # data: {"type": "P", "http_address": "ip:port",
            #        "zmq_address": "ip:port"}
            data = msgpack.loads(message)
            if data["type"] == "P":
                global prefill_instances
                global prefill_cv
                with prefill_cv:
                    node = prefill_instances.get(data["http_address"], None)
                    prefill_instances[data["http_address"]] = (
                        data["zmq_address"],
                        time.time() + DEFAULT_PING_SECONDS,
                    )
                    _remove_oldest_instances(prefill_instances)

            elif data["type"] == "D":
                global decode_instances
                global decode_cv
                with decode_cv:
                    node = decode_instances.get(data["http_address"], None)
                    decode_instances[data["http_address"]] = (
                        data["zmq_address"],
                        time.time() + DEFAULT_PING_SECONDS,
                    )
                    _remove_oldest_instances(decode_instances)
            else:
                print(
                    "Unexpected, Received message from %s, data: %s",
                    remote_address,
                    data,
                )
                return

            if node is None:
                print(f"🔵Add [HTTP:{data['http_address']}, ZMQ:{data['zmq_address']}]")
                sys.stdout.flush()  # Force output in daemon thread


def start_service_discovery(hostname, port):
    if not hostname:
        hostname = socket.gethostname()
    if port == 0:
        raise ValueError("Port cannot be 0")

    context = zmq.Context()
    router_socket = context.socket(zmq.ROUTER)
    router_socket.bind(f"tcp://{hostname}:{port}")
    print(f"🔌 ZMQ service discovery bound to tcp://{hostname}:{port}")
    sys.stdout.flush()

    poller = zmq.Poller()
    poller.register(router_socket, zmq.POLLIN)

    _listener_thread = threading.Thread(
        target=_listen_for_register, args=[poller, router_socket], daemon=True
    )
    _listener_thread.start()
    print("🚀 Service discovery thread started")
    sys.stdout.flush()
    return _listener_thread


class P2pNcclPDProxyServer(PDProxyServer):
    async def __init__(
        self, 
        prefill_server: DeploymentHandle, 
        decode_server: DeploymentHandle,
        **extra_kwargs: dict
    ):
        self._llm_config = await prefill_server.llm_config.remote()
        self.prefill_server = prefill_server
        self.decode_server = decode_server
        if "proxy_ip" not in extra_kwargs:
            raise ValueError("proxy_ip is required")
        if "proxy_port" not in extra_kwargs:
            raise ValueError("proxy_port is required")
        if "proxy_service_discovery_port" not in extra_kwargs:
            raise ValueError("proxy_service_discovery_port is required")
        self.proxy_ip = extra_kwargs["proxy_ip"]
        self.proxy_port = extra_kwargs["proxy_port"]
        self.proxy_service_discovery_port = extra_kwargs["proxy_service_discovery_port"]
        logger.debug(
            f"P2pNcclPDProxyServer __init__ with proxy_ip:"
            f"{self.proxy_ip}, proxy_port: "
            f"{self.proxy_port}, proxy_service_discovery_port: "
            f"{self.proxy_service_discovery_port}")
        # self.service_discovery_thread = start_service_discovery(
        #     self.proxy_ip, self.proxy_service_discovery_port)
        # logger.debug(
        #     f"P2pNcclPDProxyServer start with service_discovery_thread: "
        #     f"{self.service_discovery_thread}")

    async def _handle_request(
        self,
        request: RequestType,
    ) -> AsyncGenerator[
        Union[str, ChatCompletionResponse, CompletionResponse, ErrorResponse], None
    ]:

        self._maybe_add_request_id_to_request(request)

        if isinstance(request, ChatCompletionRequest):
            method = "chat"
        elif isinstance(request, CompletionRequest):
            method = "completions"
        else:
            raise ValueError(f"Unsupported request type: {type(request)}")

        session_id = getattr(request, "user", None)
        request_id = getattr(request, "request_id", None)

        logger.debug(f"session_id: {session_id}, request_id: {request_id}")

        # request.vllm_xargs = request.vllm_xargs or {}
        # request.vllm_xargs["session_id"] = "p2p_nccl_pd_proxy_session"
        if not session_id:
            # simulate a session id for the request, 
            # session routing should always match
            #pass
            ### Use a fixed session ID
            # session_id = "p2p_nccl_pd_proxy_session"
            ### Use a random session ID
            ### TODO: we can use a fixed set of session IDs to emulate
            session_id = random_uuid()

        if session_id and request_id:
            store_request_session_mapping(request_id, session_id)
            logger.debug(f"Stored request-session mapping: request_id={request_id}, session_id={session_id}")
        
        prefill_replica_id, prefill_zmq_address, prefill_dp_rank = await self.prefill_server.pd_info.remote()
        decode_replica_id, decode_zmq_address, decode_dp_rank = await self.decode_server.pd_info.remote()
        
        # Adjust addresses to account for rank differences
        # P2pNcclConnector calculates: remote_address = request_id_port + self._rank
        # 
        # For decode to reach prefill:
        #   request_id_port + decode_rank = prefill_actual_port
        #   prefill_adjusted = (base_port + prefill_rank) - decode_rank
        #
        # For prefill to reach decode:
        #   request_id_port + prefill_rank = decode_actual_port
        #   decode_adjusted = (base_port + decode_rank) - prefill_rank
        
        prefill_ip, prefill_base_port = prefill_zmq_address.split(":")
        prefill_adjusted_port = int(prefill_base_port) + prefill_dp_rank - decode_dp_rank
        prefill_zmq_address_adjusted = f"{prefill_ip}:{prefill_adjusted_port}"
        
        decode_ip, decode_base_port = decode_zmq_address.split(":")
        decode_adjusted_port = int(decode_base_port) + decode_dp_rank - prefill_dp_rank
        decode_zmq_address_adjusted = f"{decode_ip}:{decode_adjusted_port}"
        
        logger.info(
            f"Pairing prefill rank {prefill_dp_rank} with decode rank {decode_dp_rank}: "
            f"prefill {prefill_base_port}→{prefill_adjusted_port}, decode {decode_base_port}→{decode_adjusted_port}")
        logger.debug(
            f"prefill: {prefill_replica_id}@{prefill_zmq_address} (dp_rank={prefill_dp_rank}), "
            f"decode: {decode_replica_id}@{decode_zmq_address} (dp_rank={decode_dp_rank})")

        if request_id:
            nccl_request_id = (
                f"___prefill_addr_{prefill_zmq_address_adjusted}"
                f"___decode_addr_{decode_zmq_address_adjusted}"
                f"___prefill_replica_id_{prefill_replica_id}"
                f"___decode_replica_id_{decode_replica_id}"
                f"___rid_{request_id}"
            )
        else:
            nccl_request_id = (
                f"___prefill_addr_{prefill_zmq_address_adjusted}"
                f"___decode_addr_{decode_zmq_address_adjusted}"
                f"___prefill_replica_id_{prefill_replica_id}"
                f"___decode_replica_id_{decode_replica_id}"
                f"___uuid_{random_uuid()}"
            )
        logger.debug(f"nccl_request_id: {nccl_request_id}")

        prefill_request = request.model_copy(deep=True)
        prefill_request.max_tokens = 1
        if getattr(request, "max_completion_tokens", None) or request.max_tokens:
            prefill_request.max_completion_tokens = 1

        # prefill_request = self._prepare_prefill_request(request)
        # nccl_request_id = prefill_request.request_id

        # Set request id in serve request context
        # THIS IS CRITICAL:
        # request_meta will get request_id from serve request context
        # and request_router will use request_meta
        serve.context._set_request_context(request_id=nccl_request_id)

        # Send BOTH prefill and decode requests immediately (don't wait for prefill to complete)
        # This is critical for NCCL P2P: decode must be processing to receive KV cache from prefill
        prefill_gen = getattr(self.prefill_server, method).options(stream=True).remote(prefill_request)
        
        decode_request = request.model_copy(deep=True)
        decode_request.request_id = nccl_request_id
        decode_gen = getattr(self.decode_server, method).options(stream=True).remote(decode_request)

        # Consume and discard prefill output (only 1 token), then stream decode output
        prefill_chunk = await prefill_gen.__anext__()
        
        if isinstance(prefill_chunk, ErrorResponse):
            logger.error(f"Prefill returned error: {prefill_chunk}")
            yield prefill_chunk
            return

        # Stream decode output to client
        async for chunk in decode_gen:
            yield chunk

    def _prepare_prefill_request(self, request: RequestType) -> RequestType:
        prefill_request = request.model_copy(deep=True)
        prefill_request.max_tokens = 1
        if getattr(request, "max_completion_tokens", None) or request.max_tokens:
            prefill_request.max_completion_tokens = 1

        global count
        global prefill_instances
        global prefill_cv
        with prefill_cv:
            prefill_list = list(prefill_instances.items())
            prefill_addr, prefill_zmq_addr = prefill_list[count % len(prefill_list)]
            prefill_zmq_addr = prefill_zmq_addr[0]

        global decode_instances
        global decode_cv
        with decode_cv:
            decode_list = list(decode_instances.items())
            decode_addr, decode_zmq_addr = decode_list[count % len(decode_list)]
            decode_zmq_addr = decode_zmq_addr[0]

        print(
            f"handle_request count: {count}, [HTTP:{prefill_addr}, "
            f"ZMQ:{prefill_zmq_addr}] 👉 [HTTP:{decode_addr}, "
            f"ZMQ:{decode_zmq_addr}]"
        )
        count += 1

        request_id = (
            f"___prefill_addr_{prefill_zmq_addr}___decode_addr_"
            f"{decode_zmq_addr}_{random_uuid()}"
        )
        prefill_request.request_id = request_id
        # prefill_request.stream = False

        return prefill_request

    def _prepare_decode_request(
        self,
        request: RequestType,
        prefill_chunk: Union[ChatCompletionResponse, CompletionResponse],
    ) -> RequestType:
        decode_request = request.model_copy(deep=True)

        return decode_request


class SessionAwareRequestRouter(PowerOfTwoChoicesRequestRouter):
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        logger.debug(f"[DEBUG] SessionAwareRequestRouter initialized.")


    def _extract_session_id_directly(self, request: PendingRequest):
        for arg in request.args:
            xargs = None
            if isinstance(arg, dict):
                xargs = arg.get("vllm_xargs", {})
            else:
                xargs = getattr(arg, "vllm_xargs", {})
            if xargs: 
                return xargs.get("session_id")
    
    
    def _find_matched_replica_with_routing_stats(
        self, 
        candidate_replicas: List[RunningReplica], 
        pending_request: Optional[PendingRequest],
        session_id: Optional[str] = None,
    ) -> Optional[RunningReplica]:
        """
        Find the replica that matches the session-id in the request.
        """
        if not pending_request:
            return 
        
        session_id = self._extract_session_id_directly(pending_request)
        logger.debug(f"Extracted session_id: {session_id}")

        if session_id:
            for replica in candidate_replicas:
                routing_stats = replica.routing_stats
                logger.debug(f"Replica {replica.replica_id.unique_id} has routing stats: {routing_stats}")
                if not routing_stats:
                    continue
                hot_sessions = routing_stats.get('hot_sessions', set())
                logger.debug(f"[DEBUG] SessionAwareRequestRouter, hot_sessions: {hot_sessions}")
                logger.debug(f"[DEBUG] SessionAwareRequestRouter, session_id: {session_id} in hot_sessions: {session_id in hot_sessions}")
                if session_id in hot_sessions:
                    return replica
        return None
    
    def _extract_session_id(self, request: PendingRequest, delete_mapping: bool = False):
        # request_id = None
        
        # # Extract request_id from the request args (ChatCompletionRequest or CompletionRequest)
        # for arg in request.args:
        #     if hasattr(arg, 'request_id') and arg.request_id:
        #         request_id = arg.request_id
        #         break
        request_id = request.metadata.request_id
        session_id = get_request_session_mapping(request_id)
        logger.debug(f"{request_id=}, {session_id=}")
        
        if request_id:
            logger.debug(f"request_id: {request_id}")
            session_id = get_request_session_mapping(request_id)
            if session_id:
                logger.debug(f"Session ID extracted from request: session_id={session_id}, request_id={request_id}")
                if delete_mapping:
                    # Delete the mapping after use to clean up
                    delete_request_session_mapping(request_id)
                return session_id
        logger.debug(f"No session ID found for request_id: {request_id}")

    def _find_matched_replica(
        self, candidate_replicas: List[RunningReplica], 
        pending_request: Optional[PendingRequest],
        session_id: Optional[str] = None,
    ) -> Optional[RunningReplica]:
        """
        Find the replica that matches the session-id in the request.
        """
        if not pending_request:
            return 
        
        session_id = self._extract_session_id(pending_request)
        is_prefill = self.is_prefill_replica(candidate_replicas[0].replica_id.to_full_id_str())
        if not session_id:
            logger.debug(f"No session ID found for request {pending_request.metadata.request_id}, is_prefill: {is_prefill}")

        if session_id:
            logger.debug(f"Looking for replica with session ID: {session_id}")

            # Check if we have a stored mapping
            replica_id = get_replica_for_session(session_id, is_prefill)
            if replica_id:
                logger.debug(f"Found stored replica mapping for session {session_id}: replica_id={replica_id}")
                # Find the replica with this ID among candidates
                for replica in candidate_replicas:
                    if replica.replica_id.to_full_id_str() == replica_id:
                        logger.debug(f"Found matching replica from stored mapping: replica_id={replica.replica_id}")
                        return replica
                candidate_replica_ids = [replica.replica_id.to_full_id_str() for replica in candidate_replicas]
                logger.debug(f"Stored replica {replica_id} not in candidate list {candidate_replica_ids}")
            
            logger.debug(f"No matching replica found for session ID: {session_id}, is_prefill: {is_prefill}")
        return None
    
    async def choose_replicas(
        self,
        candidate_replicas: List[RunningReplica],
        pending_request: Optional[PendingRequest] = None,
    ) -> List[List[RunningReplica]]:
        logger.info(f"🔍 SessionAwareRequestRouter.choose_replicas called, call_method: {pending_request.metadata.call_method}, request_id: {pending_request.metadata.request_id}")

        if pending_request.metadata.call_method == "llm_config":
            return await super().choose_replicas(candidate_replicas, pending_request)
        elif pending_request.metadata.call_method == "pd_info":
            # For pd_info, ALWAYS use default routing (no session affinity)
            # This allows PDProxyServer to iterate through different replicas to find matching DP ranks
            logger.info(f"pd_info request - using default routing to iterate through replicas")
            return await super().choose_replicas(candidate_replicas, pending_request)

        request_id = pending_request.metadata.request_id
        decode_ip, decode_port = self.parse_zmq_address(request_id, is_prefill=False)
        prefill_ip, prefill_port = self.parse_zmq_address(request_id, is_prefill=True)

        decode_replica_id = self.parse_replica_id(request_id, is_prefill=False)
        prefill_replica_id = self.parse_replica_id(request_id, is_prefill=True)

        logger.info(f"🔍 Looking for replica with ID: prefill={prefill_replica_id} or decode={decode_replica_id}")
        for replica in candidate_replicas:
            if replica.replica_id.unique_id == decode_replica_id:
                logger.info(f"✅ Found matching decode replica: {replica.replica_id.unique_id}")
                return [[replica]]
            if replica.replica_id.unique_id == prefill_replica_id:
                logger.info(f"✅ Found matching prefill replica: {replica.replica_id.unique_id}")
                return [[replica]]
        
        logger.error(f"❌ SessionAwareRequestRouter did not find matched replica for request {request_id}, candidates: {[r.replica_id.unique_id for r in candidate_replicas]}")
        raise ValueError(f"SessionAwareRequestRouter did not find matched replica for request {request_id}")

    def on_request_routed(
        self,
        pending_request: PendingRequest,
        replica_id: ReplicaID,
        result: ReplicaResult,
    ):
        """Called when a request is routed to a replica.
        
        Associates the session ID with the replica ID if they don't already have a mapping.
        """
        if pending_request.metadata.call_method == "pd_info":
            # TODO: properly delete the mapping after use
            session_id = self._extract_session_id(pending_request)
            replica_id_str = replica_id.to_full_id_str()
            is_prefill = self.is_prefill_replica(replica_id_str)
            if session_id:
                # Check if we already have a mapping for this session
                existing_replica = get_replica_for_session(session_id, is_prefill)
                if not existing_replica:
                    # Associate this session with the replica it was routed to
                    logger.debug(f"Associating session {session_id} with replica {replica_id_str}")
                    associate_session_with_replica(session_id, replica_id_str, is_prefill)
                else:
                    # caveat: the association may be from the last `serve run`,
                    # use kill_session_manager.py to kill the session_manager actor first
                    logger.debug(f"Session {session_id} already associated with replica {existing_replica}")
            else:
                logger.debug(f"Session ID not found for request {pending_request.metadata.request_id}")

        # Call parent implementation
        super().on_request_routed(pending_request, replica_id, result)

    @staticmethod
    def is_prefill_replica(replica_id: str) -> bool:
        is_prefill = "#Prefill:" in replica_id
        if not is_prefill:
            assert "#Decode:" in replica_id, (
                f"Replica {replica_id} is not a prefill or decode replica"
            )
        return is_prefill

    @staticmethod
    def parse_zmq_address(request_id: str, is_prefill=True) -> tuple[str, int]:
        # TODO: import from vllm
        # Regular expression to match the string hostname and integer port
        if is_prefill:
            pattern = r"___decode_addr_(.*):(\d+)"
        else:
            pattern = r"___prefill_addr_(.*):(\d+)___"

        # Use re.search to find the pattern in the request_id
        match = re.search(pattern, request_id)
        if match:
            # Extract the ranks
            ip = match.group(1)
            port = int(match.group(2))

            return ip, port
        raise ValueError(
            f"Request id {request_id} does not contain hostname and port")

    @staticmethod
    def parse_replica_id(request_id: str, is_prefill=True) -> str:
        if is_prefill:
            pattern = r"___prefill_replica_id_(.*)___decode_replica_id"
        else:
            pattern = r"___decode_replica_id_(.*)___"
        match = re.search(pattern, request_id)
        if match:
            return match.group(1)
        raise ValueError(f"Request id {request_id} does not contain replica id")
    
    def parse_request_id(self, request_id: str) -> str:
        pattern = r"___rid_(.*)___"
        match = re.search(pattern, request_id)
        if match:
            return match.group(1)
        raise None


# class P2pNcclPDProxyServer(LLMServerProtocol):
#     async def __init__(self, prefill_server: DeploymentHandle, decode_server: DeploymentHandle):
#         self._llm_config = await prefill_server.llm_config.remote()
#         self.prefill_server = prefill_server.options(stream=True)
#         self.decode_server = decode_server.options(stream=True)

#     async def start(self) -> None:
#         pass

#     async def _handle_request(
#         self,
#         request: RequestType,
#     ) -> AsyncGenerator[Union[str, ChatCompletionResponse, CompletionResponse, ErrorResponse], None]:
#         pass

#     async def chat(self, request: ChatCompletionRequest) -> AsyncGenerator[Union[str, ChatCompletionResponse, ErrorResponse], None]:
#         return self._handle_request(request)

#     async def completions(self, request: CompletionRequest) -> AsyncGenerator[Union[str, CompletionResponse, ErrorResponse], None]:
#         return self._handle_request(request)

#     async def check_health(self) -> None:
#         pass

#     async def reset_prefix_cache(self) -> None:
#         pass

#     async def start_profile(self) -> None:
#         pass

#     async def stop_profile(self) -> None:
#         pass

#     async def llm_config(self) -> Optional[LLMConfig]:
#         return self._llm_config

class P2pNcclConnectorBackend(BaseConnectorBackend):
    def setup(self) -> None:
        base_port = self.kv_transfer_config["kv_port"]
        
        # For DP deployments, vLLM's P2pNcclEngine already handles port offsetting 
        # via get_world_group().rank (which equals dp_rank when TP=1).
        # Only add offset for non-DP cases (TP/PP deployments).
        dp_rank = self.llm_config.engine_kwargs.get("data_parallel_rank")
        if dp_rank is not None and dp_rank >= 0:
            # DP deployment - vLLM handles offset, don't add it here
            logger.info(f"P2pNcclConnectorBackend.setup (DP): kv_port={base_port}, dp_rank={dp_rank} (no offset added)")
        else:
            # Non-DP deployment - add offset based on replica rank
            port = int(base_port) + self._compute_port_offset()
            self.kv_transfer_config["kv_port"] = str(port)
            logger.info(f"P2pNcclConnectorBackend.setup (non-DP): base_port={base_port}, port={port}")

if not KVConnectorBackendFactory.is_registered("P2pNcclConnector"):
    KVConnectorBackendFactory.register_backend(
        "P2pNcclConnector",
        "builder:P2pNcclConnectorBackend",
    )
    print("Registered P2pNcclConnectorBackend")
else:
    print("P2pNcclConnectorBackend already registered")