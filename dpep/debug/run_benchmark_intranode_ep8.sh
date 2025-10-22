#!/bin/bash
set -ex

# Benchmark: Intra-node EP8 (single node, 8 GPUs, NVLink)
# This runs on a single worker node

NODE_IP=${1:-172.25.105.98}

echo "=== Running Intra-node EP8 Benchmark (NVLink) ==="
echo "Node: $NODE_IP"
echo "Testing: 1 and 128 tokens per GPU"

ssh -p 2222 $NODE_IP << 'EOF'
set -ex

# Source environment
source /tmp/pplx_workspace/setup_env.sh

# Override for single-node (use NVLink, not EFA)
export NVSHMEM_REMOTE_TRANSPORT=none

# Set up distributed env for single node
export MASTER_ADDR=localhost
export MASTER_PORT=29500
export WORLD_SIZE=8
export NODE_RANK=0
export WORLD_LOCAL_SIZE=8

cd /tmp/pplx_workspace/pplx-kernels

# Run benchmark
echo "Running benchmark..."
python -m tests.bench_all_to_all \
    --dp-size 1 \
    --in-dtype bfloat16 \
    --out-dtype bfloat16 \
    2>&1 | tee /tmp/benchmark_intranode_ep8.log

echo "=== Benchmark complete ==="
echo "Results saved to data/ directory"
ls -lh data/*.tsv | tail -1
EOF

echo ""
echo "=== Fetching results ===" 
scp -P 2222 $NODE_IP:/tmp/pplx_workspace/pplx-kernels/data/*.tsv ./results_intranode_ep8.tsv
echo "Results saved to: ./results_intranode_ep8.tsv"

