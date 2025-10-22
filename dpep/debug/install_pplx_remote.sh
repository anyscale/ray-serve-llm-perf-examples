#!/bin/bash
set -ex

# Remote installation script for pplx-kernels with EFA support
# This runs on the worker node - using NVSHMEM 3.4.5 with nvshmem4py
WORKSPACE=${1:-/tmp/pplx_workspace_$$}

mkdir -p $WORKSPACE
cd $WORKSPACE

# Set CUDA_HOME if not already set
export CUDA_HOME=${CUDA_HOME:-/usr/local/cuda}
export TORCH_CUDA_ARCH_LIST=${TORCH_CUDA_ARCH_LIST:-"9.0a+PTX"}

echo "=== Installing pplx-kernels with EFA support ==="
echo "WORKSPACE: $WORKSPACE"
echo "CUDA_HOME: $CUDA_HOME"
echo "TORCH_CUDA_ARCH_LIST: $TORCH_CUDA_ARCH_LIST"
echo "Using NVSHMEM 3.4.5 with nvshmem4py support"

# Install system dependencies for nvshmem4py
echo "=== Installing system dependencies ==="
sudo apt-get update -qq
sudo apt-get install -y python3.10-venv python3.11-venv

# Install build dependencies
echo "=== Installing cmake and ninja ==="
pip install cmake ninja --quiet

# Download and extract NVSHMEM 3.4.5
if [ ! -d "nvshmem_src" ]; then
    echo "=== Downloading NVSHMEM 3.4.5 ==="
    mkdir -p nvshmem_src
    wget -q https://developer.download.nvidia.com/compute/redist/nvshmem/3.4.5/source/nvshmem_src_cuda12-all-all-3.4.5.tar.gz
    tar -xzf nvshmem_src_cuda12-all-all-3.4.5.tar.gz -C nvshmem_src --strip-components=1
    echo "=== NVSHMEM extracted ==="
fi

echo "=== Building NVSHMEM 3.4.5 with EFA and nvshmem4py support ==="
cd $WORKSPACE/nvshmem_src
mkdir -p build
cd build

# Set libfabric path (AWS EFA)
export LIBFABRIC_HOME=/opt/amazon/efa

# Build NVSHMEM with nvshmem4py enabled
cmake \
    -DCMAKE_INSTALL_PREFIX=$WORKSPACE/nvshmem_install \
    -DCMAKE_CUDA_ARCHITECTURES=90a \
    -DNVSHMEM_LIBFABRIC_SUPPORT=1 \
    -DLIBFABRIC_HOME=$LIBFABRIC_HOME \
    -DNVSHMEM_BUILD_TESTS=0 \
    -DNVSHMEM_BUILD_EXAMPLES=0 \
    -DNVSHMEM_MPI_SUPPORT=0 \
    -DNVSHMEM_PMIX_SUPPORT=0 \
    -DNVSHMEM_BUILD_HYDRA_LAUNCHER=0 \
    -G Ninja \
    ..

echo "=== Compiling NVSHMEM ==="
ninja install

# Set up environment for pplx-kernels build
export CMAKE_PREFIX_PATH=$WORKSPACE/nvshmem_install:$CMAKE_PREFIX_PATH
export NVSHMEM_HOME=$WORKSPACE/nvshmem_install
export LD_LIBRARY_PATH=$NVSHMEM_HOME/lib:$LD_LIBRARY_PATH

# Clone and build pplx-kernels
cd $WORKSPACE
if [ ! -d "pplx-kernels" ]; then
    echo "=== Cloning pplx-kernels ==="
    git clone https://github.com/ppl-ai/pplx-kernels
    cd pplx-kernels
    # Use commit c336faf (tested version)
    git checkout c336faf 2>/dev/null || echo "Using latest main branch"
else
    cd pplx-kernels
fi

echo "=== Building pplx-kernels ==="
PIP_NO_BUILD_ISOLATION=0 pip install -e . --no-deps -v

echo ""
echo "=== Installation complete! ==="
echo ""
echo "Environment setup:"
echo "export NVSHMEM_HOME=$WORKSPACE/nvshmem_install"
echo "export LD_LIBRARY_PATH=\$NVSHMEM_HOME/lib:\$LD_LIBRARY_PATH"
echo "export CMAKE_PREFIX_PATH=\$NVSHMEM_HOME:\$CMAKE_PREFIX_PATH"
echo ""
echo "For EFA (multi-node):"
echo "export NVSHMEM_REMOTE_TRANSPORT=libfabric"
echo "export NVSHMEM_LIBFABRIC_PROVIDER=efa"
echo ""
echo "For single-node:"
echo "export NVSHMEM_REMOTE_TRANSPORT=none"

# Save environment to a file for easy sourcing
cat > $WORKSPACE/setup_env.sh <<'EOF'
export NVSHMEM_HOME=WORKSPACE_PLACEHOLDER/nvshmem_install
export LD_LIBRARY_PATH=$NVSHMEM_HOME/lib:$LD_LIBRARY_PATH
export CMAKE_PREFIX_PATH=$NVSHMEM_HOME:$CMAKE_PREFIX_PATH
export PYTHONPATH=$NVSHMEM_HOME/lib/python3.11/site-packages:$PYTHONPATH
export NVSHMEM_REMOTE_TRANSPORT=libfabric
export NVSHMEM_LIBFABRIC_PROVIDER=efa
EOF

sed -i "s|WORKSPACE_PLACEHOLDER|$WORKSPACE|g" $WORKSPACE/setup_env.sh
chmod +x $WORKSPACE/setup_env.sh

echo ""
echo "Source this file to set up environment: source $WORKSPACE/setup_env.sh"
echo "Workspace location: $WORKSPACE"
