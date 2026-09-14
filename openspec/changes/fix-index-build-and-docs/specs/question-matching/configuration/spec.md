## Purpose

Defines the configuration schema for question matching, including exact match criteria, content match parameters, and output formatting.

## MODIFIED Requirements

### Requirement: Configuration schema reflects implemented fields

The configuration documentation SHALL accurately describe only the fields that are actually read and used by the matching implementation.

#### Scenario: Documenting content match structure

- **WHEN** documentation describes `content_match` configuration
- **THEN** it includes `stage1` (vector retrieval parameters)
- **AND** it includes `optional_conditions` (formula_match, visual_similarity) as direct children of `content_match`
- **AND** it does NOT reference `stage2` as a container
- **AND** it does NOT reference `required_conditions`
- **AND** it does NOT reference `stem_match`, `options_match`, or `question_type_match`

#### Scenario: Documenting scoring parameters

- **WHEN** documentation describes scoring configuration
- **THEN** it includes `method` and `threshold`
- **AND** it does NOT reference `required_weight` or `optional_weight`
- **AND** it accurately describes the actual scoring formula: `0.7 * vector_similarity + 0.3 * text_similarity`

#### Scenario: User reads preset documentation

- **WHEN** user reads preset comparison in `config/presets/README.md`
- **THEN** documentation shows only parameters that affect behavior
- **AND** does NOT list removed Stage 2 required_conditions parameters
- **AND** accurately reflects the three presets (conservative, balanced, aggressive)

### Requirement: Removed field warnings eliminated

Documentation SHALL NOT instruct users to configure fields that no longer exist in the schema.

#### Scenario: Missing weight configuration warnings

- **WHEN** documentation previously warned about `required_weight` / `optional_weight` normalization
- **THEN** those warnings are removed from README.md
- **AND** no instructions tell users to "set required_weight to 1.0"
- **AND** no warnings claim results will be empty due to weight misconfiguration

#### Scenario: Removed condition fields

- **WHEN** documentation previously described `stem_match.max_edit_distance`
- **THEN** that parameter is removed from README.md
- **AND** troubleshooting sections do NOT suggest adjusting it
- **AND** preset comparison tables do NOT list it
