## 1. Project Setup and Dependencies

- [x] 1.1 Create project structure with src/qsearch module and verify directories exist (features/, matching/, config/, utils/)
- [x] 1.2 Create requirements.txt with PyTorch, Faiss-gpu, PaddleOCR, transformers, pyyaml, imagehash, opencv-python and verify pip install succeeds
- [x] 1.3 Download pretrained models (hfl/chinese-roberta-wwm-ext, sentence-transformers/all-mpnet-base-v2) and verify model loading
- [x] 1.4 Verify CUDA availability and all 8 A40 GPUs are visible via torch.cuda.device_count()
- [x] 1.5 Create configuration directory structure and verify config/features.yaml and config/matching.yaml template files exist

## 2. Configuration System

- [x] 2.1 Implement ConfigLoader class to parse YAML configuration files and verify it loads valid config without errors
- [x] 2.2 Create JSON schema for configuration validation and verify schema.validate() catches invalid configs
- [x] 2.3 Implement configuration presets (conservative, balanced, aggressive) and verify each preset loads correctly
- [x] 2.4 Add runtime configuration override mechanism and verify overrides merge correctly without mutating base config
- [x] 2.5 Implement configuration export to YAML and verify exported config round-trips successfully
- [x] 2.6 Add configuration dependency validation (e.g., formula matching requires formula extraction enabled) and verify error on invalid dependencies
- [x] 2.7 Write unit tests for ConfigLoader covering valid configs, invalid schemas, and preset loading

## 3. OCR and Text Extraction

- [x] 3.1 Implement OCREngine wrapper for PaddleOCR with Chinese/English support and verify text extraction from sample question image
- [x] 3.2 Add image preprocessing pipeline (denoise, CLAHE, resize) and verify preprocessed images have improved contrast
- [x] 3.3 Implement question structure parser to extract stem and options using regex patterns and verify extraction on multiple choice question
- [x] 3.4 Add LaTeX-OCR integration for formula extraction and verify formula extraction returns valid LaTeX strings
- [x] 3.5 Implement text normalization functions (whitespace removal, punctuation normalization, sorting) and verify "A B C" and "C B A" normalize identically
- [x] 3.6 Add OCR confidence tracking and low-confidence warnings and verify warning flag appears when confidence < 0.5
- [x] 3.7 Implement graceful OCR failure handling returning partial results and verify stem extracts even when options fail
- [x] 3.8 Write unit tests for text extraction covering successful extraction, partial failures, and normalization

## 4. Feature Extraction - Text Features

- [x] 4.1 Implement TextFeatureExtractor class with configurable components (stem, options, formulas) and verify extraction respects enabled/disabled config
- [x] 4.2 Add BERT/RoBERTa text encoding for Chinese questions using hfl/chinese-roberta-wwm-ext and verify 768-dim embeddings are generated
- [x] 4.3 Add sentence-transformers encoding for English questions and verify model switches based on language detection
- [x] 4.4 Implement option set normalization with configurable sorting and verify ["B", "A", "C"] becomes ["A", "B", "C"]
- [x] 4.5 Add question type detection (multiple choice, fill-in-blank, short answer) and verify classifier returns correct type
- [x] 4.6 Implement feature weight assignment from configuration and verify weights are included in output structure
- [x] 4.7 Write unit tests for TextFeatureExtractor covering enabled/disabled features, normalization, and encoding

## 5. Feature Extraction - Image Features

- [x] 5.1 Implement ImageFeatureExtractor class with perceptual hash computation (dHash/pHash/aHash) and verify 16x16 hash is computed
- [x] 5.2 Add CNN feature extraction using EfficientNet-B4 with configurable output dimension (default 512) and verify feature vectors have correct shape
- [x] 5.3 Implement batch image processing with GPU acceleration and verify batch of 128 images processes faster than sequential
- [x] 5.4 Add automatic batch size reduction on OOM errors and verify system reduces batch size and logs adjustment
- [x] 5.5 Implement corrupted image handling returning error records and verify corrupted image returns error with reason
- [x] 5.6 Write unit tests for ImageFeatureExtractor covering hash computation, CNN features, and error handling

## 6. Feature Extraction - Integration

- [x] 6.1 Implement FeatureExtractor orchestrator combining text and image extractors and verify both feature types are extracted
- [x] 6.2 Add parallel batch processing with multiprocessing for GPU distribution and verify 8 processes use separate GPUs
- [x] 6.3 Implement feature serialization to disk (JSON or pickle) and verify features can be saved and reloaded
- [x] 6.4 Add progress tracking with tqdm for batch processing and verify progress bar shows during 1000-image extraction
- [x] 6.5 Write integration tests covering end-to-end feature extraction on sample images

## 7. Indexing - Faiss Text Index

- [x] 7.1 Implement FaissIndexBuilder for text vectors using IndexFlatIP and verify index creation from 1000 vectors
- [x] 7.2 Add GPU acceleration for Faiss index when available and verify index moves to GPU successfully
- [x] 7.3 Implement index persistence (save/load) to disk and verify loaded index returns same results as original
- [x] 7.4 Add incremental index updates for adding new vectors and verify new vectors are searchable after add
- [x] 7.5 Implement index statistics (vector count, dimension, memory usage) and verify stats match expected values
- [x] 7.6 Write unit tests for FaissIndexBuilder covering creation, persistence, and incremental updates

## 8. Indexing - Hash Dictionary

- [x] 8.1 Implement HashIndex class as Python dict mapping hash to image IDs and verify O(1) lookup performance
- [x] 8.2 Add hash index persistence to disk (JSON or pickle) and verify loaded index matches original
- [x] 8.3 Implement collision detection for hash duplicates and verify warning when multiple images have same hash
- [x] 8.4 Write unit tests for HashIndex covering insertion, lookup, and collision detection

## 9. Matching Engine - Exact Match Path

- [x] 9.1 Implement ExactMatcher using perceptual hash distance with configurable threshold (default ≤5) and verify exact match detection on same photo
- [x] 9.2 Add confidence score computation from hash distance (1.0 - distance/256) and verify score calculation
- [x] 9.3 Implement configurable hash algorithm selection (dHash/pHash/aHash) and verify switching algorithms works
- [x] 9.4 Write unit tests for ExactMatcher covering matches below threshold, rejections above threshold, and confidence scoring

## 10. Matching Engine - Content Match Path (Stage 1: Vector Retrieval)

- [x] 10.1 Implement ContentMatcher with Faiss-based candidate retrieval and verify top-K candidates are retrieved
- [x] 10.2 Add configurable cosine similarity threshold for initial filtering (default 0.75) and verify candidates below threshold are excluded
- [x] 10.3 Implement configurable top-K for candidate retrieval (default 100) and verify correct number of candidates returned
- [x] 10.4 Write unit tests for stage 1 retrieval covering threshold filtering and top-K limiting

## 11. Matching Engine - Content Match Path (Stage 2: Text Matching)

- [x] 11.1 Implement stem matching with edit distance threshold (default 3) and verify stems differing by ≤3 characters match
- [x] 11.2 Add option set comparison with order-independent matching and verify ["A", "B", "C"] matches ["C", "B", "A"]
- [x] 11.3 Implement question type matching requirement and verify different types (multiple choice vs fill-in) are rejected
- [x] 11.4 Add optional formula matching with LaTeX similarity and verify formula scores contribute to final score
- [x] 11.5 Add optional visual similarity as secondary validation and verify image features boost confidence
- [x] 11.6 Implement weighted scoring combining required (80%) and optional (20%) conditions and verify score calculation
- [x] 11.7 Write unit tests for stage 2 matching covering stem/options/type matching and scoring

## 12. Matching Engine - Dual-Path Integration

- [x] 12.1 Implement QuestionMatcher orchestrating both exact and content match paths and verify both result types are returned
- [x] 12.2 Add result deduplication marking images appearing in both paths and verify also_exact_match flag is set correctly
- [x] 12.3 Implement per-type top-K limiting and verify each path returns at most K results
- [x] 12.4 Add detailed match metadata (scores, verification_passed, confidence_level) and verify HIGH/MEDIUM/LOW labels are assigned
- [x] 12.5 Implement processing time tracking and verify processing_time_ms is included in results
- [x] 12.6 Write integration tests for dual-path matching covering both match types and deduplication

## 13. Batch Query Processing

- [x] 13.1 Implement batch query processor with multiprocess GPU distribution (7 GPUs for extraction) and verify queries are evenly distributed
- [x] 13.2 Add result aggregation maintaining query order and verify results array matches input order
- [x] 13.3 Implement per-query error handling returning error records for failed queries and verify partial results are returned on mixed failures
- [x] 13.4 Add progress tracking across parallel processes and verify tqdm shows combined progress
- [x] 13.5 Write integration tests for batch processing covering successful batch, partial failures, and result ordering

## 14. Database Indexing Pipeline

- [x] 14.1 Implement index_database script to process 400k base images and verify features are extracted for all images
- [x] 14.2 Add checkpointing for resuming interrupted indexing and verify indexing resumes from last checkpoint
- [x] 14.3 Implement validation of built indices (count, sample searches) and verify index contains expected number of vectors
- [x] 14.4 Add performance benchmarking (throughput, memory usage) and verify indexing completes in <30 minutes
- [x] 14.5 Write end-to-end test for database indexing on 1000-image subset

## 15. Query Processing Pipeline

- [x] 15.1 Implement search_queries script to process 200k query images and verify results are generated for all queries
- [x] 15.2 Add result output to JSON format with detailed match information and verify JSON schema is valid
- [x] 15.3 Implement summary statistics (match counts, confidence distributions) and verify statistics are computed correctly
- [x] 15.4 Add performance benchmarking for query processing and verify 200k queries complete in <25 minutes
- [x] 15.5 Write end-to-end test for query processing on 100-query subset

## 16. Configuration Templates and Documentation

- [x] 16.1 Create features_config.yaml template with all available options and verify template loads without errors
- [x] 16.2 Create matching_config.yaml template with documented thresholds and verify template loads without errors
- [x] 16.3 Implement conservative preset configuration (strict thresholds) and verify preset achieves >99% precision on test set
- [x] 16.4 Implement balanced preset configuration (moderate thresholds) and verify preset balances precision/recall
- [x] 16.5 Implement aggressive preset configuration (loose thresholds) and verify preset achieves high recall
- [x] 16.6 Create configuration schema documentation in JSON Schema format and verify schema validates all presets
- [x] 16.7 Write usage examples showing how to load presets and override settings

## 17. Testing and Validation

- [x] 17.1 Create test dataset with known match pairs (exact and content matches) and verify ground truth annotations exist
- [x] 17.2 Run precision/recall evaluation on test dataset and verify metrics meet targets (precision >99%, recall >70%)
- [x] 17.3 Test edge cases (corrupted images, empty OCR, all-text questions) and verify graceful handling
- [x] 17.4 Perform memory profiling on 400k indexing and verify peak memory < 40GB per GPU
- [x] 17.5 Perform latency benchmarking on single queries and verify <500ms average latency
- [x] 17.6 Write system integration test covering full pipeline from image to match results

## 18. Documentation

- [x] 18.1 Write README.md with installation instructions and verify installation succeeds on clean environment
- [x] 18.2 Document configuration options with examples and verify examples are valid
- [x] 18.3 Create usage guide covering indexing and querying workflows and verify guide steps work as documented
- [x] 18.4 Document performance characteristics and hardware requirements and verify specs match actual system
- [x] 18.5 Add troubleshooting guide for common issues (OOM, CUDA errors, OCR failures) and verify solutions resolve issues
- [x] 18.6 Create API reference documentation for main classes and verify docstrings are complete
