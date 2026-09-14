"""Configuration dependency validation.

Validates that configuration settings have consistent dependencies (e.g., visual
similarity matching requires deep image features to be enabled).
"""

from typing import Any, Dict, List


class DependencyValidator:
    """Validates configuration dependencies and consistency."""

    def validate(self, config: Dict[str, Any]) -> List[str]:
        """Validate configuration dependencies.

        Args:
            config: Complete configuration dictionary (features + matching merged)

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        # Check visual similarity dependency
        errors.extend(self._check_visual_similarity_dependency(config))

        # Check threshold ranges
        errors.extend(self._check_threshold_ranges(config))

        # Check Faiss index parameter consistency
        errors.extend(self._check_index_params(config))

        # Check model availability (basic check)
        errors.extend(self._check_model_references(config))

        return errors

    def _check_visual_similarity_dependency(self, config: Dict[str, Any]) -> List[str]:
        """Check if visual similarity requires image feature extraction."""
        errors = []

        # Navigate to visual similarity setting
        visual_similarity_enabled = (
            config.get("matching", {})
            .get("content_match", {})
            .get("optional_conditions", {})
            .get("visual_similarity", {})
            .get("enabled", False)
        )

        # Navigate to image feature settings
        deep_features_enabled = (
            config.get("image", {})
            .get("components", {})
            .get("deep_features", {})
            .get("enabled", False)
        )

        if visual_similarity_enabled and not deep_features_enabled:
            errors.append(
                "Visual similarity is enabled but deep image features are disabled. "
                "Set image.components.deep_features.enabled to true."
            )

        return errors

    def _check_index_params(self, config: Dict[str, Any]) -> List[str]:
        """Check Faiss index parameters against each other and the vector dimension.

        These only fail at build time otherwise, after feature extraction has
        already run, so catching them up front saves a full extraction pass.
        """
        errors = []

        index_config = config.get("index", {})
        if not index_config:
            return errors

        index_type = index_config.get("type", "Flat")
        dimension = (
            config.get("text", {})
            .get("encoding", {})
            .get("embedding_dim", 768)
        )

        if index_type == "IVFPQ":
            m_pq = index_config.get("m_pq", 16)
            if dimension % m_pq != 0:
                errors.append(
                    f"IVFPQ m_pq={m_pq} must divide embedding_dim={dimension}. "
                    f"Pick a divisor, e.g. {self._divisors(dimension)}."
                )

        if index_type in ("IVFFlat", "IVFPQ"):
            nlist = index_config.get("nlist", 100)
            nprobe = index_config.get("nprobe", 10)
            if nprobe > nlist:
                errors.append(
                    f"nprobe={nprobe} exceeds nlist={nlist}; "
                    "searching more cells than exist has no effect."
                )

        return errors

    @staticmethod
    def _divisors(dimension: int, limit: int = 128) -> str:
        """List plausible PQ sub-vector counts for a dimension.

        Args:
            dimension: Vector dimension
            limit: Largest divisor worth suggesting

        Returns:
            Comma-separated divisors
        """
        found = [d for d in range(1, min(dimension, limit) + 1) if dimension % d == 0]
        return ", ".join(str(d) for d in found[-6:])

    def _check_threshold_ranges(self, config: Dict[str, Any]) -> List[str]:
        """Check that all thresholds are in valid ranges."""
        errors = []

        # Check content match threshold
        content_threshold = (
            config.get("matching", {})
            .get("content_match", {})
            .get("scoring", {})
            .get("threshold")
        )

        if content_threshold is not None:
            if content_threshold < 0.0 or content_threshold > 1.0:
                errors.append(
                    f"Content match threshold {content_threshold} is outside valid range [0.0, 1.0]"
                )

        # Check stage1 text similarity threshold
        stage1_threshold = (
            config.get("matching", {})
            .get("content_match", {})
            .get("stage1", {})
            .get("text_similarity_threshold")
        )

        if stage1_threshold is not None:
            if stage1_threshold < 0.0 or stage1_threshold > 1.0:
                errors.append(
                    f"Stage 1 text similarity threshold {stage1_threshold} is outside valid range [0.0, 1.0]"
                )

        # Check OCR confidence threshold
        ocr_threshold = config.get("text", {}).get("ocr", {}).get("confidence_threshold")

        if ocr_threshold is not None:
            if ocr_threshold < 0.0 or ocr_threshold > 1.0:
                errors.append(
                    f"OCR confidence threshold {ocr_threshold} is outside valid range [0.0, 1.0]"
                )

        return errors

    def _check_model_references(self, config: Dict[str, Any]) -> List[str]:
        """Check that referenced models are valid identifiers."""
        errors = []

        # Check text encoding models
        chinese_model = config.get("text", {}).get("encoding", {}).get("chinese_model")
        if chinese_model and not isinstance(chinese_model, str):
            errors.append(f"chinese_model must be a string, got {type(chinese_model).__name__}")

        english_model = config.get("text", {}).get("encoding", {}).get("english_model")
        if english_model and not isinstance(english_model, str):
            errors.append(f"english_model must be a string, got {type(english_model).__name__}")

        # Check CNN model
        cnn_model = (
            config.get("image", {})
            .get("components", {})
            .get("deep_features", {})
            .get("model")
        )
        if cnn_model and not isinstance(cnn_model, str):
            errors.append(f"CNN model must be a string, got {type(cnn_model).__name__}")

        return errors


def validate_dependencies(config: Dict[str, Any]) -> List[str]:
    """Validate configuration dependencies.

    Convenience function that creates a validator and runs validation.

    Args:
        config: Complete configuration dictionary

    Returns:
        List of validation error messages (empty if valid)
    """
    validator = DependencyValidator()
    return validator.validate(config)
