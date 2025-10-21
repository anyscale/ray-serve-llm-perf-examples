#!/bin/bash
# Script to build UCX 1.20 (master) with EFA support and nixl from source
# This script builds everything locally on the current node

set -e  # Exit on error

echo "=========================================="
echo "UCX 1.20 + NIXL EFA Build Script"
echo "=========================================="
echo ""

# Configuration
UCX_INSTALL_PREFIX="/usr/local/ucx"
NIXL_INSTALL_PREFIX="/usr/local/nixl"
BUILD_DIR="/tmp/nixl-ucx-build"
EFA_PATH="/opt/amazon/efa"
NUM_CORES=$(nproc)

echo "Configuration:"
echo "  UCX install path: $UCX_INSTALL_PREFIX"
echo "  NIXL install path: $NIXL_INSTALL_PREFIX"
echo "  Build directory: $BUILD_DIR"
echo "  EFA path: $EFA_PATH"
echo "  Parallel build jobs: $NUM_CORES"
echo ""

# Check if EFA is installed
if [ ! -d "$EFA_PATH" ]; then
    echo "ERROR: EFA not found at $EFA_PATH"
    echo "Please install AWS EFA first"
    exit 1
fi

echo "✓ EFA found at $EFA_PATH"
echo ""

# Create build directory
echo "Creating build directory..."
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"

# ============================================
# Step 1: Build UCX 1.20 (master) with EFA
# ============================================
echo "=========================================="
echo "Step 1: Building UCX 1.20 (master) with EFA support"
echo "=========================================="
echo ""

echo "Cloning UCX from GitHub (master branch)..."
git clone --depth 1 https://github.com/openucx/ucx.git
cd ucx

echo "Running autogen.sh..."
./autogen.sh

echo ""
echo "Configuring UCX with EFA support..."
echo "Configure options (from nixl docker + EFA):"
echo "  --prefix=$UCX_INSTALL_PREFIX"
echo "  --with-efa=$EFA_PATH"
echo "  --enable-shared"
echo "  --disable-static"
echo "  --disable-doxygen-doc"
echo "  --enable-optimizations"
echo "  --enable-cma"
echo "  --enable-devel-headers"
echo "  --with-verbs"
echo "  --with-dm"
echo "  --enable-mt"
echo ""

./configure \
    --prefix="$UCX_INSTALL_PREFIX" \
    --with-efa="$EFA_PATH" \
    --enable-shared \
    --disable-static \
    --disable-doxygen-doc \
    --enable-optimizations \
    --enable-cma \
    --enable-devel-headers \
    --with-verbs \
    --with-dm \
    --enable-mt

echo ""
echo "Building UCX (using $NUM_CORES cores)..."
make -j${NUM_CORES}

echo ""
echo "Installing UCX to $UCX_INSTALL_PREFIX..."
sudo make install

echo ""
echo "✅ UCX build complete!"
echo ""

# Verify UCX installation
echo "Verifying UCX installation..."
if [ -f "$UCX_INSTALL_PREFIX/bin/ucx_info" ]; then
    echo "✓ ucx_info found"
    $UCX_INSTALL_PREFIX/bin/ucx_info -v
    echo ""
    echo "UCX Transports available:"
    $UCX_INSTALL_PREFIX/bin/ucx_info -d | grep -E "Transport:|Device:" | head -20
else
    echo "✗ ERROR: ucx_info not found at $UCX_INSTALL_PREFIX/bin/ucx_info"
    exit 1
fi

# ============================================
# Step 2: Build NIXL from source with custom UCX
# ============================================
cd "$BUILD_DIR"

echo ""
echo "=========================================="
echo "Step 2: Building NIXL from source with UCX 1.20"
echo "=========================================="
echo ""

echo "Installing build dependencies..."
# Install meson and ninja if not present
pip3 show meson >/dev/null 2>&1 || pip3 install --user meson
pip3 show ninja >/dev/null 2>&1 || pip3 install --user ninja

# Make sure meson is in PATH
export PATH="$HOME/.local/bin:$PATH"

echo "Cloning NIXL from GitHub..."
git clone https://github.com/ai-dynamo/nixl.git
cd nixl

echo ""
echo "Configuring NIXL with custom UCX..."
echo "Meson options:"
echo "  --prefix=$NIXL_INSTALL_PREFIX"
echo "  -Ducx_path=$UCX_INSTALL_PREFIX"
echo ""

# Set up environment for meson to find UCX
export PKG_CONFIG_PATH="$UCX_INSTALL_PREFIX/lib/pkgconfig:$PKG_CONFIG_PATH"
export LD_LIBRARY_PATH="$UCX_INSTALL_PREFIX/lib:$LD_LIBRARY_PATH"

meson setup builddir \
    --prefix="$NIXL_INSTALL_PREFIX" \
    -Ducx_path="$UCX_INSTALL_PREFIX"

cd builddir

echo ""
echo "Building NIXL (using $NUM_CORES cores)..."
ninja -j${NUM_CORES}

echo ""
echo "Installing NIXL to $NIXL_INSTALL_PREFIX..."
sudo ninja install

echo ""
echo "Installing Python bindings with pip..."
cd "$BUILD_DIR/nixl"
pip3 install . 

echo ""
echo "✅ NIXL build complete!"
echo ""

# ============================================
# Step 3: Configure ldconfig and Python path
# ============================================
echo "=========================================="
echo "Step 3: Configuring system paths"
echo "=========================================="
echo ""

# Add UCX and NIXL to ldconfig
echo "Adding libraries to ldconfig..."
echo "$UCX_INSTALL_PREFIX/lib" | sudo tee /etc/ld.so.conf.d/ucx.conf >/dev/null
echo "$NIXL_INSTALL_PREFIX/lib/x86_64-linux-gnu" | sudo tee /etc/ld.so.conf.d/nixl.conf >/dev/null
sudo ldconfig

echo "✓ ldconfig updated"
echo ""

# ============================================
# Step 4: Verification
# ============================================
echo "=========================================="
echo "Step 4: Verifying installation"
echo "=========================================="
echo ""

echo "Testing NIXL import and UCX backend..."
# Set LD_LIBRARY_PATH for verification
export LD_LIBRARY_PATH="$UCX_INSTALL_PREFIX/lib:$NIXL_INSTALL_PREFIX/lib/x86_64-linux-gnu:$LD_LIBRARY_PATH"

timeout 60 python3 << 'VERIFY_EOF'
import sys
import os

try:
    import nixl
    print('✓ nixl imported successfully')
    
    # Check nixl path
    nixl_path = os.path.dirname(nixl.__file__)
    print(f'✓ nixl location: {nixl_path}')
    
    # Try to import and configure with UCX backend
    try:
        from nixl._api import nixl_agent, nixl_agent_config
        print('✓ nixl._api imported successfully')
        
        # Try to create agent config with UCX
        config = nixl_agent_config(backends=['UCX'])
        print('✓ UCX backend available')
        
        # Test basic agent creation
        agent = nixl_agent('test_agent', config)
        print('✓ nixl_agent created successfully with UCX 1.20 backend')
        
    except Exception as e:
        print(f'✗ ERROR configuring nixl with UCX: {e}')
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    print('\n✅ All verification checks passed!')
    sys.exit(0)
    
except ImportError as e:
    print(f'✗ ERROR: Cannot import nixl: {e}')
    print('\nPYTHONPATH entries:')
    for path in sys.path:
        print(f'  {path}')
    sys.exit(1)
except Exception as e:
    print(f'✗ ERROR: {e}')
    import traceback
    traceback.print_exc()
    sys.exit(1)
VERIFY_EOF

VERIFY_RESULT=$?

echo ""
if [ $VERIFY_RESULT -eq 0 ]; then
    echo "=========================================="
    echo "✅ BUILD AND INSTALLATION SUCCESSFUL!"
    echo "=========================================="
    echo ""
    echo "UCX 1.20 (master) with EFA support installed to: $UCX_INSTALL_PREFIX"
    echo "NIXL built against UCX 1.20 installed to: $NIXL_INSTALL_PREFIX"
    echo ""
    echo "IMPORTANT: To use NIXL with UCX 1.20, set the following before running:"
    echo "  export LD_LIBRARY_PATH=\"$UCX_INSTALL_PREFIX/lib:$NIXL_INSTALL_PREFIX/lib/x86_64-linux-gnu:\\\$LD_LIBRARY_PATH\""
    echo ""
    echo "UCX supports EFA SRD transport for high-performance inter-node transfers!"
    echo ""
    echo "To verify UCX transports:"
    echo "  $UCX_INSTALL_PREFIX/bin/ucx_info -d | grep -A 5 srd"
    echo ""
else
    echo "=========================================="
    echo "❌ VERIFICATION FAILED"
    echo "=========================================="
    echo ""
    echo "The build completed but verification failed."
    echo "Please check the error messages above."
    exit 1
fi

# Clean up build directory
echo "Cleaning up build directory $BUILD_DIR..."
rm -rf "$BUILD_DIR"
echo "✓ Build directory removed"

exit 0

