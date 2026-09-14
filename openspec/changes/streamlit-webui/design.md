# Design: Streamlit WebUI for QSearch

## Context

QSearch currently operates through CLI scripts (`index_database.py`, `search_queries.py`) that directly call feature extraction and matching modules. The existing architecture:

- **Feature extraction**: `FeatureExtractor` supports multi-GPU processing and returns feature records
- **Indexing**: `FaissIndexBuilder` and `HashIndex` persist indexes to disk
- **Matching**: `QuestionMatcher` orchestrates `ExactMatcher` and `ContentMatcher`
- **Configuration**: `ConfigLoader` loads YAML with preset support

The WebUI will wrap these components with a persistence layer for annotation tracking and a task queue for async processing. See proposal.md for motivation.

## Goals / Non-Goals

**Goals:**
- Interactive web interface for database management, search, and annotation
- Persistent annotation storage with SQLite for query/candidate/task tracking
- Async batch processing without blocking UI
- Multi-format export (JSONL, CSV, Excel)
- Zero breaking changes to existing CLI scripts

**Non-Goals:**
- Multi-user authentication or concurrent access control (single-user assumption)
- Real-time collaboration features
- Cloud deployment or distributed task processing (local-only)
- Modification of core matching algorithms (specs/search/matching only adds Top-N parameter)
- Migration of existing CLI results into WebUI database

## Decisions

### Decision 1: Streamlit as UI Framework

**Choice**: Use Streamlit for the web interface

**Rationale**:
- Rapid development with Python-native components
- Built-in state management via `st.session_state`
- No separate frontend/backend split needed
- Good fit for single-user data science tools

**Alternatives considered**:
- **Flask + React**: More flexible but requires frontend expertise and doubles development time
- **Gradio**: Simpler but limited layout control and harder to customize annotation workflow
- **Dash**: Similar to Streamlit but more verbose API and steeper learning curve

**Trade-offs**: Streamlit's single-threaded nature requires careful async task design (see Decision 3)

### Decision 2: SQLite for Annotation Persistence

**Choice**: Use SQLite database per database for annotation tracking

**Rationale**:
- Zero-config, serverless, file-based storage
- ACID transactions for concurrent task writes
- SQL queries for statistics aggregation
- No external database server required

**Schema design**:
```sql
-- queries: one record per search, tracks completion status
-- candidates: one record per Top-N result, stores labels
-- tasks: one record per batch job, tracks progress
```

**Location**: `databases/<db_name>/annotations/annotations.db` alongside index files

**Alternatives considered**:
- **JSON files**: Simpler but no transactions, harder to query aggregates
- **PostgreSQL**: Overkill for single-user, adds deployment complexity

**Trade-offs**: SQLite has file-locking limitations but acceptable for single-user workload

### Decision 3: Multi-process Task Queue

**Choice**: Use `multiprocessing` with SQLite-based task state tracking

**Architecture**:
```
Main Streamlit Process
    ↓ (creates task record in SQLite)
TaskManager.start_task()
    ↓ (spawns)
Background Worker Process
    ↓ (reads task config, executes search loop)
    ↓ (writes progress updates to SQLite)
    ↓ (writes query results to SQLite)
Main Process polls SQLite for progress updates
```

**Rationale**:
- Streamlit runs in single thread, cannot block on long operations
- `multiprocessing.Process` allows true background execution
- SQLite provides shared state without Redis/Celery overhead
- Process isolation prevents OOM in main process

**Alternatives considered**:
- **Threading**: GIL prevents true parallelism, still blocks Streamlit
- **Celery + Redis**: Over-engineered for single-user, adds dependencies
- **Asyncio**: Streamlit is not async-native, requires rewrite

**Checkpointing**: Store `last_processed_index` in tasks table every 10 images for resumption

**Cancellation**: `Process.terminate()` then `Process.kill()` if doesn't join within 5s

### Decision 4: Keyboard Shortcuts via Custom Component

**Choice**: Use `streamlit-shortcuts` or lightweight custom JavaScript component

**Rationale**:
- Streamlit lacks native keyboard event handling
- `streamlit-shortcuts` provides React-based keyboard bindings
- Fallback: embed minimal JS via `st.components.v1.html` with `window.addEventListener`

**Keybindings**:
- `1` → label as hit
- `0` → label as miss
- `↓` / `→` → next candidate
- `↑` / `←` → previous candidate
- `Enter` → save and next query

**Alternatives considered**:
- **Pure Streamlit buttons**: No keyboard support, slower annotation workflow
- **Custom React component**: More complex, requires npm build step

### Decision 5: Database Storage Structure

**Choice**: Unified directory per database under `data/databases/<db_name>/`

**Structure**:
```
data/databases/
  <db_name>/
    metadata.json          # Database metadata + statistics
    index/                 # Existing Faiss/Hash indexes
      features.pkl
      text_index.faiss
      text_index_ids.pkl
      hash_index.pkl
      index_stats.json
    annotations/           # New annotation data
      annotations.db       # SQLite database
```

**metadata.json schema**:
```json
{
  "name": "math_questions",
  "created_at": "2024-01-15T10:00:00Z",
  "image_count": 10000,
  "config": { "preset": "balanced" },
  "source_path": "/data/base_images",
  "statistics": {
    "total_queries": 150,
    "labeled_queries": 120,
    "unlabeled_queries": 30,
    "total_hits": 450,
    "total_misses": 180,
    "hit_rate": 0.75
  }
}
```

**Rationale**:
- Keeps all database artifacts together
- Metadata file enables fast statistics display without querying SQLite
- Statistics cached in metadata, updated on label changes

**Alternatives considered**:
- **Global SQLite**: Single database for all databases, harder to backup individual databases
- **Separate stats table**: Slower reads, need to join queries for listing page

### Decision 6: Top-N Runtime Override

**Choice**: Add optional `top_n` parameter to `QuestionMatcher.match()` method

**Implementation**:
```python
def match(self, query_features, top_n=None):
    if top_n is None:
        top_n = self.config['matching']['output']['top_k']
    top_n = max(1, min(20, top_n))  # Clamp to [1, 20]
    # ... rest of matching logic unchanged
```

**Rationale**:
- Minimal invasive change (one parameter, one if-statement)
- Preserves backward compatibility (default `None` uses config)
- No changes to scoring logic or index structure

**Alternatives considered**:
- **Config override**: Requires reloading matchers, more complex state management
- **Separate method**: Code duplication, harder to maintain

### Decision 7: Export Format Implementations

**JSONL**: Use `json.dumps()` per query, newline-separated
- Structure: `{"query_id": "...", "query_image": "...", "results": [...]}`

**CSV**: Use `pandas.DataFrame.to_csv()` with flattened schema
- One row per candidate, denormalized query fields
- UTF-8 BOM for Excel compatibility

**Excel**: Use `pandas.ExcelWriter` with `openpyxl` engine
- Sheet 1: Queries summary (query_id, image, status, time)
- Sheet 2: Candidates detail (all fields flattened)
- Sheet 3: Statistics (aggregates from stats view)

**Rationale**:
- Pandas provides consistent API for CSV/Excel
- JSONL preserves nested structure for programmatic use
- Multi-sheet Excel enables pivot tables and filtering

### Decision 8: Handling Duplicate Query Images

**Choice**: Overwrite previous query record when same image is searched again

**Implementation**:
```sql
-- Check for existing query by query_image_path
SELECT query_id FROM queries WHERE query_image_path = ?
-- If exists: DELETE CASCADE removes old candidates
-- INSERT new query and candidates
```

**Rationale**:
- Specs require overwrite behavior (specs/webui/result-annotation)
- Prevents annotation drift (labels on stale results)
- Cascade delete simplifies cleanup

**Alternatives considered**:
- **Keep history**: Adds complexity, specs say overwrite
- **Versioning**: Not required, adds schema complexity

## Risks / Trade-offs

**[Risk]** SQLite file locking causes write conflicts in concurrent tasks
**→ Mitigation**: Use `timeout=30` on connections, implement retry with exponential backoff

**[Risk]** Streamlit auto-refresh interferes with annotation workflow
**→ Mitigation**: Disable auto-rerun via `st.set_page_config(initial_sidebar_state="collapsed")`, use explicit `st.rerun()` calls

**[Risk]** Large batch tasks consume excessive memory in background process
**→ Mitigation**: Process images in batches of 100, clear feature cache after each batch

**[Risk]** Orphaned background processes if main process crashes
**→ Mitigation**: Store process PIDs in tasks table, add cleanup on app startup to kill stale processes

**[Risk]** Streamlit-shortcuts component may not work in all browsers
**→ Mitigation**: Provide fallback button-based interface, test on Chrome/Firefox/Safari

**[Trade-off]** SQLite-based task queue is not distributed-ready
**→ Accepted**: Specs explicitly state single-user scenario, no cloud deployment requirement

**[Trade-off]** Annotation data not backward-compatible with CLI scripts
**→ Accepted**: WebUI and CLI are independent workflows, no migration needed

**[Trade-off]** No real-time task progress (polling-based)
**→ Accepted**: 5-second auto-refresh is sufficient for batch workflows, WebSockets over-engineering

## Migration Plan

**Phase 1: Core Infrastructure**
1. Create `src/qsearch/webui/` module structure
2. Implement SQLite schema and migration scripts
3. Create DatabaseManager with CRUD operations
4. Add Top-N parameter to QuestionMatcher

**Phase 2: Search & Annotation**
1. Implement SearchEngine wrapper
2. Build AnnotationManager with label tracking
3. Create UI components for search and annotation
4. Add keyboard shortcuts component

**Phase 3: Async Tasks**
1. Implement TaskManager with multiprocessing
2. Add progress tracking and cancellation
3. Create task monitoring UI
4. Add checkpoint/resume support

**Phase 4: Export & Polish**
1. Implement Exporter for JSONL/CSV/Excel
2. Add statistics views
3. Polish UI/UX (error handling, loading states)
4. Documentation and testing

**Rollback**: No migration needed - WebUI is additive, CLI scripts unchanged. Remove `src/qsearch/webui/` and `data/databases/` to rollback.

## Open Questions

**Q**: Should we support importing existing CLI search results into annotation database?
**Deferred**: Not in specs, can add later if users request it

**Q**: How to handle very large databases (>100K images) with memory constraints?
**Deferred**: Current design loads all features into memory; can add pagination if needed

**Q**: Should annotation queue support filtering (e.g., show only HIGH confidence misses)?
**Deferred**: Not in specs, simple addition if useful during testing
