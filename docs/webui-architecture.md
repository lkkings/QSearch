# QSearch WebUI Architecture

## System Overview

QSearch WebUI is built as a Streamlit application that wraps the core QSearch matching engine with a persistence layer for annotation tracking and async task processing.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     Streamlit WebUI Layer                    │
├─────────────────────────────────────────────────────────────┤
│  Database UI  │  Search UI  │  Annotation UI  │  Task UI    │
└────────┬──────┴──────┬──────┴──────┬──────────┴──────┬──────┘
         │             │              │                  │
    ┌────▼─────┐  ┌───▼──────┐  ┌───▼──────────┐  ┌───▼──────┐
    │ Database │  │  Search  │  │ Annotation   │  │   Task   │
    │ Manager  │  │  Engine  │  │  Manager     │  │ Manager  │
    └────┬─────┘  └───┬──────┘  └───┬──────────┘  └───┬──────┘
         │            │              │                  │
         │      ┌─────▼──────────────▼─────┐           │
         │      │   QuestionMatcher         │           │
         │      │  (Core Matching Engine)   │           │
         │      └─────┬──────────────┬──────┘           │
         │            │              │                  │
    ┌────▼────────────▼──────────────▼──────────────────▼────┐
    │              SQLite Annotations Database                │
    │     (queries, candidates, tasks tables + views)         │
    └─────────────────────────────────────────────────────────┘
```

## Component Architecture

### 1. UI Layer (`src/qsearch/webui/ui/`)

Streamlit components for each page:

- **database_ui.py**: Database CRUD operations
- **search_ui.py**: Single and batch search interfaces
- **annotation_ui.py**: Result labeling workflow
- **task_ui.py**: Async task monitoring

### 2. Business Logic Layer

#### DatabaseManager (`database_manager.py`)
- Creates databases from folders/ZIPs/file lists
- Manages metadata and configuration
- Integrates with existing `index_database.py`

#### SearchEngine (`search_engine.py`)
- Wraps `QuestionMatcher` with persistence
- Handles image loading (upload, path, URL)
- Formats results for UI display
- Saves queries and candidates to database

#### AnnotationManager (`annotation_manager.py`)
- Tracks candidate labels (hit/miss/skip)
- Calculates query completion status
- Computes hit rate statistics
- Updates metadata.json

#### TaskManager (`task_manager.py`)
- Spawns background processes for batch search
- Tracks progress in SQLite
- Implements checkpointing (every 10 images)
- Handles cancellation and cleanup

#### Exporter (`exporter.py`)
- Exports to JSONL (nested query format)
- Exports to CSV (flattened candidate rows)
- Exports to Excel (multi-sheet with formatting)

### 3. Persistence Layer

#### SQLite Schema (`schema.sql`)

**Tables:**
- `queries`: Search queries with status tracking
- `candidates`: Top-N results per query with labels
- `tasks`: Batch job tracking with progress

**Views:**
- `stats_summary`: Aggregate statistics
- `candidate_stats`: Per-query statistics

**Triggers:**
- Auto-update query status when candidates labeled
- Timestamp updates on changes

#### Database Manager (`db_manager.py`)
- Connection pooling with retry logic
- WAL mode for concurrency
- Foreign key cascades
- Transaction management

## Data Flow

### Single Image Search Flow

```
User uploads image
    ↓
SearchEngine.search_single()
    ↓
Load image (upload/path/URL)
    ↓
QuestionMatcher.match(top_n=N)
    ↓
Format results
    ↓
Save to SQLite (queries + candidates)
    ↓
Display results in UI
```

### Batch Search Flow

```
User provides folder/file list
    ↓
TaskManager.create_batch_search_task()
    ↓
TaskManager.start_task()
    ↓
Spawn multiprocessing.Process
    ↓
Background worker:
  - Loop through images
  - SearchEngine.search_single()
  - Save results to SQLite
  - Update progress every image
  - Checkpoint every 10 images
    ↓
Task completes or fails
```

### Annotation Flow

```
AnnotationManager.get_unlabeled_queries()
    ↓
User views query + candidates
    ↓
User labels candidate (hit/miss/skip)
    ↓
AnnotationManager.label_candidate()
    ↓
SQLite UPDATE candidates SET label=?
    ↓
Trigger updates query status
    ↓
Statistics recalculated
```

## Storage Structure

```
data/databases/
  <db_name>/
    metadata.json          # Database info + statistics
    config.yaml           # Matching configuration
    image_list.txt        # Paths to indexed images
    index/                # Search indexes
      features.pkl
      text_index.faiss
      text_index_ids.pkl
      hash_index.pkl
      index_stats.json
    annotations/          # Annotation data
      annotations.db      # SQLite database
```

## Concurrency Model

### Streamlit Single-Thread Constraint
- Streamlit runs in single thread
- Long operations block UI
- Solution: Multiprocessing for batch tasks

### Task Processing
- `multiprocessing.Process` for true parallelism
- SQLite as shared state storage
- WAL mode enables concurrent reads/writes
- Retry logic handles transient locks

### Session State
- `st.session_state` for navigation tracking
- Current database, query, candidate indices
- Search results cached in session

## Configuration System

### Preset Configurations
- **balanced**: Default, good speed/accuracy trade-off
- **fast**: Optimized for speed
- **accurate**: Optimized for precision

### Custom Configurations
Users can upload YAML with:
- OCR engine selection
- Hash distance thresholds
- Stage-1 Top-K
- Scoring weights

## Error Handling

### Database Errors
- Connection retry with exponential backoff
- File lock detection and recovery
- Orphaned process cleanup on startup

### Task Errors
- Checkpoint resume for interrupted tasks
- Per-image error logging
- Failed item counter
- Error messages in task table

### UI Errors
- Try-except boundaries in app.py
- User-friendly error messages
- Exception logging
- Graceful degradation

## Performance Considerations

### Database Size
- Recommended: <100K images per database
- Index files fit in memory
- SQLite performs well for single-user workload

### Search Performance
- Feature extraction: ~100-500ms/image
- Vector search: <10ms
- Total: ~200-600ms per single search

### Batch Processing
- Checkpoint overhead: minimal (<1ms)
- Progress update: every image (~5ms)
- Bottleneck: feature extraction, not I/O

## Security

### Input Validation
- Database names: alphanumeric + underscore/hyphen
- Image paths: existence checks
- SQL: parameterized queries only

### File Uploads
- Restricted to safe file types
- Temporary storage for processing
- Cleanup after use

### Process Isolation
- Background workers run in separate processes
- Limited access to main application state
- No shared memory

## Future Enhancements

### Planned Features
- Multi-user support with authentication
- Real-time collaboration on annotations
- Cloud storage integration
- Advanced filtering and search

### Scalability Improvements
- Distributed task queue (Celery)
- PostgreSQL for multi-user
- Redis for caching
- CDN for image delivery

## Troubleshooting

### Common Issues

**File locking errors**
- Symptom: SQLite locked warnings
- Cause: Concurrent write attempts
- Solution: Retry logic handles automatically

**Orphaned processes**
- Symptom: Tasks stuck in "running"
- Cause: Process crash or session end
- Solution: Cleanup on startup

**Memory issues in batch tasks**
- Symptom: Process killed by OS
- Cause: Feature cache accumulation
- Solution: Clear cache periodically

## Development

### Adding New Features

1. **Backend**: Implement in appropriate manager class
2. **UI**: Add to corresponding UI module
3. **Integration**: Update app.py routing
4. **Tests**: Add integration test
5. **Docs**: Update user guide

### Code Organization

```
src/qsearch/webui/
  ├── app.py                 # Main entry point
  ├── schema.sql            # Database schema
  ├── db_manager.py         # Connection handling
  ├── database_manager.py   # Database CRUD
  ├── search_engine.py      # Search wrapper
  ├── annotation_manager.py # Labeling logic
  ├── task_manager.py       # Async tasks
  ├── exporter.py          # Data export
  ├── ui/                  # UI components
  │   ├── database_ui.py
  │   ├── search_ui.py
  │   ├── annotation_ui.py
  │   └── task_ui.py
  └── utils/               # Utilities
      └── shortcuts.py     # Keyboard shortcuts
```

## References

- [Streamlit Documentation](https://docs.streamlit.io/)
- [SQLite WAL Mode](https://www.sqlite.org/wal.html)
- [Python Multiprocessing](https://docs.python.org/3/library/multiprocessing.html)
