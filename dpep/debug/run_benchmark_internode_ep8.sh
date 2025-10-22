#!/bin/bash
set -ex

# Benchmark: Inter-node EP8 (2 nodes, 4 GPUs each via EFA)
# Tests EFA communication between nodes

NODE1_IP=172.25.105.98
NODE2_IP=172.25.105.130
MASTER_ADDR=$NODE1_IP

echo "=== Running Inter-node EP8 Benchmark (EFA) ==="
echo "Node 1: $NODE1_IP (rank 0-3)"
echo "Node 2: $NODE2_IP (rank 4-7)"
echo "Testing: 1 and 128 tokens per GPU"

# Start on Node 2 first (background)
ssh -p 2222 $NODE2_IP << EOF &
set -ex
source /tmp/pplx_workspace/setup_env.sh

export MASTER_ADDR=$MASTER_ADDR
export MASTER_PORT=29500
export WORLD_SIZE=8
export NODE_RANK=1
export WORLD_LOCAL_SIZE=4
export NVSHMEM_REMOTE_TRANSPORT=libfabric
export NVSHMEM_LIBFABRIC_PROVIDER=efa

cd /tmp/pplx_workspace/pplx-kernels
python -m tests.bench_all_to_all \
    --dp-size 1 \
    --in-dtype bfloat16 \
    --out-dtype bfloat16 \
    2>&1 | tee /tmp/benchmark_internode_ep8_node2.log
EOF

# Give node 2 time to start
sleep 5

# Start on Node 1 (foreground, will collect results)
ssh -p 2222 $NODE1_IP << 'EOF'
set -ex
source /tmp/pplx_workspace/setup_env.sh

export MASTER_ADDR=172.25.105.98
export MASTER_PORT=29500
export WORLD_SIZE=8
export NODE_RANK=0
export WORLD_LOCAL_SIZE=4
export NVSHMEM_REMOTE_TRANSPORT=libfabric
export NVSHMEM_LIBFABRIC_PROVIDER=efa

cd /tmp/pplx_workspace/pplx-kernels
python -m tests.bench_all_to_all \
    --dp-size 1 \
    --in-dtype bfloat16 \
    --out-dtype bfloat16 \
    2>&1 | tee /tmp/benchmark_internode_ep8_node1.log

echo "=== Benchmark complete ==="
ls -lh data/*.tsv | tail -1
EOF

# Wait for node 2 to finish
wait

echo ""
echo "=== Fetching results ==="
scp -P 2222 $NODE1_IP:/tmp/pplx_workspace/pplx-kernels/data/*.tsv ./results_internode_ep8.tsv 2>/dev/null || true
echo "Results saved to: ./results_internode_ep8.tsv"

