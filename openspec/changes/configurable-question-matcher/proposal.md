## Why

We need to match 200,000 query question images against a database of 400,000 base question images to find identical or similar questions. The challenge is that "same question" can mean different things: sometimes we need to find the exact same photograph taken from different angles, and sometimes we need to find different images containing the same question content (same text but different layout). Current image search solutions are either too rigid (perceptual hashing only works for near-identical images) or too semantic (deep learning embeddings match visually similar but semantically different questions). We need a configurable system that can distinguish between "visually identical" and "content identical" matches, with flexible feature extraction and matching rules.

## What Changes

- **New configurable feature extraction framework** supporting text features (question stem, options, formulas), image features (perceptual hash, CNN embeddings, layout), and metadata (question type, subject)
- **Dual-path matching engine** with separate detection for "exact match" (same photograph) and "content match" (same question content in different images)
- **OCR pipeline** with PaddleOCR for Chinese/English text extraction and LaTeX-OCR for mathematical formulas
- **Text-based indexing** using BERT/RoBERTa embeddings with Faiss vector search for fast retrieval
- **YAML-based configuration system** allowing runtime adjustment of feature weights, matching thresholds, and top-K parameters
- **Batch processing** with GPU parallelization across 8x A40 GPUs for both offline indexing (400k images) and online querying (200k images)
- **Structured output** returning both match types with confidence scores, feature breakdowns, and match details

## Capabilities

### New Capabilities

- `question-matching/feature-extraction`: Extract configurable features from question images including text (OCR, structure parsing), visual (hashes, CNN embeddings), and metadata
- `question-matching/dual-path-search`: Two-stage search returning both exact matches (perceptual hash based) and content matches (text similarity based)
- `question-matching/configuration`: YAML-based configuration system for features, matching rules, thresholds, and output parameters

### Modified Capabilities

<!-- No existing capabilities are being modified -->

## Impact

**New System Components:**
- Feature extraction pipeline (OCR engines, text encoders, image encoders)
- Faiss vector indices (text and image, ~1.2GB each for 400k vectors)
- Configuration management layer
- Batch processing orchestration

**Infrastructure Requirements:**
- 8x NVIDIA A40 GPUs (48GB VRAM each)
- ~250GB storage for images and indices
- Python 3.10+ runtime with PyTorch, Faiss, PaddleOCR, transformers

**External Dependencies:**
- PaddleOCR (text OCR)
- LaTeX-OCR (formula recognition)
- Faiss (vector search)
- sentence-transformers/hfl models (text encoding)
- timm (image models)

**Performance Targets:**
- Offline indexing: 400k images in ~30 minutes
- Online search: 200k queries in ~20 minutes (with 8 GPU parallelization)
- Single query latency: <500ms (including all stages)
