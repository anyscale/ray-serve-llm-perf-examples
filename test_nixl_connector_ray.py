"""
Minimal test module that follows nixl_connector.py data flow and APIs.
This helps debug NIXL backends without the full vLLM complexity.

Uses Ray placement groups to test:
- STRICT_SPREAD: Cross-node (inter-node) transfers via EFA
- STRICT_PACK: Same-node (intra-node) transfers

Key flow (matching nixl_connector.py):
1. Registration: get_reg_descs → register_memory → get_xfer_descs → prep_xfer_dlist
2. Remote handshake: add_remote_agent → get_xfer_descs → prep_xfer_dlist
3. Transfer: get_block_descs_ids → make_prepped_xfer → transfer
4. Wait: check_xfer_state → get_xfer_telemetry → release_xfer_handle

Usage:
  # Basic cross-node transfer (contiguous blocks 0-9)
  python test_nixl_connector_ray.py --strategy spread
  
  # Same-node transfer
  python test_nixl_connector_ray.py --strategy pack
  
  # Transfer random blocks (non-contiguous, different src/dst blocks)
  python test_nixl_connector_ray.py --strategy spread --random-blocks --blocks 50
  
  # Large transfer with custom parameters
  python test_nixl_connector_ray.py --blocks 100 --num-blocks 1000 --num-layers 4

  # Test specific backends
  python test_nixl_connector_ray.py --backends LIBFABRIC
  python test_nixl_connector_ray.py --backends UCX
  python test_nixl_connector_ray.py --backends LIBFABRIC,UCX

Note: With --random-blocks, source and destination blocks are different random sets,
      simulating realistic block remapping scenarios in vLLM prefix caching.
"""

import argparse
import os
import random
import time
from dataclasses import dataclass

import numpy as np
import ray
import torch
from nixl._api import nixl_agent, nixl_agent_config
from ray.util.placement_group import placement_group
from ray.util.scheduling_strategies import PlacementGroupSchedulingStrategy

# Default backends (can be overridden by command line)
BACKENDS = ["LIBFABRIC", "UCX"]
NIXL_MEMORY_TYPE = "VRAM"
FILL_VALUE = 0.05


@dataclass
class NixlAgentMetadata:
    """Mimics vLLM's NixlAgentMetadata for handshake."""
    engine_id: str
    agent_metadata: bytes
    kv_caches_base_addr: list
    num_blocks: int
    block_lens: list


@ray.remote
class EngineActor:
    """
    Mimics NixlConnectorWorker from vLLM.
    Follows the same registration and transfer flow.
    Ray remote actor for distributed execution.
    """
    def __init__(self, block_size: int, num_blocks: int, num_layers: int, 
                 num_kv_heads: int, head_dim: int, role: str, engine_id: str):
        assert role in ["decode", "prefill"]
        self._role = role
        self.engine_id = engine_id
        self._block_size = block_size
        self._num_blocks = num_blocks
        self._num_layers = num_layers
        self._num_kv_heads = num_kv_heads
        self._head_dim = head_dim
        os.environ["NIXL_TELEMETRY_ENABLE"] = "1"
        
        # Get GPU info for this actor
        print(f"[{role}] Getting GPU info...")
        self.gpu_id = torch.cuda.current_device()
        self.node_ip = ray.util.get_node_ip_address()
        print(f"[{role}] Running on node {self.node_ip}, GPU {self.gpu_id}")
        
        # Create KV cache tensors for each layer
        # Shape: [num_blocks, num_kv_heads, block_size, head_dim] (HND layout)
        # Using separate K and V tensors per layer (split_k_and_v=True case)
        print(f"[{role}] Creating KV caches...")
        fill_value = FILL_VALUE if role == "prefill" else 0.0
        self.kv_caches = {}
        self.kv_caches_base_addr = []
        
        for layer_idx in range(num_layers):
            # K cache for this layer
            k_cache = torch.full(
                (num_blocks, num_kv_heads, block_size, head_dim),
                fill_value,
                dtype=torch.float16,
                device=f"cuda:{self.gpu_id}"
            )
            # V cache for this layer  
            v_cache = torch.full(
                (num_blocks, num_kv_heads, block_size, head_dim),
                fill_value,
                dtype=torch.float16,
                device=f"cuda:{self.gpu_id}"
            )
            self.kv_caches[f"layer_{layer_idx}_k"] = k_cache
            self.kv_caches[f"layer_{layer_idx}_v"] = v_cache
        
        # Calculate block lengths (bytes per block for each cache tensor)
        # This is used for creating block descriptors
        self.block_len_per_layer = []
        for cache in self.kv_caches.values():
            tensor_size_bytes = cache.numel() * cache.element_size()
            block_len = tensor_size_bytes // num_blocks
            self.block_len_per_layer.append(block_len)
            self.kv_caches_base_addr.append(cache.data_ptr())
        
        # Number of regions = number of separate K/V tensors
        self.num_regions = len(self.kv_caches)
        
        # Initialize NIXL agent
        print(f"[{role}] Initializing NIXL agent...")
        self._agent = nixl_agent(
            self.engine_id, nixl_agent_config(backends=BACKENDS))
        
        # ===== PHASE 1: Register memory (like register_kv_caches) =====
        print(f"[{role}] Registering memory with NIXL...")
        self._register_kv_caches()
        
        # Remote agent tracking (for decode engine)
        self._remote_agent_name = None
        self._dst_xfer_side_handle = None
        self._dst_num_blocks = None
        
        # Transfer tracking
        self._xfer_handle = None
        
    def is_ready(self):
        return True
        
    def _register_kv_caches(self):
        """
        Follows nixl_connector.py:register_kv_caches() flow.
        Lines 830-949 in nixl_connector.py
        """
        # Step 1: Get registration descriptors and register memory
        caches_data = []
        for base_addr, block_len in zip(self.kv_caches_base_addr, self.block_len_per_layer):
            tensor_size_bytes = block_len * self._num_blocks
            # (addr, size_bytes, device_id, tag)
            caches_data.append((base_addr, tensor_size_bytes, 0, ""))
        
        print(f"[{self._role}] Getting registration descriptors for {len(caches_data)} tensors...")
        reg_descs = self._agent.get_reg_descs(caches_data, NIXL_MEMORY_TYPE)
        
        print(f"[{self._role}] Registering memory...")
        self._agent.register_memory(reg_descs, backends=BACKENDS)
        
        # Step 2: Prepare transfer descriptors for local blocks
        # This creates descriptors for each block that can be used in transfers
        blocks_data = []
        for i, base_addr in enumerate(self.kv_caches_base_addr):
            block_len = self.block_len_per_layer[i]
            for block_id in range(self._num_blocks):
                block_offset = block_id * block_len
                addr = base_addr + block_offset
                # (addr, len, device_id)
                blocks_data.append((addr, block_len, 0))
        
        print(f"[{self._role}] Creating {len(blocks_data)} block descriptors...")
        xfer_descs = self._agent.get_xfer_descs(blocks_data, NIXL_MEMORY_TYPE)
        
        # Step 3: Prepare local xfer side handle (src side)
        print(f"[{self._role}] Preparing local xfer side handle...")
        self.src_xfer_side_handle = self._agent.prep_xfer_dlist(
            "NIXL_INIT_AGENT", xfer_descs
        )
        
        print(f"[{self._role}] Registration complete! src_handle={self.src_xfer_side_handle}")
    
    def get_node_info(self):
        """Get node and GPU information."""
        return {
            "node_ip": self.node_ip,
            "gpu_id": self.gpu_id,
            "role": self._role,
            "engine_id": self.engine_id,
        }
    
    def get_metadata(self) -> NixlAgentMetadata:
        """Get metadata for handshake (prefill engine provides this to decode)."""
        return NixlAgentMetadata(
            engine_id=self.engine_id,
            agent_metadata=self._agent.get_agent_metadata(),
            kv_caches_base_addr=self.kv_caches_base_addr,
            num_blocks=self._num_blocks,
            block_lens=self.block_len_per_layer,
        )
    
    def add_remote_agent(self, remote_metadata: NixlAgentMetadata):
        """
        Follows nixl_connector.py:add_remote_agent() flow.
        Lines 995-1155 in nixl_connector.py
        This is called by the decode engine to register the prefill engine.
        """
        print(f"[{self._role}] Adding remote agent {remote_metadata.engine_id}...")
        
        # Step 1: Add remote agent to NIXL
        self._remote_agent_name = self._agent.add_remote_agent(
            remote_metadata.agent_metadata
        )
        print(f"[{self._role}] Remote agent name: {self._remote_agent_name}")
        
        # Step 2: Create descriptors for remote blocks
        # For TP=1, we just reference all remote blocks directly
        self._dst_num_blocks = remote_metadata.num_blocks
        
        blocks_data = []
        for i, base_addr in enumerate(remote_metadata.kv_caches_base_addr):
            block_len = remote_metadata.block_lens[i]
            for block_id in range(remote_metadata.num_blocks):
                block_offset = block_id * block_len
                addr = base_addr + block_offset
                # (addr, len, device_id)
                blocks_data.append((addr, block_len, 0))
        
        print(f"[{self._role}] Creating {len(blocks_data)} remote block descriptors...")
        remote_descs = self._agent.get_xfer_descs(blocks_data, NIXL_MEMORY_TYPE)
        
        # Step 3: Prepare remote xfer side handle (dst side)
        print(f"[{self._role}] Preparing remote xfer side handle...")
        self._dst_xfer_side_handle = self._agent.prep_xfer_dlist(
            self._remote_agent_name, remote_descs
        )
        
        print(f"[{self._role}] Remote agent setup complete! dst_handle={self._dst_xfer_side_handle}")
    
    def _get_block_descs_ids(
        self, 
        num_blocks: int,
        block_ids: list[int], 
        layer_idx: int = None
    ) -> np.ndarray:
        """
        Follows nixl_connector.py:_get_block_descs_ids() flow.
        Lines 1472-1501 in nixl_connector.py
        
        Computes descriptor IDs for the given blocks.
        For each block, we need descriptors for all regions (K and V tensors).
        """
        if layer_idx is None:
            # Transfer all layers
            region_ids = np.arange(self.num_regions)
        else:
            # Transfer specific layer (K and V)
            assert 2 * self._num_layers == self.num_regions
            region_ids = np.arange(2 * layer_idx, 2 * layer_idx + 2)
        
        # Compute descriptor IDs: region_id * num_blocks + block_id
        # This creates a 2D grid and flattens it
        region_ids = region_ids[:, None]  # Shape: (num_regions, 1)
        block_ids_arr = np.array(block_ids)[None, :]  # Shape: (1, num_blocks_to_xfer)
        descs_ids = region_ids * num_blocks + block_ids_arr
        
        return descs_ids.flatten()
    
    def start_transfer(self, local_block_ids: list[int], remote_block_ids: list[int]):
        """
        Follows nixl_connector.py:_read_blocks() flow.
        Lines 1367-1470 in nixl_connector.py
        
        Initiates async transfer from remote (prefill) to local (decode).
        """
        if self._remote_agent_name is None:
            raise ValueError("Must call add_remote_agent first")
        
        print(f"\n[{self._role}] Starting transfer...")
        print(f"  Local blocks: {local_block_ids}")
        print(f"  Remote blocks: {remote_block_ids}")
        
        # Step 1: Get descriptor IDs for local and remote blocks
        print(f"[{self._role}] Computing block descriptor IDs...")
        local_block_descs_ids = self._get_block_descs_ids(
            self._num_blocks, local_block_ids
        )
        remote_block_descs_ids = self._get_block_descs_ids(
            self._dst_num_blocks, remote_block_ids
        )
        
        print(f"[{self._role}] Local desc IDs: {local_block_descs_ids[:20]}... (total {len(local_block_descs_ids)})")
        print(f"[{self._role}] Remote desc IDs: {remote_block_descs_ids[:20]}... (total {len(remote_block_descs_ids)})")
        
        assert len(local_block_descs_ids) == len(remote_block_descs_ids), \
            f"Descriptor count mismatch: {len(local_block_descs_ids)} != {len(remote_block_descs_ids)}"
        
        # Step 2: Create transfer handle
        print(f"[{self._role}] Creating transfer with make_prepped_xfer...")
        self._xfer_handle = self._agent.make_prepped_xfer(
            "READ",  # READ operation (pull from remote)
            self.src_xfer_side_handle,  # Local side
            local_block_descs_ids,
            self._dst_xfer_side_handle,  # Remote side
            remote_block_descs_ids,
            notif_msg=b"transfer_complete",  # Optional notification
        )
        
        print(f"[{self._role}] Transfer handle created: {self._xfer_handle}")
        
        # Step 3: Start async transfer
        print(f"[{self._role}] Starting async transfer...")
        self._start_time = time.perf_counter()
        self._agent.transfer(self._xfer_handle)
        
        print(f"[{self._role}] Transfer initiated!")
        
    def wait_for_transfer(self):
        """
        Follows nixl_connector.py:_pop_done_transfers() flow.
        Lines 1275-1303 in nixl_connector.py
        
        Polls transfer state until completion.
        """
        if self._xfer_handle is None:
            raise ValueError("Must call start_transfer first")
        
        print(f"\n[{self._role}] Waiting for transfer to complete...")
        poll_count = 0
        
        while True:
            xfer_state = self._agent.check_xfer_state(self._xfer_handle)
            poll_count += 1
            
            if xfer_state == "DONE":
                elapsed = time.perf_counter() - self._start_time
                print(f"[{self._role}] Transfer DONE! Elapsed: {elapsed:.3f}s, polls: {poll_count}")
                
                # Get telemetry (like vLLM does)
                try:
                    telemetry = self._agent.get_xfer_telemetry(self._xfer_handle)
                    print(f"[{self._role}] Transfer telemetry:")
                    print(f"  - Transfer duration: {telemetry.xferDuration / 1e6:.3f}s")
                    print(f"  - Post duration: {telemetry.postDuration / 1e6:.3f}s")
                    print(f"  - Bytes transferred: {telemetry.totalBytes / 1e6:.2f} MB")
                    print(f"  - Descriptors: {telemetry.descCount}")
                    throughput = (telemetry.totalBytes / 1e6) / (telemetry.xferDuration / 1e6)
                    print(f"  - Throughput: {throughput:.2f} MB/s")
                except Exception as e:
                    print(f"[{self._role}] Could not get telemetry: {e}")
                
                # Release handle
                self._agent.release_xfer_handle(self._xfer_handle)
                break
            elif xfer_state == "PROC":
                # Still processing
                if poll_count % 10 == 0:
                    print(f"[{self._role}] Transfer in progress... (poll #{poll_count})")
                time.sleep(0.01)
            else:
                raise RuntimeError(f"Transfer failed with state: {xfer_state}")
    
    def validate_transfer(self, transferred_block_ids: list[int]):
        """
        Validate that the transfer worked correctly.
        Only checks the blocks that were actually transferred.
        """
        if self._role == "decode":
            print(f"\n[{self._role}] Validating transfer...")
            
            print(f"[{self._role}] Checking {len(transferred_block_ids)} transferred blocks: {transferred_block_ids}")
            
            for layer_name, cache_tensor in self.kv_caches.items():
                expected_value = FILL_VALUE
                
                # Only check the transferred blocks
                for block_id in transferred_block_ids:
                    block_data = cache_tensor[block_id]  # Shape: [num_kv_heads, block_size, head_dim]
                    unique_values = block_data.unique()
                    
                    if len(unique_values) != 1 or abs(unique_values[0].item() - expected_value) > 1e-5:
                        print(
                            f"Transfer validation FAILED for {layer_name}, block {block_id}. "
                            f"Expected all {expected_value}, got {unique_values.tolist()}"
                        )
                        return False
                
                print(f"[{self._role}] ✓ {layer_name}: All {len(transferred_block_ids)} blocks validated")
            
            print("✓ Transfer validation PASSED! All transferred blocks contain prefill values.")
            return True
        else:
            print(f"[{self._role}] No validation needed for prefill engine.")
            return True
    
    def run_transfer(self, remote_metadata: NixlAgentMetadata, 
                     local_block_ids: list[int], remote_block_ids: list[int]):
        """
        Execute the full transfer flow for decode engine.
        This is the main entry point called from the driver.
        """
        print(f"\n[{self._role}] ===== Starting Transfer Flow =====")
        
        # Step 1: Add remote agent
        self.add_remote_agent(remote_metadata)
        
        # Step 2: Start transfer
        self.start_transfer(local_block_ids, remote_block_ids)
        
        # Step 3: Wait for completion
        self.wait_for_transfer()
        
        # Step 4: Validate (only the transferred blocks)
        result = self.validate_transfer(local_block_ids)
        
        print(f"[{self._role}] ===== Transfer Flow Complete =====\n")
        return result


def main():
    """
    Main test flow using Ray placement groups.
    Tests both STRICT_SPREAD (cross-node) and STRICT_PACK (same-node) strategies.
    """
    parser = argparse.ArgumentParser(
        description='Test NIXL KV cache transfers following vLLM nixl_connector.py flow'
    )
    parser.add_argument(
        '--strategy', 
        type=str, 
        choices=['spread', 'pack'], 
        default='spread',
        help='Placement strategy: spread=cross-node (default), pack=same-node'
    )
    parser.add_argument(
        '--blocks', 
        type=int, 
        default=10,
        help='Number of blocks to transfer (default: 10)'
    )
    parser.add_argument(
        '--num-blocks',
        type=int,
        default=100,
        help='Total number of blocks in KV cache (default: 100)'
    )
    parser.add_argument(
        '--num-layers',
        type=int,
        default=2,
        help='Number of layers (default: 2)'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Verbose logging'
    )
    parser.add_argument(
        '--random-blocks',
        action='store_true',
        help='Transfer random blocks with different src/dst mappings (tests non-sequential access and block remapping)'
    )
    parser.add_argument(
        '--seed',
        type=int,
        default=42,
        help='Random seed for block selection (default: 42)'
    )
    parser.add_argument(
        '--backends',
        type=str,
        default='LIBFABRIC,UCX',
        help='NIXL backends to use (comma-separated: LIBFABRIC,UCX) (default: LIBFABRIC,UCX)'
    )
    args = parser.parse_args()
    
    # Parse backends
    backends = [b.strip() for b in args.backends.split(',') if b.strip()]
    global BACKENDS
    BACKENDS = backends

    strategy_name = "STRICT_SPREAD" if args.strategy == "spread" else "STRICT_PACK"
    test_type = "Cross-node (inter-node)" if args.strategy == "spread" else "Same-node (intra-node)"

    print("="*80)
    print("NIXL Connector Test - Following vLLM nixl_connector.py Flow")
    print(f"Strategy: {strategy_name} - {test_type}")
    print("="*80)
    
    # Parameters matching typical LLM configuration (TP=1)
    block_size = 16  # tokens per block
    num_blocks = args.num_blocks
    num_layers = args.num_layers
    num_kv_heads = 8  # number of KV attention heads for TP=1
    head_dim = 128  # dimension per head
    num_blocks_to_transfer = args.blocks
    
    print(f"\nConfiguration:")
    print(f"  - Block size: {block_size} tokens")
    print(f"  - Total blocks: {num_blocks}")
    print(f"  - Blocks to transfer: {num_blocks_to_transfer}")
    print(f"  - Block selection: {'RANDOM' if args.random_blocks else 'CONTIGUOUS'}")
    if args.random_blocks:
        print(f"  - Random seed: {args.seed}")
    print(f"  - Num layers: {num_layers}")
    print(f"  - KV heads: {num_kv_heads}")
    print(f"  - Head dim: {head_dim}")
    print(f"  - NIXL backends: {BACKENDS}")

    # Calculate transfer size
    bytes_per_block = num_kv_heads * block_size * head_dim * 2  # 2 bytes for fp16
    transfer_bytes = bytes_per_block * num_blocks_to_transfer * num_layers * 2  # 2 for K and V
    total_cache_bytes = bytes_per_block * num_blocks * num_layers * 2
    print(f"  - Transfer size: {transfer_bytes / 1e6:.2f} MB")
    print(f"  - Total cache size: {total_cache_bytes / 1e6:.2f} MB")
    print()
    
    extra_verbosity_flags = {}
    if args.verbose: 
        extra_verbosity_flags = {
            "FI_LOG_LEVEL": "debug",
            "FI_LOG_PROV": "efa",
            "UCX_LOG_LEVEL": "debug",
            "NIXL_LOG_LEVEL": "DEBUG",
        }
    
    # Initialize Ray with EFA/UCX environment
    print("Initializing Ray...")
    ray.init(runtime_env={
        "env_vars": {
            "LD_LIBRARY_PATH": "/opt/amazon/efa/lib:" + os.environ.get("LD_LIBRARY_PATH", ""),
            **extra_verbosity_flags,
        }
    })
    
    # Create placement group
    print(f"Creating placement group with {strategy_name}...")
    pg = placement_group(
        [{"GPU": 1, "CPU": 1}, {"GPU": 1, "CPU": 1}], 
        strategy=strategy_name
    )
    ray.get(pg.ready())
    print("✓ Placement group ready\n")
    
    try:
        # ===== PHASE 1: Create actors =====
        print("="*80)
        print("PHASE 1: Creating Ray actors on different GPUs")
        print("="*80)
        
        print("\n--- Creating Prefill Engine Actor ---")
        prefill = EngineActor.options(
            num_gpus=1,
            scheduling_strategy=PlacementGroupSchedulingStrategy(
                placement_group=pg, 
                placement_group_bundle_index=0
            )
        ).remote(
            block_size=block_size,
            num_blocks=num_blocks,
            num_layers=num_layers,
            num_kv_heads=num_kv_heads,
            head_dim=head_dim,
            role="prefill",
            engine_id="prefill_engine"
        )
        
        print("\n--- Creating Decode Engine Actor ---")
        decode = EngineActor.options(
            num_gpus=1,
            scheduling_strategy=PlacementGroupSchedulingStrategy(
                placement_group=pg, 
                placement_group_bundle_index=1
            )
        ).remote(
            block_size=block_size,
            num_blocks=num_blocks,
            num_layers=num_layers,
            num_kv_heads=num_kv_heads,
            head_dim=head_dim,
            role="decode",
            engine_id="decode_engine"
        )
        
        ray.get(prefill.is_ready.remote())
        ray.get(decode.is_ready.remote())
        time.sleep(1)
        
        
        # Get node information
        print("\n--- Actor Placement Info ---")
        prefill_info = ray.get(prefill.get_node_info.remote())
        decode_info = ray.get(decode.get_node_info.remote())
        time.sleep(1)
        
        
        print(f"Prefill: node={prefill_info['node_ip']}, GPU={prefill_info['gpu_id']}")
        print(f"Decode:  node={decode_info['node_ip']}, GPU={decode_info['gpu_id']}")
        
        if prefill_info['node_ip'] == decode_info['node_ip']:
            print("✓ Both actors on SAME NODE (intra-node transfer)")
        else:
            print("✓ Actors on DIFFERENT NODES (cross-node transfer)")
        
        # ===== PHASE 2: Handshake =====
        print("\n" + "="*80)
        print("PHASE 2: Handshake - Exchanging metadata")
        print("="*80)
        
        print("\n[Driver] Getting prefill metadata...")
        prefill_metadata = ray.get(prefill.get_metadata.remote())
        print(f"[Driver] Prefill metadata received:")
        print(f"  - Engine ID: {prefill_metadata.engine_id}")
        print(f"  - Num blocks: {prefill_metadata.num_blocks}")
        print(f"  - Num regions and layers: {len(prefill_metadata.kv_caches_base_addr)}")

        
        # ===== PHASE 3: Transfer =====
        print("\n" + "="*80)
        print("PHASE 3: Execute KV Cache Transfer")
        print("="*80)
        
        # Select blocks to transfer
        if args.random_blocks:
            # Random non-contiguous blocks with different src/dst mappings
            random.seed(args.seed)
            
            # Select random local (destination) blocks
            all_local_blocks = list(range(num_blocks))
            local_block_ids = sorted(random.sample(all_local_blocks, num_blocks_to_transfer))
            
            # Select different random remote (source) blocks
            # Use different seed to ensure different blocks
            random.seed(args.seed + 1000)
            all_remote_blocks = list(range(num_blocks))
            remote_block_ids = sorted(random.sample(all_remote_blocks, num_blocks_to_transfer))
            
            print(f"\n[Driver] Using RANDOM block selection (seed={args.seed})")
            print(f"[Driver] Source and destination blocks are DIFFERENT")
            if len(local_block_ids) <= 10:
                print(f"[Driver] Mapping:")
                for local, remote in zip(local_block_ids, remote_block_ids):
                    print(f"    Remote block {remote} → Local block {local}")
            else:
                print(f"[Driver] Sample mapping (first 10):")
                for local, remote in zip(local_block_ids[:10], remote_block_ids[:10]):
                    print(f"    Remote block {remote} → Local block {local}")
        else:
            # Contiguous blocks starting from 0
            local_block_ids = list(range(num_blocks_to_transfer))
            remote_block_ids = list(range(num_blocks_to_transfer))
            print(f"\n[Driver] Using CONTIGUOUS block selection (0 to {num_blocks_to_transfer-1})")
        
        print(f"\n[Driver] Initiating transfer of {num_blocks_to_transfer} blocks...")
        print(f"[Driver] Local (dst) block IDs:  {local_block_ids if len(local_block_ids) <= 20 else str(local_block_ids[:20]) + ' ...'}")
        print(f"[Driver] Remote (src) block IDs: {remote_block_ids if len(remote_block_ids) <= 20 else str(remote_block_ids[:20]) + ' ...'}")
        
        # Start transfer on decode actor
        start_time = time.time()
        result = ray.get(decode.run_transfer.remote(
            prefill_metadata,
            local_block_ids,
            remote_block_ids
        ))
        elapsed = time.time() - start_time
        time.sleep(1)
        
        # ===== PHASE 4: Results =====
        print("\n" + "="*80)
        print("TEST RESULTS")
        print("="*80)
        
        if result:
            print(f"✅ TEST PASSED - {test_type} transfer successful!")
            print(f"   Strategy: {strategy_name}")
            print(f"   Prefill: {prefill_info['node_ip']}:GPU{prefill_info['gpu_id']}")
            print(f"   Decode:  {decode_info['node_ip']}:GPU{decode_info['gpu_id']}")
            print(f"   Transferred: {transfer_bytes / 1e6:.2f} MB")
            print(f"   Total time: {elapsed:.3f}s")
            print(f"   Backends: {', '.join(BACKENDS)}")
        else:
            print(f"❌ TEST FAILED")
            print(f"   Check logs above for details")
        
        print("="*80)
        
    finally:
        print("\nShutting down Ray...")
        ray.shutdown()
        print("Done!")


if __name__ == "__main__":
    main()