## Why

The `index_database.py` script fails to build FAISS indexes due to a field name mismatch introduced when `QuestionParser` was removed. The script looks for `stem_embedding` but `text_extractor.py` now produces `text_embedding`, causing the vector list to remain empty and silently skipping index creation. Additionally, README.md contains 32 references to configuration fields (`stem_match`, `options_match`, `question_type_match`, `required_weight`, `optional_weight`) that were removed in the recent config cleanup, misleading users about available configuration options.

## What Changes

- Fix `scripts/index_database.py` to use correct field name `text_embedding` instead of `stem_embedding`
- Add explicit warning when no vectors are extracted during indexing (prevent silent failures)
- Update README.md to remove references to deleted configuration fields and update scoring documentation to reflect actual implementation
- Update `config/presets/README.md` to remove references to deleted Stage 2 structure

## Capabilities

### New Capabilities
<!-- No new capabilities - this is a bug fix and documentation update -->

### Modified Capabilities
- `question-matching/indexing`: Fix field name mismatch that prevents FAISS index creation
- `question-matching/configuration`: Update documentation to reflect actual configuration schema after recent cleanup

## Impact

**Code Changes:**
- `scripts/index_database.py`: One-line field name fix + validation check
- README.md: ~32 references to remove/update (mainly in configuration sections)
- `config/presets/README.md`: Remove Stage 2 documentation

**User Impact:**
- Users can successfully build indexes after this fix
- Documentation accurately reflects available configuration options
- Clear error messages when indexing fails

**No Breaking Changes** - This fixes broken functionality and updates docs to match reality
