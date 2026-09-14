"""Configuration presets for common matching scenarios.

Provides predefined configurations optimized for different precision/recall trade-offs.
"""

from typing import Dict, Any


# Conservative preset: High precision, strict thresholds
CONSERVATIVE_PRESET = {
    "name": "conservative",
    "description": "High precision configuration with strict matching thresholds (>99% precision target)",
    "matching": {
        "exact_match": {
            "enabled": True,
            "criteria": {
                "perceptual_hash": {
                    "max_distance": 3  # Very strict
                }
            }
        },
        "content_match": {
            "enabled": True,
            "stage1": {
                "text_similarity_threshold": 0.85,
                "top_k": 50  # Fewer candidates
            },
            "optional_conditions": {
                "visual_similarity": {
                    "enabled": True,
                    "weight": 0.05
                }
            },
            "scoring": {
                "method": "weighted_sum",
                "threshold": 0.90  # High threshold
            }
        },
        "output": {
            "top_k": 5,
            "grouping": {
                "by_match_type": True
            },
            "include_details": {
                "feature_scores": True,
                "debug_info": False
            }
        }
    }
}


# Balanced preset: Moderate precision/recall balance
BALANCED_PRESET = {
    "name": "balanced",
    "description": "Balanced configuration with moderate thresholds (precision/recall trade-off)",
    "matching": {
        "exact_match": {
            "enabled": True,
            "criteria": {
                "perceptual_hash": {
                    "max_distance": 5  # Default
                }
            }
        },
        "content_match": {
            "enabled": True,
            "stage1": {
                "text_similarity_threshold": 0.75,
                "top_k": 100  # Standard candidate count
            },
            "optional_conditions": {
                "visual_similarity": {
                    "enabled": True,
                    "weight": 0.05
                }
            },
            "scoring": {
                "method": "weighted_sum",
                "threshold": 0.85  # Moderate threshold
            }
        },
        "output": {
            "top_k": 10,
            "grouping": {
                "by_match_type": True
            },
            "include_details": {
                "feature_scores": True,
                "debug_info": False
            }
        }
    }
}


# Aggressive preset: High recall, loose thresholds
AGGRESSIVE_PRESET = {
    "name": "aggressive",
    "description": "High recall configuration with loose matching thresholds (capture borderline cases)",
    "matching": {
        "exact_match": {
            "enabled": True,
            "criteria": {
                "perceptual_hash": {
                    "max_distance": 8  # More lenient
                }
            }
        },
        "content_match": {
            "enabled": True,
            "stage1": {
                "text_similarity_threshold": 0.65,
                "top_k": 200  # More candidates
            },
            "optional_conditions": {
                "visual_similarity": {
                    "enabled": True,
                    "weight": 0.10
                }
            },
            "scoring": {
                "method": "weighted_sum",
                "threshold": 0.75  # Lower threshold
            }
        },
        "output": {
            "top_k": 20,
            "grouping": {
                "by_match_type": True
            },
            "include_details": {
                "feature_scores": True,
                "debug_info": True
            }
        }
    }
}


# Registry of all presets
PRESETS = {
    "conservative": CONSERVATIVE_PRESET,
    "balanced": BALANCED_PRESET,
    "aggressive": AGGRESSIVE_PRESET
}


def get_preset(name: str) -> Dict[str, Any]:
    """Get configuration preset by name.

    Args:
        name: Preset name (conservative, balanced, aggressive)

    Returns:
        Configuration dictionary

    Raises:
        ValueError: If preset name is not recognized
    """
    if name not in PRESETS:
        available = ", ".join(PRESETS.keys())
        raise ValueError(f"Unknown preset '{name}'. Available presets: {available}")

    return PRESETS[name].copy()


def list_presets() -> Dict[str, str]:
    """List all available presets with descriptions.

    Returns:
        Dictionary mapping preset names to descriptions
    """
    return {
        name: config["description"]
        for name, config in PRESETS.items()
    }
