## Purpose

Enables users to create, browse, and manage multiple question image databases with different configurations through a web interface, eliminating the need for command-line operations.

## ADDED Requirements

### Requirement: Create database from image sources

The system SHALL allow users to create a new question database by providing images through folder paths, file lists, or ZIP archives.

#### Scenario: Create database from folder
- **WHEN** user provides a folder path containing images and specifies a database name
- **THEN** system recursively scans the folder for supported image formats (jpg, jpeg, png, bmp), builds the index, and creates the database

#### Scenario: Create database from file list
- **WHEN** user uploads a text file containing one image path per line
- **THEN** system reads all paths, validates they exist, builds the index from those images

#### Scenario: Create database from ZIP archive
- **WHEN** user uploads a ZIP file containing images
- **THEN** system extracts images to temporary location, builds the index, and stores the database

#### Scenario: Reject invalid database name
- **WHEN** user provides a database name with invalid characters or that already exists
- **THEN** system displays error message and does not create the database

### Requirement: Configure database parameters

The system SHALL allow users to configure feature extraction and matching parameters when creating a database.

#### Scenario: Use preset configuration
- **WHEN** user selects a preset (conservative, balanced, or aggressive)
- **THEN** system applies the corresponding parameter set from presets.py

#### Scenario: Use custom configuration
- **WHEN** user provides a custom YAML configuration file
- **THEN** system validates the configuration against schema and uses it for index building

#### Scenario: Display default values
- **WHEN** user is creating a database
- **THEN** system pre-fills the configuration form with balanced preset defaults

### Requirement: List existing databases

The system SHALL display all existing databases with their metadata and statistics.

#### Scenario: Display database list
- **WHEN** user navigates to database management page
- **THEN** system displays each database with name, image count, creation date, and configuration preset

#### Scenario: Display annotation statistics
- **WHEN** database has annotation data
- **THEN** system displays total queries, labeled/unlabeled counts, hit count, miss count, and hit rate percentage

#### Scenario: Empty database list
- **WHEN** no databases exist
- **THEN** system displays message prompting user to create their first database

### Requirement: View database details

The system SHALL allow users to view detailed information about a specific database.

#### Scenario: View database metadata
- **WHEN** user clicks on database details
- **THEN** system displays full metadata including source path, index statistics, and complete configuration

#### Scenario: View index statistics
- **WHEN** viewing database details
- **THEN** system displays number of images indexed, extraction success rate, vector dimensions, and hash index size

### Requirement: Delete database

The system SHALL allow users to delete a database and all its associated data.

#### Scenario: Delete database with confirmation
- **WHEN** user clicks delete and confirms the action
- **THEN** system removes the database directory including index files and annotation database

#### Scenario: Cancel deletion
- **WHEN** user clicks delete but cancels the confirmation
- **THEN** system does not delete the database and returns to the list

### Requirement: Database name uniqueness

The system SHALL enforce unique database names within the application.

#### Scenario: Reject duplicate name
- **WHEN** user attempts to create a database with a name that already exists
- **THEN** system displays error message and does not create the database

#### Scenario: Accept unique name
- **WHEN** user provides a name that does not exist
- **THEN** system allows database creation to proceed
