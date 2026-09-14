"""Transformer-based OCR for Chinese and English question images."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Union

import numpy as np
import torch
from PIL import Image
from huggingface_hub import snapshot_download
from transformers import AutoModelForImageTextToText, AutoProcessor


logger = logging.getLogger(__name__)

OCR_MODEL = "stepfun-ai/GOT-OCR-2.0-hf"



class OCREngine:
    """Load and run a Hugging Face Transformers OCR model.

    The model is downloaded once, then saved as a normal ``save_pretrained``
    directory below the project's ``models`` folder. With more than one CUDA
    device, Transformers/Accelerate automatically distributes the model across
    all visible GPUs. A single GPU is selected with ``gpu_id``; CPU is always a
    supported fallback.
    """

    def __init__(
        self,
        max_new_tokens: int = 2048,
        use_gpu: bool = True,
        gpu_id: int = 0
    ):
        self.use_gpu = bool(use_gpu and torch.cuda.is_available())
        self.gpu_id = int(gpu_id)
        self.device = torch.device(f'cuda:{self.gpu_id}' if self.use_gpu else 'cpu')
        self._processor: Any = None
        self._ocr_engine: Any = None
        self._initialize_engine()

    def _initialize_engine(self) -> None:
        """Load the local OCR model, downloading and persisting it if needed."""
        project_root = Path(__file__).resolve().parents[3]
        models_dir = project_root / "models"
        models_dir.mkdir(parents=True, exist_ok=True)
        

        # ============================================================
        # Chinese embedding model
        # ============================================================

        ocr_local = models_dir / "got-ocr-2.0-hf"
        ocr_path = (
            str(ocr_local)
            if ocr_local.exists()
            else OCR_MODEL
        )

        try:
            # 本地不存在则下载到指定目录
            if not ocr_local.exists():
                logger.info(
                    "OCR model not found locally, downloading: %s",
                    OCR_MODEL,
                )

                snapshot_download(
                    repo_id=OCR_MODEL,
                    local_dir=str(ocr_local),
                )

                logger.info(
                    "OCR model downloaded to: %s",
                    ocr_local,
                )

            # 始终从本地目录加载
            self._processor = AutoProcessor.from_pretrained(
                str(ocr_local),
            )

            self._ocr_engine = AutoModelForImageTextToText.from_pretrained(
                str(ocr_local),
            )
            self._ocr_engine.to(self.device)
            self._ocr_engine.eval()
            logger.info(
                f"Loaded OCR model from "
                f"{ocr_path} on {self.device}"
            )
        except Exception as exc:
            logger.error("Failed to initialize OCR: %s", exc)
            raise RuntimeError(
                f"Unable to load OCR model {ocr_path!r}. The first run requires "
                f"network access; the model is then stored in {models_dir}."
            ) from exc
            
    def extract_text(
        self,
        images: Union[
            str,
            Path,
            np.ndarray,
            Image.Image,
            List[Union[str, Path, np.ndarray, Image.Image]],
        ],
    ) -> Union[str, List[str]]:
        """Extract text from one or multiple images."""

        if self._ocr_engine is None or self._processor is None:
            logger.error("OCR engine not initialized")
            return "" if not isinstance(images, list) else []

        single = not isinstance(images, list)
        images = [images] if single else images

        try:
            inputs = self._processor(
                images=images,
                return_tensors="pt",
                padding=True,
            )

            inputs = {
                key: value.to(self.device) if hasattr(value, "to") else value
                for key, value in inputs.items()
            }

            with torch.inference_mode():
                output = self._ocr_engine.generate(
                    **inputs,
                    max_new_tokens=self.max_new_tokens,
                    do_sample=False,
                )

            texts = self._processor.batch_decode(
                output,
                skip_special_tokens=True,
            )

            texts = [text.strip() for text in texts]

            return texts[0] if single else texts

        except Exception as exc:
            logger.error(
                "OCR extraction failed: %s",
                exc,
                exc_info=True,
            )
            return "" if single else []
    
        """Convert supported inputs to an RGB PIL image for AutoProcessor."""
        if isinstance(image, (str, Path)):
            with Image.open(image) as opened:
                return opened.convert("RGB")
        if isinstance(image, Image.Image):
            return image.convert("RGB")
        if isinstance(image, np.ndarray):
            if image.ndim == 2:
                return Image.fromarray(image).convert("RGB")
            if image.ndim == 3 and image.shape[2] == 4:
                # OpenCV arrays are BGRA throughout QSearch.
                return Image.fromarray(image[:, :, [2, 1, 0, 3]], mode="RGBA").convert("RGB")
            if image.ndim == 3 and image.shape[2] == 3:
                # OpenCV arrays are BGR throughout QSearch.
                return Image.fromarray(image[:, :, ::-1].copy(), mode="RGB")
            raise ValueError(f"Unsupported numpy image shape: {image.shape}")