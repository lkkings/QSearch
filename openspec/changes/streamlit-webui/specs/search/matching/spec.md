## Purpose

Exposes runtime configuration of Top-N result count to enable WebUI dynamic adjustment while preserving existing matching logic and scoring.

## MODIFIED Requirements

### Requirement: Configurable result count

The system SHALL accept runtime Top-N parameter to control number of results returned per query.

#### Scenario: Override Top-N at runtime
- **WHEN** caller provides top_n parameter to match() method
- **THEN** system returns up to that many results instead of config default

#### Scenario: Use config default when not specified
- **WHEN** caller does not provide top_n parameter
- **THEN** system uses output.top_k value from loaded configuration

#### Scenario: Enforce maximum limit
- **WHEN** caller requests Top-N greater than 20
- **THEN** system clamps value to 20 and proceeds with search

#### Scenario: Enforce minimum limit
- **WHEN** caller requests Top-N less than 1
- **THEN** system clamps value to 1 and proceeds with search

#### Scenario: Return fewer when database smaller
- **WHEN** database contains fewer images than requested Top-N
- **THEN** system returns all available matches without error

### Requirement: Preserve scoring consistency

The matching logic and score calculation SHALL remain unchanged when Top-N is overridden.

#### Scenario: Same scores regardless of Top-N
- **WHEN** same query is run with different Top-N values
- **THEN** common results appear with identical confidence scores in both result sets

#### Scenario: Exact match unaffected
- **WHEN** Top-N is overridden
- **THEN** exact matching logic and hamming distance calculations remain unchanged

#### Scenario: Content match unaffected
- **WHEN** Top-N is overridden
- **THEN** vector similarity, text similarity, and final score calculations remain unchanged
