## Purpose

Provides YAML-based configuration management for feature extraction, matching rules, thresholds, and output parameters enabling flexible adaptation to different matching scenarios without code changes.

## ADDED Requirements

### Requirement: Load configuration from YAML files

The system SHALL read feature extraction and matching configuration from YAML files with schema validation.

#### Scenario: Load valid configuration file

- **WHEN** system initializes with path to valid YAML configuration file
- **THEN** system parses configuration and applies settings to all components

#### Scenario: Reject invalid configuration schema

- **WHEN** configuration file contains invalid structure (e.g., missing required fields, wrong types)
- **THEN** system raises validation error with specific field and expected type before starting

#### Scenario: Provide helpful error messages

- **WHEN** configuration contains error at line 45 with invalid threshold value
- **THEN** system error message includes file path, line number, field name, and constraint violated

#### Scenario: Support multiple configuration files

- **WHEN** system loads features_config.yaml and matching_config.yaml separately
- **THEN** system merges configurations with matching rules applied after feature settings

### Requirement: Configure feature extraction components

The system SHALL allow enabling/disabling and weighting individual feature extraction components through configuration.

#### Scenario: Enable specific text features

- **WHEN** configuration sets text.components.stem.enabled to true and text.components.options.enabled to false
- **THEN** system extracts stem but skips option extraction

#### Scenario: Configure feature weights

- **WHEN** configuration sets stem weight to 0.6 and options weight to 0.3
- **THEN** system stores these weights in extracted features for use in scoring

#### Scenario: Configure normalization rules

- **WHEN** configuration specifies normalization rules ["remove_whitespace", "sort"] for options
- **THEN** system applies rules in order during feature extraction

#### Scenario: Configure OCR engines

- **WHEN** configuration sets ocr.engine to "paddleocr" with languages ["ch", "en"]
- **THEN** system initializes PaddleOCR with Chinese and English language models

#### Scenario: Configure image feature models

- **WHEN** configuration sets image.components.deep_features.model to "efficientnet_b4"
- **THEN** system loads EfficientNet-B4 model for CNN feature extraction

### Requirement: Configure matching thresholds and rules

The system SHALL support configurable thresholds for both exact match and content match detection.

#### Scenario: Configure exact match hash distance

- **WHEN** configuration sets exact_match.criteria.perceptual_hash.max_distance to 8
- **THEN** system accepts hash distances ≤8 as exact matches

#### Scenario: Configure content match required conditions

- **WHEN** configuration enables stem_match, options_match, and question_type_match as required
- **THEN** system rejects matches failing any of these three checks

#### Scenario: Configure content match optional conditions

- **WHEN** configuration enables formula_match and visual_similarity as optional with weights 0.2 and 0.1
- **THEN** system includes these scores in final calculation but does not require them

#### Scenario: Configure scoring method

- **WHEN** configuration sets scoring.method to "weighted_sum" with required_weight 0.8 and optional_weight 0.2
- **THEN** system computes final score as 0.8 * required_score + 0.2 * optional_score

#### Scenario: Configure text matching parameters

- **WHEN** configuration sets stem_match.max_edit_distance to 5
- **THEN** system allows up to 5 character differences in stem comparison

### Requirement: Configure output parameters

The system SHALL allow configuration of result quantity, grouping, and detail level.

#### Scenario: Configure top-K results

- **WHEN** configuration sets output.top_k to 10
- **THEN** system returns at most 10 matches per type (exact and content)

#### Scenario: Configure result grouping

- **WHEN** configuration sets output.grouping.by_match_type to true
- **THEN** system returns separate arrays for exact_matches and content_matches

#### Scenario: Configure detail inclusion

- **WHEN** configuration sets output.include_details.feature_scores to true
- **THEN** system includes individual feature scores in each match result

#### Scenario: Configure debug information

- **WHEN** configuration sets output.include_details.debug_info to true
- **THEN** system includes additional diagnostic data in results (e.g., intermediate candidate counts)

### Requirement: Support configuration presets

The system SHALL provide named configuration presets for common use cases.

#### Scenario: Load conservative preset

- **WHEN** initializing with preset "conservative"
- **THEN** system applies high thresholds (stem_edit_distance: 2, final_score: 0.90) for maximum precision

#### Scenario: Load balanced preset

- **WHEN** initializing with preset "balanced"
- **THEN** system applies moderate thresholds (stem_edit_distance: 5, final_score: 0.85) balancing precision and recall

#### Scenario: Load aggressive preset

- **WHEN** initializing with preset "aggressive"
- **THEN** system applies low thresholds (stem_edit_distance: 10, final_score: 0.75) for maximum recall

#### Scenario: Override preset values

- **WHEN** loading preset "balanced" with override setting final_score to 0.80
- **THEN** system uses balanced preset values except final_score which uses override

### Requirement: Support runtime configuration overrides

The system SHALL allow temporary threshold overrides at query time without modifying stored configuration.

#### Scenario: Override threshold for single query

- **WHEN** calling search with override_config setting content_match.scoring.threshold to 0.80
- **THEN** system applies 0.80 threshold for this query only, preserving global configuration

#### Scenario: Override top-K for single query

- **WHEN** calling search with top_k parameter set to 15
- **THEN** system returns up to 15 matches for this query, preserving configured default for subsequent queries

#### Scenario: Runtime override validation

- **WHEN** runtime override contains invalid value (e.g., threshold > 1.0)
- **THEN** system raises validation error before executing query

#### Scenario: Preserve configuration state

- **WHEN** multiple queries use different runtime overrides
- **THEN** system maintains base configuration unchanged between queries

### Requirement: Validate configuration consistency

The system SHALL detect and report inconsistent or conflicting configuration settings.

#### Scenario: Detect conflicting feature dependencies

- **WHEN** configuration enables formula matching but disables formula extraction
- **THEN** system raises configuration error indicating formula_match requires formulas.enabled

#### Scenario: Detect invalid weight sum

- **WHEN** configuration sets feature weights that sum to >1.0
- **THEN** system issues warning but normalizes weights to sum to 1.0

#### Scenario: Detect missing required models

- **WHEN** configuration specifies CNN model not available in system
- **THEN** system raises initialization error listing available models

#### Scenario: Validate threshold ranges

- **WHEN** configuration contains threshold outside valid range (e.g., -0.5 or 1.5)
- **THEN** system raises validation error with field name and valid range (0.0-1.0)

### Requirement: Export current configuration

The system SHALL allow exporting active configuration to YAML format for persistence or sharing.

#### Scenario: Export configuration after runtime overrides

- **WHEN** exporting configuration after applying multiple runtime overrides
- **THEN** system exports current effective configuration including override values

#### Scenario: Export configuration with comments

- **WHEN** exporting configuration with include_comments parameter set to true
- **THEN** system includes explanatory comments for each configuration section

#### Scenario: Export minimal configuration

- **WHEN** exporting configuration with only_non_defaults parameter set to true
- **THEN** system exports only values differing from defaults, producing compact output

#### Scenario: Save configuration to file

- **WHEN** calling save_config with file path
- **THEN** system writes current configuration to specified YAML file with atomic write (temp file + rename)

### Requirement: Provide configuration schema documentation

The system SHALL expose machine-readable configuration schema for validation and tooling.

#### Scenario: Get JSON schema for configuration

- **WHEN** requesting configuration schema
- **THEN** system returns JSON schema defining all fields, types, constraints, and defaults

#### Scenario: Validate configuration against schema

- **WHEN** validating user-provided YAML against schema
- **THEN** system reports all validation errors with field paths and constraint violations

#### Scenario: Generate example configuration

- **WHEN** requesting example configuration
- **THEN** system generates valid YAML with explanatory comments for all available options

#### Scenario: List available presets

- **WHEN** requesting preset list
- **THEN** system returns names and descriptions of all built-in configuration presets

### Requirement: Support hot configuration reload

The system SHALL allow reloading configuration without restarting the system for matching rule adjustments.

#### Scenario: Reload matching configuration

- **WHEN** updating matching_config.yaml and calling reload_config
- **THEN** system applies new thresholds to subsequent queries without restarting

#### Scenario: Reject reload of feature configuration

- **WHEN** attempting to reload features_config.yaml after indices are built
- **THEN** system raises error indicating feature configuration cannot be changed after indexing

#### Scenario: Validate before applying reload

- **WHEN** reloading configuration file with validation errors
- **THEN** system rejects reload and maintains current valid configuration

#### Scenario: Notify reload completion

- **WHEN** configuration reload succeeds
- **THEN** system logs confirmation with timestamp and changed fields
