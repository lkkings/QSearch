"""Matching engines for exact and content-based question matching.

Simplified version without QuestionParser dependency.
Implements dual-path matching: exact match via perceptual hashing and
content match via text similarity.
"""

import logging
import time
from typing import Dict, List, Optional, Tuple

import Levenshtein
import numpy as np

from ..indexing.hash_index import HashIndex
from ..indexing.faiss_index import FaissIndexBuilder

logger = logging.getLogger(__name__)


class ExactMatcher:
    """Exact match detection using perceptual hash distance."""

    def __init__(
        self,
        hash_index: HashIndex,
        config: Dict
    ):
        """Initialize exact matcher.

        Args:
            hash_index: HashIndex instance
            config: Configuration for exact matching
        """
        self.hash_index = hash_index
        self.config = config
        self.max_distance = config.get('criteria', {}).get('perceptual_hash', {}).get('max_distance', 5)

    def match(self, query_hash: str, top_n: Optional[int] = None) -> List[Dict]:
        """Find exact matches for query hash.

        Args:
            query_hash: Query perceptual hash
            top_n: Optional limit on number of results (for WebUI support)

        Returns:
            List of match dictionaries with image_id, distance, confidence
        """
        # Check if exact matching is enabled
        if not self.config.get('enabled', True):
            return []

        # Find similar hashes
        results = self.hash_index.lookup_similar(query_hash, self.max_distance)

        matches = []
        for image_id, distance in results:
            confidence = self._compute_confidence(distance)

            matches.append({
                'image_id': image_id,
                'match_type': 'EXACT_MATCH',
                'distance': distance,
                'confidence': confidence,
                'similarity': confidence,
                'scores': {
                    'hash_distance': distance
                }
            })

        # Sort by confidence
        matches.sort(key=lambda x: x['confidence'], reverse=True)

        # Apply top_n limit if specified
        if top_n is not None and top_n > 0:
            matches = matches[:top_n]

        return matches

    def _compute_confidence(self, distance: int) -> float:
        """Compute confidence score from hash distance.

        Args:
            distance: Hamming distance

        Returns:
            Confidence score (0-1)
        """
        # Normalize: 1.0 - distance/256 (for 16x16 hash = 256 bits)
        max_bits = 256
        return max(0.0, 1.0 - distance / max_bits)


class ContentMatcher:
    """Content match detection via two-stage text similarity (simplified)."""

    def __init__(
        self,
        faiss_index: FaissIndexBuilder,
        features_db: Dict,  # image_id -> features
        config: Dict
    ):
        """Initialize content matcher.

        Args:
            faiss_index: FaissIndexBuilder instance
            features_db: Database of extracted features
            config: Configuration for content matching
        """
        self.faiss_index = faiss_index
        self.features_db = features_db
        self.config = config

        # Stage 1 config
        self.stage1_threshold = config.get('stage1', {}).get('text_similarity_threshold', 0.75)
        self.stage1_top_k = config.get('stage1', {}).get('top_k', 100)

        # Scoring config
        self.scoring_config = config.get('scoring', {})
        self.final_threshold = self.scoring_config.get('threshold', 0.85)

    def match(
        self,
        query_features: Dict,
        top_n: Optional[int] = None
    ) -> List[Dict]:
        """Find content matches for query.

        Args:
            query_features: Extracted features from query image
            top_n: Optional limit on number of results (for WebUI support)

        Returns:
            List of match dictionaries
        """
        # Check if content matching is enabled
        if not self.config.get('enabled', True):
            return []

        # Stage 1: Vector similarity retrieval
        # Use stage1_top_k for candidate retrieval, not top_n
        candidates = self._stage1_retrieval(query_features, None)

        if not candidates:
            return []

        # Stage 2: Text similarity verification
        matches = self._stage2_verification(query_features, candidates)

        # Sort by final score
        matches.sort(key=lambda x: x['final_score'], reverse=True)

        # Apply top_n limit if specified
        if top_n is not None and top_n > 0:
            matches = matches[:top_n]

        return matches

    def match_batch(
        self,
        query_features_list: List[Dict],
        top_n: Optional[int] = None,
        batch_size: int = 1024,
    ) -> List[List[Dict]]:
        """Find content matches for multiple queries with batched FAISS calls.

        Feature extraction is deliberately kept outside this method.  This lets
        callers finish their CPU-heavy OCR/encoding work in parallel, then feed
        dense query matrices to FAISS instead of issuing one search call per
        image.
        """
        matches_by_query: List[List[Dict]] = [
            [] for _ in range(len(query_features_list))
        ]
        if not self.config.get('enabled', True) or not query_features_list:
            return matches_by_query

        positions: List[int] = []
        embeddings: List[np.ndarray] = []
        expected_dimension = int(self.faiss_index.dimension)

        for position, query_features in enumerate(query_features_list):
            embedding = (
                query_features.get('text_features') or {}
            ).get('text_embedding')
            if embedding is None:
                continue

            vector = np.asarray(embedding, dtype=np.float32)
            if vector.ndim != 1 or vector.shape[0] != expected_dimension:
                logger.warning(
                    "Ignoring query embedding with shape %s; expected (%d,)",
                    vector.shape,
                    expected_dimension,
                )
                continue

            positions.append(position)
            embeddings.append(vector)

        if not embeddings:
            return matches_by_query

        batch_size = max(1, int(batch_size))
        for start in range(0, len(embeddings), batch_size):
            stop = min(start + batch_size, len(embeddings))
            query_matrix = np.stack(embeddings[start:stop])
            candidate_batches = self.faiss_index.search(
                query_matrix,
                k=self.stage1_top_k,
                threshold=self.stage1_threshold,
            )

            for position, candidates in zip(
                positions[start:stop], candidate_batches
            ):
                matches = self._stage2_verification(
                    query_features_list[position], candidates
                )
                matches.sort(key=lambda item: item['final_score'], reverse=True)
                if top_n is not None and top_n > 0:
                    matches = matches[:top_n]
                matches_by_query[position] = matches

        return matches_by_query

    def _stage1_retrieval(self, query_features: Dict, top_n: Optional[int] = None) -> List[Tuple[str, float]]:
        """Stage 1: Retrieve candidates via vector similarity.

        Args:
            query_features: Query features
            top_n: Optional limit on number of candidates

        Returns:
            List of (image_id, similarity) tuples
        """
        # Get text embedding
        text_embedding = query_features.get('text_features', {}).get('text_embedding')

        if text_embedding is None:
            logger.warning("No text embedding for query")
            return []

        # Determine k for Faiss search
        # Use top_n if provided, otherwise use config default
        k = top_n if top_n is not None else self.stage1_top_k

        # Search index
        query_vector = np.array([text_embedding])
        results = self.faiss_index.search(
            query_vector,
            k=k,
            threshold=self.stage1_threshold
        )

        return results[0] if results else []

    def _stage2_verification(
        self,
        query_features: Dict,
        candidates: List[Tuple[str, float]]
    ) -> List[Dict]:
        """Stage 2: Simplified text matching.

        Args:
            query_features: Query features
            candidates: Candidate list from stage 1

        Returns:
            List of verified matches
        """
        matches = []

        query_text = query_features.get('text_features', {})
        query_full_text = query_text.get('full_text', '')

        for candidate_id, vec_similarity in candidates:
            # Get candidate features
            candidate_features = self.features_db.get(candidate_id, {})
            candidate_text = candidate_features.get('text_features', {})
            candidate_full_text = candidate_text.get('full_text', '')

            # Compute text similarity using Levenshtein distance
            if not query_full_text or not candidate_full_text:
                continue

            max_len = max(len(query_full_text), len(candidate_full_text))
            if max_len == 0:
                text_similarity = 0.0
                edit_distance = 0
            else:
                edit_distance = Levenshtein.distance(query_full_text, candidate_full_text)
                text_similarity = 1.0 - (edit_distance / max_len)

            # Combine vector and text similarity
            final_score = 0.75 * vec_similarity + 0.25 * text_similarity

            if final_score >= self.final_threshold:
                matches.append({
                    'image_id': candidate_id,
                    'match_type': 'CONTENT_MATCH',
                    'final_score': final_score,
                    'confidence': final_score,
                    'similarity': final_score,
                    'scores': {
                        'vector_similarity': float(vec_similarity),
                        'text_similarity': float(text_similarity),
                        'edit_distance': int(edit_distance)
                    }
                })

        return matches


class QuestionMatcher:
    """Top-level matcher that combines exact and content matching."""

    def __init__(
        self,
        exact_matcher: ExactMatcher,
        content_matcher: ContentMatcher,
        config: Dict
    ):
        """Initialize question matcher.

        Args:
            exact_matcher: ExactMatcher instance
            content_matcher: ContentMatcher instance
            config: Output configuration
        """
        self.exact_matcher = exact_matcher
        self.content_matcher = content_matcher
        self.config = config
        self.top_k = config.get('top_k', 3)  # 默认返回 Top 3

    def match(self, query_features: Dict, top_n: Optional[int] = None) -> Dict:
        """Match query against database.

        Args:
            query_features: Extracted query features
            top_n: Optional override for number of results (1-20).
                   If None, uses config default (top_k).
                   Clamped to valid range internally.

        Returns:
            Match results dictionary with top matches
        """
        start_time = time.time()

        # Validate and clamp top_n
        if top_n is not None:
            top_n = max(1, min(20, top_n))  # Clamp to [1, 20]
            result_limit = top_n
        else:
            result_limit = self.top_k  # Use config default

        # Try exact match first
        exact_matches = []
        query_hash = query_features.get('image_features', {}).get('perceptual_hash')

        if query_hash:
            exact_matches = self.exact_matcher.match(query_hash, top_n=result_limit)

        # Try content match
        content_matches = self.content_matcher.match(query_features, top_n=result_limit)

        # Combine and deduplicate
        all_matches = self._combine_matches(exact_matches, content_matches)

        # Keep only result_limit results
        top_matches = all_matches[:result_limit]

        processing_time = (time.time() - start_time) * 1000

        return {
            'total_matches': len(all_matches),
            'top_k': len(top_matches),
            'matches': top_matches,
            'processing_time_ms': processing_time
        }

    def match_batch(
        self,
        query_features_list: List[Dict],
        top_n: Optional[int] = None,
        vector_batch_size: int = 1024,
    ) -> List[Dict]:
        """Match multiple feature dictionaries using batched vector retrieval."""
        if top_n is not None:
            result_limit = max(1, min(20, top_n))
        else:
            result_limit = self.top_k

        started_at = time.time()
        content_batches = self.content_matcher.match_batch(
            query_features_list,
            top_n=result_limit,
            batch_size=vector_batch_size,
        )
        elapsed_ms = (time.time() - started_at) * 1000
        average_ms = elapsed_ms / len(query_features_list) if query_features_list else 0.0

        results: List[Dict] = []
        for query_features, content_matches in zip(
            query_features_list, content_batches
        ):
            exact_matches = []
            query_hash = (
                query_features.get('image_features') or {}
            ).get('perceptual_hash')
            if query_hash:
                exact_matches = self.exact_matcher.match(
                    query_hash, top_n=result_limit
                )

            all_matches = self._combine_matches(exact_matches, content_matches)
            top_matches = all_matches[:result_limit]
            results.append({
                'total_matches': len(all_matches),
                'top_k': len(top_matches),
                'matches': top_matches,
                'processing_time_ms': average_ms,
            })

        return results

    def _combine_matches(
        self,
        exact_matches: List[Dict],
        content_matches: List[Dict]
    ) -> List[Dict]:
        """Combine and deduplicate exact and content matches.

        Args:
            exact_matches: List of exact matches
            content_matches: List of content matches

        Returns:
            Combined and sorted list
        """
        # Use dict to deduplicate by image_id
        combined = {}

        # Exact matches have higher priority
        for match in exact_matches:
            image_id = match['image_id']
            combined[image_id] = match

        # Add content matches if not already present
        for match in content_matches:
            image_id = match['image_id']
            if image_id not in combined:
                combined[image_id] = match

        # Sort by similarity/confidence
        matches_list = list(combined.values())
        matches_list.sort(key=lambda x: x.get('similarity', x.get('confidence', 0)), reverse=True)

        return matches_list
