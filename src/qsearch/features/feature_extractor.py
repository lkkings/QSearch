"""Feature extraction orchestrator combining text and image extractors.

Coordinates text and image feature extraction with parallel batch processing.
"""

import json
import logging
import pickle
from pathlib import Path
from typing import Dict, List, Optional, Union
from multiprocessing import Pool, cpu_count

import numpy as np
from tqdm import tqdm
from PIL import Image

from .ocr_engine import OCREngine
from .text_extractor import TextFeatureExtractor
from .image_extractor import ImageFeatureExtractor

logger = logging.getLogger(__name__)



class FeatureExtractor:
    """Orchestrates text and image feature extraction."""

    def __init__(
        self,
        ocr_engine:Optional[OCREngine] = None,
        text_extractor: Optional[TextFeatureExtractor] = None,
        image_extractor: Optional[ImageFeatureExtractor] = None
    ):
        """Initialize feature extractor.

        Args:
            ocr_engine: OCR
            text_extractor: TextFeatureExtractor instance (creates default if None)
            image_extractor: ImageFeatureExtractor instance (creates default if None)
        """
        self.ocr_engine = ocr_engine
        self.text_extractor = text_extractor
        self.image_extractor = image_extractor

    def extract(
        self,
        images: Union[
            str,
            Path,
            List[str],
            List[Path],
        ],
        batch_size: int = 2,
    ) -> Union[Dict, List[dict]]:
        """Extract text and image features from images.

        Args:
            images:
                A single image path or a list of image paths.

            batch_size:
                Number of images processed in each batch.

        Returns:
            Single image:
                dict

            Multiple images:
                list[dict]
        """
        if batch_size <= 0:
            raise ValueError("batch_size must be greater than 0")

        # --------------------------------------------------
        # Normalize input
        # --------------------------------------------------
        single = isinstance(images, (str, Path))

        if single:
            image_list = [images]
        else:
            image_list = list(images)

        if not image_list:
            return {} if single else []

        # --------------------------------------------------
        # Process by batch
        # --------------------------------------------------
        results: List[dict] = []

        for start in range(0, len(image_list), batch_size):
            batch_images = image_list[start:start + batch_size]

            # OCR
            if self.ocr_engine is not None:
                texts = self.ocr_engine.extract_text(batch_images)
            else:
                texts = [""] * len(batch_images)

            # Text embedding
            if self.text_extractor is not None:
                text_embeddings = self.text_extractor.encode(texts)
            else:
                text_embeddings = None

            # Image embedding
            if self.image_extractor is not None:
                image_embeddings = self.image_extractor.encode(batch_images)
            else:
                image_embeddings = None

            # --------------------------------------------------
            # Build results
            # --------------------------------------------------
            for i, image_path in enumerate(batch_images):
                result = {
                    "image_path": str(image_path),
                    "text": texts[i] if texts is not None else "",
                    "text_features": (
                        text_embeddings[i]
                        if text_embeddings is not None
                        else None
                    ),
                    "image_features": (
                        image_embeddings[i]
                        if image_embeddings is not None
                        else None
                    ),
                }

                results.append(result)

        return results[0] if single else results