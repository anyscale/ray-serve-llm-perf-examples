# DeepSeek-V3 Disaggregated Prefill/Decode with Wide Expert Parallelism

Production configuration for running DeepSeek-V3 with prefill/decode disaggregation, data parallelism, and expert parallelism using Ray Serve.

## Tested Versions

This configuration has been validated via vLLM, with:

- **vLLM**: v0.11.1rc5
- **Ray**: 2.51.0
- **CUDA**: 12.8
- **NVSHMEM**: 3.4.5
- **DeepGEMM**: c9f8b34dcdacc20aa746b786f983492c51072870
- **DeepEP**: 92fe2deaec24bc92ebd9de276daa6ca9ed602ed4
- **Hardware**: Four 8xH200 nodes (tested on Nebius)

## Installation

Install vLLM with precompiled binaries:

```bash
VLLM_USE_PRECOMPILED=1 uv pip install git+https://github.com/vllm-project/vllm.git@v0.11.1rc5 \
  --extra-index-url https://download.pytorch.org/whl/cu128 \
  --index-strategy unsafe-best-match \
  --prerelease=allow
```

## Configuration Features

This setup includes:
- **EPLB (Expert Parallel Load Balancing)**: Dynamic expert load balancing with 32 redundant experts
- **DBO (Decode Batch Optimization)**: Decode batch optimization with 32-token threshold
- **CUDA Graph Optimization**: Full decode-only CUDA graph mode with fusion optimizations
- **Data Parallelism**: Prefill DP=16, Decode DP=32 with 8 DP workers per node
- **Expert Parallelism**: Enabled with DeepGEMM and DeepEP backends
- **KV Transfer**: GPU-to-GPU KV transfer using NIXL/DecodeBench connectors

## Cluster Setup

### Option 1: Manual Ray Cluster

**On the head node:**
```bash
ray start --head
```

**On each of the prefill nodes (8xH200):**
```bash
ray start --address='<head_ip>:6379' --resources='{"prefill": 8}'
```

**On each of the decode nodes (8xH200):**
```bash
ray start --address='<head_ip>:6379' --resources='{"decode": 8}'
```

Replace `<head_ip>` with your actual head node IP address.

### Option 2: KubeRay (Recommended for Production)

For Kubernetes deployments, use KubeRay. See the [KubeRay examples repository](https://docs.ray.io/en/latest/cluster/kubernetes/examples/rayserve-deepseek-example.html) for sample configurations.

Key requirements for your RayCluster spec:
- Custom resources for each prefill/decode worker node: `{"prefill": 8}` and `{"decode": 8}`
- GPU resources per worker node

## Running the Application

Once your Ray cluster is running:

```bash
serve run pd.yaml
```

This will deploy:
- One wide-EP prefill workers of size 16
- One wide-EP decode group of size 32
- 16 API server replicas for request handling

## Standalone vLLM Command Reference

For comparison, here's the equivalent standalone vLLM server command with all optimizations (run from each node):

```bash
export VLLM_USE_DEEP_GEMM=1
export VLLM_ALL2ALL_BACKEND=deepep_low_latency
export VLLM_MOE_DP_CHUNK_SIZE=512
export VLLM_SKIP_P2P_CHECK=1
export VLLM_RANDOMIZE_DP_DUMMY_INPUTS=1
export NVIDIA_GDRCOPY=enabled
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export VLLM_MOE_ROUTING_SIMULATION_STRATEGY=uniform_random
export NVSHMEM_QP_DEPTH=1512
export GLOO_SOCKET_IFNAME=eth0

uv run vllm serve deepseek-ai/DeepSeek-V3-0324 \
  --data-parallel-hybrid-lb \
  --api-server-count 8 \
  --data-parallel-address $COORDINATOR_IP \
  --data-parallel-rpc-port $COORDINATOR_RPC_PORT \
  --tensor-parallel-size 1 \
  --data-parallel-size 32 \
  --data-parallel-size-local 8 \
  --data-parallel-start-rank $START_RANK \
  --enable-expert-parallel \
  --no-enable-prefix-caching \
  --max-model-len 16384 \
  --enable-dbo \
  --dbo-decode-token-threshold 32 \
  --async-scheduling \
  --enable-eplb \
  --eplb-config '{"window_size":"1000",
                  "step_interval":"3000",
                  "num_redundant_experts":"32",
                  "log_balancedness":"False"}' \
  --max-num-seqs 512 \
  --compilation_config '{"pass_config":{"enable_fusion":true,"enable_attn_fusion":true,"enable_noop":true},"custom_ops":["+rms_norm"],"cudagraph_mode":"FULL_DECODE_ONLY"}' \
  --kv-transfer-config '{"kv_connector":"NixlConnector", "kv_role":"kv_both"}'
```

