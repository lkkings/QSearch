"""JSON Schema for configuration validation.

Provides schema definitions and validation for feature extraction and matching configurations.
"""

from typing import Any, Dict, List, Optional

# JSON Schema for feature extraction configuration
FEATURES_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "text": {
            "type": "object",
            "properties": {
                "components": {
                    "type": "object",
                    "properties": {
                        "stem": {
                            "type": "object",
                            "properties": {
                                "enabled": {"type": "boolean"},
                                "weight": {"type": "number", "minimum": 0, "maximum": 1}
                            },
                            "required": ["enabled"]
                        },
                        "options": {
                            "type": "object",
                            "properties": {
                                "enabled": {"type": "boolean"},
                                "weight": {"type": "number", "minimum": 0, "maximum": 1},
                                "normalization": {
                                    "type": "array",
                                    "items": {
                                        "type": "string",
                                        "enum": ["remove_whitespace", "normalize_punctuation", "sort", "lowercase"]
                                    }
                                }
                            },
                            "required": ["enabled"]
                        },
                        "formulas": {
                            "type": "object",
                            "properties": {
                                "enabled": {"type": "boolean"},
                                "weight": {"type": "number", "minimum": 0, "maximum": 1}
                            },
                            "required": ["enabled"]
                        }
                    }
                },
                "encoding": {
                    "type": "object",
                    "properties": {
                        "chinese_model": {"type": "string"},
                        "english_model": {"type": "string"},
                        "embedding_dim": {"type": "integer", "minimum": 1}
                    }
                }
            }
        },
        "image": {
            "type": "object",
            "properties": {
                "components": {
                    "type": "object",
                    "properties": {
                        "perceptual_hash": {
                            "type": "object",
                            "properties": {
                                "enabled": {"type": "boolean"},
                                "algorithm": {"type": "string", "enum": ["dHash", "pHash", "aHash"]},
                                "hash_size": {"type": "integer", "minimum": 8, "maximum": 32}
                            },
                            "required": ["enabled"]
                        },
                        "deep_features": {
                            "type": "object",
                            "properties": {
                                "enabled": {"type": "boolean"},
                                "model": {"type": "string"},
                                "output_dim": {"type": "integer", "minimum": 128}
                            },
                            "required": ["enabled"]
                        }
                    }
                },
                "batch_size": {"type": "integer", "minimum": 1, "maximum": 512}
            }
        },
        "ocr": {
            "type": "object",
            "properties": {
                "engine": {"type": "string", "enum": ["paddleocr"]},
                "languages": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["ch", "en"]}
                },
                "confidence_threshold": {"type": "number", "minimum": 0, "maximum": 1}
            }
        },
        "metadata": {
            "type": "object",
            "properties": {
                "question_type_detection": {"type": "boolean"}
            }
        }
    }
}

# JSON Schema for matching configuration
MATCHING_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "exact_match": {
            "type": "object",
            "properties": {
                "enabled": {"type": "boolean"},
                "criteria": {
                    "type": "object",
                    "properties": {
                        "perceptual_hash": {
                            "type": "object",
                            "properties": {
                                "max_distance": {"type": "integer", "minimum": 0, "maximum": 256}
                            },
                            "required": ["max_distance"]
                        }
                    }
                }
            },
            "required": ["enabled"]
        },
        "content_match": {
            "type": "object",
            "properties": {
                "enabled": {"type": "boolean"},
                "stage1": {
                    "type": "object",
                    "properties": {
                        "text_similarity_threshold": {"type": "number", "minimum": 0, "maximum": 1},
                        "top_k": {"type": "integer", "minimum": 1, "maximum": 1000}
                    },
                    "required": ["text_similarity_threshold", "top_k"]
                },
                "stage2": {
                    "type": "object",
                    "properties": {
                        "required_conditions": {
                            "type": "object",
                            "properties": {
                                "stem_match": {
                                    "type": "object",
                                    "properties": {
                                        "enabled": {"type": "boolean"},
                                        "max_edit_distance": {"type": "integer", "minimum": 0}
                                    },
                                    "required": ["enabled"]
                                },
                                "options_match": {
                                    "type": "object",
                                    "properties": {
                                        "enabled": {"type": "boolean"},
                                        "order_independent": {"type": "boolean"}
                                    },
                                    "required": ["enabled"]
                                },
                                "question_type_match": {
                                    "type": "object",
                                    "properties": {
                                        "enabled": {"type": "boolean"}
                                    },
                                    "required": ["enabled"]
                                }
                            }
                        },
                        "optional_conditions": {
                            "type": "object",
                            "properties": {
                                "formula_match": {
                                    "type": "object",
                                    "properties": {
                                        "enabled": {"type": "boolean"},
                                        "weight": {"type": "number", "minimum": 0, "maximum": 1}
                                    },
                                    "required": ["enabled"]
                                },
                                "visual_similarity": {
                                    "type": "object",
                                    "properties": {
                                        "enabled": {"type": "boolean"},
                                        "weight": {"type": "number", "minimum": 0, "maximum": 1}
                                    },
                                    "required": ["enabled"]
                                }
                            }
                        }
                    }
                },
                "scoring": {
                    "type": "object",
                    "properties": {
                        "method": {"type": "string", "enum": ["weighted_sum"]},
                        "required_weight": {"type": "number", "minimum": 0, "maximum": 1},
                        "optional_weight": {"type": "number", "minimum": 0, "maximum": 1},
                        "threshold": {"type": "number", "minimum": 0, "maximum": 1}
                    },
                    "required": ["method", "threshold"]
                }
            },
            "required": ["enabled"]
        },
        "output": {
            "type": "object",
            "properties": {
                "top_k": {"type": "integer", "minimum": 1, "maximum": 100},
                "grouping": {
                    "type": "object",
                    "properties": {
                        "by_match_type": {"type": "boolean"}
                    }
                },
                "include_details": {
                    "type": "object",
                    "properties": {
                        "feature_scores": {"type": "boolean"},
                        "debug_info": {"type": "boolean"}
                    }
                }
            }
        }
    }
}


class ConfigValidator:
    """Validates configuration against JSON schemas."""

    def __init__(self):
        """Initialize validator with schemas."""
        try:
            import jsonschema
            self.jsonschema = jsonschema
            self.has_jsonschema = True
        except ImportError:
            self.has_jsonschema = False

    def validate_features(self, config: Dict[str, Any]) -> List[str]:
        """Validate features configuration.

        Args:
            config: Features configuration dictionary

        Returns:
            List of validation error messages (empty if valid)
        """
        return self._validate(config, FEATURES_SCHEMA)

    def validate_matching(self, config: Dict[str, Any]) -> List[str]:
        """Validate matching configuration.

        Args:
            config: Matching configuration dictionary

        Returns:
            List of validation error messages (empty if valid)
        """
        return self._validate(config, MATCHING_SCHEMA)

    def _validate(self, config: Dict[str, Any], schema: Dict[str, Any]) -> List[str]:
        """Validate configuration against schema.

        Args:
            config: Configuration to validate
            schema: JSON schema

        Returns:
            List of validation error messages
        """
        if not self.has_jsonschema:
            # Fallback: basic type checking
            return self._basic_validate(config, schema)

        errors = []
        validator = self.jsonschema.Draft7Validator(schema)

        for error in validator.iter_errors(config):
            # Format error message with path
            path = ".".join(str(p) for p in error.path) if error.path else "root"
            errors.append(f"{path}: {error.message}")

        return errors

    def _basic_validate(self, config: Dict[str, Any], schema: Dict[str, Any]) -> List[str]:
        """Basic validation without jsonschema library.

        Args:
            config: Configuration to validate
            schema: JSON schema

        Returns:
            List of validation error messages
        """
        errors = []

        # Check if config is a dict
        if schema.get("type") == "object" and not isinstance(config, dict):
            errors.append(f"Expected object, got {type(config).__name__}")
            return errors

        # Check required properties
        required = schema.get("required", [])
        for prop in required:
            if prop not in config:
                errors.append(f"Missing required property: {prop}")

        # Validate properties
        properties = schema.get("properties", {})
        for key, value in config.items():
            if key in properties:
                prop_schema = properties[key]
                prop_type = prop_schema.get("type")

                # Type checking
                if prop_type == "object" and not isinstance(value, dict):
                    errors.append(f"{key}: Expected object, got {type(value).__name__}")
                elif prop_type == "array" and not isinstance(value, list):
                    errors.append(f"{key}: Expected array, got {type(value).__name__}")
                elif prop_type == "string" and not isinstance(value, str):
                    errors.append(f"{key}: Expected string, got {type(value).__name__}")
                elif prop_type == "number" and not isinstance(value, (int, float)):
                    errors.append(f"{key}: Expected number, got {type(value).__name__}")
                elif prop_type == "integer" and not isinstance(value, int):
                    errors.append(f"{key}: Expected integer, got {type(value).__name__}")
                elif prop_type == "boolean" and not isinstance(value, bool):
                    errors.append(f"{key}: Expected boolean, got {type(value).__name__}")

                # Range checking for numbers
                if prop_type in ("number", "integer") and isinstance(value, (int, float)):
                    minimum = prop_schema.get("minimum")
                    maximum = prop_schema.get("maximum")
                    if minimum is not None and value < minimum:
                        errors.append(f"{key}: Value {value} is less than minimum {minimum}")
                    if maximum is not None and value > maximum:
                        errors.append(f"{key}: Value {value} is greater than maximum {maximum}")

        return errors
