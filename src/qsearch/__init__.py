"""QSearch: Configurable Question Matcher

A dual-path question matching system for finding identical or similar questions
in large image databases.
"""

__version__ = "1.0.0"

from .config.loader import ConfigLoader
from .config.presets import get_preset, list_presets
from .features.feature_extractor import FeatureExtractor
from .indexing.faiss_index import FaissIndexBuilder
from .indexing.hash_index import HashIndex
from .matching.matchers import ExactMatcher, ContentMatcher, QuestionMatcher

__all__ = [
    'ConfigLoader',
    'get_preset',
    'list_presets',
    'FeatureExtractor',
    'FaissIndexBuilder',
    'HashIndex',
    'ExactMatcher',
    'ContentMatcher',
    'QuestionMatcher',
]
