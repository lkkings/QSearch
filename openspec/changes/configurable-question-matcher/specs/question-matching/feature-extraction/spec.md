## Purpose

Extracts configurable features from question images including text content (question stem, options, formulas), visual characteristics (perceptual hashes, CNN embeddings), and metadata (question type, subject) to enable flexible matching strategies.

## ADDED Requirements

### Requirement: Extract text features from question images

The system SHALL extract structured text features from question images including question stem, multiple choice options, and mathematical formulas.

#### Scenario: Extract question stem and options

- **WHEN** processing a multiple choice question image
- **THEN** system extracts the question stem text and all options (A, B, C, D) as separate text fields

#### Scenario: Extract mathematical formulas

- **WHEN** processing a question image containing LaTeX-formatted mathematical expressions
- **THEN** system extracts formulas in LaTeX format preserving mathematical notation

#### Scenario: Handle missing text components

- **WHEN** processing a question image without detectable options
- **THEN** system extracts available text fields and marks missing components in the output

### Requirement: Extract image features from question images

The system SHALL extract visual features including perceptual hashes for exact matching and CNN-based deep features for similarity matching.

#### Scenario: Compute perceptual hash

- **WHEN** processing any question image
- **THEN** system computes a perceptual hash (dHash, pHash, or aHash based on configuration) of configurable size (default 16x16)

#### Scenario: Extract CNN deep features

- **WHEN** processing a question image with deep features enabled
- **THEN** system extracts feature vectors from specified CNN model and layer producing vectors of configured dimension (default 512)

#### Scenario: Handle corrupted images

- **WHEN** processing a corrupted or unreadable image file
- **THEN** system returns an error with image path and reason for failure

### Requirement: Extract metadata from question images

The system SHALL detect and extract metadata including question type, subject area, and difficulty level when configured.

#### Scenario: Detect question type

- **WHEN** processing a question image with question type detection enabled
- **THEN** system classifies the question as one of: multiple choice, fill-in-blank, short answer, or essay

#### Scenario: Skip disabled metadata extraction

- **WHEN** processing a question image with specific metadata extraction disabled in configuration
- **THEN** system omits that metadata field from output without error

### Requirement: Normalize extracted features

The system SHALL apply configurable normalization rules to extracted features to ensure consistent matching behavior.

#### Scenario: Normalize text whitespace and punctuation

- **WHEN** text normalization includes remove_whitespace and normalize_punctuation
- **THEN** system removes extra spaces and converts punctuation marks (e.g., Chinese comma to ASCII comma)

#### Scenario: Sort options to ignore order

- **WHEN** option normalization includes sort
- **THEN** system sorts option texts alphabetically so options [B, A, C] and [A, B, C] produce identical output

#### Scenario: Normalize LaTeX formulas

- **WHEN** formula normalization is enabled
- **THEN** system applies LaTeX standardization to make equivalent expressions match (e.g., `x^2` and `x^{2}` normalize to same form)

### Requirement: Support configurable feature selection

The system SHALL allow enabling or disabling individual feature components through YAML configuration.

#### Scenario: Extract only enabled features

- **WHEN** configuration enables text.stem but disables text.options
- **THEN** system extracts question stem but returns null for options field

#### Scenario: Assign configurable weights to features

- **WHEN** configuration assigns weight 0.6 to stem and 0.3 to options
- **THEN** system includes these weights in output feature structure

#### Scenario: Validate configuration on initialization

- **WHEN** initializing feature extractor with invalid configuration (e.g., negative weights, unknown feature names)
- **THEN** system raises configuration error before processing any images

### Requirement: Handle OCR errors gracefully

The system SHALL detect and report OCR quality issues while continuing to extract other available features.

#### Scenario: Low OCR confidence

- **WHEN** OCR returns text with confidence below threshold (default 0.5)
- **THEN** system includes low-confidence warning in output but includes the extracted text

#### Scenario: Complete OCR failure

- **WHEN** OCR fails to extract any text from image
- **THEN** system returns empty text fields with OCR failure flag set, but continues extracting image features

#### Scenario: Partial text extraction

- **WHEN** OCR successfully extracts question stem but fails on options
- **THEN** system returns stem with success status and options with failure status

### Requirement: Support batch feature extraction

The system SHALL process multiple images in batches for GPU efficiency.

#### Scenario: Batch process with GPU parallelization

- **WHEN** extracting features from 1000 images with batch size 256
- **THEN** system processes images in 4 batches utilizing GPU acceleration

#### Scenario: Handle mixed batch failures

- **WHEN** batch contains both valid and corrupted images
- **THEN** system extracts features from valid images and returns individual error records for corrupted ones

#### Scenario: Respect memory constraints

- **WHEN** batch size would exceed available GPU memory
- **THEN** system automatically reduces batch size and logs adjustment
