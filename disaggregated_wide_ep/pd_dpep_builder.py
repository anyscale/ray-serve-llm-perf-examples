"""Builder for PD + DP deployments with NIXL KV transfer.

Handles disaggregated prefill-decode with Data Parallelism
"""

from typing import Any, Dict

from ray import serve
from ray.serve.deployment import Application
from ray.llm._internal.common.dict_utils import deep_merge_dicts
from ray.llm._internal.serve.core.ingress.ingress import make_fastapi_ingress
from ray.llm._internal.serve.serving_patterns.prefill_decode.builder import (
    PDServingArgs,
)
from ray.serve.llm import build_dp_deployment


def build_pd_dp_openai_app(config: Dict[str, Any]) -> Application:
    """Build PD + DP OpenAI app using Ray's standard components with NIXL."""

    pd_config = PDServingArgs.model_validate(config)

    # Build prefill and decode deployments with DP support using Ray's standard builder
    prefill_deployment = build_dp_deployment(
        pd_config.prefill_config, name_prefix="Prefill:"
    )
    decode_deployment = build_dp_deployment(
        pd_config.decode_config, name_prefix="Decode:"
    )

    # Build proxy using Ray's standard PDProxyServer
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
