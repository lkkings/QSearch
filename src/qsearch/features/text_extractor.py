"""Text feature extraction from question images.

Two steps only:
    1. OCR the image into plain text.
    2. Encode that text into a semantic vector with BERT/RoBERTa.
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Union

import numpy as np
import torch
from huggingface_hub import snapshot_download
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

CHINESE_EMBEDDING_MODEL = "richinfoai/ritrieve_zh_v1"
ENGLISH_EMBEDDING_MODEL ="BAAI/bge-base-en-v1.5"


def simple_normalize_text(text: str) -> str:
    """Simple text normalization without external dependencies.

    Args:
        text: Input text

    Returns:
        Normalized text
    """
    if not text:
        return ""
    normalized = ' '.join(text.split())
    return normalized


class TextFeatureExtractor:
    """Extracts text features from question images."""

    def __init__(
        self,
        max_length: int = 2048,
        use_gpu: bool = True,
        gpu_id: int = 0,
    ):
        """Initialize text feature extractor.

        Args:
            preprocessor: Image preprocessor (creates default if None)
            use_gpu: Whether to use CUDA when it is available
            gpu_id: CUDA device index
        """
        self.max_length = max_length
        self.use_gpu = bool(use_gpu and torch.cuda.is_available())
        self.gpu_id = int(gpu_id)
        self.device = torch.device(f'cuda:{self.gpu_id}' if self.use_gpu else 'cpu')

        # Initialize text encoders
        self._chinese_encoder = None
        self._english_encoder = None

        self._initialize_encoders()

    
    def _initialize_encoders(self) -> None:
        """Initialize Chinese and English sentence embedding models."""
        project_root = Path(__file__).resolve().parents[3]
        models_dir = project_root / "models"
        models_dir.mkdir(parents=True, exist_ok=True)

        # ============================================================
        # Chinese embedding model
        # ============================================================

        chinese_local = models_dir / "ritrieve_zh_v1"

        try:
            if not chinese_local.exists():
                logger.info(
                    "Chinese embedding model not found locally, "
                    "downloading: %s",
                    CHINESE_EMBEDDING_MODEL,
                )

                snapshot_download(
                    repo_id=CHINESE_EMBEDDING_MODEL,
                    local_dir=str(chinese_local),
                )

                logger.info(
                    "Chinese embedding model downloaded to: %s",
                    chinese_local,
                )

            self._chinese_encoder = SentenceTransformer(
                str(chinese_local),
                device=self.device,
            )

            self._chinese_encoder.eval()

            logger.info(
                "Loaded Chinese embedding model from %s on %s",
                chinese_local,
                self.device,
            )

        except Exception as exc:
            logger.exception(
                "Failed to load Chinese embedding model",
            )

            raise RuntimeError(
                f"Unable to load Chinese embedding model "
                f"from {chinese_local!r}."
            ) from exc

        # ============================================================
        # English embedding model
        # ============================================================

        english_local = models_dir / "bge-base-en-v1.5"

        try:
            if not english_local.exists():
                logger.info(
                    "English embedding model not found locally, "
                    "downloading: %s",
                    ENGLISH_EMBEDDING_MODEL,
                )

                snapshot_download(
                    repo_id=ENGLISH_EMBEDDING_MODEL,
                    local_dir=str(english_local),
                )

                logger.info(
                    "English embedding model downloaded to: %s",
                    english_local,
                )

            self._english_encoder = SentenceTransformer(
                str(english_local),
                device=self.device,
            )

            self._english_encoder.eval()

            logger.info(
                "Loaded English embedding model from %s on %s",
                english_local,
                self.device,
            )

        except Exception as exc:
            logger.exception(
                "Failed to load English embedding model",
            )

            raise RuntimeError(
                f"Unable to load English embedding model "
                f"from {english_local!r}."
            ) from exc 
    def encode(
        self,
        texts: Union[str, List[str]],
    ) -> np.ndarray:
        """Encode one or multiple texts into normalized embeddings.

        Args:
            texts: A single text or a list of texts.

        Returns:
            A single embedding with shape [D] for one text,
            or embeddings with shape [N, D] for multiple texts.
        """
        single = isinstance(texts, str)

        if single:
            texts = [texts]

        texts = [
            simple_normalize_text(text)
            for text in texts
        ]

        if not texts:
            return np.empty((0, 0), dtype=np.float32)

        results = [None] * len(texts)

        chinese_indices = []
        chinese_texts = []

        english_indices = []
        english_texts = []

        for index, text in enumerate(texts):
            if not text:
                continue

            language = self._detect_language(text)

            if language == "zh":
                chinese_indices.append(index)
                chinese_texts.append(text)

            elif language == "en":
                english_indices.append(index)
                english_texts.append(text)

            else:
                logger.warning(
                    "Unsupported language for text[%d]",
                    index,
                )

        # Chinese
        if chinese_texts:
            if self._chinese_encoder is None:
                raise RuntimeError("Chinese embedding model is not initialized.")

            embeddings = self._chinese_encoder.encode(
                chinese_texts,
                batch_size=len(chinese_texts),
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )

            for index, embedding in zip(chinese_indices, embeddings):
                results[index] = embedding.astype(np.float32)

        # English
        if english_texts:
            if self._english_encoder is None:
                raise RuntimeError("English embedding model is not initialized.")

            embeddings = self._english_encoder.encode(
                english_texts,
                batch_size=len(english_texts),
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )

            for index, embedding in zip(english_indices, embeddings):
                results[index] = embedding.astype(np.float32)

        valid_embeddings = [
            embedding for embedding in results
            if embedding is not None
        ]

        if not valid_embeddings:
            return np.empty((0, 0), dtype=np.float32)

        dimensions = {
            embedding.shape[0]
            for embedding in valid_embeddings
        }

        if len(dimensions) > 1:
            raise ValueError(
                f"Embedding dimensions are inconsistent: {dimensions}. "
                "Chinese and English embeddings must use separate indexes."
            )

        dimension = valid_embeddings[0].shape[0]

        output = np.zeros(
            (len(texts), dimension),
            dtype=np.float32,
        )

        for index, embedding in enumerate(results):
            if embedding is not None:
                output[index] = embedding

        return output[0] if single else output
    
    def _detect_language(self, text: str) -> str:
        """Detect whether text is primarily Chinese or English."""
        chinese = 0
        english = 0

        for char in text:
            if "\u4e00" <= char <= "\u9fff":
                chinese += 1
            elif char.isascii() and char.isalpha():
                english += 1

        if chinese == 0 and english == 0:
            return "unknown"

        return "zh" if chinese >= english else "en"
                
