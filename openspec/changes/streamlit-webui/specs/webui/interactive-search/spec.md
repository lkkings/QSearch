## Purpose

Enables users to perform visual similarity searches on question images through a web interface, supporting both single-image and batch search modes with configurable result counts.

## ADDED Requirements

### Requirement: Single-image search via upload

The system SHALL allow users to search by uploading an image file through the web interface.

#### Scenario: Upload and search valid image
- **WHEN** user uploads a supported image file (jpg, jpeg, png, bmp) and clicks search
- **THEN** system processes the image, performs the search, and displays Top-N matching results

#### Scenario: Reject invalid file type
- **WHEN** user uploads a non-image file
- **THEN** system displays error message and does not perform search

#### Scenario: Reject oversized file
- **WHEN** user uploads an image larger than maximum allowed size
- **THEN** system displays error message indicating size limit

### Requirement: Single-image search via path

The system SHALL allow users to search by providing a local file path to an image.

#### Scenario: Search with valid local path
- **WHEN** user enters a valid local file path and clicks search
- **THEN** system reads the image from disk and performs the search

#### Scenario: Handle non-existent path
- **WHEN** user enters a path that does not exist
- **THEN** system displays error message indicating file not found

### Requirement: Single-image search via URL

The system SHALL allow users to search by providing an image URL.

#### Scenario: Search with valid URL
- **WHEN** user enters a valid image URL and clicks search
- **THEN** system downloads the image and performs the search

#### Scenario: Handle invalid URL
- **WHEN** user enters an invalid or unreachable URL
- **THEN** system displays error message indicating URL cannot be accessed

#### Scenario: Handle download timeout
- **WHEN** image download exceeds timeout limit
- **THEN** system cancels the download and displays timeout error

### Requirement: Batch search from folder

The system SHALL allow users to search multiple images from a folder path.

#### Scenario: Create batch search task
- **WHEN** user provides a folder path containing query images and clicks start batch search
- **THEN** system creates an async task, scans folder recursively for images, and begins processing

#### Scenario: Empty folder handling
- **WHEN** user provides a folder with no supported images
- **THEN** system displays error message indicating no valid images found

### Requirement: Batch search from file list

The system SHALL allow users to search multiple images by providing a file list.

#### Scenario: Process file list
- **WHEN** user uploads a text file with one image path per line
- **THEN** system creates async task and processes each valid path

#### Scenario: Skip invalid entries
- **WHEN** file list contains invalid or non-existent paths
- **THEN** system skips those entries, logs them as failed, and continues with valid paths

### Requirement: Configurable Top-N results

The system SHALL allow users to configure the number of top matching results returned per query.

#### Scenario: Set Top-N value
- **WHEN** user selects a Top-N value between 1 and 20
- **THEN** system returns exactly that many results per query (or fewer if database is smaller)

#### Scenario: Default Top-N value
- **WHEN** user does not specify Top-N
- **THEN** system defaults to 10 results per query

#### Scenario: Enforce maximum limit
- **WHEN** user attempts to set Top-N above 20
- **THEN** system rejects the value and displays error message

### Requirement: Visual result display

The system SHALL display both query images and matching candidate images with detailed information.

#### Scenario: Display query image
- **WHEN** search completes
- **THEN** system displays query image with filename and processing time

#### Scenario: Display candidate results
- **WHEN** search returns matches
- **THEN** system displays each candidate image with rank number, match type, confidence score, confidence level, and image path

#### Scenario: Display no matches
- **WHEN** search returns zero matches
- **THEN** system displays message indicating no matches found

### Requirement: Display matching details

The system SHALL display detailed matching information for each candidate result.

#### Scenario: Exact match details
- **WHEN** candidate is an exact match
- **THEN** system displays match type as EXACT_MATCH, hamming distance, and confidence score

#### Scenario: Content match details
- **WHEN** candidate is a content match
- **THEN** system displays match type as CONTENT_MATCH, vector similarity, text similarity, and final score

#### Scenario: Confidence level indication
- **WHEN** displaying any match
- **THEN** system shows confidence level as HIGH (≥0.9), MEDIUM (≥0.8), or LOW (<0.8)

### Requirement: Use database default configuration

The system SHALL use the database's stored matching configuration by default.

#### Scenario: Apply default configuration
- **WHEN** user performs search without specifying configuration
- **THEN** system uses the configuration stored in database metadata

#### Scenario: Configuration consistency
- **WHEN** database was created with specific preset or custom config
- **THEN** searches use the same configuration to ensure result consistency

### Requirement: Temporary configuration override

The system SHALL allow users to temporarily override matching configuration for experimental searches.

#### Scenario: Override with different preset
- **WHEN** user selects "temporary override" and chooses a different preset
- **THEN** system performs search with the selected preset but does not modify database metadata

#### Scenario: Override with custom parameters
- **WHEN** user provides custom matching parameters for current search
- **THEN** system uses those parameters only for this search session

#### Scenario: Return to default
- **WHEN** user clears temporary override
- **THEN** subsequent searches revert to database default configuration
