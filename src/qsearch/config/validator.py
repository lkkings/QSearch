"""Configuration dependency validation.

Validates that configuration settings have consistent dependencies (e.g., formula matching
requires formula extraction to be enabled).
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

        # Check formula matching dependency
        errors.extend(self._check_formula_dependency(config))

        # Check visual similarity dependency
        errors.extend(self._check_visual_similarity_dependency(config))

        # Check feature weight consistency
        errors.extend(self._check_feature_weights(config))

        # Check threshold ranges
        errors.extend(self._check_threshold_ranges(config))

        # Check model availability (basic check)
        errors.extend(self._check_model_references(config))

        return errors

    def _check_formula_dependency(self, config: Dict[str, Any]) -> List[str]:
        """Check if formula matching requires formula extraction enabled."""
        errors = []

        # Navigate to formula matching setting
        formula_match_enabled = (
            config.get("matching", {})
            .get("content_match", {})
            .get("stage2", {})
            .get("optional_conditions", {})
            .get("formula_match", {})
            .get("enabled", False)
        )

        # Navigate to formula extraction setting
        formula_extraction_enabled = (
            config.get("text", {})
            .get("components", {})
            .get("formulas", {})
            .get("enabled", False)
        )

        if formula_match_enabled and not formula_extraction_enabled:
            errors.append(
                "Formula matching is enabled but formula extraction is disabled. "
                "Set text.components.formulas.enabled to true."
            )

        return errors

    def _check_visual_similarity_dependency(self, config: Dict[str, Any]) -> List[str]:
        """Check if visual similarity requires image feature extraction."""
        errors = []

        # Navigate to visual similarity setting
        visual_similarity_enabled = (
            config.get("matching", {})
            .get("content_match", {})
            .get("stage2", {})
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

    def _check_feature_weights(self, config: Dict[str, Any]) -> List[str]:
        """Check if feature weights are valid and issue warnings if they don't sum to 1.0."""
        errors = []

        # Check text component weights
        text_components = config.get("text", {}).get("components", {})
        weights = []

        for component in ["stem", "options", "formulas"]:
            comp_config = text_components.get(component, {})
            if comp_config.get("enabled", False):
                weight = comp_config.get("weight")
                if weight is not None:
                    weights.append(weight)

        if weights:
            total = sum(weights)
            if total > 1.0:
                errors.append(
                    f"Text component weights sum to {total:.2f} which exceeds 1.0. "
                    "Weights will be normalized, but consider adjusting manually."
                )

        return errors

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
        ocr_threshold = config.get("ocr", {}).get("confidence_threshold")

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
