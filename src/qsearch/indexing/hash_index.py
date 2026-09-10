"""Hash index for O(1) perceptual hash lookups.

Simple dictionary-based index for fast exact match detection.
"""

import json
import logging
import pickle
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class HashIndex:
    """Dictionary-based index for perceptual hash lookups."""

    def __init__(self):
        """Initialize hash index."""
        self.hash_to_ids = defaultdict(list)  # hash_string -> list of image_ids
        self.collisions = 0

    def add(self, image_id: str, hash_value: str):
        """Add image hash to index.

        Args:
            image_id: Image identifier
            hash_value: Perceptual hash as string
        """
        if hash_value in self.hash_to_ids:
            self.collisions += 1
            logger.debug(f"Hash collision detected for {hash_value}")

        self.hash_to_ids[hash_value].append(image_id)

    def add_batch(self, hash_dict: Dict[str, str]):
        """Add multiple hashes at once.

        Args:
            hash_dict: Dictionary mapping image_id -> hash_value
        """
        for image_id, hash_value in hash_dict.items():
            self.add(image_id, hash_value)

    def lookup(self, hash_value: str) -> List[str]:
        """Lookup image IDs by hash.

        Args:
            hash_value: Perceptual hash as string

        Returns:
            List of matching image IDs
        """
        return self.hash_to_ids.get(hash_value, [])

    def lookup_similar(
        self,
        hash_value: str,
        max_distance: int = 5
    ) -> List[tuple]:
        """Lookup images with similar hashes within distance threshold.

        Args:
            hash_value: Query hash as string
            max_distance: Maximum hamming distance

        Returns:
            List of (image_id, distance) tuples
        """
        results = []

        for stored_hash, image_ids in self.hash_to_ids.items():
            distance = self._hamming_distance(hash_value, stored_hash)

            if distance <= max_distance:
                for image_id in image_ids:
                    results.append((image_id, distance))

        # Sort by distance
        results.sort(key=lambda x: x[1])

        return results

    def _hamming_distance(self, hash1: str, hash2: str) -> int:
        """Compute Hamming distance between two hash strings.

        Args:
            hash1: First hash
            hash2: Second hash

        Returns:
            Hamming distance (number of differing bits)
        """
        if len(hash1) != len(hash2):
            return max(len(hash1), len(hash2))

        # Convert hex strings to integers and XOR
        try:
            int1 = int(hash1, 16)
            int2 = int(hash2, 16)
            xor = int1 ^ int2
            # Count set bits
            return bin(xor).count('1')
        except ValueError:
            # Fallback: character-wise comparison
            return sum(c1 != c2 for c1, c2 in zip(hash1, hash2))

    def save(self, output_path: str, format: str = 'pickle'):
        """Save hash index to disk.

        Args:
            output_path: Output file path
            format: Save format ('pickle' or 'json')
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Convert defaultdict to regular dict for serialization
        data = dict(self.hash_to_ids)

        if format == 'pickle':
            with open(output_path, 'wb') as f:
                pickle.dump(data, f)
        elif format == 'json':
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        else:
            raise ValueError(f"Unknown format: {format}")

        logger.info(f"Saved hash index to {output_path}")

    def load(self, input_path: str, format: str = 'pickle'):
        """Load hash index from disk.

        Args:
            input_path: Input file path
            format: File format ('pickle' or 'json')
        """
        if format == 'pickle':
            with open(input_path, 'rb') as f:
                data = pickle.load(f)
        elif format == 'json':
            with open(input_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        else:
            raise ValueError(f"Unknown format: {format}")

        self.hash_to_ids = defaultdict(list, data)

        # Recount collisions
        self.collisions = sum(1 for ids in self.hash_to_ids.values() if len(ids) > 1)

        logger.info(f"Loaded hash index from {input_path} with {len(self.hash_to_ids)} unique hashes")

    def get_stats(self) -> dict:
        """Get index statistics.

        Returns:
            Dictionary with stats
        """
        total_entries = sum(len(ids) for ids in self.hash_to_ids.values())

        return {
            'unique_hashes': len(self.hash_to_ids),
            'total_entries': total_entries,
            'collisions': self.collisions,
            'avg_entries_per_hash': total_entries / len(self.hash_to_ids) if self.hash_to_ids else 0
        }
