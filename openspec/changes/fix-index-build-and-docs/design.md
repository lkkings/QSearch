## Context

The indexing script and documentation became misaligned after removing `QuestionParser`:
- `text_extractor.py` was updated to output `text_embedding` instead of `stem_embedding`
- `matchers.py` was updated to read `text_embedding`
- `index_database.py` was not updated, still reads `stem_embedding` → always returns None
- Config cleanup removed `stem_match`, `options_match`, `question_type_match`, `required_weight`, `optional_weight` from code but not from README

Current silent failure: empty vectors list → `if vectors:` evaluates False → index save block skipped → no error logged.

## Goals / Non-Goals

**Goals:**
- Fix field name mismatch in `index_database.py` (one line change)
- Add explicit validation to prevent silent indexing failures
- Update README.md to remove all references to deleted config fields
- Document actual scoring formula instead of obsolete weight-based formula

**Non-Goals:**
- Not rebuilding existing indexes (users must re-run after fix)
- Not changing the actual matching logic or scoring implementation
- Not adding new configuration options

## Decisions

### Decision 1: Add validation instead of just fixing the bug

**Rationale:** The bug was silent because the code path has no validation that vectors were actually collected. Adding a check prevents similar issues in the future.

**Approach:**
```python
if not vectors:
    logger.warning("No text embeddings extracted - index will not be created")
# else: proceed with save
```

**Alternatives considered:**
- Just fix the field name: Simpler but leaves silent failure path open
- Raise exception: Too aggressive - might break existing workflows that expect graceful handling

**Choice:** Warning + skip is consistent with existing error handling patterns in the codebase.

### Decision 2: Document actual implementation vs ideal design

**Rationale:** README described a sophisticated two-stage matching system with required/optional conditions and weighted scoring. The actual implementation uses simple `0.7*vec + 0.3*text`. Documentation should reflect reality, not aspirations.

**Approach:**
- Remove all references to deleted config fields
- Document the actual scoring formula used in `matchers.py`
- Remove warnings about weight normalization (no longer applicable)
- Keep preset comparison but only for parameters that actually vary

**Alternatives considered:**
- Leave "coming soon" notes for removed features: Creates false expectations
- Remove all detailed config docs: Too extreme - users still need to understand presets

**Choice:** Accurate reflection of current state with no forward-looking promises.

## Risks / Trade-offs

**Risk:** Users with existing indexes will need to rebuild them
→ **Mitigation:** Clear note in tasks.md to delete old `data/index/` directory before re-running

**Risk:** Documentation updates are extensive (~32 occurrences) - might introduce new errors
→ **Mitigation:** Focus on removing obsolete content rather than rewriting. Use search-and-replace for field names, manual review for warnings about weights.

**Trade-off:** Adding validation makes indexing slightly slower (one extra `if` check)
→ **Acceptable:** Negligible performance impact vs. debugging time saved

## Migration Plan

1. Users apply the fix to `index_database.py`
2. Delete old index files: `rm -rf data/index/*`
3. Re-run indexing: `python scripts/index_database.py --image-dir data/images --output-dir data/index`
4. Verify `.faiss` files are created and logs show vector count > 0
5. Test search: `python scripts/search_queries.py` with corrected `--index-dir data/index`

No rollback needed - this is a bug fix with no breaking changes to the API or config schema.
