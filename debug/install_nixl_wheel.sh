#!/bin/bash
# Script to install nixl wheel (0.6.1) on all GPU nodes and head node
# This is a simpler alternative to building from source

# Note: We don't use 'set -e' here because we want to continue to other nodes even if one fails

NIXL_VERSION="0.6.1"
SSH_PORT=2222
AUTO_PROCEED=true  # Set to false to prompt before proceeding

echo "=========================================="
echo "NIXL Wheel Installation Script"
echo "=========================================="
echo "Version: ${NIXL_VERSION}"
echo "Installation method: uv pip install"
echo ""

# Function to install nixl wheel on a single node
install_nixl_wheel_on_node() {
    local NODE_IP=$1
    local NODE_INDEX=$2
    local IS_LOCAL=$3  # "true" if this is the local/head node
    
    echo ""
    echo "=========================================="
    echo "[$NODE_INDEX] Installing on node: $NODE_IP $([ "$IS_LOCAL" = "true" ] && echo "(LOCAL/HEAD NODE)")"
    echo "=========================================="
    
    # Helper function to execute command locally or remotely
    exec_cmd() {
        if [ "$IS_LOCAL" = "true" ]; then
            bash -c "$1"
        else
            ssh -p ${SSH_PORT} ${NODE_IP} "$1"
        fi
    }
    
    # Step 1: Complete uninstallation
    echo "[$NODE_INDEX] Step 1/3: Completely uninstalling existing nixl..."
    exec_cmd "
        # Uninstall pip package
        pip uninstall -y nixl 2>/dev/null || true
        uv pip uninstall -y nixl --system 2>/dev/null || true
        
        # Remove any source-built installations
        if [ -d /usr/local/nixl ]; then
            echo '  Removing /usr/local/nixl...'
            sudo rm -rf /usr/local/nixl
        fi
        
        # Remove ldconfig entry
        if [ -f /etc/ld.so.conf.d/nixl.conf ]; then
            echo '  Removing ldconfig entry...'
            sudo rm -f /etc/ld.so.conf.d/nixl.conf
            sudo ldconfig
        fi
        
        # Remove build directory if it exists
        if [ -d /tmp/nixl-build ]; then
            echo '  Removing build directory...'
            rm -rf /tmp/nixl-build
        fi
        
        echo '  Cleanup complete'
    " 2>&1 | sed "s/^/  /"
    
    # Step 2: Install nixl wheel using uv
    echo "[$NODE_INDEX] Step 2/3: Installing nixl==${NIXL_VERSION} using uv..."
    exec_cmd "
        uv pip install nixl==${NIXL_VERSION} --system
    " 2>&1 | tail -10 | sed "s/^/  /"
    
    # Step 3: Verify installation
    echo "[$NODE_INDEX] Step 3/3: Verifying installation..."
    VERIFY_OUTPUT=$(exec_cmd "
        python3 << 'VERIFY_EOF'
import sys
try:
    import nixl
    from nixl._api import nixl_agent, nixl_agent_config
    print('✓ nixl imported successfully')
    
    # Check that we're using the wheel installation
    import os
    nixl_path = os.path.dirname(nixl.__file__)
    if '/usr/local/nixl' in nixl_path:
        print('✗ ERROR: Still using source-built nixl at /usr/local/nixl')
        sys.exit(1)
    else:
        print(f'✓ Using wheel installation from: {nixl_path}')
    
    # Check backends are available
    try:
        config = nixl_agent_config(backends=['LIBFABRIC', 'UCX'])
        print('✓ Backends: LIBFABRIC and UCX available')
    except Exception as e:
        print(f'⚠ Warning: Could not create agent config: {e}')
    
    sys.exit(0)
except ImportError as e:
    print(f'✗ ERROR: Cannot import nixl: {e}')
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
ALL_NODES=$(python3 << 'EOF'
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
echo "$ALL_NODES" | python3 -m json.tool

# Parse nodes and install on each
NODE_IPS=$(echo "$ALL_NODES" | python3 -c "
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
echo "Will install nixl==${NIXL_VERSION} on $NODE_COUNT nodes (GPU workers + head node)"
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
    
    if install_nixl_wheel_on_node "$NODE_IP" "$NODE_INDEX" "$IS_LOCAL"; then
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
    echo "Note: nixl ${NIXL_VERSION} wheel includes bundled UCX and libfabric libraries."
    echo "      To use system EFA libfabric, you may need to set LD_LIBRARY_PATH."
    exit 0
fi

