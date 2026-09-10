"""Database indexing script for question images.

Processes 400k base images, extracts features, and builds search indices.
"""

import argparse
import json
import logging
from pathlib import Path
from typing import List

from qsearch.config.loader import ConfigLoader
from qsearch.config.presets import get_preset
from qsearch.features.feature_extractor import FeatureExtractor
from qsearch.indexing.faiss_index import FaissIndexBuilder
from qsearch.indexing.hash_index import HashIndex

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_image_paths(image_dir: Path) -> List[Path]:
    """Load all image paths from directory.

    Args:
        image_dir: Directory containing images

    Returns:
        List of image paths
    """
    extensions = ['.jpg', '.jpeg', '.png', '.bmp']
    image_paths = []

    for ext in extensions:
        image_paths.extend(image_dir.glob(f'**/*{ext}'))

    return sorted(image_paths)


def main():
    parser = argparse.ArgumentParser(description='Index question image database')
    parser.add_argument('--image-dir', type=str, required=True, help='Directory containing base images')
    parser.add_argument('--output-dir', type=str, required=True, help='Output directory for indices')
    parser.add_argument('--config', type=str, help='Configuration file path')
    parser.add_argument('--preset', type=str, default='balanced', help='Configuration preset')
    parser.add_argument('--checkpoint-every', type=int, default=10000, help='Save checkpoint every N images')
    parser.add_argument('--resume-from', type=str, help='Resume from checkpoint file')
    parser.add_argument('--num-gpus', type=int, default=8, help='Number of GPUs to use')

    args = parser.parse_args()

    # Setup paths
    image_dir = Path(args.image_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load configuration
    if args.config:
        config_loader = ConfigLoader(args.config)
        config = config_loader.base_config
    else:
        config = get_preset(args.preset)

    logger.info(f"Using configuration preset: {args.preset}")

    # Load image paths
    logger.info(f"Loading image paths from {image_dir}")
    image_paths = load_image_paths(image_dir)
    logger.info(f"Found {len(image_paths)} images")

    # Resume from checkpoint if specified
    start_idx = 0
    if args.resume_from:
        checkpoint_path = Path(args.resume_from)
        if checkpoint_path.exists():
            with open(checkpoint_path, 'r') as f:
                checkpoint = json.load(f)
                start_idx = checkpoint['last_processed_index'] + 1
                logger.info(f"Resuming from index {start_idx}")

    # Initialize feature extractor
    feature_extractor = FeatureExtractor(config)

    # Extract features with GPU distribution
    logger.info(f"Extracting features using {args.num_gpus} GPUs")
    features_list = feature_extractor.extract_batch_gpu_distributed(
        image_paths[start_idx:],
        num_gpus=args.num_gpus,
        show_progress=True
    )

    # Save features
    features_path = output_dir / 'features.pkl'
    logger.info(f"Saving features to {features_path}")
    feature_extractor.save_features(features_list, features_path, format='pickle')

    # Build Faiss text index
    logger.info("Building Faiss text index")
    faiss_index = FaissIndexBuilder(dimension=768, use_gpu=True)

    vectors = []
    ids = []

    for i, features in enumerate(features_list):
        stem_embedding = features.get('text_features', {}).get('stem_embedding')
        if stem_embedding is not None:
            vectors.append(stem_embedding)
            ids.append(features['image_path'])

    if vectors:
        import numpy as np
        vectors_array = np.array(vectors)
        faiss_index.add_vectors(vectors_array, ids)

        # Save index
        index_path = output_dir / 'text_index.faiss'
        id_map_path = output_dir / 'text_index_ids.pkl'
        faiss_index.save(str(index_path), str(id_map_path))
        logger.info(f"Saved Faiss index with {faiss_index.index.ntotal} vectors")

    # Build hash index
    logger.info("Building hash index")
    hash_index = HashIndex()

    for features in features_list:
        image_path = features['image_path']
        perceptual_hash = features.get('image_features', {}).get('perceptual_hash')

        if perceptual_hash:
            hash_index.add(image_path, perceptual_hash)

    # Save hash index
    hash_path = output_dir / 'hash_index.pkl'
    hash_index.save(str(hash_path), format='pickle')
    logger.info(f"Saved hash index with {hash_index.get_stats()['unique_hashes']} unique hashes")

    # Save statistics
    stats = {
        'total_images': len(image_paths),
        'features_extracted': len(features_list),
        'text_vectors': faiss_index.index.ntotal if vectors else 0,
        'hash_index_stats': hash_index.get_stats()
    }

    stats_path = output_dir / 'index_stats.json'
    with open(stats_path, 'w') as f:
        json.dump(stats, f, indent=2)

    logger.info(f"Indexing complete. Statistics saved to {stats_path}")


if __name__ == '__main__':
    main()
