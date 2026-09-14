# Tasks: Streamlit WebUI Implementation

## 1. Project Setup

- [x] 1.1 Create `src/qsearch/webui/` module directory structure with `__init__.py`, `app.py`, and subdirectories `ui/`, `utils/` and verify all directories exist
- [x] 1.2 Add dependencies to `requirements.txt`: `streamlit>=1.30.0`, `streamlit-shortcuts>=0.1.0`, `pandas>=2.0.0`, `openpyxl>=3.1.0` and verify `uv pip install -e .` succeeds
- [x] 1.3 Create startup script `scripts/start_webui.py` that launches Streamlit and verify it runs without errors
- [x] 1.4 Create `data/databases/` directory for database storage and verify directory is created

## 2. Database Schema and Persistence

- [x] 2.1 Create SQLite schema file `src/qsearch/webui/schema.sql` with queries, candidates, tasks tables and verify schema is valid SQL
- [x] 2.2 Implement `src/qsearch/webui/db_manager.py` with connection handling, schema initialization, and migration support and verify database file is created correctly
- [x] 2.3 Create database views `stats_summary` and `candidate_stats` for quick statistics and verify views return expected columns
- [x] 2.4 Add indexes on status, task_id, label, and query_id columns and verify `EXPLAIN QUERY PLAN` shows index usage
- [x] 2.5 Implement connection pooling with timeout=30 and retry logic and verify no file-locking errors under concurrent access

## 3. Database Management Module

- [x] 3.1 Implement `DatabaseManager.create_database()` to create database from folder/file list/ZIP and verify database directory structure is created
- [x] 3.2 Add image scanning with recursive folder support for jpg/jpeg/png/bmp formats and verify correct image count
- [x] 3.3 Implement configuration handling (preset selection and custom YAML) and verify config is stored in metadata.json
- [x] 3.4 Add index building integration calling existing `index_database.py` logic and verify index files are created
- [x] 3.5 Implement `DatabaseManager.list_databases()` to scan `data/databases/` and return metadata and verify correct listing
- [x] 3.6 Implement `DatabaseManager.get_database_info()` to read metadata.json and annotation statistics and verify all fields are present
- [x] 3.7 Implement `DatabaseManager.delete_database()` with directory removal and verify directory is removed
- [x] 3.8 Add database name validation (unique names, valid characters) and verify duplicate names are rejected
- [x] 3.9 Create `metadata.json` schema with statistics fields and verify JSON is valid

## 4. Search Engine Wrapper

- [x] 4.1 Implement `SearchEngine.__init__()` to load database index files (Faiss, Hash, features.pkl) and verify indexes load successfully
- [x] 4.2 Add `SearchEngine.search_single()` wrapper around `QuestionMatcher.match()` with Top-N parameter and verify correct number of results returned
- [x] 4.3 Implement image loading from upload, local path, and URL with error handling and verify all three modes work
- [x] 4.4 Add result formatting to match expected JSON structure with query_image, exact_matches, content_matches and verify structure matches specs
- [x] 4.5 Implement `SearchEngine.save_query_result()` to persist query and candidates to SQLite and verify records are inserted
- [x] 4.6 Add configuration override support (temporary preset/custom parameters) and verify overrides work without modifying metadata
- [x] 4.7 Implement query_id generation with UUID and verify uniqueness

## 5. Core Matching Top-N Support

- [x] 5.1 Add optional `top_n` parameter to `QuestionMatcher.match()` method signature and verify backward compatibility
- [x] 5.2 Implement Top-N clamping logic (min=1, max=20) with fallback to config default and verify clamping works
- [x] 5.3 Update `ExactMatcher` to respect top_n parameter and verify correct number of exact matches returned
- [x] 5.4 Update `ContentMatcher` stage1 to use top_n for Faiss search and verify correct number of candidates
- [x] 5.5 Update output truncation to respect top_n per match type and verify exact and content matches both limited correctly
- [x] 5.6 Add unit tests verifying scoring consistency regardless of Top-N value and verify tests pass

## 6. Annotation Manager

- [x] 6.1 Implement `AnnotationManager.label_candidate()` to update candidate label and timestamp and verify label is persisted
- [x] 6.2 Add query status calculation (unlabeled/partial/completed) based on candidate labels and verify status updates correctly
- [x] 6.3 Implement `AnnotationManager.get_query_results()` to fetch query with all candidates and verify correct data structure
- [x] 6.4 Add `AnnotationManager.get_unlabeled_queries()` for annotation queue and verify only unlabeled queries returned
- [x] 6.5 Implement statistics calculation methods (hit_rate, labeled_counts) using SQL views and verify correct calculations
- [x] 6.6 Add `AnnotationManager.update_database_statistics()` to refresh metadata.json and verify statistics are updated
- [x] 6.7 Implement duplicate query handling (DELETE CASCADE old query, INSERT new) and verify old annotations are removed
- [x] 6.8 Add optional notes field support for candidates and verify notes are stored and retrieved

## 7. Task Manager (Async Processing)

- [x] 7.1 Implement `TaskManager.create_batch_search_task()` to create task record with config and verify task_id is returned
- [x] 7.2 Add `TaskManager.start_task()` to spawn background process with multiprocessing.Process and verify process starts
- [x] 7.3 Implement `TaskManager._run_batch_search()` worker function for background execution and verify it processes images
- [x] 7.4 Add progress tracking with processed_items and progress percentage updates and verify progress updates in database
- [x] 7.5 Implement failure tracking with failed_items counter and error logging and verify failures are recorded
- [x] 7.6 Add task completion handling (status update, completion timestamp) and verify status changes to completed
- [x] 7.7 Implement `TaskManager.cancel_task()` with process termination and verify process is killed
- [x] 7.8 Add `TaskManager.get_task_status()` to read task state from database and verify correct status returned
- [x] 7.9 Implement checkpoint saving every 10 images with last_processed_index and verify checkpoints are saved
- [x] 7.10 Add checkpoint resume logic in worker function and verify task resumes from checkpoint
- [x] 7.11 Implement orphaned process cleanup on app startup and verify stale processes are killed
- [x] 7.12 Add `TaskManager.list_tasks()` with filtering and sorting by creation date and verify correct task list

## 8. Data Export Module

- [x] 8.1 Implement `Exporter.export_jsonl()` with one query per line nested format and verify valid JSONL output
- [x] 8.2 Add UTF-8 encoding for JSONL export and verify non-ASCII characters are preserved
- [x] 8.3 Implement `Exporter.export_csv()` with flattened schema (one candidate per row) and verify correct CSV structure
- [x] 8.4 Add UTF-8 BOM to CSV for Excel compatibility and verify Excel opens file correctly
- [x] 8.5 Implement `Exporter.export_excel()` with three sheets (Queries, Candidates, Statistics) and verify all sheets exist
- [x] 8.6 Add Excel formatting (auto-width columns, frozen headers) and verify formatting is applied
- [x] 8.7 Implement export scope filtering (all/labeled/completed/date range) and verify correct filtering
- [x] 8.8 Add metadata inclusion (database name, export timestamp, statistics) and verify metadata is present
- [x] 8.9 Implement filename generation with timestamp format and sanitization and verify valid filenames
- [x] 8.10 Add progress indication for large exports (>1000 queries) and verify progress bar displays
- [x] 8.11 Implement error handling for write failures and data corruption and verify graceful error messages

## 9. UI Components - Database Management

- [x] 9.1 Create `ui/database_ui.py` with database management page layout and verify page renders
- [x] 9.2 Implement database creation form with name input, source selection (folder/file/ZIP), and preset dropdown and verify form submission works
- [x] 9.3 Add file upload widget for ZIP archives and file lists and verify uploads are handled
- [x] 9.4 Implement custom configuration YAML upload option and verify YAML validation
- [x] 9.5 Add database list display with cards showing name, image count, statistics and verify all databases listed
- [x] 9.6 Implement database detail view showing full metadata and index statistics and verify details display correctly
- [x] 9.7 Add delete button with confirmation dialog and verify database is deleted after confirmation
- [x] 9.8 Implement "Enter Search" button navigation to search page with database pre-selected and verify navigation works
- [x] 9.9 Add loading spinners during index building and verify spinner displays during processing

## 10. UI Components - Interactive Search

- [x] 10.1 Create `ui/search_ui.py` with search page layout and verify page renders
- [x] 10.2 Add database selector dropdown populated from DatabaseManager and verify correct database list
- [x] 10.3 Implement single-image search tab with upload/path/URL input options and verify all three input modes work
- [x] 10.4 Add Top-N configuration slider (1-20) with default value 10 and verify slider updates value
- [x] 10.5 Implement matching strategy selector (use default / override preset / custom) and verify override works
- [x] 10.6 Add batch search tab with folder/file list upload and task naming and verify batch task creation
- [x] 10.7 Implement query image display with filename and processing time and verify image displays
- [x] 10.8 Add candidate results display with rank, image, confidence, match type, scores and verify all fields display
- [x] 10.9 Implement result grouping by match type (exact_matches, content_matches) and verify correct grouping
- [x] 10.10 Add confidence level badges (HIGH/MEDIUM/LOW) with color coding and verify correct colors
- [x] 10.11 Implement "No matches found" message when search returns empty and verify message displays

## 11. UI Components - Annotation Interface

- [x] 11.1 Create `ui/annotation_ui.py` with annotation page layout and verify page renders
- [x] 11.2 Implement annotation queue navigation with current query counter (X / Y) and verify counter updates
- [x] 11.3 Add progress bar showing overall annotation completion percentage and verify progress updates
- [x] 11.4 Implement query image display with current query information and verify image displays
- [x] 11.5 Add candidate carousel navigation (previous/next candidate arrows) and verify navigation works
- [x] 11.6 Implement candidate details display (rank, confidence, image, scores) and verify all fields display
- [x] 11.7 Add label buttons (Hit / Miss / Skip) for current candidate and verify label is saved
- [x] 11.8 Implement keyboard shortcuts component with key bindings (1, 0, arrows, Enter) and verify shortcuts work
- [x] 11.9 Add visual status indicators (checkmark, cross, clock icons) for labeled/unlabeled and verify icons display
- [x] 11.10 Implement "Modify Label" button for already-labeled candidates and verify relabeling works
- [x] 11.11 Add "Save and Next Query" button to advance to next query and verify navigation
- [x] 11.12 Implement "Skip to Next Unlabeled" button and verify it finds unlabeled queries
- [x] 11.13 Add optional notes text area for candidate labels and verify notes are saved
- [x] 11.14 Implement sidebar with keyboard shortcut legend and progress summary and verify sidebar displays

## 12. UI Components - Task Monitoring

- [x] 12.1 Create `ui/task_ui.py` with task monitor page layout and verify page renders
- [x] 12.2 Implement active tasks section with running tasks list and verify list displays
- [x] 12.3 Add progress bars showing percentage complete for each task and verify progress updates
- [x] 12.4 Implement task details display (status, processed/total, failed count, start time) and verify all fields display
- [x] 12.5 Add ETA calculation and display for running tasks and verify ETA updates
- [x] 12.6 Implement cancel button for running tasks and verify cancellation works
- [x] 12.7 Add completed tasks section with task history and verify history displays
- [x] 12.8 Implement status filtering (all/running/completed/failed/cancelled) and verify filtering works
- [x] 12.9 Add "View Results" and "Enter Annotation" buttons for completed tasks and verify navigation works
- [x] 12.10 Implement "Retry" button for failed tasks and verify retry creates new task
- [x] 12.11 Add auto-refresh toggle with configurable interval (1s/5s/10s/30s/off) and verify auto-refresh works
- [x] 12.12 Implement manual refresh button and verify immediate refresh

## 13. Main Application

- [x] 13.1 Create `app.py` with Streamlit page configuration and multi-page navigation and verify app launches
- [x] 13.2 Implement top-level navigation tabs (Database Management / Search / Annotation / Tasks) and verify tab switching works
- [x] 13.3 Add session state initialization for current database, query, candidate indices and verify state persists
- [x] 13.4 Implement page routing logic to render appropriate UI component and verify correct pages load
- [x] 13.5 Add error boundaries with try-except and user-friendly error messages and verify errors display gracefully
- [x] 13.6 Implement TaskManager singleton initialization on startup and verify no orphaned processes

## 14. Keyboard Shortcuts Component

- [x] 14.1 Create `utils/shortcuts.py` wrapper for streamlit-shortcuts library and verify import succeeds
- [x] 14.2 Implement fallback JavaScript component if streamlit-shortcuts unavailable and verify fallback works
- [x] 14.3 Add key binding registration for annotation shortcuts (1, 0, arrows, Enter) and verify bindings work
- [x] 14.4 Implement event callback integration with Streamlit rerun and verify callbacks trigger correctly
- [x] 14.5 Add browser compatibility testing (Chrome, Firefox, Safari) and verify shortcuts work in all browsers

## 15. Integration and Testing

- [x] 15.1 Create integration test for database creation end-to-end flow and verify database is created correctly
- [x] 15.2 Add integration test for single-image search workflow and verify results are correct
- [x] 15.3 Create integration test for batch search task execution and verify all queries are processed
- [x] 15.4 Add integration test for annotation workflow with label persistence and verify labels are saved
- [x] 15.5 Create integration test for export functionality in all three formats and verify files are valid
- [x] 15.6 Add test for Top-N parameter override in matching and verify correct result count
- [x] 15.7 Create test for duplicate query overwrite behavior and verify old data is replaced
- [x] 15.8 Add test for task cancellation and checkpoint resume and verify task state is correct
- [x] 15.9 Create test for database statistics calculation and verify hit rate is accurate
- [x] 15.10 Add test for concurrent task writes to SQLite and verify no file-locking errors

## 16. Documentation

- [x] 16.1 Create `docs/webui-user-guide.md` with screenshots and usage instructions and verify documentation is complete
- [x] 16.2 Add keyboard shortcuts reference card to documentation and verify all shortcuts documented
- [x] 16.3 Create `docs/webui-architecture.md` with system diagrams and component descriptions and verify architecture is documented
- [x] 16.4 Add troubleshooting section for common issues (port conflicts, file locking, memory) and verify solutions are clear
- [x] 16.5 Update main README.md with WebUI quick start section and verify instructions work
- [x] 16.6 Create example configuration files for common use cases and verify examples are valid

## 17. Polish and Optimization

- [x] 17.1 Add loading states and spinners for all async operations and verify spinners display during operations
- [x] 17.2 Implement toast notifications for success/error messages and verify toasts appear correctly
- [x] 17.3 Add confirmation dialogs for destructive actions (delete database, cancel task) and verify dialogs prevent accidents
- [x] 17.4 Optimize database queries with proper indexing and verify query performance is acceptable
- [x] 17.5 Add caching for database list and statistics using `st.cache_data` and verify cache improves performance
- [x] 17.6 Implement image thumbnail generation for faster display and verify thumbnails load quickly
- [x] 17.7 Add responsive layout adjustments for different screen sizes and verify layout works on mobile
- [x] 17.8 Implement dark mode support using Streamlit theme configuration and verify both themes work
- [x] 17.9 Add help tooltips for complex UI elements and verify tooltips are helpful
- [x] 17.10 Optimize memory usage in batch processing with feature cache clearing and verify no OOM errors
