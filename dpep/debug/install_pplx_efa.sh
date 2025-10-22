#!/bin/bash
set -ex

# Installation script for pplx-kernels with EFA support
WORKSPACE=${1:-$(pwd)/pplx_workspace}

if [ ! -d "$WORKSPACE" ]; then
    mkdir -p $WORKSPACE
fi

# Set CUDA_HOME if not already set
export CUDA_HOME=${CUDA_HOME:-/usr/local/cuda}
export TORCH_CUDA_ARCH_LIST=${TORCH_CUDA_ARCH_LIST:-"9.0a+PTX"}

echo "Installing pplx-kernels with EFA support"
echo "WORKSPACE: $WORKSPACE"
echo "CUDA_HOME: $CUDA_HOME"
echo "TORCH_CUDA_ARCH_LIST: $TORCH_CUDA_ARCH_LIST"

# Install dependencies
pip3 install cmake torch ninja --quiet

# Build NVSHMEM with EFA (libfabric) support
pushd $WORKSPACE

if [ ! -d "nvshmem_src" ]; then
    echo "Downloading and extracting NVSHMEM..."
    mkdir -p nvshmem_src
    wget -q https://developer.download.nvidia.com/compute/redist/nvshmem/3.2.5/source/nvshmem_src_3.2.5-1.txz
    tar -xf nvshmem_src_3.2.5-1.txz -C nvshmem_src --strip-components=1
fi

pushd nvshmem_src

# Apply patch if not already applied
if [ ! -f ".patch_applied" ]; then
    echo "Applying NVSHMEM patches..."
    wget -q https://github.com/deepseek-ai/DeepEP/raw/main/third-party/nvshmem.patch
    git init
    git add -A
    git commit -m "initial" || true
    git apply -vvv nvshmem.patch || true
    touch .patch_applied
fi

# Configure NVSHMEM for EFA
export NVSHMEM_LIBFABRIC_SUPPORT=1
export NVSHMEM_IBGDA_SUPPORT=0
export NVSHMEM_IBRC_SUPPORT=0
export NVSHMEM_SHMEM_SUPPORT=0
export NVSHMEM_UCX_SUPPORT=0
export NVSHMEM_USE_NCCL=0
export NVSHMEM_PMIX_SUPPORT=0
export NVSHMEM_TIMEOUT_DEVICE_POLLING=0
export NVSHMEM_USE_GDRCOPY=0
export NVSHMEM_BUILD_TESTS=0
export NVSHMEM_BUILD_EXAMPLES=0
export NVSHMEM_MPI_SUPPORT=0
export NVSHMEM_BUILD_HYDRA_LAUNCHER=0
export NVSHMEM_BUILD_TXZ_PACKAGE=0

# Set libfabric path (AWS EFA)
export LIBFABRIC_HOME=/opt/amazon/efa

echo "Building NVSHMEM..."
cmake -G Ninja \
    -S . \
    -B $WORKSPACE/nvshmem_build/ \
    -DCMAKE_INSTALL_PREFIX=$WORKSPACE/nvshmem_install \
    -DLIBFABRIC_HOME=$LIBFABRIC_HOME

cmake --build $WORKSPACE/nvshmem_build/ --target install

popd # nvshmem_src

# Set up environment for pplx-kernels build
export CMAKE_PREFIX_PATH=$WORKSPACE/nvshmem_install:$CMAKE_PREFIX_PATH
export NVSHMEM_HOME=$WORKSPACE/nvshmem_install
export LD_LIBRARY_PATH=$NVSHMEM_HOME/lib:$LD_LIBRARY_PATH

# Build and install pplx-kernels
if [ ! -d "pplx-kernels" ]; then
    echo "Cloning pplx-kernels..."
    git clone https://github.com/ppl-ai/pplx-kernels
    cd pplx-kernels
    git checkout c336faf
    cd ..
fi

pushd pplx-kernels
echo "Building pplx-kernels..."
PIP_NO_BUILD_ISOLATION=0 pip install -e . --no-deps -v

popd # pplx-kernels
popd # WORKSPACE

echo "Installation complete!"
echo "Set these environment variables before running:"
echo "export NVSHMEM_HOME=$WORKSPACE/nvshmem_install"
echo "export LD_LIBRARY_PATH=\$NVSHMEM_HOME/lib:\$LD_LIBRARY_PATH"
echo "export CMAKE_PREFIX_PATH=\$NVSHMEM_HOME:\$CMAKE_PREFIX_PATH"

