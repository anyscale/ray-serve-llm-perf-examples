"""Builder for PD + DP + NCCL P2P deployments.

Handles disaggregated prefill-decode with Data Parallel and NCCL KV transfer.
"""

import logging
import re
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

import ray
from ray import serve
from ray.serve.deployment import Application
from ray.serve.handle import DeploymentHandle, ReplicaResult
from ray.llm._internal.common.dict_utils import deep_merge_dicts
from ray.llm._internal.serve.core.configs.openai_api_models import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    CompletionRequest,
    CompletionResponse,
    ErrorResponse,
)
from ray.llm._internal.serve.core.ingress.ingress import make_fastapi_ingress
from ray.llm._internal.serve.core.server.builder import build_llm_deployment
from ray.llm._internal.serve.engines.vllm.kv_transfer.base import BaseConnectorBackend
from ray.llm._internal.serve.engines.vllm.kv_transfer.factory import (
    KVConnectorBackendFactory,
)
from ray.llm._internal.serve.serving_patterns.data_parallel.dp_rank_assigner import (
    DPRankAssigner,
)
from ray.llm._internal.serve.serving_patterns.data_parallel.dp_server import (
    DPServer as _DPServer,
)
from ray.llm._internal.serve.serving_patterns.prefill_decode.builder import (
    PDServingArgs,
)
from ray.llm._internal.serve.serving_patterns.prefill_decode.pd_server import (
    RequestType,
)
from ray.serve._private.common import ReplicaID
from ray.serve._private.request_router.common import PendingRequest
from ray.serve._private.request_router.pow_2_router import (
    PowerOfTwoChoicesRequestRouter,
)
from ray.serve._private.request_router.replica_wrapper import RunningReplica
from ray.serve.llm import LLMConfig
from ray.serve.llm.deployment import PDProxyServer

logger = logging.getLogger(__name__)


def random_uuid() -> str:
    return str(uuid.uuid4())


class PDInfoMixin:
    """Mixin for LLMServer to return PD info including DP rank."""

    async def pd_info(self):
        replica_id = serve.get_replica_context().replica_id.unique_id
        from vllm import utils as vllm_utils

        ip = vllm_utils.get_ip()
        port = None
        if self.engine.llm_config.engine_kwargs["kv_transfer_config"][
            "kv_connector"
        ] == "P2pNcclConnector":
            port = self.engine.llm_config.engine_kwargs["kv_transfer_config"]["kv_port"]
        elif self.engine.llm_config.engine_kwargs["kv_transfer_config"][
            "kv_connector"
        ] == "MultiConnector":
            for connector in self.engine.llm_config.engine_kwargs["kv_transfer_config"][
                "kv_connector_extra_config"
            ]["connectors"]:
                if connector["kv_connector"] == "P2pNcclConnector":
                    port = connector["kv_port"]
                    break
        if port is None:
            raise ValueError("P2pNcclConnector not found in engine kwargs")

        dp_rank = self.engine.llm_config.engine_kwargs.get("data_parallel_rank", 0)
        return replica_id, f"{ip}:{port}", dp_rank


class DPServerWithPDInfo(_DPServer, PDInfoMixin):
    """DPServer with PD info support."""

    async def __init__(self, llm_config: LLMConfig, dp_rank_assigner):
        await _DPServer.__init__(self, llm_config, dp_rank_assigner)


class P2pNcclPDProxyServer(PDProxyServer):
    """PDProxyServer that adjusts ports for DP rank differences."""

    async def __init__(
        self,
        prefill_server: DeploymentHandle,
        decode_server: DeploymentHandle,
        **extra_kwargs: dict,
    ):
        self._llm_config = await prefill_server.llm_config.remote()
        self.prefill_server = prefill_server
        self.decode_server = decode_server

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

        request_id = getattr(request, "request_id", None)

        prefill_replica_id, prefill_zmq_address, prefill_dp_rank = (
            await self.prefill_server.pd_info.remote()
        )
        decode_replica_id, decode_zmq_address, decode_dp_rank = (
            await self.decode_server.pd_info.remote()
        )

        # Adjust addresses for rank difference
        # P2pNcclConnector: remote_address = request_id_port + self._rank
        prefill_ip, prefill_base_port = prefill_zmq_address.split(":")
        prefill_adjusted_port = (
            int(prefill_base_port) + prefill_dp_rank - decode_dp_rank
        )
        prefill_zmq_address_adjusted = f"{prefill_ip}:{prefill_adjusted_port}"

        decode_ip, decode_base_port = decode_zmq_address.split(":")
        decode_adjusted_port = int(decode_base_port) + decode_dp_rank - prefill_dp_rank
        decode_zmq_address_adjusted = f"{decode_ip}:{decode_adjusted_port}"

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

        prefill_request = request.model_copy(deep=True)
        prefill_request.max_tokens = 1
        if getattr(request, "max_completion_tokens", None) or request.max_tokens:
            prefill_request.max_completion_tokens = 1

        serve.context._set_request_context(request_id=nccl_request_id)

        # Send both requests immediately (decode must process to receive NCCL data)
        prefill_gen = (
            getattr(self.prefill_server, method).options(stream=True).remote(prefill_request)
        )

        decode_request = request.model_copy(deep=True)
        decode_request.request_id = nccl_request_id
        decode_gen = (
            getattr(self.decode_server, method).options(stream=True).remote(decode_request)
        )

        # Consume prefill output (1 token), then stream decode
        prefill_chunk = await prefill_gen.__anext__()

        if isinstance(prefill_chunk, ErrorResponse):
            logger.error(f"Prefill error: {prefill_chunk}")
            yield prefill_chunk
            return

        async for chunk in decode_gen:
            yield chunk


class SessionAwareRequestRouter(PowerOfTwoChoicesRequestRouter):
    """Routes requests based on replica IDs in request metadata."""

    def is_prefill_replica(self, replica_id_str: str) -> bool:
        return "Prefill:" in replica_id_str

    async def choose_replicas(
        self,
        candidate_replicas: List[RunningReplica],
        pending_request: Optional[PendingRequest] = None,
    ) -> List[List[RunningReplica]]:
        if pending_request.metadata.call_method == "llm_config":
            return await super().choose_replicas(candidate_replicas, pending_request)
        elif pending_request.metadata.call_method == "pd_info":
            # Use default routing to iterate through replicas
            return await super().choose_replicas(candidate_replicas, pending_request)

        request_id = pending_request.metadata.request_id
        decode_replica_id = self.parse_replica_id(request_id, is_prefill=False)
        prefill_replica_id = self.parse_replica_id(request_id, is_prefill=True)

        for replica in candidate_replicas:
            if replica.replica_id.unique_id == decode_replica_id:
                return [[replica]]
            if replica.replica_id.unique_id == prefill_replica_id:
                return [[replica]]

        raise ValueError(f"Replica not found for request {request_id}")

    @staticmethod
    def parse_replica_id(request_id: str, is_prefill=True) -> str:
        if is_prefill:
            pattern = r"___prefill_replica_id_(.*)___decode_replica_id"
        else:
            pattern = r"___decode_replica_id_(.*)___"
        match = re.search(pattern, request_id)
        if match:
            return match.group(1)
        raise ValueError(f"Replica ID not found in request: {request_id}")


class P2pNcclConnectorBackend(BaseConnectorBackend):
    """Backend that skips port offset for DP deployments (vLLM handles it)."""

    def setup(self) -> None:
        base_port = self.kv_transfer_config["kv_port"]
        dp_rank = self.llm_config.engine_kwargs.get("data_parallel_rank")
        if dp_rank is not None and dp_rank >= 0:
            # DP deployment - vLLM handles offset via get_world_group().rank
            logger.info(f"P2pNcclConnectorBackend (DP): kv_port={base_port}, dp_rank={dp_rank}")
        else:
            # Non-DP - add offset based on replica rank  
            port = int(base_port) + self._compute_port_offset()
            self.kv_transfer_config["kv_port"] = str(port)
            logger.info(f"P2pNcclConnectorBackend (non-DP): {base_port}→{port}")


# Register backend (handle race conditions across workers)
try:
    if KVConnectorBackendFactory.is_registered("P2pNcclConnector"):
        KVConnectorBackendFactory.unregister_backend("P2pNcclConnector")
except Exception:
    pass

try:
    KVConnectorBackendFactory.register_backend(
        "P2pNcclConnector",
        "pd_dpep_builder:P2pNcclConnectorBackend",
    )
except ValueError:
    pass  # Already registered by another worker


def build_pd_dp_openai_app(config: Dict[str, Any]) -> Application:
    """Build PD + DP OpenAI app with NCCL P2P support."""

    pd_config = PDServingArgs.model_validate(config)

    # Build prefill and decode deployments
    prefill_deployment = _build_dp_deployment(pd_config.prefill_config, "Prefill")
    decode_deployment = _build_dp_deployment(pd_config.decode_config, "Decode")

    # Build proxy
    proxy_cls_config = pd_config.proxy_cls_config
    proxy_options = proxy_cls_config.proxy_cls.get_deployment_options(
        pd_config.prefill_config, pd_config.decode_config
    )

    if pd_config.proxy_deployment_config:
        proxy_options = deep_merge_dicts(
            proxy_options, pd_config.proxy_deployment_config
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
            ingress_options, pd_config.ingress_deployment_config
        )

    ingress_cls = make_fastapi_ingress(ingress_cls_config.ingress_cls)

    return serve.deployment(ingress_cls, **ingress_options).bind(
        llm_deployments=[proxy_deployment],
        **ingress_cls_config.ingress_extra_kwargs,
    )


def _build_dp_deployment(config: LLMConfig, deployment_name: str) -> Application:
    """Build DP deployment with DPServerWithPDInfo."""

    dp_size = config.engine_kwargs.get("data_parallel_size", 1)
    if dp_size == 1:
        raise ValueError(f"{deployment_name} requires data_parallel_size > 1")

    dp_size_per_node = config.experimental_configs.get("dp_size_per_node", None)
    dp_rank_assigner = DPRankAssigner.bind(
        dp_size=dp_size, dp_size_per_node=dp_size_per_node
    )

    return build_llm_deployment(
        config,
        name_prefix=f"{deployment_name}:",
        bind_kwargs=dict(dp_rank_assigner=dp_rank_assigner),
        deployment_cls=DPServerWithPDInfo,
    )
