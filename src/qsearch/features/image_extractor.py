"""SigLIP-based image embedding engine for document/question image retrieval."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Union

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from transformers import AutoModel, AutoProcessor
from huggingface_hub import snapshot_download


logger = logging.getLogger(__name__)


# ============================================================
# Model
# ============================================================

SIGLIP_MODEL = "google/siglip-base-patch16-224"




class ImageFeatureExtractor:
    """SigLIP image embedding engine.

    Convert document/question images into normalized vectors.

    The returned vectors are L2-normalized float32 numpy arrays,
    which can be directly used with FAISS IndexFlatIP.
    """

    def __init__(
        self,
        use_fp16: bool = True,
        use_gpu: bool = True,
        gpu_id: int = 0,
    ):

        self.normalize = True

        self.use_fp16 = use_fp16

        self.use_gpu = bool(
            use_gpu and torch.cuda.is_available()
        )

        self.gpu_id = int(gpu_id)

        if self.use_gpu:
            self.device = torch.device(
                f"cuda:{self.gpu_id}"
            )
        else:
            self.device = torch.device("cpu")

        # FP16 only makes sense on CUDA.
        self.use_fp16 = bool(
            self.use_fp16 and self.device.type == "cuda"
        )

        self._processor: Any = None
        self._model: Any = None

        self.embedding_dim: int | None = None

        self._initialize_encoders()

    # ============================================================
    # Initialization
    # ============================================================

    def _initialize_encoders(self) -> None:
        """Load SigLIP processor and model, downloading it if necessary."""
        project_root = Path(__file__).resolve().parents[3]
        models_dir = project_root / "models"
        models_dir.mkdir(parents=True, exist_ok=True)

        siglip_local = models_dir / "siglip-base-patch16-224"

        try:
            # --------------------------------------------------------
            # Download model if it does not exist locally
            # --------------------------------------------------------
            if not siglip_local.exists():
                logger.info(
                    "SigLIP model not found locally, downloading: %s",
                    SIGLIP_MODEL,
                )

                snapshot_download(
                    repo_id=SIGLIP_MODEL,
                    local_dir=str(siglip_local),
                )

                logger.info(
                    "SigLIP model downloaded to: %s",
                    siglip_local,
                )

            # --------------------------------------------------------
            # Load from local directory
            # --------------------------------------------------------
            siglip_path = str(siglip_local)

            self._processor = AutoProcessor.from_pretrained(
                siglip_path,
            )

            self._model = AutoModel.from_pretrained(
                siglip_path,
            )

            # --------------------------------------------------------
            # Move model to device
            # --------------------------------------------------------
            self._model.to(self.device)
            self._model.eval()

            if self.use_fp16:
                self._model.half()

            # --------------------------------------------------------
            # Detect embedding dimension
            # --------------------------------------------------------
            self.embedding_dim = self._get_embedding_dim()

            logger.info(
                "Loaded SigLIP embedding model from %s on %s",
                siglip_path,
                self.device,
            )

        except Exception as exc:
            logger.exception(
                "Failed to initialize SigLIP",
            )

            raise RuntimeError(
                f"Unable to load SigLIP model from {siglip_local!r}."
            ) from exc
    def _get_embedding_dim(self) -> int:
        """Get SigLIP image embedding dimension."""

        # SigLIP usually exposes projection_dim through
        # config.projection_dim.
        projection_dim = getattr(
            self._model.config,
            "projection_dim",
            None,
        )

        if projection_dim is not None:
            return int(projection_dim)

        # Fallback.
        vision_config = getattr(
            self._model.config,
            "vision_config",
            None,
        )

        if vision_config is not None:
            hidden_size = getattr(
                vision_config,
                "hidden_size",
                None,
            )

            if hidden_size is not None:
                return int(hidden_size)

        raise RuntimeError(
            "Unable to determine SigLIP embedding dimension."
        )

    def encode(
        self,
        images: Union[
            str,
            Path,
            np.ndarray,
            Image.Image,
            List[Union[str, Path, np.ndarray, Image.Image]],
        ],
    ) -> np.ndarray:
        """Encode images with SigLIP.

        The input list is treated as one batch.
        """

        single = not isinstance(images, list)

        image_list = [images] if single else images

        if not image_list:
            return np.empty(
                (0, self.embedding_dim),
                dtype=np.float32,
            )

        try:
            inputs = self._processor(
                images=image_list,
                return_tensors="pt",
            )

            inputs = {
                key: value.to(
                    self.device,
                    non_blocking=True,
                )
                if hasattr(value, "to")
                else value
                for key, value in inputs.items()
            }

            with torch.inference_mode():

                if self.use_fp16:
                    with torch.autocast(
                        device_type="cuda",
                        dtype=torch.float16,
                    ):
                        features = self._model.get_image_features(
                            **inputs
                        )
                else:
                    features = self._model.get_image_features(
                        **inputs
                    )

                if self.normalize:
                    features = F.normalize(
                        features,
                        p=2,
                        dim=-1,
                    )

            embeddings = (
                features
                .float()
                .cpu()
                .numpy()
            )

            return embeddings[0] if single else embeddings

        except Exception:
            logger.exception(
                "Image embedding failed."
            )
            raise