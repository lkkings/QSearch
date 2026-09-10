"""Feature extraction orchestrator combining text and image extractors.

Coordinates text and image feature extraction with parallel batch processing.
"""

import json
import logging
import pickle
from pathlib import Path
from typing import Dict, List, Optional, Union
from multiprocessing import Pool, cpu_count

import numpy as np
from tqdm import tqdm

from .text_extractor import TextFeatureExtractor
from .image_extractor import ImageFeatureExtractor

logger = logging.getLogger(__name__)

# Each worker holds its own OCR engine plus Chinese and English encoders.
# Measured resident footprint is ~1GB, with headroom for per-image buffers.
WORKER_MEMORY_GB = 1.5

# Fallback cap when psutil is missing and available memory cannot be measured.
MAX_WORKERS_WITHOUT_MEMINFO = 4


# Set once per worker process by _init_worker. The extractor holds a PaddleOCR
# predictor that cannot be pickled, so it is built inside the worker rather than
# sent across the process boundary.
_worker_extractor = None


def _init_worker(config: Dict):
    """Build this worker process's own extractor instance.

    Runs once per worker. Constructing the extractor here instead of pickling it
    from the parent is what avoids the unpicklable PaddleOCR predictor.
    """
    global _worker_extractor

    text_config = config.get('text', {})
    image_config = config.get('image', {})

    text_extractor = TextFeatureExtractor(text_config)
    image_extractor = ImageFeatureExtractor(image_config)
    _worker_extractor = FeatureExtractor(config, text_extractor, image_extractor)


def _worker_extract(image_path: Union[str, Path]) -> Dict:
    """Worker function that uses the process-local extractor.

    This function is pickled and sent to workers, but it only contains
    the image path, not the extractor itself.
    """
    global _worker_extractor
    if _worker_extractor is None:
        raise RuntimeError("Worker not initialized. Call _init_worker first.")
    return _worker_extractor.extract(image_path)


def _gpu_worker(gpu_id: int, image_chunk: List, results_dict, config: Dict):
    """Worker process for GPU-distributed extraction.

    Defined at module level so it is picklable on Windows (spawn start method).
    Each process builds its own extractors pinned to one GPU.
    """
    import copy

    config_copy = copy.deepcopy(config)
    config_copy.setdefault('image', {})['gpu_id'] = gpu_id

    text_ext = TextFeatureExtractor(config_copy.get('text', {}))
    image_ext = ImageFeatureExtractor(
        config_copy.get('image', {}),
        use_gpu=True,
        gpu_id=gpu_id
    )
    extractor = FeatureExtractor(config_copy, text_ext, image_ext)

    chunk_results = [extractor.extract(image_path) for image_path in image_chunk]
    results_dict[gpu_id] = chunk_results


class FeatureExtractor:
    """Orchestrates text and image feature extraction."""

    def __init__(
        self,
        config: Dict,
        text_extractor: Optional[TextFeatureExtractor] = None,
        image_extractor: Optional[ImageFeatureExtractor] = None
    ):
        """Initialize feature extractor.

        Args:
            config: Complete configuration dictionary
            text_extractor: TextFeatureExtractor instance (creates default if None)
            image_extractor: ImageFeatureExtractor instance (creates default if None)
        """
        self.config = config

        # Initialize extractors
        text_config = config.get('text', {})
        image_config = config.get('image', {})

        self.text_extractor = text_extractor or TextFeatureExtractor(text_config)
        self.image_extractor = image_extractor or ImageFeatureExtractor(image_config)

    def extract(self, image_path: Union[str, Path]) -> Dict:
        """Extract all features from single image.

        Args:
            image_path: Path to image file

        Returns:
            Dictionary containing both text and image features
        """
        result = {
            'image_path': str(image_path),
            'text_features': None,
            'image_features': None,
            'extraction_success': False
        }

        # Extract text features
        try:
            text_features = self.text_extractor.extract(image_path)
            result['text_features'] = text_features
        except Exception as e:
            logger.error(f"Text extraction failed for {image_path}: {e}")
            result['text_features'] = {'error': str(e)}

        # Extract image features
        try:
            image_features = self.image_extractor.extract(image_path)
            result['image_features'] = image_features
        except Exception as e:
            logger.error(f"Image extraction failed for {image_path}: {e}")
            result['image_features'] = {'error': str(e)}

        # Check overall success
        text_success = result['text_features'] and result['text_features'].get('extraction_success', False)
        image_success = result['image_features'] and result['image_features'].get('extraction_success', False)
        result['extraction_success'] = text_success or image_success

        return result

    @staticmethod
    def _default_worker_count() -> int:
        """Choose a worker count that fits in available memory.

        Every worker loads its own OCR engine and text encoders (~1GB resident),
        so a CPU-count-based default reliably exhausts RAM on typical machines.
        """
        cpu_budget = max(1, cpu_count() - 1)

        try:
            import psutil
            available_gb = psutil.virtual_memory().available / (1024 ** 3)
        except ImportError:
            logger.debug("psutil unavailable; limiting workers conservatively")
            return min(cpu_budget, MAX_WORKERS_WITHOUT_MEMINFO)

        memory_budget = max(1, int(available_gb // WORKER_MEMORY_GB))
        workers = min(cpu_budget, memory_budget)

        if workers < cpu_budget:
            logger.info(
                f"Limiting to {workers} workers ({available_gb:.1f}GB available, "
                f"~{WORKER_MEMORY_GB}GB needed per worker)"
            )

        return workers

    def extract_batch(
        self,
        image_paths: List[Union[str, Path]],
        num_workers: int = None,
        show_progress: bool = True
    ) -> List[Dict]:
        """Extract features from multiple images with parallel processing.

        Args:
            image_paths: List of image paths
            num_workers: Number of parallel workers (default: CPU count - 1)
            show_progress: Whether to show progress bar

        Returns:
            List of feature dictionaries
        """
        if num_workers is None:
            num_workers = self._default_worker_count()

        results = []

        # Use tqdm for progress tracking
        iterator = tqdm(image_paths, desc="Extracting features") if show_progress else image_paths

        if num_workers == 1:
            # Sequential processing
            for image_path in iterator:
                features = self.extract(image_path)
                results.append(features)
        else:
            # Parallel processing with worker initialization
            # Each worker gets its own extractor instance to avoid pickling issues
            with Pool(processes=num_workers, initializer=_init_worker, initargs=(self.config,)) as pool:
                results = list(pool.imap(_worker_extract, iterator))

        return results

    def extract_batch_gpu_distributed(
        self,
        image_paths: List[Union[str, Path]],
        num_gpus: int = 8,
        show_progress: bool = True
    ) -> List[Dict]:
        """Extract features with GPU distribution across multiple GPUs.

        Args:
            image_paths: List of image paths
            num_gpus: Number of GPUs to use
            show_progress: Whether to show progress bar

        Returns:
            List of feature dictionaries
        """
        import torch
        from multiprocessing import Process, Manager

        if not torch.cuda.is_available():
            logger.warning("CUDA not available, falling back to CPU")
            return self.extract_batch(image_paths, show_progress=show_progress)

        # Split images across GPUs
        chunk_size = len(image_paths) // num_gpus
        chunks = [
            image_paths[i * chunk_size:(i + 1) * chunk_size]
            for i in range(num_gpus)
        ]
        # Add remainder to last chunk
        if len(image_paths) % num_gpus != 0:
            chunks[-1].extend(image_paths[num_gpus * chunk_size:])

        # Use Manager to collect results
        manager = Manager()
        results_dict = manager.dict()

        # Launch processes using a module-level worker so it can be pickled on Windows
        processes = []
        for gpu_id, chunk in enumerate(chunks):
            if chunk:  # Skip empty chunks
                p = Process(
                    target=_gpu_worker,
                    args=(gpu_id, chunk, results_dict, self.config)
                )
                p.start()
                processes.append(p)

        # Wait for completion
        for p in processes:
            p.join()

        # Combine results maintaining order
        all_results = []
        for gpu_id in range(len(chunks)):
            if gpu_id in results_dict:
                all_results.extend(results_dict[gpu_id])

        return all_results

    def save_features(
        self,
        features: List[Dict],
        output_path: Union[str, Path],
        format: str = 'pickle'
    ):
        """Save extracted features to disk.

        Args:
            features: List of feature dictionaries
            output_path: Output file path
            format: Save format ('pickle' or 'json')
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            if format == 'pickle':
                with open(output_path, 'wb') as f:
                    pickle.dump(features, f, protocol=pickle.HIGHEST_PROTOCOL)

            elif format == 'json':
                # Convert numpy arrays to lists for JSON serialization
                features_serializable = self._make_json_serializable(features)
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(features_serializable, f, ensure_ascii=False, indent=2)

            else:
                raise ValueError(f"Unknown format: {format}")

            logger.info(f"Saved features to {output_path}")

        except Exception as e:
            logger.error(f"Failed to save features: {e}")
            raise

    def load_features(
        self,
        input_path: Union[str, Path],
        format: str = 'pickle'
    ) -> List[Dict]:
        """Load features from disk.

        Args:
            input_path: Input file path
            format: File format ('pickle' or 'json')

        Returns:
            List of feature dictionaries
        """
        input_path = Path(input_path)

        if not input_path.exists():
            raise FileNotFoundError(f"Features file not found: {input_path}")

        try:
            if format == 'pickle':
                with open(input_path, 'rb') as f:
                    features = pickle.load(f)

            elif format == 'json':
                with open(input_path, 'r', encoding='utf-8') as f:
                    features = json.load(f)

            else:
                raise ValueError(f"Unknown format: {format}")

            logger.info(f"Loaded features from {input_path}")
            return features

        except Exception as e:
            logger.error(f"Failed to load features: {e}")
            raise

    def _make_json_serializable(self, obj):
        """Convert numpy arrays and other non-serializable objects to JSON-compatible format."""
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, dict):
            return {k: self._make_json_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._make_json_serializable(item) for item in obj]
        elif isinstance(obj, (np.int64, np.int32)):
            return int(obj)
        elif isinstance(obj, (np.float64, np.float32)):
            return float(obj)
        else:
            return obj
