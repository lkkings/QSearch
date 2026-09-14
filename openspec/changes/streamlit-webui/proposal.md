# Proposal: Streamlit WebUI for QSearch

## Why

QSearch currently operates entirely through command-line scripts (`index_database.py`, `search_queries.py`), requiring users to manually manage paths, configurations, and result files. This creates friction for iterative workflows like quality evaluation, parameter tuning, and result annotation. A web-based UI would enable:

1. **Visual database management**: Create, browse, and manage multiple question databases with different configurations
2. **Interactive search**: Upload images or provide paths/URLs for immediate visual feedback
3. **Human-in-the-loop annotation**: Label search results (hit/miss) to evaluate and improve matching quality
4. **Async batch processing**: Handle large-scale batch searches with progress tracking without blocking the UI

This transforms QSearch from a batch processing tool into an interactive search and annotation platform, enabling quality assessment workflows essential for production deployment.

## What Changes

- **New WebUI application** built with Streamlit, providing:
  - Database management interface (create, list, view statistics)
  - Single-image search (upload, path, or URL)
  - Batch search with async task queue and progress monitoring
  - Result annotation interface with keyboard shortcuts (1=hit, 0=miss)
  - Export functionality (JSONL, CSV, Excel formats)

- **New data persistence layer**:
  - Unified database storage structure under `data/databases/<db_name>/`
  - SQLite-based annotation tracking (queries, candidates, tasks tables)
  - Metadata management for each database (statistics, configuration snapshots)

- **New async task system**:
  - Multi-process task queue for batch searches
  - Progress tracking and cancellation support
  - Task history and resumption

- **Enhanced search engine wrapper**:
  - Unified interface over existing `QuestionMatcher` components
  - Configurable Top-N results (1-20)
  - Result persistence integration

## Capabilities

### New Capabilities

- `webui/database-management`: Managing question image databases through web interface
  - Create databases from folders, file lists, or ZIP archives
  - Configure extraction and matching parameters (presets or custom YAML)
  - List databases with statistics (image count, query count, hit/miss rates)
  - Delete databases

- `webui/interactive-search`: Performing searches through web interface
  - Single-image search via upload, local path, or URL
  - Batch search from folders or file lists
  - Configurable Top-N results per query (1-20)
  - Visual display of query images and matching candidates
  - Confidence scores and detailed matching information

- `webui/result-annotation`: Annotating search results for quality evaluation
  - Binary labeling (hit/miss) for each candidate result
  - Keyboard shortcuts for rapid annotation (1, 0, arrow keys)
  - Annotation queue navigation for batch results
  - Persistent storage of labels and timestamps
  - Statistics tracking (hit rate, labeled/unlabeled counts)

- `webui/async-tasks`: Managing long-running batch operations
  - Background task execution for batch searches
  - Real-time progress tracking (percentage, processed/total counts)
  - Task cancellation and error handling
  - Task history with status filtering
  - Auto-refresh monitoring dashboard

- `webui/data-export`: Exporting annotation data and statistics
  - JSONL format (one query per line with nested results)
  - CSV format (flattened, one candidate per row)
  - Excel format (multi-sheet: queries, candidates, statistics)
  - Configurable export scope (all data, date range, specific database)

### Modified Capabilities

- `search/matching`: Expose configurable Top-N results
  - Current implementation returns fixed Top-K from `output.top_k` config
  - Need to support runtime override of result count (1-20 range)
  - Preserve existing matching logic and scoring unchanged

## Impact

**New Code**:
- `src/qsearch/webui/` module (estimated ~2000 lines):
  - `app.py`: Streamlit application entry point
  - `database_manager.py`: Database CRUD operations
  - `search_engine.py`: Search wrapper and result persistence
  - `annotation_manager.py`: Annotation tracking and statistics
  - `task_manager.py`: Async task queue with multiprocessing
  - `exporter.py`: Multi-format data export
  - `ui/`: UI component modules for each page
  
**New Dependencies**:
- `streamlit` (~50MB): Web framework
- `streamlit-shortcuts` or custom component: Keyboard shortcuts
- `pandas`: Excel export support
- `openpyxl`: Excel file writing

**Data Storage**:
- New directory structure: `data/databases/<db_name>/`
  - `metadata.json`: Database metadata and statistics
  - `index/`: Existing Faiss/Hash index files (unchanged)
  - `annotations/`: New SQLite database for query/candidate/task tracking

**Modified Code**:
- `matching/matchers.py`: Add Top-N parameter to `QuestionMatcher.match()` method
- Configuration override mechanism for runtime Top-N adjustment

**No Breaking Changes**: CLI scripts remain unchanged and continue to work independently of WebUI.
