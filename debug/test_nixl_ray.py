#!/usr/bin/env python3
"""
Simple Ray + nixl test with 2 actors on different nodes.
Tests cross-node GPU-to-GPU memory transfers via EFA/LIBFABRIC.
Based on nixl's blocking_send_recv_example.py

The test:
- Target on node A creates a tensor with 1.0s (default: 1GB)
- Initiator on node B creates a tensor with 0.0s (same size)
- Initiator READs from Target (cross-node transfer via EFA)
- Both verify: Initiator should have 1.0s, Target should still have 1.0s

Usage:
  python test_nixl_ray.py                  # Default: 1GB transfer
  python test_nixl_ray.py --size-mb 100    # 100MB transfer
  python test_nixl_ray.py --size-mb 10000  # 10GB transfer
"""

import argparse
import os
import time
import uuid

import ray
import torch
from nixl._api import nixl_agent, nixl_agent_config
from ray.util.placement_group import placement_group
from ray.util.scheduling_strategies import PlacementGroupSchedulingStrategy

BACKENDS = ["LIBFABRIC", "UCX"]
# BACKENDS = ["LIBFABRIC"]

@ray.remote
class TargetActor:
    def __init__(self, port=5556, transfer_size_mb=1000):
        self.gpu_id = torch.cuda.current_device()
        print(f"[Target] GPU {self.gpu_id}")
        
        # Both target AND initiator need listener - this is key!
        config = nixl_agent_config(
            enable_prog_thread=True,
            enable_listen_thread=True,  # Required!
            listen_port=port,
            backends=BACKENDS
        )
        self.agent = nixl_agent("target", config)
        self.port = port
        
        # Allocate and register memory upfront
        print(f"[Target] Allocating {transfer_size_mb} MB buffer...")
        num_elements = (transfer_size_mb * 1024 * 1024) // 4
        self.tensors = [torch.ones(num_elements, dtype=torch.float32, device=f'cuda:{self.gpu_id}')]
        
        self.reg_descs = self.agent.register_memory(self.tensors)
        print(f"[Target] Ready on port {self.port}")
        
    def get_node_and_port(self):
        cur_node = ray.util.get_node_ip_address()
        return cur_node, self.port
        
    def run(self):
        """Target main loop - wait for initiator and transfer"""
        print(f"[Target] Waiting for initiator metadata...")
        
        # Wait for initiator metadata
        ready = False
        while not ready:
            ready = self.agent.check_remote_metadata("initiator")
            time.sleep(0.1)
        
        print(f"[Target] Initiator connected, sending descriptors...")
        
        # Send our descriptors to initiator
        target_descs = self.reg_descs.trim()
        target_desc_str = self.agent.get_serialized_descs(target_descs)
        self.agent.send_notif("initiator", target_desc_str)
        
        print(f"[Target] Waiting for transfer...")
        
        # Wait for transfer to complete
        while not self.agent.check_remote_xfer_done("initiator", b"UUID"):
            time.sleep(0.01)
        
        print(f"[Target] Transfer received!")
        
        # Verify data - Target should still have 1.0s (READ doesn't modify source)
        for i, tensor in enumerate(self.tensors):
            print(f"[Target]   Tensor {i}: {tensor[:10]}")
            if not torch.allclose(tensor, torch.ones_like(tensor)):
                print(f"[Target] ✗ Verification FAILED for tensor {i}")
                print(f"[Target]   Expected all 1.0 (unchanged), got: {tensor[:10]}")
                return False
        
        print(f"[Target] ✓ Verification PASSED (source unchanged)")
        return True


@ray.remote
class InitiatorActor:
    def __init__(self, transfer_size_mb=1000):
        self.gpu_id = torch.cuda.current_device()
        print(f"[Initiator] GPU {self.gpu_id}")
        
        # Initiator also needs listener for metadata exchange!
        config = nixl_agent_config(
            enable_prog_thread=True,
            enable_listen_thread=True,  # Required!
            listen_port=0,  # Random port
            backends=BACKENDS
        )
        self.agent = nixl_agent("initiator", config)
        
        # Allocate and register memory upfront
        print(f"[Initiator] Allocating {transfer_size_mb} MB buffer...")
        num_elements = (transfer_size_mb * 1024 * 1024) // 4
        self.tensors = [torch.zeros(num_elements, dtype=torch.float32, device=f'cuda:{self.gpu_id}')]
        
        self.reg_descs = self.agent.register_memory(self.tensors)
        print(f"[Initiator] Ready")
        
    def run(self, target_ip, target_port):
        """Initiator main loop - connect and transfer"""
        print(f"[Initiator] Connecting to {target_ip}:{target_port}...")
        
        # Fetch target metadata and send our metadata
        self.agent.fetch_remote_metadata("target", target_ip, target_port)
        self.agent.send_local_metadata(target_ip, target_port)
        
        print(f"[Initiator] Waiting for target descriptors...")
        
        # Wait for target's descriptors
        notifs = []
        while len(notifs) == 0:
            notifs = self.agent.get_new_notifs()
            time.sleep(0.1)
        
        target_descs = self.agent.deserialize_descs(notifs["target"][0])
        initiator_descs = self.reg_descs.trim()
        
        print(f"[Initiator] Got descriptors, waiting for metadata...")
        
        # Ensure remote metadata has arrived
        ready = False
        while not ready:
            ready = self.agent.check_remote_metadata("target")
            time.sleep(0.1)
        
        print(f"[Initiator] Creating transfer (READ from target)...")
        
        # Create transfer
        xfer_handle = self.agent.initialize_xfer(
            "READ",                 # Read from target
            initiator_descs,        # Our buffer (will receive)
            target_descs,           # Target buffer (source)
            "target",
            b"UUID"
        )
        
        if not xfer_handle:
            print(f"[Initiator] ✗ Failed to create transfer")
            return False
        
        # Execute transfer
        print(f"[Initiator] Posting transfer...")
        state = self.agent.transfer(xfer_handle)
        if state == "ERR":
            print(f"[Initiator] ✗ Failed to post transfer")
            return False
        
        # Wait for completion
        while True:
            state = self.agent.check_xfer_state(xfer_handle)
            if state == "ERR":
                print(f"[Initiator] ✗ Transfer failed")
                return False
            elif state == "DONE":
                break
            time.sleep(0.01)
        
        print(f"[Initiator] ✓ Transfer complete!")
        
        # Verify data - should have received ones from target
        for i, tensor in enumerate(self.tensors):
            print(f"[Initiator]   Tensor {i}: {tensor[:10]}")
            if not torch.allclose(tensor, torch.ones_like(tensor)):
                print(f"[Initiator] ✗ Verification FAILED for tensor {i}")
                print(f"[Initiator]   Expected all 1.0, got: {tensor[:10]}")
                return False
        
        print(f"[Initiator] ✓ Verification PASSED")
        
        # Cleanup
        self.agent.remove_remote_agent("target")
        self.agent.release_xfer_handle(xfer_handle)
        self.agent.invalidate_local_metadata(target_ip, target_port)
        
        return True


def main():
    parser = argparse.ArgumentParser(description='Test NIXL cross-node GPU memory transfers')
    parser.add_argument('--size-mb', type=int, default=1000,
                        help='Transfer size in MB (default: 1000 MB = 1 GB)')
    args = parser.parse_args()
    
    print("="*80)
    print("NIXL Cross-Node GPU Memory Transfer Test")
    print("Tests EFA/LIBFABRIC for GPU-to-GPU transfers between nodes")
    print(f"Transfer size: {args.size_mb} MB ({args.size_mb / 1024:.2f} GB)")
    print("="*80)
    
    # Initialize Ray
    ray.init(runtime_env={
        "env_vars": {
            "LD_LIBRARY_PATH": "/opt/amazon/efa/lib:" + os.environ.get("LD_LIBRARY_PATH", ""),
            "FI_LOG_LEVEL": "debug",  # Enable detailed libfabric logging
            "FI_LOG_PROV": "efa",  # Enable EFA provider-specific logs
            "UCX_LOG_LEVEL": "info", 
            "UCX_PROTO_INFO": "y",
            # Remove TLS restrictions to let UCX auto-detect best path
            # "UCX_TLS": "all",  # Let UCX choose
            "NIXL_LOG_LEVEL": "INFO"
        }
    })
    
    
    pg = placement_group([{"GPU": 1, "CPU": 1}, {"GPU": 1, "CPU": 1}], strategy="STRICT_SPREAD")
    ray.get(pg.ready())
    
    try:
        print("\n1. Creating actors...")
        target = TargetActor.options(
            num_gpus=1,
            scheduling_strategy=PlacementGroupSchedulingStrategy(
                placement_group=pg, placement_group_bundle_index=0)
            ).remote(port=5556, transfer_size_mb=args.size_mb)
        initiator = InitiatorActor.options(
            num_gpus=1,
            scheduling_strategy=PlacementGroupSchedulingStrategy(
                placement_group=pg, placement_group_bundle_index=1)
            ).remote(transfer_size_mb=args.size_mb)
        
        # Get target port
        target_ip, target_port = ray.get(target.get_node_and_port.remote())
        
        print(f"\n2. Starting transfer test...")
        print(f"   Target: {target_ip}:{target_port}")
        
        # Run both actors concurrently
        target_future = target.run.remote()
        time.sleep(1)  # Give target time to start listening
        initiator_future = initiator.run.remote(target_ip, target_port)
        
        # Wait for both to complete
        print(f"\n3. Waiting for completion...")
        target_result = ray.get(target_future)
        initiator_result = ray.get(initiator_future)
        time.sleep(5)
        
        print("\n" + "="*80)
        if target_result and initiator_result:
            print("✅ TEST PASSED - Cross-node GPU memory transfer successful!")
            print(f"   Transferred {args.size_mb} MB ({args.size_mb / 1024:.2f} GB) from {target_ip} to initiator")
            print("   Backend: LIBFABRIC/EFA")
        else:
            print("❌ TEST FAILED")
            print(f"   Target result: {target_result}")
            print(f"   Initiator result: {initiator_result}")
        print("="*80)
        
    finally:
        ray.shutdown()


if __name__ == "__main__":
    main()