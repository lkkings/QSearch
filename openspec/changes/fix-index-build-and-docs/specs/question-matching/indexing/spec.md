## Purpose

Builds searchable indexes from extracted question features to enable fast similarity-based retrieval.

## MODIFIED Requirements

### Requirement: Feature extraction uses correct field names

The indexing process SHALL use the `text_embedding` field from extracted features, matching the output schema of `text_extractor.py`.

#### Scenario: Building text vector index

- **WHEN** indexing script processes extracted features
- **THEN** system reads `text_features.text_embedding` from each feature dict
- **AND** adds non-null embeddings to the FAISS index
- **AND** saves the index to disk with corresponding ID mappings

#### Scenario: Empty embedding field detected

- **WHEN** a feature dict has `text_features.text_embedding` set to None
- **THEN** system skips that entry (does not add to vectors list)
- **AND** continues processing remaining features

### Requirement: Silent failure prevention

The indexing process SHALL explicitly validate that vectors were collected before attempting to save the index.

#### Scenario: No vectors extracted

- **WHEN** indexing completes with an empty vectors list
- **THEN** system logs a WARNING message indicating zero vectors were extracted
- **AND** does NOT silently skip index creation
- **AND** writes index statistics showing `text_vectors: 0`

#### Scenario: Successful vector extraction

- **WHEN** indexing completes with non-empty vectors list
- **THEN** system saves FAISS index to disk
- **AND** logs confirmation with vector count
- **AND** writes index statistics showing actual vector count
