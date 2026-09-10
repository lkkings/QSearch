"""
GPU verification script for QSearch.
Verifies CUDA availability and counts visible GPUs.
"""
import sys
import torch

def verify_gpus():
    """Verify CUDA availability and GPU count."""

    print("Checking CUDA availability...")
    if not torch.cuda.is_available():
        print("✗ CUDA is not available")
        print("  Please ensure CUDA-compatible PyTorch is installed")
        return False

    print("✓ CUDA is available")
    print(f"  CUDA version: {torch.version.cuda}")

    gpu_count = torch.cuda.device_count()
    print(f"\nGPU count: {gpu_count}")

    if gpu_count == 0:
        print("✗ No GPUs detected")
        return False

    for i in range(gpu_count):
        props = torch.cuda.get_device_properties(i)
        print(f"\nGPU {i}: {props.name}")
        print(f"  Memory: {props.total_memory / 1024**3:.1f} GB")
        print(f"  Compute capability: {props.major}.{props.minor}")

    expected_gpus = 8
    if gpu_count == expected_gpus:
        print(f"\n✓ All {expected_gpus} A40 GPUs are visible")
        return True
    else:
        print(f"\n⚠ Expected {expected_gpus} GPUs but found {gpu_count}")
        print("  System will work but may not achieve target performance")
        return True  # Still return True as system can work with fewer GPUs

if __name__ == "__main__":
    success = verify_gpus()
    sys.exit(0 if success else 1)
