# QSearch: Configurable Question Matcher

A dual-path question matching system for finding identical or similar questions in large image databases.

## Features

- **Dual-path matching**: Exact match (same photograph) + Content match (same question text)
- **Configurable feature extraction**: Text (OCR, stem, options, formulas) + Image (perceptual hash, CNN features)
- **Multi-GPU support**: Parallel processing across 8x NVIDIA A40 GPUs
- **High precision**: >99% precision target with configurable presets
- **Scalable**: Handles 400k base images and 200k queries efficiently

## Installation

### Windows (CPU-only)

```bash
# Clone repository
cd QSearch

# Install dependencies (CPU version of Faiss)
pip install -r requirements-windows.txt
# OR with uv:
uv pip sync requirements-windows.txt

# Download pretrained models (done automatically on first run)
# - hfl/chinese-roberta-wwm-ext
# - sentence-transformers/all-mpnet-base-v2
```

### Linux with CUDA GPUs

```bash
# Clone repository
cd QSearch

# Install dependencies (GPU version of Faiss)
pip install -r requirements-linux-gpu.txt
# OR with uv:
uv pip sync requirements-linux-gpu.txt

# Verify CUDA setup
python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}, GPUs: {torch.cuda.device_count()}')"
```

### Notes

- **Windows**: Uses `faiss-cpu` (no GPU acceleration for Faiss, but PyTorch/CNN models can still use GPU)
- **Linux**: Uses `faiss-gpu` for full GPU acceleration across all components
- The system will automatically detect and use available GPUs for PyTorch operations on both platforms

## Quick Start

### 1. Index the database (400k base images)

```bash
python scripts/index_database.py \
  --image-dir /path/to/base/images \
  --output-dir ./indices \
  --preset balanced \
  --num-gpus 8
```

This will:
- Extract text features (OCR, question parsing, BERT embeddings)
- Extract image features (perceptual hashes, CNN features)
- Build Faiss vector index for text similarity
- Build hash index for exact matching
- Save indices to `./indices/`

### 2. Search queries (200k query images)

```bash
python scripts/search_queries.py \
  --query-dir /path/to/query/images \
  --index-dir ./indices \
  --output-file ./results.json \
  --preset balanced \
  --num-gpus 7
```

This will:
- Extract features from query images
- Search for exact matches (perceptual hash)
- Search for content matches (text similarity + verification)
- Save results to `results.json`

## Configuration

### Using Presets

Three built-in presets optimize for different precision/recall trade-offs:

- **conservative**: High precision (>99%), strict thresholds, fewer matches
- **balanced**: Moderate precision/recall, default configuration
- **aggressive**: High recall, loose thresholds, more matches

```bash
# Use preset
python scripts/search_queries.py --preset conservative ...
```

### Custom Configuration

Create YAML configuration files:

**config/features.yaml**:
```yaml
text:
  components:
    stem:
      enabled: true
      weight: 0.6
    options:
      enabled: true
      weight: 0.3
      normalization: [remove_whitespace, normalize_punctuation, sort]
    formulas:
      enabled: false
      weight: 0.1

image:
  components:
    perceptual_hash:
      enabled: true
      algorithm: dHash  # dHash, pHash, or aHash
      hash_size: 16
    deep_features:
      enabled: true
      model: efficientnet_b4
      output_dim: 512
  batch_size: 128

ocr:
  engine: paddleocr
  languages: [ch, en]
  confidence_threshold: 0.5
```

**config/matching.yaml**:
```yaml
exact_match:
  enabled: true
  criteria:
    perceptual_hash:
      max_distance: 5

content_match:
  enabled: true
  stage1:
    text_similarity_threshold: 0.75
    top_k: 100
  stage2:
    required_conditions:
      stem_match:
        enabled: true
        max_edit_distance: 3
      options_match:
        enabled: true
        order_independent: true
      question_type_match:
        enabled: true
    optional_conditions:
      formula_match:
        enabled: false
        weight: 0.15
      visual_similarity:
        enabled: false
        weight: 0.05
  scoring:
    method: weighted_sum
    required_weight: 0.8
    optional_weight: 0.2
    threshold: 0.85

output:
  top_k: 10
  grouping:
    by_match_type: true
  include_details:
    feature_scores: true
    debug_info: false
```

Use custom config:
```bash
python scripts/search_queries.py --config config/matching.yaml ...
```

## Output Format

Results are saved as JSON:

```json
[
  {
    "query_image": "/path/to/query/image1.jpg",
    "exact_matches": [
      {
        "image_id": "/path/to/base/image123.jpg",
        "match_type": "EXACT_MATCH",
        "distance": 2,
        "confidence": 0.992,
        "confidence_level": "HIGH",
        "scores": {
          "hash_distance": 2
        }
      }
    ],
    "content_matches": [
      {
        "image_id": "/path/to/base/image456.jpg",
        "match_type": "CONTENT_MATCH",
        "final_score": 0.89,
        "confidence": 0.89,
        "confidence_level": "MEDIUM",
        "also_exact_match": false,
        "verification_passed": ["stage1_vector", "stage2_required"],
        "scores": {
          "vector_similarity": 0.87,
          "required_score": 0.91,
          "optional_score": 0.75
        }
      }
    ],
    "processing_time_ms": 245.3
  }
]
```

## Performance Targets

- **Indexing**: 400k images in ~30 minutes (8 GPUs)
- **Query processing**: 200k queries in ~25 minutes (7 GPUs for extraction + 1 for search)
- **Single query latency**: <500ms average
- **Precision**: >99% for content matches
- **Recall**: >70% for content matches

## Hardware Requirements

- **GPUs**: 8x NVIDIA A40 (48GB VRAM each) or similar
- **RAM**: 64GB minimum
- **Storage**: ~250GB for images and indices
- **OS**: Linux or Windows with CUDA 11+

## Troubleshooting

### OOM Errors

If you encounter out-of-memory errors:
- Reduce batch size in config: `image.batch_size: 64`
- Use fewer GPUs: `--num-gpus 4`
- The system automatically reduces batch size on OOM

### CUDA Errors

Verify CUDA setup:
```python
import torch
print(torch.cuda.is_available())
print(torch.cuda.device_count())
```

### OCR Failures

Check OCR confidence in results. Low confidence (<0.5) triggers warnings.
- Improve image quality
- Enable preprocessing: denoise, CLAHE
- Adjust `ocr.confidence_threshold`

### Slow Processing

- Use GPU acceleration (automatically enabled if available)
- Increase batch size if GPU memory permits
- Use more parallel workers: `--num-gpus 8`

## Architecture

```
┌─────────────────────────────────────────────┐
│          Feature Extraction                 │
├─────────────────┬───────────────────────────┤
│   Text Features │   Image Features          │
│   - OCR (Paddle)│   - Perceptual Hash       │
│   - Stem/Options│   - CNN (EfficientNet-B4) │
│   - BERT Embed  │                           │
└─────────────────┴───────────────────────────┘
                    │
                    ▼
        ┌───────────────────────┐
        │   Indexing            │
        ├───────────────────────┤
        │ - Faiss (text vectors)│
        │ - HashIndex (images)  │
        └───────────────────────┘
                    │
                    ▼
        ┌───────────────────────┐
        │   Dual-Path Matching  │
        ├───────────────────────┤
        │ Exact: Hash distance  │
        │ Content: Text + verify│
        └───────────────────────┘
```

## API Reference

See docstrings in source files:
- `src/qsearch/config/`: Configuration management
- `src/qsearch/features/`: Feature extraction
- `src/qsearch/indexing/`: Index building
- `src/qsearch/matching/`: Matching engines

## License

See LICENSE file.
