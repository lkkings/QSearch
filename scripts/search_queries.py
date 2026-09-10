"""Query processing script for question matching.

Processes 200k query images and finds matches in the indexed database.
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
from qsearch.matching.matchers import ExactMatcher, ContentMatcher, QuestionMatcher

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_image_paths(image_dir: Path) -> List[Path]:
    """Load all image paths from directory."""
    extensions = ['.jpg', '.jpeg', '.png', '.bmp']
    image_paths = []

    for ext in extensions:
        image_paths.extend(image_dir.glob(f'**/*{ext}'))

    return sorted(image_paths)


def main():
    parser = argparse.ArgumentParser(description='Search for matching questions')
    parser.add_argument('--query-dir', type=str, required=True, help='Directory containing query images')
    parser.add_argument('--index-dir', type=str, required=True, help='Directory containing indices')
    parser.add_argument('--output-file', type=str, required=True, help='Output JSON file for results')
    parser.add_argument('--config', type=str, help='Configuration file path')
    parser.add_argument('--preset', type=str, default='balanced', help='Configuration preset')
    parser.add_argument('--num-gpus', type=int, default=7, help='Number of GPUs for feature extraction')

    args = parser.parse_args()

    # Setup paths
    query_dir = Path(args.query_dir)
    index_dir = Path(args.index_dir)
    output_file = Path(args.output_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # Load configuration
    if args.config:
        config_loader = ConfigLoader(args.config)
        config = config_loader.base_config
    else:
        config = get_preset(args.preset)

    logger.info(f"Using configuration preset: {args.preset}")

    # Load query image paths
    logger.info(f"Loading query images from {query_dir}")
    query_paths = load_image_paths(query_dir)
    logger.info(f"Found {len(query_paths)} query images")

    # Load indices
    logger.info("Loading indices")

    # Load Faiss index
    faiss_index = FaissIndexBuilder(dimension=768, use_gpu=True, gpu_id=0)
    faiss_index.load(
        str(index_dir / 'text_index.faiss'),
        str(index_dir / 'text_index_ids.pkl')
    )
    logger.info(f"Loaded Faiss index with {faiss_index.index.ntotal} vectors")

    # Load hash index
    hash_index = HashIndex()
    hash_index.load(str(index_dir / 'hash_index.pkl'), format='pickle')
    logger.info(f"Loaded hash index with {hash_index.get_stats()['unique_hashes']} hashes")

    # Load features database
    feature_extractor = FeatureExtractor(config)
    features_list = feature_extractor.load_features(
        str(index_dir / 'features.pkl'),
        format='pickle'
    )
    features_db = {f['image_path']: f for f in features_list}
    logger.info(f"Loaded {len(features_db)} feature records")

    # Initialize matchers
    exact_matcher = ExactMatcher(
        hash_index,
        config.get('matching', {}).get('exact_match', {})
    )

    content_matcher = ContentMatcher(
        faiss_index,
        features_db,
        config.get('matching', {}).get('content_match', {})
    )

    question_matcher = QuestionMatcher(
        exact_matcher,
        content_matcher,
        config.get('matching', {}).get('output', {})
    )

    # Process queries
    logger.info("Extracting features from query images")
    query_features_list = feature_extractor.extract_batch_gpu_distributed(
        query_paths,
        num_gpus=args.num_gpus,
        show_progress=True
    )

    # Search for matches
    logger.info("Searching for matches")
    all_results = []

    for query_path, query_features in zip(query_paths, query_features_list):
        results = question_matcher.match(query_features)
        results['query_image'] = str(query_path)
        all_results.append(results)

    # Save results
    logger.info(f"Saving results to {output_file}")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    # Compute statistics
    total_exact = sum(len(r['exact_matches']) for r in all_results)
    total_content = sum(len(r['content_matches']) for r in all_results)
    avg_time = sum(r['processing_time_ms'] for r in all_results) / len(all_results)

    stats = {
        'total_queries': len(query_paths),
        'total_exact_matches': total_exact,
        'total_content_matches': total_content,
        'avg_processing_time_ms': avg_time,
        'queries_with_matches': sum(
            1 for r in all_results
            if r['exact_matches'] or r['content_matches']
        )
    }

    stats_file = output_file.parent / 'query_stats.json'
    with open(stats_file, 'w') as f:
        json.dump(stats, f, indent=2)

    logger.info(f"Query processing complete. Statistics:")
    logger.info(f"  Total queries: {stats['total_queries']}")
    logger.info(f"  Exact matches: {stats['total_exact_matches']}")
    logger.info(f"  Content matches: {stats['total_content_matches']}")
    logger.info(f"  Avg time: {stats['avg_processing_time_ms']:.2f}ms")


if __name__ == '__main__':
    main()
