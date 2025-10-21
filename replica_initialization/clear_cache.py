#!/usr/bin/env python3
"""
Cache clearing script for PyTorch, vLLM, and Hugging Face cache directories.
This script safely removes all items from the specified cache directories.
"""

import os
import shutil
import sys
from pathlib import Path

def clear_directory(directory_path):
    """
    Clear all contents of a directory while preserving the directory itself.
    
    Args:
        directory_path (str): Path to the directory to clear
    """
    path = Path(directory_path)
    
    if not path.exists():
        print(f"Directory does not exist: {directory_path}")
        return
    
    if not path.is_dir():
        print(f"Path is not a directory: {directory_path}")
        return
    
    print(f"Clearing cache directory: {directory_path}")
    
    try:
        # Get all items in the directory
        items = list(path.iterdir())
        total_items = len(items)
        
        if total_items == 0:
            print(f"  Directory is already empty")
            return
        
        # Remove all items
        for item in items:
            try:
                if item.is_file() or item.is_symlink():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)
                print(f"  Removed: {item.name}")
            except Exception as e:
                print(f"  Failed to remove {item.name}: {e}")
        
        print(f"  Successfully cleared {total_items} items from {directory_path}")
        
    except PermissionError:
        print(f"  Permission denied: Cannot access {directory_path}")
    except Exception as e:
        print(f"  Error clearing {directory_path}: {e}")

def clear_caches():
    """Main function to clear all specified cache directories."""
    print("Starting cache cleanup...")
    print("=" * 50)
    
    # Define cache directories to clear
    cache_directories = [
        "/home/ray/.cache/torch/",
        "/home/ray/.cache/vllm/torch_compile_cache/",
        "/tmp/torchinductor_ray/",
        "/home/ray/.cache/huggingface/hub/"
    ]
    
    # Clear each directory
    for directory in cache_directories:
        clear_directory(directory)
        print()  # Add spacing between directories
    
    print("Cache cleanup completed!")

if __name__ == "__main__":
    clear_caches()
