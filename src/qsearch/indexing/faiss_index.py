"""Faiss index builder for text vector similarity search.

Supports Flat (exact), IVFFlat, IVFPQ and HNSW indexes. All use inner product
on L2-normalized vectors, which is equivalent to cosine similarity.
"""

import logging
from pathlib import Path
from typing import List, Optional, Tuple

import faiss
import numpy as np

logger = logging.getLogger(__name__)


class FaissIndexBuilder:
    """Builds and manages Faiss index for text vectors."""

    #: Index types this builder knows how to create.
    SUPPORTED_TYPES = ('Flat', 'IVFFlat', 'IVFPQ', 'HNSW')

    # Faiss wants at least this many training vectors per centroid before it
    # stops warning about an under-trained quantizer.
    MIN_VECTORS_PER_CENTROID = 39

    def __init__(
        self,
        dimension: int = 768,
        use_gpu: bool = True,
        gpu_id: int = 0,
        index_type: str = 'Flat',
        nlist: int = 100,
        nprobe: int = 10,
        m_pq: int = 16,
        nbits: int = 8,
        hnsw_m: int = 16,
        ef_construction: int = 40,
        ef_search: int = 32
    ):
        """Initialize Faiss index builder.

        Args:
            dimension: Vector dimension (default 768 for BERT/RoBERTa)
            use_gpu: Whether to use GPU acceleration
            gpu_id: GPU device ID
            index_type: One of Flat, IVFFlat, IVFPQ, HNSW
            nlist: Number of Voronoi cells (IVFFlat, IVFPQ)
            nprobe: Cells visited per query (IVFFlat, IVFPQ)
            m_pq: Product quantizer sub-vector count (IVFPQ); must divide dimension
            nbits: Bits per PQ sub-quantizer (IVFPQ)
            hnsw_m: Neighbours per node in the HNSW graph
            ef_construction: HNSW build-time candidate list size
            ef_search: HNSW query-time candidate list size

        Raises:
            ValueError: If index_type is unknown or m_pq does not divide dimension
        """
        if index_type not in self.SUPPORTED_TYPES:
            raise ValueError(
                f"Unknown index_type {index_type!r}. "
                f"Supported: {', '.join(self.SUPPORTED_TYPES)}"
            )

        if index_type == 'IVFPQ' and dimension % m_pq != 0:
            raise ValueError(
                f"m_pq={m_pq} must divide dimension={dimension} for IVFPQ"
            )

        self.dimension = dimension
        self.use_gpu = use_gpu and faiss.get_num_gpus() > 0
        self.gpu_id = gpu_id

        self.index_type = index_type
        self.nlist = nlist
        self.nprobe = nprobe
        self.m_pq = m_pq
        self.nbits = nbits
        self.hnsw_m = hnsw_m
        self.ef_construction = ef_construction
        self.ef_search = ef_search

        self.index = None
        self.id_map = []  # Maps index position to image ID

        self._build_index()

    def _build_index(self):
        """Build Faiss index according to index_type."""
        cpu_index = self._create_cpu_index()

        if self.use_gpu:
            try:
                # Move to GPU
                res = faiss.StandardGpuResources()
                self.index = faiss.index_cpu_to_gpu(res, self.gpu_id, cpu_index)
                logger.info(f"Created GPU Faiss index on GPU {self.gpu_id}")
            except Exception as e:
                logger.warning(f"Failed to create GPU index: {e}, using CPU")
                self.index = cpu_index
                self.use_gpu = False
        else:
            self.index = cpu_index
            logger.info(f"Created CPU Faiss index ({self.index_type})")

    def _create_cpu_index(self) -> faiss.Index:
        """Create the CPU-side index for the configured type.

        All variants use inner product so that L2-normalized vectors give
        cosine similarity.

        Returns:
            An untrained Faiss index
        """
        if self.index_type == 'Flat':
            return faiss.IndexFlatIP(self.dimension)

        if self.index_type == 'IVFFlat':
            quantizer = faiss.IndexFlatIP(self.dimension)
            index = faiss.IndexIVFFlat(
                quantizer, self.dimension, self.nlist, faiss.METRIC_INNER_PRODUCT
            )
            index.nprobe = self.nprobe
            return index

        if self.index_type == 'IVFPQ':
            quantizer = faiss.IndexFlatIP(self.dimension)
            index = faiss.IndexIVFPQ(
                quantizer, self.dimension, self.nlist, self.m_pq, self.nbits
            )
            index.nprobe = self.nprobe
            return index

        # HNSW
        index = faiss.IndexHNSWFlat(
            self.dimension, self.hnsw_m, faiss.METRIC_INNER_PRODUCT
        )
        index.hnsw.efConstruction = self.ef_construction
        index.hnsw.efSearch = self.ef_search
        return index

    def add_vectors(
        self,
        vectors: np.ndarray,
        ids: List[str]
    ):
        """Add vectors to index.

        Args:
            vectors: Numpy array of shape (n, dimension)
            ids: List of image IDs corresponding to vectors
        """
        if vectors.shape[1] != self.dimension:
            raise ValueError(f"Vector dimension {vectors.shape[1]} doesn't match index dimension {self.dimension}")

        # Normalize vectors for cosine similarity
        vectors = self._normalize_vectors(vectors)
        vectors = vectors.astype(np.float32)

        # IVF variants must be trained before they accept vectors. Training on
        # the same set we are about to add is standard for a one-shot build.
        if not self.index.is_trained:
            self._train(vectors)

        self.index.add(vectors)

        # Update ID map
        self.id_map.extend(ids)

        logger.info(f"Added {len(vectors)} vectors to index. Total: {self.index.ntotal}")

    def _train(self, vectors: np.ndarray):
        """Train the quantizer of an IVF index.

        Faiss needs roughly 39 vectors per centroid. With fewer vectors it still
        trains but logs a warning and produces poorly balanced cells, so nlist is
        reduced to fit the data rather than leaving a degenerate index behind.

        Args:
            vectors: Normalized float32 training vectors
        """
        n = len(vectors)
        max_centroids = max(1, n // self.MIN_VECTORS_PER_CENTROID)

        if self.nlist > max_centroids:
            logger.warning(
                f"nlist={self.nlist} is too large for {n} vectors; "
                f"reducing to {max_centroids}"
            )
            self.nlist = max_centroids
            self.index = self._create_cpu_index()
            if self.use_gpu:
                try:
                    res = faiss.StandardGpuResources()
                    self.index = faiss.index_cpu_to_gpu(res, self.gpu_id, self.index)
                except Exception as e:
                    logger.warning(f"Failed to move rebuilt index to GPU: {e}")
                    self.use_gpu = False

        logger.info(f"Training {self.index_type} index on {n} vectors")
        self.index.train(vectors)

    def search(
        self,
        query_vectors: np.ndarray,
        k: int = 100,
        threshold: Optional[float] = None
    ) -> List[List[Tuple[str, float]]]:
        """Search for k nearest neighbors.

        Args:
            query_vectors: Query vectors of shape (n, dimension)
            k: Number of neighbors to return
            threshold: Optional similarity threshold (filter results below this)

        Returns:
            List of results for each query. Each result is list of (id, similarity_score) tuples
        """
        if self.index.ntotal == 0:
            logger.warning("Index is empty")
            return [[] for _ in range(len(query_vectors))]

        # Normalize query vectors
        query_vectors = self._normalize_vectors(query_vectors)

        # Search
        k_actual = min(k, self.index.ntotal)
        similarities, indices = self.index.search(query_vectors.astype(np.float32), k_actual)

        # Convert to results with IDs
        results = []
        for i in range(len(query_vectors)):
            query_results = []
            for j in range(k_actual):
                idx = indices[i][j]
                sim = float(similarities[i][j])

                # Skip invalid indices
                if idx < 0 or idx >= len(self.id_map):
                    continue

                # Apply threshold filter
                if threshold is not None and sim < threshold:
                    continue

                image_id = self.id_map[idx]
                query_results.append((image_id, sim))

            results.append(query_results)

        return results

    def _normalize_vectors(self, vectors: np.ndarray) -> np.ndarray:
        """Normalize vectors to unit length for cosine similarity.

        Args:
            vectors: Input vectors

        Returns:
            Normalized vectors
        """
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        # Avoid division by zero
        norms = np.where(norms == 0, 1, norms)
        return vectors / norms

    def save(self, index_path: str, id_map_path: str):
        """Save index and ID map to disk.

        Args:
            index_path: Path to save index file
            id_map_path: Path to save ID map file
        """
        index_path = Path(index_path)
        id_map_path = Path(id_map_path)

        # Create directories
        index_path.parent.mkdir(parents=True, exist_ok=True)
        id_map_path.parent.mkdir(parents=True, exist_ok=True)

        # Save index (move to CPU first if on GPU)
        if self.use_gpu:
            cpu_index = faiss.index_gpu_to_cpu(self.index)
            faiss.write_index(cpu_index, str(index_path))
        else:
            faiss.write_index(self.index, str(index_path))

        # Save ID map
        import pickle
        with open(id_map_path, 'wb') as f:
            pickle.dump(self.id_map, f)

        logger.info(f"Saved index to {index_path} and ID map to {id_map_path}")

    def load(self, index_path: str, id_map_path: str):
        """Load index and ID map from disk.

        Args:
            index_path: Path to index file
            id_map_path: Path to ID map file
        """
        # Load index
        cpu_index = faiss.read_index(str(index_path))

        # Move to GPU if requested
        if self.use_gpu:
            try:
                res = faiss.StandardGpuResources()
                self.index = faiss.index_cpu_to_gpu(res, self.gpu_id, cpu_index)
            except Exception as e:
                logger.warning(f"Failed to move index to GPU: {e}")
                self.index = cpu_index
                self.use_gpu = False
        else:
            self.index = cpu_index

        # Load ID map
        import pickle
        with open(id_map_path, 'rb') as f:
            self.id_map = pickle.load(f)

        logger.info(f"Loaded index from {index_path} with {self.index.ntotal} vectors")

    def get_stats(self) -> dict:
        """Get index statistics.

        Returns:
            Dictionary with index stats
        """
        return {
            'total_vectors': self.index.ntotal,
            'dimension': self.dimension,
            'use_gpu': self.use_gpu,
            'gpu_id': self.gpu_id if self.use_gpu else None,
            'memory_bytes': self.index.ntotal * self.dimension * 4  # Approximate
        }

    def apply_search_params(self):
        """Apply search-time parameters to the loaded index.

        Must be called after load() to restore nprobe/efSearch settings, since
        loading from disk overwrites the index object and discards constructor params.

        Only affects index types that have search-time tuning knobs: IVF* for nprobe,
        HNSW for efSearch. Flat indexes have no search-time parameters.
        """
        if self.index is None:
            return

        # Extract the CPU index for parameter setting
        cpu_index = self.index
        if self.use_gpu:
            try:
                cpu_index = faiss.index_gpu_to_cpu(self.index)
            except Exception:
                pass  # Already CPU or extraction failed, work with what we have

        # Apply IVF nprobe (for IVFFlat, IVFPQ)
        if hasattr(cpu_index, 'nprobe'):
            cpu_index.nprobe = self.nprobe
            logger.debug(f"Applied nprobe={self.nprobe} to {self.index_type} index")

        # Apply HNSW efSearch
        if hasattr(cpu_index, 'hnsw') and hasattr(cpu_index.hnsw, 'efSearch'):
            cpu_index.hnsw.efSearch = self.ef_search
            logger.debug(f"Applied efSearch={self.ef_search} to HNSW index")

        # If we extracted to CPU, we don't need to move back since the changes
        # apply to the underlying index object referenced by both GPU and CPU wrappers
