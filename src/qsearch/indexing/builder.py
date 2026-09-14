"""Index builder for QSearch databases.

Orchestrates feature extraction and index building for image databases.

Feature extraction is injectable: the CLI lets the builder run its own local
extraction, while the task queue passes a mapper backed by a long-lived worker
pool so models are loaded once and reused across tasks.
"""

import json
import logging
from pathlib import Path
from typing import Callable, Dict, Iterable, Iterator, List, Optional

from qsearch.config.loader import ConfigLoader
from qsearch.features.feature_extractor import FeatureExtractor
from qsearch.indexing.faiss_index import FaissIndexBuilder
from qsearch.indexing.hash_index import HashIndex

logger = logging.getLogger(__name__)

# Takes the image paths, yields one feature dict per image in any order.
FeatureMapper = Callable[[List[str]], Iterable[Dict]]

# Reported to progress_cb between the extraction and index-assembly phases.
STAGE_EXTRACT = "提取特征"
STAGE_FAISS = "构建向量索引"
STAGE_HASH = "构建哈希索引"


def load_image_paths(image_list: Path) -> List[str]:
    """Read and validate image paths from a list file.

    Args:
        image_list: Text file with one image path per line

    Returns:
        Paths that exist on disk

    Raises:
        ValueError: If no listed path exists
    """
    image_paths: List[str] = []
    missing = 0

    with open(image_list, 'r', encoding='utf-8') as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue

            path = Path(line)
            if path.exists():
                image_paths.append(str(path))
            else:
                missing += 1
                logger.warning(f"Image not found: {path}")

    if missing:
        logger.warning(f"{missing} listed image(s) missing and skipped")

    if not image_paths:
        raise ValueError("No valid images found in image list")

    logger.info(f"Loaded {len(image_paths)} valid image paths")
    return image_paths


def build_index(
    config_path: str,
    image_list: str,
    output_dir: str,
    num_workers: Optional[int] = None,
    num_gpus: int = 0,
    feature_mapper: Optional[FeatureMapper] = None,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
    batch_size: Optional[int] = None,
) -> Dict:
    """Build search index from image list.

    Args:
        config_path: Path to YAML config file
        image_list: Path to text file with image paths (one per line)
        output_dir: Directory to save index files
        num_workers: CPU worker processes for extraction. Ignored when
            feature_mapper or num_gpus is given.
        num_gpus: GPUs to distribute extraction across. 0 (default) uses CPU
            workers, which is the only mode that honours num_workers.
        batch_size: Images/texts processed per feature-extraction batch
        feature_mapper: Injected extraction strategy. When given, the builder
            performs no extraction of its own and loads no models.
        progress_cb: Called as (processed, total, stage) during the run

    Returns:
        Index statistics dictionary

    Raises:
        ValueError: If no valid images found
    """
    config_path = Path(config_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if batch_size is not None:
        batch_size = int(batch_size)
        if batch_size < 1:
            raise ValueError(f"batch_size must be at least 1, got {batch_size}")

    logger.info(f"Loading configuration from {config_path}")
    config = ConfigLoader(config_path).get_config()

    logger.info(f"Loading image paths from {image_list}")
    image_paths = load_image_paths(Path(image_list))
    total = len(image_paths)

    features_list = _extract_features(
        image_paths,
        config,
        num_workers,
        num_gpus,
        batch_size,
        feature_mapper,
        progress_cb,
        total,
    )

    if progress_cb:
        progress_cb(total, total, STAGE_FAISS)

    # Persisting features is not optional bookkeeping: ContentMatcher needs the
    # full text of every indexed image at query time to run stage-2 verification.
    features_path = output_dir / 'features.pkl'
    logger.info(f"Saving features to {features_path}")
    FeatureExtractor.save_features_to(features_list, features_path)

    text_vectors = _build_faiss_index(features_list, output_dir, config)

    if progress_cb:
        progress_cb(total, total, STAGE_HASH)

    hash_stats = _build_hash_index(features_list, output_dir)

    stats = {
        'total_images': total,
        'features_extracted': len(features_list),
        'features_failed': sum(
            1 for item in features_list if not item.get('extraction_success')
        ),
        'text_vectors': text_vectors,
        'hash_index_stats': hash_stats,
    }

    stats_path = output_dir / 'index_stats.json'
    with open(stats_path, 'w', encoding='utf-8') as handle:
        json.dump(stats, handle, indent=2, ensure_ascii=False)

    logger.info(f"Indexing complete. Statistics saved to {stats_path}")
    return stats


def _extract_features(
    image_paths: List[str],
    config: Dict,
    num_workers: Optional[int],
    num_gpus: int,
    batch_size: Optional[int],
    feature_mapper: Optional[FeatureMapper],
    progress_cb: Optional[Callable[[int, int, str], None]],
    total: int,
) -> List[Dict]:
    """Run feature extraction through whichever strategy was selected.

    Args:
        image_paths: Images to process
        config: Loaded configuration
        num_workers: CPU worker count for the built-in path
        num_gpus: GPU count; >0 selects GPU-distributed extraction
        batch_size: Images/texts per extraction batch
        feature_mapper: Injected extraction strategy, takes precedence
        progress_cb: Progress callback
        total: Total image count, for progress reporting

    Returns:
        Feature dictionaries, one per image
    """
    if feature_mapper is not None:
        logger.info("Extracting features via injected mapper")
        return _drain(feature_mapper(image_paths), progress_cb, total)

    extractor = FeatureExtractor(config, use_gpu=bool(num_gpus and num_gpus > 0))

    if num_gpus and num_gpus > 0:
        logger.info(f"Extracting features across {num_gpus} GPU(s)")
        return extractor.extract_batch_gpu_distributed(
            image_paths,
            num_gpus=num_gpus,
            show_progress=True,
            batch_size=batch_size,
        )

    logger.info(f"Extracting features with {num_workers or 'auto'} CPU worker(s)")
    return extractor.extract_batch(
        image_paths,
        num_workers=num_workers,
        show_progress=True,
        batch_size=batch_size,
    )


def _drain(
    results: Iterable[Dict],
    progress_cb: Optional[Callable[[int, int, str], None]],
    total: int,
) -> List[Dict]:
    """Consume a feature stream, reporting progress as it arrives.

    Args:
        results: Stream of feature dictionaries
        progress_cb: Progress callback
        total: Expected total

    Returns:
        Collected feature dictionaries
    """
    collected: List[Dict] = []

    for features in results:
        collected.append(features)
        if progress_cb:
            progress_cb(len(collected), total, STAGE_EXTRACT)

    return collected


def _build_faiss_index(
    features_list: List[Dict],
    output_dir: Path,
    config: Optional[Dict] = None,
) -> int:
    """Build and save the Faiss text index.

    Args:
        features_list: Extracted features
        output_dir: Directory to write index files into
        config: Loaded configuration; the 'index' section selects the index
            type and its parameters, and text.encoding.embedding_dim the
            vector dimension

    Returns:
        Number of vectors indexed
    """
    import numpy as np

    logger.info("Building Faiss text index")

    vectors = []
    ids = []

    for features in features_list:
        text_features = features.get('text_features') or {}
        embedding = text_features.get('text_embedding')
        if embedding is not None:
            vectors.append(embedding)
            ids.append(features['image_path'])

    config = config or {}
    index_config = config.get('index', {})
    dimension = (
        config.get('text', {})
        .get('encoding', {})
        .get('embedding_dim', 768)
    )

    # CPU index here regardless of query-time settings: this runs inside a
    # scheduler that may already have GPU-resident worker pools, and a second
    # claimant on the same device is how index builds start failing on VRAM.
    faiss_index = FaissIndexBuilder(
        dimension=dimension,
        use_gpu=False,
        index_type=index_config.get('type', 'Flat'),
        nlist=index_config.get('nlist', 100),
        nprobe=index_config.get('nprobe', 10),
        m_pq=index_config.get('m_pq', 16),
        nbits=index_config.get('nbits', 8),
        hnsw_m=index_config.get('hnsw_m', 16),
        ef_construction=index_config.get('ef_construction', 40),
        ef_search=index_config.get('ef_search', 32),
    )

    if not vectors:
        logger.warning("No text embeddings extracted - FAISS index will be empty")
    else:
        faiss_index.add_vectors(np.array(vectors), ids)

    faiss_index.save(
        str(output_dir / 'text_index.faiss'),
        str(output_dir / 'text_index_ids.pkl'),
    )

    count = int(faiss_index.index.ntotal)
    logger.info(f"Saved Faiss index with {count} vectors")
    return count


def _build_hash_index(features_list: List[Dict], output_dir: Path) -> Dict:
    """Build and save the perceptual hash index.

    Args:
        features_list: Extracted features
        output_dir: Directory to write index files into

    Returns:
        Hash index statistics
    """
    logger.info("Building perceptual hash index")

    hash_index = HashIndex()

    for features in features_list:
        image_features = features.get('image_features') or {}
        perceptual_hash = image_features.get('perceptual_hash')
        if perceptual_hash:
            hash_index.add(features['image_path'], perceptual_hash)

    hash_index.save(str(output_dir / 'hash_index.pkl'), format='pickle')

    stats = hash_index.get_stats()
    logger.info(f"Saved hash index with {stats['unique_hashes']} unique hashes")
    return stats
