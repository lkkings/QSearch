## Purpose

Provides two distinct search paths for matching questions: exact match for finding the same photograph taken from different angles, and content match for finding different images containing identical question content.

## ADDED Requirements

### Requirement: Exact match detection via perceptual hash

The system SHALL identify exact matches based on perceptual hash distance to find the same photograph regardless of minor variations.

#### Scenario: Find identical photograph with minor differences

- **WHEN** query image is the same photograph as database image with slight lighting or angle changes
- **THEN** system returns match with type "EXACT_MATCH" when hash distance is below threshold (default ≤5)

#### Scenario: Reject visually different images

- **WHEN** query image and database image are different photographs even if containing same question
- **THEN** system does not return exact match when hash distance exceeds threshold

#### Scenario: Apply configurable hash distance threshold

- **WHEN** configuration sets max hash distance to 8 instead of default 5
- **THEN** system allows more lenient exact matching using the configured threshold

#### Scenario: Compute exact match confidence score

- **WHEN** exact match is found with hash distance 3
- **THEN** system returns confidence score normalized from distance (e.g., 1.0 - 3/256 = 0.988)

### Requirement: Content match detection via text similarity

The system SHALL identify content matches based on question text comparison to find same question in different images.

#### Scenario: Match question with same stem and options in different order

- **WHEN** query question has stem "What is 2+2?" with options [A: 3, B: 4, C: 5] and database has same stem with options [B: 4, A: 3, C: 5]
- **THEN** system returns content match since option set is identical (order-independent)

#### Scenario: Reject question with same stem but different options

- **WHEN** query question has stem "What is 2+2?" with options [A: 3, B: 4] and database has same stem with options [A: 5, B: 4]
- **THEN** system does not return content match since option sets differ

#### Scenario: Apply edit distance threshold for stem matching

- **WHEN** query stem differs from database stem by 2 characters (typo or OCR error) and threshold is 3
- **THEN** system considers stems matching and continues to option comparison

#### Scenario: Enforce required conditions for content match

- **WHEN** stem matches and options match but question types differ (multiple choice vs fill-in-blank)
- **THEN** system does not return content match since all required conditions must pass

#### Scenario: Compute content match confidence score

- **WHEN** content match passes all required checks and optional visual similarity is 0.75
- **THEN** system returns weighted confidence combining required (1.0) and optional (0.75) scores

### Requirement: Two-stage retrieval for content matching

The system SHALL use vector similarity search for candidate retrieval followed by detailed text matching for precision.

#### Scenario: Retrieve candidates via text vector search

- **WHEN** searching for content matches with top_k configured to 100
- **THEN** system retrieves top 100 candidates from Faiss index based on stem text vector similarity

#### Scenario: Filter candidates with detailed matching

- **WHEN** 100 candidates are retrieved and 15 pass stem edit distance check
- **THEN** system applies option matching to the 15 candidates and returns only those passing all criteria

#### Scenario: Apply vector similarity threshold

- **WHEN** configuration sets stage1_text_similarity threshold to 0.75
- **THEN** system only retrieves candidates with cosine similarity ≥0.75

#### Scenario: Handle no candidates passing initial retrieval

- **WHEN** vector search returns no candidates above similarity threshold
- **THEN** system returns empty content match list without proceeding to detailed matching

### Requirement: Return both match types simultaneously

The system SHALL return both exact matches and content matches in a structured response with clear type labeling.

#### Scenario: Return results grouped by match type

- **WHEN** query matches 2 database images exactly and 3 images by content
- **THEN** system returns object with exact_matches array (length 2) and content_matches array (length 3)

#### Scenario: Mark dual matches

- **WHEN** database image appears in both exact matches and content matches
- **THEN** system includes also_exact_match flag in content match entry

#### Scenario: Respect top-K configuration per type

- **WHEN** configuration sets top_k to 5 and query has 8 exact matches and 12 content matches
- **THEN** system returns top 5 exact matches (by score) and top 5 content matches (by score)

#### Scenario: Include detailed scoring breakdown

- **WHEN** returning any match result
- **THEN** system includes scores object with individual feature scores (e.g., stem_match: 0.95, options_match: 1.0, visual: 0.70)

### Requirement: Apply configurable matching thresholds

The system SHALL support runtime threshold adjustment for precision-recall tradeoff.

#### Scenario: Use conservative thresholds for high precision

- **WHEN** configuration uses conservative preset (stem_edit_distance: 2, final_score: 0.90)
- **THEN** system returns fewer matches with higher confidence

#### Scenario: Use aggressive thresholds for high recall

- **WHEN** configuration uses aggressive preset (stem_edit_distance: 10, final_score: 0.75)
- **THEN** system returns more matches including borderline cases

#### Scenario: Override thresholds at query time

- **WHEN** calling search with runtime override setting final_score threshold to 0.80
- **THEN** system applies 0.80 threshold for this query without changing global configuration

#### Scenario: Validate threshold ranges

- **WHEN** configuration contains invalid threshold (e.g., negative value or >1.0)
- **THEN** system raises configuration error during initialization

### Requirement: Support batch query processing

The system SHALL process multiple query images efficiently with parallel GPU execution.

#### Scenario: Batch process queries with GPU parallelization

- **WHEN** searching 200,000 queries across 8 GPUs with 7 used for feature extraction
- **THEN** system distributes queries evenly (~28,571 per GPU) and processes in parallel

#### Scenario: Aggregate batch results

- **WHEN** batch processing completes across GPUs
- **THEN** system returns aggregated results array maintaining query order with match results per query

#### Scenario: Handle batch processing errors

- **WHEN** some queries fail during batch processing (e.g., corrupted images)
- **THEN** system returns error record for failed queries while including successful results for others

### Requirement: Index management for base database

The system SHALL build and maintain Faiss indices for the 400k base question database.

#### Scenario: Build text vector index for 400k images

- **WHEN** initializing system with 400k base images
- **THEN** system extracts text features, encodes to vectors, and builds Faiss IndexFlatIP

#### Scenario: Build image hash index

- **WHEN** initializing system with base images
- **THEN** system computes perceptual hashes and stores in dictionary for O(1) lookup

#### Scenario: Support incremental index updates

- **WHEN** adding new base images to existing index
- **THEN** system appends vectors to Faiss index and updates hash dictionary without rebuilding

#### Scenario: Persist and load indices

- **WHEN** system shuts down after building indices
- **THEN** system saves indices to disk and loads them on restart without recomputation

### Requirement: Return match metadata and diagnostics

The system SHALL include sufficient detail in results for validation and debugging.

#### Scenario: Include processing time

- **WHEN** query completes
- **THEN** system includes processing_time_ms in response showing total elapsed time

#### Scenario: Include verification status per stage

- **WHEN** content match passes all checks
- **THEN** system includes verification_passed array listing which stages succeeded (e.g., ["stage1_vector", "stage2_stem", "stage2_options"])

#### Scenario: Return confidence levels

- **WHEN** match has final score 0.93
- **THEN** system includes confidence_level label (HIGH for ≥0.9, MEDIUM for 0.8-0.9, LOW for <0.8)

#### Scenario: Include matched image identifiers

- **WHEN** returning match result
- **THEN** system includes both database image ID and file path for retrieval
