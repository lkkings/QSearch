"""Faiss index builder for text vector similarity search.

Builds and manages Faiss IndexFlatIP for exact cosine similarity search.
"""

import logging
from pathlib import Path
from typing import List, Optional, Tuple

import faiss
import numpy as np

logger = logging.getLogger(__name__)


class FaissIndexBuilder:
    """Builds and manages Faiss index for text vectors."""

    def __init__(
        self,
        dimension: int = 768,
        use_gpu: bool = True,
        gpu_id: int = 0
    ):
        """Initialize Faiss index builder.

        Args:
            dimension: Vector dimension (default 768 for BERT/RoBERTa)
            use_gpu: Whether to use GPU acceleration
            gpu_id: GPU device ID
        """
        self.dimension = dimension
        self.use_gpu = use_gpu and faiss.get_num_gpus() > 0
        self.gpu_id = gpu_id

        self.index = None
        self.id_map = []  # Maps index position to image ID

        self._build_index()

    def _build_index(self):
        """Build Faiss index."""
        # Create CPU index (IndexFlatIP for inner product = cosine similarity with normalized vectors)
        cpu_index = faiss.IndexFlatIP(self.dimension)

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
            logger.info("Created CPU Faiss index")

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

        # Add to index
        self.index.add(vectors.astype(np.float32))

        # Update ID map
        self.id_map.extend(ids)

        logger.info(f"Added {len(vectors)} vectors to index. Total: {self.index.ntotal}")

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
