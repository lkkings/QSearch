"""Install the correct paddlepaddle build for this machine.

paddleocr depends on the paddlepaddle runtime, which ships as two mutually
exclusive distributions: `paddlepaddle-gpu` (CUDA) and `paddlepaddle` (CPU).
Neither is pulled in automatically, so this script detects NVIDIA hardware and
installs the GPU build when possible, falling back to CPU otherwise.

Usage:
    uv run scripts/install_paddle.py            # auto-detect
    uv run scripts/install_paddle.py --cpu      # force CPU build
    uv run scripts/install_paddle.py --gpu      # force GPU build
    uv run scripts/install_paddle.py --dry-run  # print the command only
"""

import argparse
import logging
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

PADDLE_VERSION = "3.0.0"

# Paddle publishes one wheel index per CUDA minor version. Map a detected driver
# CUDA version onto the closest index that is not newer than the driver.
CUDA_INDEXES: Tuple[Tuple[Tuple[int, int], str], ...] = (
    ((12, 6), "https://www.paddlepaddle.org.cn/packages/stable/cu126/"),
    ((12, 3), "https://www.paddlepaddle.org.cn/packages/stable/cu123/"),
    ((11, 8), "https://www.paddlepaddle.org.cn/packages/stable/cu118/"),
)
DEFAULT_CUDA_INDEX = CUDA_INDEXES[0][1]


def _find_nvidia_smi() -> Optional[str]:
    """Locate nvidia-smi, including the standard Windows path outside PATH."""
    found = shutil.which("nvidia-smi")
    if found:
        return found

    if sys.platform == "win32":
        candidate = Path(r"C:\Windows\System32\nvidia-smi.exe")
        if candidate.exists():
            return str(candidate)

    return None


def detect_cuda_version() -> Optional[Tuple[int, int]]:
    """Detect the driver's supported CUDA version via nvidia-smi.

    Returns:
        (major, minor) CUDA version, or None when no NVIDIA GPU is usable.
    """
    smi = _find_nvidia_smi()
    if smi is None:
        logger.info("nvidia-smi not found: no NVIDIA GPU detected")
        return None

    try:
        result = subprocess.run(
            [smi],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning(f"Could not run nvidia-smi ({e}); assuming no GPU")
        return None

    if result.returncode != 0:
        logger.warning("nvidia-smi failed; assuming no usable GPU")
        return None

    match = re.search(r"CUDA Version:\s*(\d+)\.(\d+)", result.stdout)
    if match is None:
        # A GPU exists but the version line is missing; default to the newest index.
        logger.warning("Could not parse CUDA version from nvidia-smi output")
        return None

    version = (int(match.group(1)), int(match.group(2)))
    logger.info(f"Detected NVIDIA driver with CUDA {version[0]}.{version[1]}")
    return version


def select_cuda_index(cuda_version: Optional[Tuple[int, int]]) -> str:
    """Pick the newest paddle wheel index the installed driver can run."""
    if cuda_version is None:
        return DEFAULT_CUDA_INDEX

    for required, index_url in CUDA_INDEXES:
        if cuda_version >= required:
            return index_url

    oldest, index_url = CUDA_INDEXES[-1]
    logger.warning(
        f"CUDA {cuda_version[0]}.{cuda_version[1]} is older than the oldest supported "
        f"build (cu{oldest[0]}{oldest[1]}); trying it anyway"
    )
    return index_url


def _uv_pip(args: List[str]) -> List[str]:
    """Build a `uv pip` command, falling back to the current interpreter's pip."""
    if shutil.which("uv"):
        return ["uv", "pip", *args]
    return [sys.executable, "-m", "pip", *args]


def build_install_command(use_gpu: bool, cuda_version: Optional[Tuple[int, int]]) -> List[str]:
    """Build the install command for the chosen paddlepaddle build."""
    if use_gpu:
        return _uv_pip([
            "install",
            f"paddlepaddle-gpu=={PADDLE_VERSION}",
            "-i",
            select_cuda_index(cuda_version),
        ])

    return _uv_pip(["install", f"paddlepaddle=={PADDLE_VERSION}"])


def run_install(command: List[str]) -> bool:
    """Run an install command, streaming output. Returns True on success."""
    logger.info("Running: %s", " ".join(command))
    try:
        result = subprocess.run(command, check=False)
    except OSError as e:
        logger.error(f"Failed to launch installer: {e}")
        return False

    return result.returncode == 0


def verify_install() -> bool:
    """Verify paddle imports and report whether CUDA is usable."""
    probe = (
        "import paddle;"
        "print('paddle', paddle.__version__);"
        "print('cuda_compiled', paddle.device.is_compiled_with_cuda())"
    )
    result = subprocess.run(
        [sys.executable, "-W", "ignore", "-c", probe],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        logger.error(f"paddle import failed after install:\n{result.stderr.strip()}")
        return False

    for line in result.stdout.strip().splitlines():
        logger.info(line)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--gpu", action="store_true", help="Force the CUDA build")
    mode.add_argument("--cpu", action="store_true", help="Force the CPU build")
    parser.add_argument(
        "--no-fallback",
        action="store_true",
        help="Fail instead of falling back to the CPU build when the GPU install fails",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the install command without running it",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    cuda_version = None if args.cpu else detect_cuda_version()

    if args.gpu:
        use_gpu = True
    elif args.cpu:
        use_gpu = False
    else:
        use_gpu = cuda_version is not None or _find_nvidia_smi() is not None

    command = build_install_command(use_gpu, cuda_version)

    if args.dry_run:
        print(" ".join(command))
        return 0

    logger.info("Installing %s build of paddlepaddle", "GPU" if use_gpu else "CPU")

    if not run_install(command):
        if use_gpu and not args.no_fallback:
            logger.warning("GPU install failed; falling back to the CPU build")
            if not run_install(build_install_command(False, None)):
                logger.error("CPU install also failed")
                return 1
        else:
            logger.error("paddlepaddle install failed")
            return 1

    if not verify_install():
        return 1

    logger.info("paddlepaddle is ready")
    return 0


if __name__ == "__main__":
    sys.exit(main())
