## Context

Current system needs to match 200k query question images against 400k base images. Two distinct matching scenarios exist: (1) finding the exact same photograph with minor variations (angle, lighting), and (2) finding different photographs containing identical question content (same text but different layout or source). Existing solutions don't handle this dual requirement - perceptual hashing only catches scenario 1, while semantic embeddings alone miss exact text requirements in scenario 2.

Constraints:
- 8x NVIDIA A40 GPUs (48GB VRAM each) available
- Batch processing acceptable (not real-time streaming)
- User requires high precision (no false positives preferred over missing matches)
- Questions are primarily Chinese with English and mathematical formulas
- Image quality varies (printed photos, screenshots, different resolutions)

See proposal.md - Why for business motivation.

## Goals / Non-Goals

**Goals:**
- Enable dual-path matching with clear separation between exact and content matches
- Support flexible configuration without code changes (thresholds, features, weights)
- Achieve <30min indexing for 400k images, <25min search for 200k queries
- Maintain 99%+ precision for content matches (tolerate lower recall)
- Provide detailed match diagnostics for validation

**Non-Goals:**
- Real-time single-query latency <100ms (batch processing is acceptable)
- Training custom models (use pretrained models only)
- Supporting non-question image types (general image search)
- Distributed deployment across multiple machines (single-node multi-GPU is sufficient)
- Web UI or REST API (Python library interface sufficient for initial version)

## Decisions

### Decision 1: OCR-first architecture with text as primary matching signal

**Choice:** Extract text via OCR first, use text embeddings for primary retrieval, with image features as secondary validation.

**Rationale:**
- Content match requirement (same question in different images) cannot be satisfied by image features alone
- Text is the authoritative source of question identity
- Image features useful for exact match path and validation but not primary signal

**Alternatives considered:**
- Image-only with CNN embeddings: Would miss content matches where layout differs significantly
- Multimodal models (CLIP): Too semantic - would match "similar" questions not "identical" questions
- Hybrid retrieval without OCR: Cannot distinguish "same text" from "visually similar"

### Decision 2: Faiss with CPU/GPU IndexFlatIP over Milvus

**Choice:** Use Faiss library directly with IndexFlatIP for exact cosine similarity search, deployable on both CPU and GPU.

**Rationale:**
- Milvus is server-based system requiring separate service management
- 400k vectors is small enough for in-memory exact search (<2GB)
- Exact search ensures no false negatives from approximate indexing
- Single-process deployment simpler for batch use case
- Faiss supports GPU acceleration when available

**Alternatives considered:**
- Milvus: Overengineered for single-node batch processing, adds operational complexity
- Approximate indices (IVF, HNSW): Unnecessary complexity given dataset size and exact search speed (~10ms with GPU)
- Elasticsearch: Text-optimized not vector-optimized, slower for dense embeddings

### Decision 3: Three-spec capability structure

**Choice:** Split into three capabilities: feature-extraction, dual-path-search, configuration

**Rationale:**
- Feature extraction is independently testable and reusable
- Dual-path search encapsulates matching logic
- Configuration is cross-cutting concern
- Clear boundaries enable parallel development

**Alternatives considered:**
- Single monolithic spec: Would blur boundaries between concerns
- Five+ specs (separate OCR, indexing, etc.): Over-fragmentation for scope of change

### Decision 4: PaddleOCR + LaTeX-OCR combination

**Choice:** PaddleOCR for Chinese/English text, LaTeX-OCR for mathematical formulas, separate extraction passes.

**Rationale:**
- PaddleOCR has superior Chinese accuracy (>95%) and is open source
- LaTeX-OCR specialized for mathematical notation
- Separate passes allow independent confidence scoring

**Alternatives considered:**
- Tesseract only: Poor Chinese support
- Mathpix API: Commercial cost per image prohibitive for 400k+ images
- Single OCR for both text and formulas: No general-purpose model handles both well

### Decision 5: BERT/RoBERTa text encoding over sentence-transformers

**Choice:** Use hfl/chinese-roberta-wwm-ext for Chinese questions, sentence-transformers/all-mpnet-base-v2 for English.

**Rationale:**
- RoBERTa provides 768-dim dense embeddings suitable for similarity search
- hfl models specifically optimized for Chinese
- Pretrained models avoid training data requirements
- Dimension (768) balances expressiveness and memory

**Alternatives considered:**
- OpenAI embeddings: API cost and latency prohibitive for batch processing
- Smaller models (MiniLM): Lower accuracy on Chinese text
- Larger models (XLM-RoBERTa-large): Marginal accuracy gain not worth 3x slower inference

### Decision 6: Dual-index strategy (text + hash)

**Choice:** Maintain separate Faiss index for text vectors and Python dict for perceptual hashes.

**Rationale:**
- Different access patterns: vector search (approximate k-NN) vs exact hash lookup (O(1))
- Perceptual hash lookup is fast enough without indexing structure
- Separation simplifies exact match path (no vector computation needed)

**Alternatives considered:**
- Single unified index: Would require unnecessary vector computation for exact matches
- Image vector index: Perceptual hash is faster and more appropriate for exact duplicate detection

### Decision 7: YAML configuration with runtime overrides

**Choice:** YAML files for persistent configuration, Python dict overrides at query time.

**Rationale:**
- YAML is human-readable and supports comments
- Runtime overrides enable experimentation without file changes
- Schema validation at load time prevents invalid configurations

**Alternatives considered:**
- JSON: Less readable, no comments
- Python config files: Security risk (code execution), harder to validate
- Database storage: Overkill for configuration data

### Decision 8: Multiprocess parallelization over multithreading

**Choice:** Use Python multiprocessing to distribute work across 8 GPUs, one process per GPU.

**Rationale:**
- Python GIL limits multithreading effectiveness for CPU-bound work
- Each process has dedicated GPU for clean resource isolation
- ProcessPoolExecutor provides clean API

**Alternatives considered:**
- Ray for distributed computing: Unnecessary complexity for single-node
- Threading: GIL contention limits scalability
- Single process with GPU switching: Adds complexity, no benefit over multiprocess

## Risks / Trade-offs

### Risk: OCR errors propagate to matching

**Impact:** Low OCR confidence or errors could cause missed matches or false matches.

**Mitigation:**
- Include OCR confidence scores in output for filtering
- Multiple normalization strategies (whitespace, punctuation) to handle minor errors
- Edit distance threshold allows small OCR mistakes
- Image features provide validation layer

### Risk: Memory usage with large batch sizes

**Impact:** 256 image batch could exceed GPU memory on complex models.

**Mitigation:**
- Implement automatic batch size reduction on OOM
- Start with conservative batch size (128) and scale up
- Monitor GPU memory usage during indexing phase

### Risk: Configuration complexity leads to errors

**Impact:** Many configuration options could lead to invalid combinations.

**Mitigation:**
- JSON Schema validation on load
- Provide well-tested presets (conservative, balanced, aggressive)
- Validate feature dependencies (e.g., formula matching requires formula extraction)
- Clear error messages with field paths

### Trade-off: Exact search over approximate

**Chosen:** IndexFlatIP (exact) over IVF/HNSW (approximate)

**Cost:** Slightly slower search (~10ms vs ~2ms per query)

**Benefit:** Zero false negatives from approximate indexing, simpler implementation

**Justification:** At 400k scale, exact search is fast enough (<500ms for 200k queries in batch). Precision requirement favors exact over speed.

### Trade-off: Pretrained models over fine-tuning

**Chosen:** Use pretrained embeddings without fine-tuning

**Cost:** Potentially lower accuracy than domain-specific fine-tuned model

**Benefit:** No training data required, faster implementation, proven model quality

**Justification:** Pretrained models sufficient for text similarity task. Fine-tuning requires labeled question pairs (unavailable per proposal).

### Risk: Perceptual hash false negatives on heavy edits

**Impact:** Same photograph with crops, overlays, or filters may not match via hash.

**Mitigation:**
- Multi-scale hash computation (optional feature for future)
- Fallback to CNN features for exact match candidates
- Document limitations in user guide

### Trade-off: Python implementation over compiled language

**Chosen:** Pure Python with PyTorch/Faiss (C++ backends)

**Cost:** Some overhead compared to full C++/Rust implementation

**Benefit:** Faster development, rich ML ecosystem, easier maintenance

**Justification:** Performance dominated by GPU computation and Faiss (both use C++/CUDA backends). Python overhead negligible in overall pipeline.

## Migration Plan

**Phase 1: Development Environment Setup**
1. Install dependencies (PyTorch, Faiss, PaddleOCR, transformers)
2. Download pretrained models (RoBERTa, EfficientNet, LaTeX-OCR)
3. Verify GPU visibility and CUDA compatibility

**Phase 2: Initial Indexing**
1. Run feature extraction on 400k base images (save to disk for iterating)
2. Build Faiss text index and hash dictionary
3. Persist indices to disk
4. Validate index load/save cycle

**Phase 3: Query Testing**
1. Start with small test set (100 queries)
2. Validate both match paths return expected results
3. Tune thresholds using test set
4. Scale to full 200k queries

**Phase 4: Configuration Optimization**
1. Create preset configurations (conservative, balanced, aggressive)
2. Document configuration schema
3. Provide example YAML files

**Rollback:**
- No rollback needed (new system, not replacing existing)
- Keep base images and query images for re-indexing if needed
- Configuration changes are non-destructive (restart with different config)

## Open Questions

None - all design-level decisions resolved. Implementation details (specific layer names, exact hyperparameters for preprocessing) can be determined during coding.
