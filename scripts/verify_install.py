"""Verify QSearch installation and dependencies.

This version marks PaddleOCR as optional since it has complex dependencies.
"""

import sys

def check_import(module_name, package_name=None, optional=False):
    """Check if a module can be imported."""
    package_name = package_name or module_name
    try:
        __import__(module_name)
        print(f"✓ {package_name} installed")
        return True
    except ImportError as e:
        if optional:
            print(f"⚠ {package_name} NOT installed (optional): {e}")
            return True  # Don't fail for optional deps
        else:
            print(f"✗ {package_name} NOT installed: {e}")
            return False

def check_cuda():
    """Check CUDA availability."""
    try:
        import torch
        cuda_available = torch.cuda.is_available()
        if cuda_available:
            gpu_count = torch.cuda.device_count()
            print(f"✓ CUDA available with {gpu_count} GPU(s)")
            for i in range(gpu_count):
                print(f"  - GPU {i}: {torch.cuda.get_device_name(i)}")
        else:
            print("✓ PyTorch installed (CPU-only mode)")
        return True
    except Exception as e:
        print(f"✗ Error checking CUDA: {e}")
        return False

def main():
    print("=" * 60)
    print("QSearch Installation Verification")
    print("=" * 60)
    print()

    # Core dependencies
    print("Core Dependencies:")
    all_ok = True
    all_ok &= check_import("torch", "PyTorch")
    all_ok &= check_import("torchvision", "TorchVision")
    all_ok &= check_import("numpy", "NumPy")
    print()

    # Vector search
    print("Vector Search:")
    has_faiss = check_import("faiss", "Faiss")
    all_ok &= has_faiss
    if has_faiss:
        import faiss
        print(f"  Faiss version: {faiss.__version__ if hasattr(faiss, '__version__') else 'unknown'}")
    print()

    # OCR engines - PaddleOCR is now optional
    print("OCR Engines:")
    check_import("paddleocr", "PaddleOCR", optional=True)  # Optional
    all_ok &= check_import("pix2tex", "LaTeX-OCR")
    print()

    # NLP models
    print("NLP Libraries:")
    all_ok &= check_import("transformers", "Transformers")
    all_ok &= check_import("sentence_transformers", "Sentence-Transformers")
    print()

    # Image processing
    print("Image Processing:")
    all_ok &= check_import("cv2", "OpenCV")
    all_ok &= check_import("PIL", "Pillow")
    all_ok &= check_import("imagehash", "ImageHash")
    print()

    # Utilities
    print("Utilities:")
    all_ok &= check_import("yaml", "PyYAML")
    all_ok &= check_import("tqdm", "tqdm")
    all_ok &= check_import("Levenshtein", "python-Levenshtein")
    all_ok &= check_import("skimage", "scikit-image")
    print()

    # CUDA check
    print("GPU Support:")
    check_cuda()
    print()

    # QSearch modules
    print("QSearch Modules:")
    try:
        from qsearch.config.loader import ConfigLoader
        from qsearch.config.presets import list_presets
        print("✓ QSearch configuration module")

        presets = list_presets()
        print(f"  Available presets: {', '.join(presets.keys())}")
    except Exception as e:
        print(f"✗ QSearch modules: {e}")
        all_ok = False
    print()

    # Summary
    print("=" * 60)
    if all_ok:
        print("✓ All required dependencies installed successfully!")
        print()
        print("Note: PaddleOCR is optional and can be installed separately")
        print("with: uv pip install paddleocr paddlex modelscope")
        print()
        print("Next steps:")
        print("1. Prepare your image directories")
        print("2. Run: uv run scripts/index_database.py --help")
        print("3. Run: uv run scripts/search_queries.py --help")
    else:
        print("✗ Some required dependencies are missing. Please install them.")
        return 1
    print("=" * 60)

    return 0

if __name__ == '__main__':
    sys.exit(main())
