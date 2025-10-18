#!/bin/bash
# Script to install NIXL with UCX 1.20 + EFA on all GPU nodes in parallel
# This builds everything from source on each node

set -e  # Exit on error

GPU_NODES=("172.25.105.35" "172.25.105.65")
SSH_PORT=2222
BUILD_SCRIPT="build_nixl_ucx_efa.sh"
LOCAL_SCRIPT_PATH="/home/ray/default/ray-serve-pd-example/debug/${BUILD_SCRIPT}"

echo "=========================================="
echo "NIXL + UCX 1.20 + EFA Parallel Installation"
echo "=========================================="
echo "Nodes to install: ${GPU_NODES[@]}"
echo "Build script: ${BUILD_SCRIPT}"
echo ""

# Check if build script exists
if [ ! -f "$LOCAL_SCRIPT_PATH" ]; then
    echo "ERROR: Build script not found at $LOCAL_SCRIPT_PATH"
    exit 1
fi

echo "✓ Build script found"
echo ""

# Function to install nixl on a single node
install_nixl_on_node() {
    local NODE_IP=$1
    local NODE_INDEX=$2
    local LOG_FILE="/tmp/nixl_install_${NODE_IP}.log"
    
    echo "[$NODE_INDEX] Starting installation on $NODE_IP..."
    
    {
        echo "=========================================="
        echo "[$NODE_INDEX] Installing on node: $NODE_IP"
        echo "=========================================="
        echo "$(date): Starting installation"
        
        # Step 1: Copy build script to node
        echo "[$NODE_INDEX] Copying build script..."
        if scp -P ${SSH_PORT} "$LOCAL_SCRIPT_PATH" ${NODE_IP}:/tmp/${BUILD_SCRIPT} 2>&1; then
            echo "[$NODE_INDEX] ✓ Build script copied"
        else
            echo "[$NODE_INDEX] ✗ Failed to copy build script"
            exit 1
        fi
        
        # Step 2: Make it executable
        echo "[$NODE_INDEX] Making script executable..."
        if ssh -p ${SSH_PORT} ${NODE_IP} "chmod +x /tmp/${BUILD_SCRIPT}" 2>&1; then
            echo "[$NODE_INDEX] ✓ Script is executable"
        else
            echo "[$NODE_INDEX] ✗ Failed to make script executable"
            exit 1
        fi
        
        # Step 3: Run build script
        echo "[$NODE_INDEX] Running build (this will take 10-15 minutes)..."
        echo "$(date): Build started"
        if ssh -p ${SSH_PORT} ${NODE_IP} "/tmp/${BUILD_SCRIPT}" 2>&1; then
            echo "$(date): Build completed successfully"
            echo "[$NODE_INDEX] ✅ SUCCESS"
            exit 0
        else
            echo "$(date): Build failed"
            echo "[$NODE_INDEX] ❌ FAILED"
            exit 1
        fi
        
    } > "$LOG_FILE" 2>&1
    
    return $?
}

# Start installations in parallel
echo "Starting parallel installations on ${#GPU_NODES[@]} nodes..."
echo "Logs will be saved to /tmp/nixl_install_*.log"
echo ""

declare -A PIDS
NODE_INDEX=1

for NODE_IP in "${GPU_NODES[@]}"; do
    install_nixl_on_node "$NODE_IP" "$NODE_INDEX" &
    PIDS[$NODE_IP]=$!
    echo "Started installation on $NODE_IP (PID: ${PIDS[$NODE_IP]})"
    ((NODE_INDEX++))
done

echo ""
echo "All installations started. Waiting for completion..."
echo "You can monitor progress in another terminal with:"
for NODE_IP in "${GPU_NODES[@]}"; do
    echo "  tail -f /tmp/nixl_install_${NODE_IP}.log"
done
echo ""

# Wait for all installations to complete and track results
declare -A RESULTS
SUCCESS_COUNT=0
FAIL_COUNT=0

for NODE_IP in "${GPU_NODES[@]}"; do
    PID=${PIDS[$NODE_IP]}
    echo "Waiting for $NODE_IP (PID: $PID)..."
    
    if wait $PID; then
        RESULTS[$NODE_IP]="SUCCESS"
        ((SUCCESS_COUNT++))
        echo "✅ $NODE_IP completed successfully"
    else
        RESULTS[$NODE_IP]="FAILED"
        ((FAIL_COUNT++))
        echo "❌ $NODE_IP failed"
    fi
done

# Print summary
echo ""
echo "=========================================="
echo "INSTALLATION SUMMARY"
echo "=========================================="
echo "Total nodes: ${#GPU_NODES[@]}"
echo "Successful: $SUCCESS_COUNT"
echo "Failed: $FAIL_COUNT"
echo ""

echo "Results by node:"
for NODE_IP in "${GPU_NODES[@]}"; do
    STATUS="${RESULTS[$NODE_IP]}"
    if [ "$STATUS" = "SUCCESS" ]; then
        echo "  ✅ $NODE_IP - SUCCESS"
    else
        echo "  ❌ $NODE_IP - FAILED (check /tmp/nixl_install_${NODE_IP}.log)"
    fi
done

echo ""
echo "=========================================="

if [ $FAIL_COUNT -gt 0 ]; then
    echo "❌ Some installations failed"
    echo ""
    echo "To debug failed nodes, check the logs:"
    for NODE_IP in "${GPU_NODES[@]}"; do
        if [ "${RESULTS[$NODE_IP]}" = "FAILED" ]; then
            echo "  cat /tmp/nixl_install_${NODE_IP}.log"
        fi
    done
    exit 1
else
    echo "✅ All installations completed successfully!"
    echo ""
    echo "IMPORTANT: To use NIXL with UCX 1.20 on each node, set:"
    echo "  export LD_LIBRARY_PATH=/usr/local/ucx/lib:/usr/local/nixl/lib/x86_64-linux-gnu:\$LD_LIBRARY_PATH"
    echo ""
    echo "Verify installation on each node:"
    for NODE_IP in "${GPU_NODES[@]}"; do
        echo "  ssh -p ${SSH_PORT} ${NODE_IP} 'export LD_LIBRARY_PATH=/usr/local/ucx/lib:/usr/local/nixl/lib/x86_64-linux-gnu:\$LD_LIBRARY_PATH && /usr/local/ucx/bin/ucx_info -d | grep -c srd'"
    done
    exit 0
fi
