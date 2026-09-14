## 1. Fix Indexing Script

- [x] 1.1 Change `scripts/index_database.py` line 109 from `stem_embedding` to `text_embedding` and verify the field name matches `text_extractor.py` output
- [x] 1.2 Add validation check after line 113 to warn if vectors list is empty and verify warning appears in logs when no embeddings found
- [x] 1.3 Delete existing index files in `data/index/` directory to clear outdated indexes
- [x] 1.4 Run indexing script with test data and verify `.faiss` file is created and logs show non-zero vector count

## 2. Update README.md Configuration Documentation

- [x] 2.1 Remove all references to `stem_match`, `options_match`, `question_type_match` from configuration sections and verify no occurrences remain
- [x] 2.2 Remove all references to `required_weight` and `optional_weight` from configuration sections and verify no occurrences remain
- [x] 2.3 Remove or update warnings about weight normalization (lines 610, 623, 838, 1008) and verify no instructions tell users to set weights
- [x] 2.4 Update scoring documentation to reflect actual formula `0.7 * vector_similarity + 0.3 * text_similarity` and verify it matches `matchers.py` implementation
- [x] 2.5 Update content_match structure documentation to show `optional_conditions` as direct child (not under `stage2`) and verify it matches actual YAML schema
- [x] 2.6 Update preset comparison tables to remove deleted parameters and verify only active parameters are documented
- [x] 2.7 Review troubleshooting sections and remove suggestions to adjust deleted parameters

## 3. Update config/presets/README.md

- [x] 3.1 Remove Stage 2 documentation section and verify no references to `stage2.required_conditions` remain
- [x] 3.2 Update preset parameter tables to reflect current structure and verify consistency with main README

## 4. Verification

- [x] 4.1 Run config validation to confirm YAML files still parse correctly after doc updates
- [x] 4.2 Build fresh indexes with fixed script and verify `.faiss`, `.pkl`, and `index_stats.json` are created
- [x] 4.3 Run search queries against new indexes and verify results are returned
- [x] 4.4 Review all documentation changes to ensure no broken links or incomplete edits
