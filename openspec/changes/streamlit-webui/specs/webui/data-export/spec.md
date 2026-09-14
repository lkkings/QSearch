## Purpose

Enables users to export annotation data and search statistics in multiple formats (JSONL, CSV, Excel) for analysis, reporting, and integration with external tools.

## ADDED Requirements

### Requirement: Export to JSONL format

The system SHALL export annotation data in JSONL format with one query per line.

#### Scenario: JSONL structure
- **WHEN** user exports to JSONL
- **THEN** each line contains complete query record with nested candidate results as JSON object

#### Scenario: JSONL includes all fields
- **WHEN** exporting to JSONL
- **THEN** each query includes query_id, query_image, timestamp, processing_time, and array of candidates with labels

#### Scenario: UTF-8 encoding
- **WHEN** exporting JSONL with non-ASCII characters
- **THEN** system uses UTF-8 encoding to preserve all characters

### Requirement: Export to CSV format

The system SHALL export annotation data in flattened CSV format.

#### Scenario: CSV flattened structure
- **WHEN** user exports to CSV
- **THEN** each row represents one candidate result with denormalized query information

#### Scenario: CSV column headers
- **WHEN** generating CSV
- **THEN** file includes headers: query_id, query_image, query_time, rank, candidate_image, match_type, confidence, label, labeled_at

#### Scenario: CSV comma handling
- **WHEN** data contains commas or quotes
- **THEN** system properly escapes values according to CSV standard

#### Scenario: UTF-8 BOM for Excel
- **WHEN** exporting CSV
- **THEN** system includes UTF-8 BOM to ensure Excel displays characters correctly

### Requirement: Export to Excel format

The system SHALL export annotation data as multi-sheet Excel workbook.

#### Scenario: Excel multiple sheets
- **WHEN** user exports to Excel
- **THEN** system creates workbook with three sheets: Queries, Candidates, and Statistics

#### Scenario: Queries sheet structure
- **WHEN** generating Queries sheet
- **THEN** sheet contains one row per query with query_id, image path, status, processing time

#### Scenario: Candidates sheet structure
- **WHEN** generating Candidates sheet
- **THEN** sheet contains one row per candidate with query_id, rank, candidate image, scores, and label

#### Scenario: Statistics sheet structure
- **WHEN** generating Statistics sheet
- **THEN** sheet contains summary metrics: total queries, hit rate, labeled counts, per-match-type breakdown

#### Scenario: Excel formatting
- **WHEN** creating Excel file
- **THEN** system applies column auto-width and freezes header row for readability

### Requirement: Configurable export scope

The system SHALL allow users to filter what data is included in the export.

#### Scenario: Export all data
- **WHEN** user selects "Export All" option
- **THEN** system includes all queries and candidates regardless of label status

#### Scenario: Export labeled only
- **WHEN** user selects "Labeled Only" filter
- **THEN** system includes only queries with at least one labeled candidate

#### Scenario: Export completed only
- **WHEN** user selects "Completed Queries" filter
- **THEN** system includes only queries where all candidates are labeled

#### Scenario: Export date range
- **WHEN** user specifies date range
- **THEN** system includes only queries within that time period

#### Scenario: Export specific database
- **WHEN** exporting from database management page
- **THEN** system exports only data for that specific database

### Requirement: Export metadata inclusion

The system SHALL include database and export metadata in exported files.

#### Scenario: Database information
- **WHEN** exporting data
- **THEN** system includes database name, creation date, and configuration preset in metadata

#### Scenario: Export timestamp
- **WHEN** generating export file
- **THEN** system includes export timestamp in metadata or filename

#### Scenario: Statistics summary
- **WHEN** exporting
- **THEN** system includes aggregate statistics: total queries, hit rate, labeled counts

### Requirement: Export file naming

The system SHALL generate descriptive filenames for exported files.

#### Scenario: Default filename format
- **WHEN** system generates export filename
- **THEN** format is "annotations_<database>_<timestamp>.<ext>" where timestamp is YYYYMMDD_HHMMSS

#### Scenario: User custom filename
- **WHEN** user provides custom filename
- **THEN** system uses that name while preserving correct file extension

#### Scenario: Filename sanitization
- **WHEN** filename contains invalid characters
- **THEN** system replaces them with underscores

### Requirement: Export progress indication

The system SHALL show progress for large exports.

#### Scenario: Display export progress
- **WHEN** exporting large dataset (>1000 queries)
- **THEN** system displays progress bar with percentage complete

#### Scenario: Small export immediate
- **WHEN** exporting small dataset (<100 queries)
- **THEN** system generates file immediately without progress indicator

### Requirement: Export download handling

The system SHALL provide download mechanism for generated export files.

#### Scenario: Download button
- **WHEN** export completes
- **THEN** system displays download button and automatically triggers browser download

#### Scenario: Multiple format generation
- **WHEN** user requests exports in multiple formats
- **THEN** system generates all requested formats and provides separate download links

### Requirement: Export error handling

The system SHALL handle export failures gracefully.

#### Scenario: Handle write errors
- **WHEN** export fails due to disk space or permission issues
- **THEN** system displays error message explaining the failure

#### Scenario: Handle data errors
- **WHEN** database contains corrupted records
- **THEN** system skips invalid records, logs warnings, and completes export with valid data

#### Scenario: Partial export on interruption
- **WHEN** export is interrupted
- **THEN** system does not create partial file and displays error message

### Requirement: Export data validation

The system SHALL validate exported data integrity.

#### Scenario: Verify record counts
- **WHEN** export completes
- **THEN** system verifies number of records written matches query count

#### Scenario: Validate JSON structure
- **WHEN** exporting JSONL
- **THEN** system ensures each line is valid JSON object

#### Scenario: Check file size
- **WHEN** export completes
- **THEN** system verifies output file is not empty and has expected minimum size
