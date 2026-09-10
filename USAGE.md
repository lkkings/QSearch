# QSearch Usage Guide

## Installation

The package has been configured with proper dependencies and structure.

### Install in editable mode:
```bash
uv pip install -e .
```

## Running Scripts

**Important:** Use `uv run` to run scripts, not direct `python`:

### 1. Index Database
Build search indices from base images:
```bash
uv run scripts/index_database.py --help
uv run scripts/index_database.py --image-dir ./data/base --output-dir ./data/indices
```

### 2. Search Queries
Search for matching questions:
```bash
uv run scripts/search_queries.py --help
uv run scripts/search_queries.py --query-dir ./data/queries --index-dir ./data/indices --output-file results.json
```

### 3. Verify Installation
Check if all dependencies are installed correctly:
```bash
uv run scripts/verify_install.py
```

### 4. Download Models
Download required ML models:
```bash
uv run scripts/download_models.py
```

### 5. Download Images
Download sample images:
```bash
uv run scripts/download_images.py
```

### 6. Verify GPUs
Check GPU availability:
```bash
uv run scripts/verify_gpus.py
```

## Import in Python Code

When importing qsearch modules in your own scripts:

```python
from qsearch.config.loader import ConfigLoader
from qsearch.features.feature_extractor import FeatureExtractor
from qsearch.indexing.faiss_index import FaissIndexBuilder
```

## Configuration Presets

Available presets can be found in `src/qsearch/config/presets.py`:
- `speed`: Fast processing, lower accuracy
- `balanced`: Balance between speed and accuracy
- `accuracy`: High accuracy, slower processing

Use with `--preset` flag:
```bash
uv run scripts/index_database.py --preset balanced --image-dir ./data/base --output-dir ./data/indices
```
