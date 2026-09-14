## Purpose

Enables batch search operations to run in the background without blocking the UI, with real-time progress tracking, cancellation support, and task history management.

## ADDED Requirements

### Requirement: Create batch search task

The system SHALL create a background task when user initiates a batch search.

#### Scenario: Create task with image list
- **WHEN** user provides image sources and clicks "Start Batch Search"
- **THEN** system creates task record with pending status and returns task ID immediately

#### Scenario: Store task configuration
- **WHEN** creating batch search task
- **THEN** system stores database name, image list, Top-N setting, and matching config in task record

#### Scenario: Optional task naming
- **WHEN** user provides custom task name
- **THEN** system uses that name, otherwise generates default name like "Batch Search 100 images"

### Requirement: Execute task in background

The system SHALL run batch search tasks in background processes without blocking the UI.

#### Scenario: Start background processing
- **WHEN** task is created
- **THEN** system launches background process, updates status to "running", and records start timestamp

#### Scenario: UI remains responsive
- **WHEN** task is running
- **THEN** user can navigate to other pages, start new tasks, or perform single searches

#### Scenario: Process isolation
- **WHEN** multiple tasks are running
- **THEN** each task runs in separate process and does not interfere with others

### Requirement: Track task progress

The system SHALL update task progress as images are processed.

#### Scenario: Update progress counters
- **WHEN** each query image is processed
- **THEN** system increments processed_items count and updates progress percentage

#### Scenario: Track failures
- **WHEN** query processing fails
- **THEN** system increments failed_items count but continues processing remaining images

#### Scenario: Calculate remaining items
- **WHEN** displaying progress
- **THEN** system shows "X / Y processed" where X is processed count and Y is total items

### Requirement: Display task status

The system SHALL display current status for each task.

#### Scenario: Status pending
- **WHEN** task is created but not yet started
- **THEN** system displays status as "pending"

#### Scenario: Status running
- **WHEN** task is actively processing
- **THEN** system displays status as "running" with progress bar and percentage

#### Scenario: Status completed
- **WHEN** all items are processed successfully
- **THEN** system displays status as "completed" with completion timestamp

#### Scenario: Status failed
- **WHEN** task encounters fatal error
- **THEN** system displays status as "failed" with error message

#### Scenario: Status cancelled
- **WHEN** user cancels running task
- **THEN** system displays status as "cancelled"

### Requirement: Real-time progress monitoring

The system SHALL provide a monitoring dashboard that updates task progress without manual refresh.

#### Scenario: Auto-refresh progress
- **WHEN** viewing task monitor page with active tasks
- **THEN** system automatically refreshes progress every 5 seconds

#### Scenario: Manual refresh option
- **WHEN** user clicks "Refresh Now"
- **THEN** system immediately fetches latest task status

#### Scenario: Configurable refresh interval
- **WHEN** user changes auto-refresh interval
- **THEN** system applies new interval (options: 1s, 5s, 10s, 30s, or off)

### Requirement: Cancel running task

The system SHALL allow users to cancel tasks that are in progress.

#### Scenario: Cancel task
- **WHEN** user clicks "Cancel" on running task
- **THEN** system terminates background process and updates task status to "cancelled"

#### Scenario: Partial results preserved
- **WHEN** task is cancelled
- **THEN** system keeps query results that were processed before cancellation

#### Scenario: Cannot cancel completed task
- **WHEN** user attempts to cancel completed or failed task
- **THEN** system displays message that task cannot be cancelled

### Requirement: Display task history

The system SHALL maintain history of all tasks with filtering and sorting options.

#### Scenario: List all tasks
- **WHEN** user navigates to task monitor
- **THEN** system displays all tasks ordered by creation time (newest first)

#### Scenario: Filter by status
- **WHEN** user selects status filter (running, completed, failed, cancelled)
- **THEN** system displays only tasks matching selected status

#### Scenario: Limit history length
- **WHEN** displaying task list
- **THEN** system shows most recent 50 tasks by default with option to load more

### Requirement: Task completion notification

The system SHALL notify users when background tasks complete.

#### Scenario: Completion notification
- **WHEN** task finishes successfully
- **THEN** system displays notification with task name and option to view results

#### Scenario: Failure notification
- **WHEN** task fails
- **THEN** system displays notification with error summary and option to retry

### Requirement: Navigate to task results

The system SHALL provide direct navigation from completed tasks to their results.

#### Scenario: View results from completed task
- **WHEN** user clicks "View Results" on completed batch search task
- **THEN** system navigates to annotation queue showing that task's query results

#### Scenario: Enter annotation mode from task
- **WHEN** user clicks "Enter Annotation" on completed task
- **THEN** system opens annotation interface with first query from that task

### Requirement: Task retry capability

The system SHALL allow users to retry failed tasks.

#### Scenario: Retry failed task
- **WHEN** user clicks "Retry" on failed task
- **THEN** system creates new task with same configuration and starts processing

#### Scenario: Retry preserves configuration
- **WHEN** retrying task
- **THEN** system uses original database, image list, and matching parameters

### Requirement: Display estimated time remaining

The system SHALL calculate and display estimated time to completion for running tasks.

#### Scenario: Calculate ETA
- **WHEN** task has processed at least 5 images
- **THEN** system calculates average processing time and estimates remaining time

#### Scenario: Update ETA dynamically
- **WHEN** processing speed changes
- **THEN** system recalculates ETA based on recent processing rate

#### Scenario: Display ETA format
- **WHEN** showing estimated time
- **THEN** system formats as "Xm Ys" for minutes and seconds remaining

### Requirement: Task checkpoint support

The system SHALL save task progress to enable recovery from interruptions.

#### Scenario: Periodic checkpoint saving
- **WHEN** task processes images
- **THEN** system saves checkpoint every 10 items processed

#### Scenario: Resume from checkpoint
- **WHEN** task is interrupted and restarted
- **THEN** system resumes from last checkpoint instead of starting over

#### Scenario: Checkpoint cleanup
- **WHEN** task completes or is cancelled
- **THEN** system removes checkpoint data to free storage
