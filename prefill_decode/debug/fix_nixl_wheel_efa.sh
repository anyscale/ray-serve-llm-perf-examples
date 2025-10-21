#!/bin/bash
# Script to fix nixl wheel EFA compatibility by replacing bundled libfabric
# with symlinks to AWS EFA libfabric
#
# Usage: ./fix_nixl_wheel_efa.sh

set -e

SSH_PORT=2222
GPU_NODES=("172.25.105.35" "172.25.105.65")
NIXL_LIBS_PATH="/home/ray/anaconda3/lib/python3.11/site-packages/nixl.libs"
EFA_LIB_PATH="/opt/amazon/efa/lib"

echo "=========================================="
echo "NIXL Wheel EFA Compatibility Fix"
echo "=========================================="
echo ""
echo "This script will:"
echo "  1. Disable bundled libfabric/libefa/libibverbs (vanilla upstream)"
echo "  2. Create symlinks to AWS EFA libraries (2.1.0amzn3.0)"
echo ""
echo "Target nodes: ${GPU_NODES[@]}"
echo ""

# Function to fix a single node
fix_node() {
    local NODE_IP=$1
    echo "----------------------------------------"
    echo "Processing node: $NODE_IP"
    echo "----------------------------------------"
    
    # Step 1: Verify AWS EFA is installed
    echo "[1/4] Verifying AWS EFA installation..."
    EFA_VERSION=$(ssh -p ${SSH_PORT} ${NODE_IP} "${EFA_LIB_PATH}/../bin/fi_info --version 2>&1 | head -2 | tail -1")
    echo "  $EFA_VERSION"
    
    if [[ ! $EFA_VERSION == *"2."* ]]; then
        echo "  ⚠ WARNING: Expected AWS EFA libfabric 2.x, got: $EFA_VERSION"
        read -p "  Continue anyway? (y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "  Skipping node $NODE_IP"
            return 1
        fi
    fi
    
    # Step 2: Disable bundled libraries
    echo "[2/4] Disabling bundled libraries..."
    ssh -p ${SSH_PORT} ${NODE_IP} "
        cd ${NIXL_LIBS_PATH}
        if [ -f libfabric-fc70961d.so.1.29.0 ] && [ ! -L libfabric-fc70961d.so.1.29.0 ]; then
            mv libfabric-fc70961d.so.1.29.0 libfabric-fc70961d.so.1.29.0.DISABLED
            echo '  ✓ Disabled libfabric'
        else
            echo '  - libfabric already disabled or is symlink'
        fi
        
        if [ -f libefa-f5f6ec5c.so.1.2.48.0 ] && [ ! -L libefa-f5f6ec5c.so.1.2.48.0 ]; then
            mv libefa-f5f6ec5c.so.1.2.48.0 libefa-f5f6ec5c.so.1.2.48.0.DISABLED
            echo '  ✓ Disabled libefa'
        else
            echo '  - libefa already disabled or is symlink'
        fi
        
        if [ -f libibverbs-1de1263b.so.1.14.48.0 ] && [ ! -L libibverbs-1de1263b.so.1.14.48.0 ]; then
            mv libibverbs-1de1263b.so.1.14.48.0 libibverbs-1de1263b.so.1.14.48.0.DISABLED
            echo '  ✓ Disabled libibverbs'
        else
            echo '  - libibverbs already disabled or is symlink'
        fi
    "
    
    # Step 3: Create symlinks to system EFA libraries
    echo "[3/4] Creating symlinks to AWS EFA libraries..."
    ssh -p ${SSH_PORT} ${NODE_IP} "
        cd ${NIXL_LIBS_PATH}
        
        # Remove old symlinks if they exist
        [ -L libfabric-fc70961d.so.1.29.0 ] && rm -f libfabric-fc70961d.so.1.29.0
        [ -L libefa-f5f6ec5c.so.1.2.48.0 ] && rm -f libefa-f5f6ec5c.so.1.2.48.0
        [ -L libibverbs-1de1263b.so.1.14.48.0 ] && rm -f libibverbs-1de1263b.so.1.14.48.0
        
        # Create new symlinks
        ln -s ${EFA_LIB_PATH}/libfabric.so.1 libfabric-fc70961d.so.1.29.0
        echo '  ✓ Created libfabric symlink'
        
        ln -s ${EFA_LIB_PATH}/libefa.so.1 libefa-f5f6ec5c.so.1.2.48.0
        echo '  ✓ Created libefa symlink'
        
        ln -s ${EFA_LIB_PATH}/libibverbs.so.1 libibverbs-1de1263b.so.1.14.48.0
        echo '  ✓ Created libibverbs symlink'
    "
    
    # Step 4: Verify
    echo "[4/4] Verifying symlinks..."
    VERIFY_OUTPUT=$(ssh -p ${SSH_PORT} ${NODE_IP} "
        cd ${NIXL_LIBS_PATH}
        ls -la libfabric-fc70961d.so.1.29.0 | awk '{print \$9, \$10, \$11}'
    ")
    echo "  $VERIFY_OUTPUT"
    
    echo "✅ Node $NODE_IP fixed successfully!"
    echo ""
    
    return 0
}

# Apply fix to all nodes
SUCCESS_COUNT=0
FAIL_COUNT=0

for NODE_IP in "${GPU_NODES[@]}"; do
    if fix_node "$NODE_IP"; then
        ((SUCCESS_COUNT++))
    else
        ((FAIL_COUNT++))
    fi
done

echo "=========================================="
echo "SUMMARY"
echo "=========================================="
echo "Successful: $SUCCESS_COUNT"
echo "Failed: $FAIL_COUNT"
echo ""

if [ $FAIL_COUNT -eq 0 ]; then
    echo "✅ All nodes fixed successfully!"
    echo ""
    echo "You can now test with:"
    echo "  cd /home/ray/default/ray-serve-pd-example/debug"
    echo "  RAY_DEDUP_LOGS=0 python test_nixl_connector_ray.py --strategy spread --random-blocks --backends LIBFABRIC --num-blocks 3750 --num-layers 50 --blocks 128"
    exit 0
else
    echo "⚠ Some nodes failed. Please check the output above."
    exit 1
fi

