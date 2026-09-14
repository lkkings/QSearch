"""Search engine wrapper for QSearch WebUI.

Provides a unified interface over QuestionMatcher with result persistence and formatting.
Refactored into three layers:
1. MatcherWrapper: 封装 QuestionMatcher（持有索引引用）
2. SearchEngine: 结果格式化与持久化（调用 matcher，持有 FeatureExtractor）
"""

import logging
import pickle
import tempfile
import uuid
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Union

import requests
from PIL import Image

from qsearch.config.loader import ConfigLoader
from qsearch.features.feature_extractor import FeatureExtractor
from qsearch.indexing.faiss_index import FaissIndexBuilder
from qsearch.indexing.hash_index import HashIndex
from qsearch.matching.matchers import ContentMatcher, ExactMatcher, QuestionMatcher
from qsearch.webui import result_store
from qsearch.webui.matcher_wrapper import MatcherWrapper

logger = logging.getLogger(__name__)


class SearchEngine:
    """Search engine wrapper with result persistence."""

    def __init__(
        self,
        database_path: Path,
        config: Optional[Dict] = None,
        load_feature_extractor: bool = True,
        index_resources: Optional[
            tuple[FaissIndexBuilder, HashIndex, Dict[str, Dict]]
        ] = None,
        feature_extractor: Optional[FeatureExtractor] = None,
    ):
        """Initialize search engine for a database.

        Args:
            database_path: Path to database directory containing index files
            config: Pre-loaded configuration. Pass this from a worker process to
                skip re-reading config.yaml; omit it to load from the database.
            load_feature_extractor: Whether to load OCR/encoding models locally.
                Batch search disables this because its worker pool owns those
                models and this process only performs index lookup.
            index_resources: Already loaded FAISS/hash/features resources. Used
                by the shared cache to avoid reading the same index again.
            feature_extractor: Already loaded extractor supplied by the shared
                model cache. Takes precedence over ``load_feature_extractor``.

        Raises:
            FileNotFoundError: If index files not found
        """
        self.database_path = Path(database_path)
        self.index_dir = self.database_path / "index"
        self.annotations_db = self.database_path / "annotations" / "annotations.db"

        # Verify index files exist
        required_files = [
            "features.pkl",
            "text_index.faiss",
            "text_index_ids.pkl",
            "hash_index.pkl",
        ]

        for filename in required_files:
            file_path = self.index_dir / filename
            if not file_path.exists():
                raise FileNotFoundError(
                    f"Index file not found: {file_path}. "
                    f"Please build the index first."
                )

        # Load configuration.
        #
        # ConfigLoader has no `load` method — the reader is `load_yaml`. The
        # previous call raised AttributeError on every construction, which is
        # why batch search never ran.
        if config is not None:
            self.config = config
        else:
            config_path = self.database_path / "config.yaml"
            if not config_path.exists():
                raise FileNotFoundError(f"Configuration not found: {config_path}")
            self.config = ConfigLoader.load_yaml(config_path)

        # Build matcher wrapper with loaded indices
        self.matcher_wrapper = self._build_matcher(index_resources)

        # The query image must be turned into features before it can be matched;
        # the matcher consumes a feature dict, not a path.
        if feature_extractor is not None:
            self.feature_extractor = feature_extractor
        else:
            self.feature_extractor = (
                FeatureExtractor(self.config) if load_feature_extractor else None
            )

        logger.info(f"Search engine initialized for database: {self.database_path.name}")

    def _build_matcher(
        self,
        index_resources: Optional[
            tuple[FaissIndexBuilder, HashIndex, Dict[str, Dict]]
        ] = None,
    ) -> MatcherWrapper:
        """Load indices and assemble the matcher.

        Returns:
            MatcherWrapper wrapping QuestionMatcher wired to this database's indices

        Raises:
            RuntimeError: If index files cannot be loaded
        """
        matching_config = self.config.get("matching", {})

        # GPU is off by default here. A search pool runs one engine per worker,
        # and N workers each claiming GPU/Faiss resources exhausts VRAM well
        # before it exhausts CPU. Opt in explicitly for single-query use.
        index_config = self.config.get("index", {})
        use_gpu = bool(index_config.get("use_gpu", False))
        index_type = str(index_config.get("type", "Flat"))
        nprobe = int(index_config.get("nprobe", 10))
        ef_search = int(index_config.get("ef_search", 32))

        if index_resources is None:
            try:
                faiss_index = FaissIndexBuilder(
                    dimension=768,
                    use_gpu=use_gpu,
                    index_type=index_type,
                    nprobe=nprobe,
                    ef_search=ef_search,
                )
                faiss_index.load(
                    str(self.index_dir / "text_index.faiss"),
                    str(self.index_dir / "text_index_ids.pkl"),
                )
                # Apply search-time parameters after loading
                faiss_index.apply_search_params()

                hash_index = HashIndex()
                hash_index.load(str(self.index_dir / "hash_index.pkl"), format="pickle")

                with open(self.index_dir / "features.pkl", "rb") as handle:
                    features_list = pickle.load(handle)

            except Exception as exc:
                raise RuntimeError(
                    f"Failed to load indices from {self.index_dir}: {exc}"
                ) from exc

            features_db = {item["image_path"]: item for item in features_list}
        else:
            faiss_index, hash_index, features_db = index_resources

        self.index_resources = (faiss_index, hash_index, features_db)

        exact_matcher = ExactMatcher(hash_index, matching_config.get("exact_match", {}))
        content_matcher = ContentMatcher(
            faiss_index, features_db, matching_config.get("content_match", {})
        )

        question_matcher = QuestionMatcher(
            exact_matcher, content_matcher, matching_config.get("output", {})
        )

        return MatcherWrapper(question_matcher, faiss_index, hash_index, features_db)

    def search_single(
        self,
        query_image: Union[Path, str, Image.Image, BytesIO],
        top_n: Optional[int] = None,
        config_override: Optional[Dict] = None,
        batch_size: Optional[int] = None,
    ) -> Dict:
        """Search for matching questions for a single query image.

        Args:
            query_image: Query image (path, URL, PIL Image, or BytesIO)
            top_n: Number of top results to return (1-20, default from config)
            config_override: Temporary configuration overrides
            batch_size: Feature extraction batch size (useful for API consistency)

        Returns:
            Formatted search results dictionary

        Raises:
            ValueError: If query image is invalid or top_n out of range
        """
        # Load query image
        try:
            image_path, pil_image = self._load_image(query_image)
        except Exception as e:
            raise ValueError(f"Failed to load query image: {e}") from e

        # Validate and clamp top_n
        if top_n is not None:
            if top_n < 1 or top_n > 20:
                raise ValueError(f"top_n must be between 1 and 20, got {top_n}")
        else:
            # Use default from config
            top_n = self.config.get("output", {}).get("top_k", 10)

        # Apply config overrides if provided
        if config_override:
            # Temporarily merge config
            original_config = self.config.copy()
            self.config.update(config_override)
            self.matcher_wrapper.matcher.config = self.config

        try:
            # Perform matching.
            #
            # QuestionMatcher.match consumes a feature dict, not a path. The
            # query has to go through the same extractor the index was built
            # with, otherwise there is no embedding or hash to compare against.
            start_time = datetime.utcnow()
            if self.feature_extractor is None:
                raise RuntimeError(
                    "This SearchEngine was created without a feature extractor"
                )
            if batch_size is None:
                query_features = self.feature_extractor.extract(image_path)
            else:
                query_features = self.feature_extractor.extract_batch(
                    [image_path],
                    num_workers=1,
                    show_progress=False,
                    batch_size=batch_size,
                )[0]
            results = self.matcher_wrapper.matcher.match(query_features, top_n=top_n)
            processing_time = (datetime.utcnow() - start_time).total_seconds() * 1000

            # Format results
            formatted_results = self._format_results(
                query_image_path=str(image_path),
                results=results,
                processing_time_ms=processing_time,
            )

            return formatted_results

        finally:
            # Restore original config
            if config_override:
                self.config = original_config
                self.matcher_wrapper.matcher.config = original_config

    def search_features_batch(
        self,
        query_features_list: List[Dict],
        top_n: Optional[int] = None,
        batch_size: Optional[int] = None,
    ) -> List[Dict]:
        """Search a fully extracted feature batch with batched FAISS queries.

        The returned list preserves input order, which is required by the task
        runner's checkpoint semantics.
        """
        if top_n is not None:
            if top_n < 1 or top_n > 20:
                raise ValueError(f"top_n must be between 1 and 20, got {top_n}")
        else:
            top_n = self.config.get("output", {}).get("top_k", 10)

        content_config = self.config.get("matching", {}).get("content_match", {})
        vector_batch_size = int(
            content_config.get("stage1", {}).get("batch_size", 1024)
            if batch_size is None
            else batch_size
        )
        if vector_batch_size < 1:
            raise ValueError(
                f"batch_size must be at least 1, got {vector_batch_size}"
            )
        raw_results = self.matcher_wrapper.match_batch(
            query_features_list,
            top_n=top_n,
            vector_batch_size=vector_batch_size,
        )

        return [
            self._format_results(
                query_image_path=str(features.get("image_path", "")),
                results=result,
                processing_time_ms=float(result.get("processing_time_ms", 0.0)),
            )
            for features, result in zip(query_features_list, raw_results)
        ]

    def close(self) -> None:
        """Drop references to models and indices so cached memory is released."""
        self.feature_extractor = None
        self.matcher_wrapper = None

    def save_query_result(
        self,
        query_id: str,
        query_image_path: str,
        database_name: str,
        results: Dict,
        top_n: int,
        config_preset: Optional[str] = None,
        config_yaml: Optional[str] = None,
    ) -> str:
        """Save query and candidate results to annotations database.

        Args:
            query_id: Unique query identifier (UUID)
            query_image_path: Path to query image
            database_name: Name of the database
            results: Formatted search results
            top_n: Number of top results requested
            config_preset: Configuration preset used (if any)
            config_yaml: Custom configuration YAML (if any)

        Returns:
            Query ID

        Raises:
            Exception: If database save fails
        """
        return result_store.save_query_result(
            annotations_db=self.annotations_db,
            database_name=database_name,
            query_image_path=query_image_path,
            results=results,
            top_n=top_n,
            config_preset=config_preset,
            config_yaml=config_yaml,
            query_id=query_id,
        )

    def _load_image(
        self,
        image: Union[Path, str, Image.Image, BytesIO],
    ) -> tuple[Path, Image.Image]:
        """Load image from various sources.

        Args:
            image: Image source (path, URL, PIL Image, or BytesIO)

        Returns:
            Tuple of (image_path, PIL Image)

        Raises:
            ValueError: If image cannot be loaded
        """
        if isinstance(image, Image.Image):
            # Already a PIL Image, save to temp file
            temp_path = self._temp_image_path()
            image.save(temp_path)
            return temp_path, image

        elif isinstance(image, BytesIO):
            # BytesIO buffer
            pil_image = Image.open(image)
            temp_path = self._temp_image_path()
            pil_image.save(temp_path)
            return temp_path, pil_image

        elif isinstance(image, (str, Path)):
            image_str = str(image)

            # Check if it's a URL
            if image_str.startswith(("http://", "https://")):
                try:
                    response = requests.get(image_str, timeout=30)
                    response.raise_for_status()
                    pil_image = Image.open(BytesIO(response.content))
                    temp_path = self._temp_image_path()
                    pil_image.save(temp_path)
                    return temp_path, pil_image
                except requests.RequestException as e:
                    raise ValueError(f"Failed to download image from URL: {e}") from e
                except Exception as e:
                    raise ValueError(f"Failed to open downloaded image: {e}") from e

            else:
                # Local file path
                image_path = Path(image)
                if not image_path.exists():
                    raise ValueError(f"Image file not found: {image_path}")

                try:
                    pil_image = Image.open(image_path)
                    return image_path, pil_image
                except Exception as e:
                    raise ValueError(f"Failed to open image: {e}") from e

        else:
            raise ValueError(f"Unsupported image type: {type(image)}")

    def _format_results(
        self,
        query_image_path: str,
        results: Dict,
        processing_time_ms: float,
    ) -> Dict:
        """Format matching results to expected JSON structure.

        Args:
            query_image_path: Path to query image
            results: Raw results from QuestionMatcher
            processing_time_ms: Processing time in milliseconds

        Returns:
            Formatted results dictionary
        """
        formatted = {
            "query_image": query_image_path,
            "processing_time_ms": processing_time_ms,
            "exact_matches": [],
            "content_matches": [],
        }

        # QuestionMatcher returns one combined `matches` list where each entry
        # carries `match_type`; it does not pre-split into exact/content. The
        # previous code read two keys that are never present, so every result
        # formatted as empty.
        for match in results.get("matches", []):
            scores = match.get("scores", {})
            score = float(match.get("similarity", match.get("confidence", 0.0)))

            entry = {
                "image_path": match.get("image_id", ""),
                "confidence_level": self._confidence_level(score),
                "overall_score": score,
                "text_score": scores.get("text_similarity"),
                "visual_score": scores.get("vector_similarity"),
                "hash_distance": scores.get("hash_distance"),
            }

            if match.get("match_type") == "EXACT_MATCH":
                formatted["exact_matches"].append(entry)
            else:
                formatted["content_matches"].append(entry)

        return formatted

    @staticmethod
    def _temp_image_path() -> Path:
        """Build a temp path for a decoded query image.

        Uses the platform temp dir rather than a literal /tmp, which does not
        exist on Windows — the previous hardcoded path made every upload and
        URL query fail there.

        Returns:
            Path inside the system temp directory
        """
        return Path(tempfile.gettempdir()) / f"qsearch_query_{uuid.uuid4().hex}.png"

    @staticmethod
    def _confidence_level(score: float) -> str:
        """Bucket a score into a confidence label.

        Args:
            score: Overall score in [0, 1]

        Returns:
            Confidence level: 'HIGH', 'MEDIUM', or 'LOW'
        """
        if score >= 0.8:
            return "HIGH"
        if score >= 0.5:
            return "MEDIUM"
        return "LOW"

    @staticmethod
    def generate_query_id() -> str:
        """Generate a unique query ID.

        Returns:
            UUID string
        """
        return str(uuid.uuid4())
