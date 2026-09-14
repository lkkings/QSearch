# QSearch WebUI User Guide

## Overview

QSearch WebUI is an interactive web interface for visual similarity search on question images. It provides:

- **Database Management**: Create and manage multiple question image databases
- **Interactive Search**: Single-image and batch search capabilities
- **Result Annotation**: Label search results for quality evaluation
- **Task Monitoring**: Track progress of batch operations
- **Data Export**: Export annotations in JSONL, CSV, and Excel formats

## Getting Started

### 1. Launch the WebUI

```bash
python scripts/start_webui.py
```

The application will open at `http://localhost:8501`

### 2. Create a Database

1. Navigate to **Database Management** tab
2. Click **Create Database** tab
3. Fill in the form:
   - **Database Name**: Alphanumeric name for your database
   - **Image Source**: Choose folder, file list, or ZIP
   - **Configuration**: Select a preset (balanced, fast, accurate) or upload custom YAML

4. Click **Create Database**
5. Wait for index building to complete

### 3. Perform a Search

#### Single Image Search

1. Go to **Search** tab
2. Select your database from the dropdown
3. Choose input mode:
   - **Upload Image**: Upload a query image file
   - **Local File Path**: Enter path to image on disk
   - **Image URL**: Provide URL to image

4. Configure search parameters:
   - **Top-N Results**: Number of matches to return (1-20)
   - **Matching Strategy**: Use database default or override

5. Click **Search**

#### Batch Search

1. Go to **Search** → **Batch Search** tab
2. Provide task name
3. Choose batch input mode:
   - **Folder**: Recursively scan folder for images
   - **File List**: Upload text file with image paths

4. Set Top-N results per query
5. Click **Start Batch Search**
6. Monitor progress in **Tasks** tab

### 4. Annotate Results

1. Navigate to **Annotation** tab
2. Select database
3. Review query and candidate images
4. Label each candidate:
   - **Press `1`** or click **Hit** → Candidate is a correct match
   - **Press `0`** or click **Miss** → Candidate is incorrect
   - **Click Skip** → Skip this candidate

5. Add optional notes
6. Navigate through candidates and queries:
   - **Arrow keys**: Next/previous candidate
   - **Enter**: Save and move to next query

### 5. Monitor Tasks

1. Go to **Tasks** tab
2. View running and completed tasks
3. For running tasks:
   - See real-time progress
   - View ETA
   - Cancel if needed

4. For completed tasks:
   - View results
   - Enter annotation workflow

### 6. Export Data

(Export UI to be implemented)

Currently, use the Exporter API:

```python
from pathlib import Path
from qsearch.webui.exporter import Exporter

db_path = Path("data/databases/my_database")
exporter = Exporter(db_path)

# Export to JSONL
exporter.export_jsonl(Path("export.jsonl"), scope="all")

# Export to CSV
exporter.export_csv(Path("export.csv"), scope="labeled")

# Export to Excel
exporter.export_excel(Path("export.xlsx"), scope="completed")
```

## Keyboard Shortcuts

In the Annotation interface:

| Key | Action |
|-----|--------|
| `1` | Label as Hit |
| `0` | Label as Miss |
| `↑` or `←` | Previous Candidate |
| `↓` or `→` | Next Candidate |
| `Enter` | Save & Next Query |

## Configuration Presets

### Balanced (Default)
- Good balance between speed and accuracy
- Suitable for most use cases

### Fast
- Optimized for speed
- Lower accuracy, faster processing

### Accurate
- Optimized for accuracy
- Slower processing, better results

### Custom
Upload your own YAML configuration file for full control.

## Tips and Best Practices

### Database Creation
- Use meaningful database names
- Organize images by category or dataset
- Build index immediately for faster searches

### Search
- Start with Top-10 results, adjust based on needs
- Use batch search for large query sets
- Monitor tasks page for batch progress

### Annotation
- Label consistently across all queries
- Use notes field for edge cases
- Complete all candidates before moving to next query
- Use keyboard shortcuts for faster workflow

### Performance
- Keep databases under 100K images for best performance
- Use SSD storage for faster index access
- Close unused browser tabs during batch operations

## Troubleshooting

### Database creation fails
- Check image folder path is correct
- Ensure images are in supported formats (jpg, png, bmp)
- Verify sufficient disk space

### Search returns no results
- Ensure index is built
- Check query image is valid
- Try adjusting Top-N parameter

### Batch task stuck
- Check Tasks page for error messages
- Cancel and retry if needed
- Check system resources (CPU, memory)

### Annotation not saving
- Verify database is not locked by another process
- Check browser console for errors
- Refresh page and try again

## Advanced Features

### Custom Configuration

Create a YAML file with custom parameters:

```yaml
extraction:
  ocr_engine: paddleocr
  latex_enabled: true

matching:
  exact:
    perceptual_hash:
      max_distance: 5

  content:
    stage1:
      top_k: 100
      text_similarity_threshold: 0.75

    scoring:
      threshold: 0.85

output:
  top_k: 10
```

### Database Statistics

View detailed statistics in Database Management → Details:
- Total queries and completion status
- Hit rate and labeling progress
- Index file sizes and metadata

### Task Checkpointing

Batch tasks save checkpoints every 10 images. If a task fails:
1. View error in Tasks page
2. Fix the issue
3. Retry (task will resume from last checkpoint)

## Support

For issues or questions:
- Check [GitHub Issues](https://github.com/your-repo/issues)
- Review [Architecture Documentation](webui-architecture.md)
- See main [README](../README.md)
