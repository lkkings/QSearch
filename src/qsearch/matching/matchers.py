"""Matching engines for exact and content-based question matching.

Implements dual-path matching: exact match via perceptual hashing and
content match via text similarity with multi-stage verification.
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

    def match(self, query_hash: str) -> List[Dict]:
        """Find exact matches for query hash.

        Args:
            query_hash: Query perceptual hash

        Returns:
            List of match dictionaries with image_id, distance, confidence
        """
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
                'scores': {
                    'hash_distance': distance
                }
            })

        # Sort by confidence
        matches.sort(key=lambda x: x['confidence'], reverse=True)

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
    """Content match detection via two-stage text similarity."""

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

        # Stage 2 config
        self.stage2_config = config.get('stage2', {})
        self.required_conditions = self.stage2_config.get('required_conditions', {})
        self.optional_conditions = self.stage2_config.get('optional_conditions', {})

        # Scoring config
        self.scoring_config = config.get('scoring', {})
        self.required_weight = self.scoring_config.get('required_weight', 0.8)
        self.optional_weight = self.scoring_config.get('optional_weight', 0.2)
        self.final_threshold = self.scoring_config.get('threshold', 0.85)

    def match(
        self,
        query_features: Dict
    ) -> List[Dict]:
        """Find content matches for query.

        Args:
            query_features: Extracted features from query image

        Returns:
            List of match dictionaries
        """
        # Stage 1: Vector similarity retrieval
        candidates = self._stage1_retrieval(query_features)

        if not candidates:
            return []

        # Stage 2: Detailed text matching
        matches = self._stage2_verification(query_features, candidates)

        # Sort by final score
        matches.sort(key=lambda x: x['final_score'], reverse=True)

        return matches

    def _stage1_retrieval(self, query_features: Dict) -> List[Tuple[str, float]]:
        """Stage 1: Retrieve candidates via vector similarity.

        Args:
            query_features: Query features

        Returns:
            List of (image_id, similarity) tuples
        """
        # Get stem embedding
        stem_embedding = query_features.get('text_features', {}).get('stem_embedding')

        if stem_embedding is None:
            logger.warning("No stem embedding for query")
            return []

        # Search index
        query_vector = np.array([stem_embedding])
        results = self.faiss_index.search(
            query_vector,
            k=self.stage1_top_k,
            threshold=self.stage1_threshold
        )

        return results[0] if results else []

    def _stage2_verification(
        self,
        query_features: Dict,
        candidates: List[Tuple[str, float]]
    ) -> List[Dict]:
        """Stage 2: Detailed text and optional feature matching.

        Args:
            query_features: Query features
            candidates: Candidate list from stage 1

        Returns:
            List of verified matches
        """
        matches = []

        query_text = query_features.get('text_features', {})
        query_stem = query_text.get('stem', '')
        query_options = query_text.get('options_normalized', [])
        query_type = query_text.get('question_type', 'unknown')

        for candidate_id, vec_similarity in candidates:
            # Get candidate features
            candidate_features = self.features_db.get(candidate_id, {})
            candidate_text = candidate_features.get('text_features', {})

            # Check required conditions
            required_score, required_passed = self._check_required_conditions(
                query_stem,
                query_options,
                query_type,
                candidate_text
            )

            if not required_passed:
                continue

            # Check optional conditions
            optional_score = self._check_optional_conditions(
                query_features,
                candidate_features
            )

            # Compute final score
            final_score = (
                self.required_weight * required_score +
                self.optional_weight * optional_score
            )

            if final_score >= self.final_threshold:
                matches.append({
                    'image_id': candidate_id,
                    'match_type': 'CONTENT_MATCH',
                    'final_score': final_score,
                    'confidence': final_score,
                    'verification_passed': ['stage1_vector', 'stage2_required'],
                    'scores': {
                        'vector_similarity': vec_similarity,
                        'required_score': required_score,
                        'optional_score': optional_score
                    }
                })

        return matches

    def _check_required_conditions(
        self,
        query_stem: str,
        query_options: List[str],
        query_type: str,
        candidate_text: Dict
    ) -> Tuple[float, bool]:
        """Check required matching conditions.

        Returns:
            Tuple of (score, all_passed)
        """
        scores = []
        all_passed = True

        # Stem matching
        stem_config = self.required_conditions.get('stem_match', {})
        if stem_config.get('enabled', True):
            candidate_stem = candidate_text.get('stem', '')
            max_edit_distance = stem_config.get('max_edit_distance', 3)

            edit_distance = Levenshtein.distance(query_stem, candidate_stem)

            if edit_distance > max_edit_distance:
                all_passed = False

            stem_score = max(0.0, 1.0 - edit_distance / max(len(query_stem), len(candidate_stem), 1))
            scores.append(stem_score)

        # Options matching
        options_config = self.required_conditions.get('options_match', {})
        if options_config.get('enabled', True):
            candidate_options = candidate_text.get('options_normalized', [])

            # Order-independent comparison
            if set(query_options) != set(candidate_options):
                all_passed = False
                scores.append(0.0)
            else:
                scores.append(1.0)

        # Question type matching
        type_config = self.required_conditions.get('question_type_match', {})
        if type_config.get('enabled', True):
            candidate_type = candidate_text.get('question_type', 'unknown')

            if query_type != candidate_type:
                all_passed = False
                scores.append(0.0)
            else:
                scores.append(1.0)

        avg_score = sum(scores) / len(scores) if scores else 0.0
        return avg_score, all_passed

    def _check_optional_conditions(
        self,
        query_features: Dict,
        candidate_features: Dict
    ) -> float:
        """Check optional matching conditions.

        Returns:
            Weighted optional score
        """
        scores = []
        weights = []

        # Formula matching
        formula_config = self.optional_conditions.get('formula_match', {})
        if formula_config.get('enabled', False):
            weight = formula_config.get('weight', 0.15)
            # Simplified: just check if both have formulas
            query_formulas = query_features.get('text_features', {}).get('formulas', [])
            candidate_formulas = candidate_features.get('text_features', {}).get('formulas', [])

            score = 1.0 if (query_formulas and candidate_formulas) else 0.5
            scores.append(score)
            weights.append(weight)

        # Visual similarity
        visual_config = self.optional_conditions.get('visual_similarity', {})
        if visual_config.get('enabled', False):
            weight = visual_config.get('weight', 0.05)
            # Would use CNN features if available
            score = 0.7  # Placeholder
            scores.append(score)
            weights.append(weight)

        if not scores:
            return 0.0

        # Weighted average
        weighted_sum = sum(s * w for s, w in zip(scores, weights))
        total_weight = sum(weights)

        return weighted_sum / total_weight if total_weight > 0 else 0.0


class QuestionMatcher:
    """Orchestrates exact and content matching paths."""

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
        self.top_k = config.get('top_k', 10)

    def match(self, query_features: Dict) -> Dict:
        """Match query using both paths.

        Args:
            query_features: Extracted query features

        Returns:
            Results dictionary with both match types
        """
        start_time = time.time()

        # Extract query hash
        query_hash = query_features.get('image_features', {}).get('perceptual_hash')

        # Exact matches
        exact_matches = []
        if query_hash:
            exact_matches = self.exact_matcher.match(query_hash)

        # Content matches
        content_matches = self.content_matcher.match(query_features)

        # Deduplication: mark images in both
        exact_ids = set(m['image_id'] for m in exact_matches)
        for match in content_matches:
            if match['image_id'] in exact_ids:
                match['also_exact_match'] = True

        # Apply top-K per type
        exact_matches = exact_matches[:self.top_k]
        content_matches = content_matches[:self.top_k]

        # Add confidence levels
        for match in exact_matches + content_matches:
            conf = match['confidence']
            if conf >= 0.9:
                match['confidence_level'] = 'HIGH'
            elif conf >= 0.8:
                match['confidence_level'] = 'MEDIUM'
            else:
                match['confidence_level'] = 'LOW'

        processing_time = (time.time() - start_time) * 1000

        return {
            'exact_matches': exact_matches,
            'content_matches': content_matches,
            'processing_time_ms': processing_time
        }
