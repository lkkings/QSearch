## Purpose

Enables users to manually label search results as hits or misses to evaluate matching quality, track annotation progress, and export labeled data for analysis.

## ADDED Requirements

### Requirement: Binary labeling of candidates

The system SHALL allow users to label each candidate result as either hit or miss.

#### Scenario: Label candidate as hit
- **WHEN** user clicks "Hit" button on a candidate result
- **THEN** system records the label as "hit" with timestamp and updates database

#### Scenario: Label candidate as miss
- **WHEN** user clicks "Miss" button on a candidate result
- **THEN** system records the label as "miss" with timestamp and updates database

#### Scenario: Label remains persistent
- **WHEN** user labels a candidate and navigates away
- **THEN** system preserves the label when user returns to view the same result

### Requirement: Keyboard shortcut support

The system SHALL provide keyboard shortcuts for rapid annotation workflow.

#### Scenario: Hit shortcut
- **WHEN** user presses "1" key
- **THEN** system labels current candidate as hit and advances to next candidate

#### Scenario: Miss shortcut
- **WHEN** user presses "0" key
- **THEN** system labels current candidate as miss and advances to next candidate

#### Scenario: Navigation shortcuts
- **WHEN** user presses arrow down or right arrow key
- **THEN** system advances to next candidate without labeling

#### Scenario: Previous candidate shortcut
- **WHEN** user presses arrow up or left arrow key
- **THEN** system goes back to previous candidate

#### Scenario: Next query shortcut
- **WHEN** user presses Enter key
- **THEN** system saves current labels and advances to next query in queue

### Requirement: Display annotation status

The system SHALL clearly indicate which candidates are labeled and which are unlabeled.

#### Scenario: Visual status indicators
- **WHEN** viewing candidate results
- **THEN** system displays checkmark icon for hit, cross icon for miss, and clock icon for unlabeled

#### Scenario: Auto-expand unlabeled
- **WHEN** displaying candidate list
- **THEN** system automatically expands unlabeled candidates and collapses labeled ones

#### Scenario: Show label timestamp
- **WHEN** candidate is labeled
- **THEN** system displays when the label was recorded

### Requirement: Modify existing labels

The system SHALL allow users to change labels after initial annotation.

#### Scenario: Change label
- **WHEN** user clicks "Modify Label" on a labeled candidate
- **THEN** system displays labeling buttons and allows relabeling

#### Scenario: Overwrite previous label
- **WHEN** user applies new label to previously labeled candidate
- **THEN** system replaces old label with new one and updates timestamp

### Requirement: Track annotation progress per query

The system SHALL track completion status for each query based on its candidate labels.

#### Scenario: Query status unlabeled
- **WHEN** none of the query's candidates are labeled
- **THEN** system marks query status as "unlabeled"

#### Scenario: Query status partial
- **WHEN** some but not all candidates are labeled
- **THEN** system marks query status as "partial"

#### Scenario: Query status completed
- **WHEN** all candidates are labeled
- **THEN** system marks query status as "completed" and updates last_labeled_at timestamp

### Requirement: Annotation queue navigation

The system SHALL provide navigation controls for moving through multiple queries.

#### Scenario: Next query navigation
- **WHEN** user clicks "Next" or presses Enter
- **THEN** system saves current labels and displays next query with its candidates

#### Scenario: Previous query navigation
- **WHEN** user clicks "Previous"
- **THEN** system navigates to previous query in the queue

#### Scenario: Jump to specific query
- **WHEN** user selects "Jump to Query #N"
- **THEN** system navigates directly to that query

#### Scenario: Skip to unlabeled
- **WHEN** user clicks "Skip to Next Unlabeled"
- **THEN** system finds and navigates to next query with unlabeled status

### Requirement: Display overall annotation progress

The system SHALL show aggregate progress across all queries in the current batch.

#### Scenario: Progress bar display
- **WHEN** user is in annotation mode
- **THEN** system displays progress bar showing percentage of labeled queries

#### Scenario: Progress counts
- **WHEN** viewing annotation interface
- **THEN** system displays "X / Y queries labeled" where X is completed count and Y is total

#### Scenario: Update progress in real-time
- **WHEN** user labels candidates and changes query status
- **THEN** system immediately updates progress indicators without page refresh

### Requirement: Database-level annotation statistics

The system SHALL maintain aggregate statistics for each database.

#### Scenario: Track hit and miss counts
- **WHEN** users label candidates
- **THEN** system increments total_hits or total_misses counters in database metadata

#### Scenario: Calculate hit rate
- **WHEN** database has labeled candidates
- **THEN** system calculates hit_rate as hits / (hits + misses) and displays as percentage

#### Scenario: Track query counts
- **WHEN** queries are performed and labeled
- **THEN** system maintains total_queries, labeled_queries, and unlabeled_queries counts

### Requirement: Handle duplicate query results

The system SHALL overwrite previous annotations when the same query is searched multiple times.

#### Scenario: Overwrite previous results
- **WHEN** user searches the same query image that was previously annotated
- **THEN** system replaces old query record and candidates with new search results

#### Scenario: Archive old annotations
- **WHEN** query is re-searched
- **THEN** system deletes previous annotation records for that query image from database

#### Scenario: Update statistics after overwrite
- **WHEN** old annotations are replaced
- **THEN** system recalculates database statistics to reflect only current annotations

### Requirement: Optional annotation notes

The system SHALL allow users to add optional text notes to candidate labels.

#### Scenario: Add note during labeling
- **WHEN** user enters text in notes field and labels candidate
- **THEN** system stores note along with label

#### Scenario: View existing notes
- **WHEN** candidate has associated note
- **THEN** system displays the note text below the label status

#### Scenario: Empty notes are allowed
- **WHEN** user labels candidate without entering note
- **THEN** system stores label with NULL note field
