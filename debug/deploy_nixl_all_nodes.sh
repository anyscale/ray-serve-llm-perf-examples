#!/bin/bash
# Script to deploy nixl with system libfabric to all GPU nodes
# This builds nixl from source with AWS EFA libfabric support

# Note: We don't use 'set -e' here because we want to continue to other nodes even if one fails

NIXL_VERSION="main"  # Use main branch instead of tag
NIXL_BUILD_DIR="/tmp/nixl-build"
NIXL_INSTALL_PREFIX="/usr/local/nixl"
EFA_LIBFABRIC_PATH="/opt/amazon/efa"
SSH_PORT=2222
AUTO_PROCEED=true  # Set to false to prompt before proceeding

echo "=========================================="
echo "NIXL Deployment Script"
echo "=========================================="
echo "Version: ${NIXL_VERSION}"
echo "Install prefix: ${NIXL_INSTALL_PREFIX}"
echo "EFA libfabric: ${EFA_LIBFABRIC_PATH}"
echo ""

# Function to install nixl on a single node
install_nixl_on_node() {
    local NODE_IP=$1
    local NODE_INDEX=$2
    local IS_LOCAL=$3  # "true" if this is the local/head node
    
    echo ""
    echo "=========================================="
    echo "[$NODE_INDEX] Installing on node: $NODE_IP $([ "$IS_LOCAL" = "true" ] && echo "(LOCAL/HEAD NODE)")"
    echo "=========================================="
    
    # Determine command prefix (local or SSH)
    local CMD_PREFIX=""
    if [ "$IS_LOCAL" = "true" ]; then
        CMD_PREFIX=""
    else
        CMD_PREFIX="ssh -p ${SSH_PORT} ${NODE_IP}"
    fi
    
    # Step 1: Uninstall pip nixl
    echo "[$NODE_INDEX] Step 1/7: Uninstalling pip nixl..."
    if [ "$IS_LOCAL" = "true" ]; then
        pip uninstall -y nixl 2>/dev/null || true
    else
        ssh -p ${SSH_PORT} ${NODE_IP} "pip uninstall -y nixl 2>/dev/null || true"
    fi
    
    # Helper function to execute command locally or remotely
    exec_cmd() {
        if [ "$IS_LOCAL" = "true" ]; then
            bash -c "$1"
        else
            ssh -p ${SSH_PORT} ${NODE_IP} "$1"
        fi
    }
    
    # Step 2: Clone nixl if not exists
    echo "[$NODE_INDEX] Step 2/7: Cloning nixl repository..."
    exec_cmd "
        if [ -d ${NIXL_BUILD_DIR} ]; then
            echo '  Cleaning existing build directory...'
            rm -rf ${NIXL_BUILD_DIR}
        fi
        cd /tmp && git clone --depth 1 --branch ${NIXL_VERSION} https://github.com/ai-dynamo/nixl.git nixl-build
    " 2>&1 | sed "s/^/  /"
    
    # Step 3: Configure build with RPATH for EFA libfabric
    echo "[$NODE_INDEX] Step 3/7: Configuring meson build..."
    exec_cmd "
        cd ${NIXL_BUILD_DIR} && \
        LDFLAGS='-Wl,-rpath,${EFA_LIBFABRIC_PATH}/lib' \
        meson setup -Dlibfabric_path=${EFA_LIBFABRIC_PATH} build/ --prefix=${NIXL_INSTALL_PREFIX}
    " 2>&1 | tail -20 | sed "s/^/  /"
    
    # Step 4: Build with ninja
    echo "[$NODE_INDEX] Step 4/7: Building nixl (this may take 2-3 minutes)..."
    exec_cmd "
        cd ${NIXL_BUILD_DIR}/build && ninja
    " 2>&1 | tail -10 | sed "s/^/  /"
    
    # Step 5: Install to /usr/local/nixl
    echo "[$NODE_INDEX] Step 5/7: Installing nixl to ${NIXL_INSTALL_PREFIX}..."
    exec_cmd "
        cd ${NIXL_BUILD_DIR}/build && sudo ninja install
    " 2>&1 | tail -10 | sed "s/^/  /"
    
    # Step 6: Configure ldconfig
    echo "[$NODE_INDEX] Step 6/7: Configuring library paths..."
    exec_cmd "
        sudo sh -c 'echo ${NIXL_INSTALL_PREFIX}/lib/x86_64-linux-gnu > /etc/ld.so.conf.d/nixl.conf'
        sudo sh -c 'echo ${EFA_LIBFABRIC_PATH}/lib >> /etc/ld.so.conf.d/nixl.conf'
        sudo ldconfig
    "
    
    # Step 7: Install Python package
    echo "[$NODE_INDEX] Step 7/7: Installing Python package..."
    exec_cmd "
        cd ${NIXL_BUILD_DIR} && pip install . --no-cache-dir
    " 2>&1 | tail -5 | sed "s/^/  /"
    
    # Verify installation
    echo "[$NODE_INDEX] Verifying installation..."
    VERIFY_OUTPUT=$(exec_cmd "
        python3 << 'VERIFY_EOF'
import sys
try:
    import nixl
    from nixl._api import nixl_agent, nixl_agent_config
    print('✓ nixl imported successfully')
    
    # Check libfabric linking
    import subprocess
    result = subprocess.run(
        ['ldd', '${NIXL_INSTALL_PREFIX}/lib/x86_64-linux-gnu/plugins/libplugin_LIBFABRIC.so'],
        capture_output=True, text=True
    )
    if '${EFA_LIBFABRIC_PATH}/lib/libfabric.so' in result.stdout:
        print('✓ Using EFA libfabric from ${EFA_LIBFABRIC_PATH}')
        sys.exit(0)
    else:
        print('✗ ERROR: Not using EFA libfabric')
        print(result.stdout)
        sys.exit(1)
except Exception as e:
    print(f'✗ ERROR: {e}')
    sys.exit(1)
VERIFY_EOF
    " 2>&1)
    
    echo "$VERIFY_OUTPUT" | sed "s/^/  /"
    
    if echo "$VERIFY_OUTPUT" | grep -q "ERROR"; then
        echo "[$NODE_INDEX] ❌ FAILED on $NODE_IP"
        return 1
    else
        echo "[$NODE_INDEX] ✅ SUCCESS on $NODE_IP"
        return 0
    fi
}

# Main execution
echo "Getting list of nodes from Ray cluster..."

# Get all node IPs (GPU workers + head node) using Ray
GPU_NODES=$(python3 << 'EOF'
import ray
import json
import socket

# Connect to existing Ray cluster
ray.init(address="auto")

# Get all nodes with GPUs
nodes = ray.nodes()
all_nodes = []

for node in nodes:
    if node['Alive']:
        node_ip = node['NodeManagerAddress']
        gpu_count = int(node['Resources'].get('GPU', 0))
        is_head = node.get('NodeName', '').endswith('-head') or node_ip == socket.gethostbyname(socket.gethostname())
        
        # Add GPU nodes and head node
        if gpu_count > 0:
            all_nodes.append({'ip': node_ip, 'gpus': gpu_count, 'type': 'GPU worker'})
        elif is_head:
            all_nodes.append({'ip': node_ip, 'gpus': 0, 'type': 'Head node (for Ray driver)'})

# Print as JSON
print(json.dumps(all_nodes))
ray.shutdown()
EOF
)

echo "Nodes found:"
echo "$GPU_NODES" | python3 -m json.tool

# Parse nodes and install on each
NODE_IPS=$(echo "$GPU_NODES" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for node in data:
    print(node['ip'])
")

if [ -z "$NODE_IPS" ]; then
    echo "ERROR: No nodes found in Ray cluster"
    exit 1
fi

# Count nodes
NODE_COUNT=$(echo "$NODE_IPS" | wc -l)
echo ""
echo "Will install nixl on $NODE_COUNT nodes (GPU workers + head node)"
echo ""
if [ "$AUTO_PROCEED" != "true" ]; then
    read -p "Press Enter to continue or Ctrl+C to cancel..."
else
    echo "Auto-proceeding with installation..."
fi

# Get local IP to detect head node
LOCAL_IP=$(hostname -I | awk '{print $1}')

# Install on each node
SUCCESS_COUNT=0
FAIL_COUNT=0
FAILED_NODES=""

NODE_INDEX=1
for NODE_IP in $NODE_IPS; do
    # Check if this is the local node
    IS_LOCAL="false"
    if [ "$NODE_IP" = "$LOCAL_IP" ] || [ "$NODE_IP" = "127.0.0.1" ] || [ "$NODE_IP" = "localhost" ]; then
        IS_LOCAL="true"
    fi
    
    if install_nixl_on_node "$NODE_IP" "$NODE_INDEX" "$IS_LOCAL"; then
        ((SUCCESS_COUNT++))
    else
        ((FAIL_COUNT++))
        FAILED_NODES="${FAILED_NODES}${NODE_IP}\n"
    fi
    ((NODE_INDEX++))
done

# Summary
echo ""
echo "=========================================="
echo "DEPLOYMENT SUMMARY"
echo "=========================================="
echo "Total nodes: $NODE_COUNT"
echo "Successful: $SUCCESS_COUNT"
echo "Failed: $FAIL_COUNT"

if [ $FAIL_COUNT -gt 0 ]; then
    echo ""
    echo "Failed nodes:"
    echo -e "$FAILED_NODES"
    exit 1
else
    echo ""
    echo "✅ All nodes deployed successfully!"
    echo ""
    echo "Next steps:"
    echo "  1. Test with: cd /home/ray/default/ray-serve-pd-example"
    echo "  2. Run: RAY_DEDUP_LOGS=0 python test_nixl_connector_ray.py --strategy spread --random-blocks --backends LIBFABRIC --num-blocks 3750 --num-layers 50 --blocks 128 --verbose"
    exit 0
fi

