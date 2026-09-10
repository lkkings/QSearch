"""OCR Engine wrapper for text extraction from question images.

Provides unified interface for PaddleOCR with Chinese/English support.
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


class OCRResult:
    """Represents OCR extraction result."""

    def __init__(
        self,
        text: str,
        confidence: float,
        bbox: Optional[List[List[int]]] = None,
        language: Optional[str] = None
    ):
        """Initialize OCR result.

        Args:
            text: Extracted text
            confidence: Confidence score (0-1)
            bbox: Bounding box coordinates [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
            language: Detected language ('ch' or 'en')
        """
        self.text = text
        self.confidence = confidence
        self.bbox = bbox
        self.language = language

    def __repr__(self):
        return f"OCRResult(text='{self.text[:30]}...', confidence={self.confidence:.2f})"


class OCREngine:
    """Wrapper for PaddleOCR with Chinese/English support."""

    def __init__(
        self,
        languages: List[str] = None,
        use_gpu: bool = True,
        gpu_id: int = 0,
        model_dir: Optional[str] = None
    ):
        """Initialize OCR engine.

        Args:
            languages: List of language codes ('ch', 'en'). Default: ['ch', 'en']
            use_gpu: Whether to use GPU acceleration
            gpu_id: GPU device ID
            model_dir: Base directory for PaddleOCR models (defaults to models/paddle)
        """
        self.languages = languages or ['ch', 'en']
        self.gpu_id = gpu_id
        self.model_dir = model_dir
        # Only enable GPU when the installed paddlepaddle build actually supports CUDA.
        # A CPU-only build asked to use GPU either warns and degrades or fails outright,
        # depending on the paddle version, so resolve it here instead.
        self.use_gpu = use_gpu and self._is_paddle_gpu_available()
        self._ocr_engine = None

        self._initialize_engine()

    @staticmethod
    def _is_paddle_gpu_available() -> bool:
        """Check whether the installed paddlepaddle build has usable CUDA support.

        Returns:
            True if paddle is compiled with CUDA and at least one device is visible.
        """
        try:
            import paddle
        except ImportError:
            return False

        try:
            if not paddle.device.is_compiled_with_cuda():
                return False
            return paddle.device.cuda.device_count() > 0
        except Exception as e:  # pragma: no cover - depends on driver/runtime state
            logger.debug(f"Paddle GPU probe failed, falling back to CPU: {e}")
            return False

    def _initialize_engine(self):
        """Initialize PaddleOCR engine."""
        try:
            from paddleocr import PaddleOCR
            from pathlib import Path

            # PaddleOCR supports 'ch' (Chinese + English) or 'en' (English only)
            # Use 'ch' if Chinese is in languages list, otherwise 'en'
            lang = 'ch' if 'ch' in self.languages else 'en'

            # Resolve model directory
            if self.model_dir is None:
                # Default: models/paddle in project root
                # OCREngine may be initialized from anywhere, so find project root
                # src/qsearch/features/ocr_engine.py -> project root is 3 levels up
                project_root = Path(__file__).resolve().parents[3]
                self.model_dir = str(project_root / "models" / "paddle")

            model_base = Path(self.model_dir)

            # Point PaddleOCR to local models if they exist
            kwargs = {
                'use_angle_cls': True,
                'lang': lang,
                'use_gpu': self.use_gpu,
                'gpu_mem': 8000,
                'show_log': False,
            }

            # If local models exist, use them; otherwise PaddleOCR will download to ~/.paddleocr
            det_dir = model_base / "det" / "ch_PP-OCRv4_det_infer"
            rec_dir = model_base / "rec" / "ch_PP-OCRv4_rec_infer"
            cls_dir = model_base / "cls" / "ch_ppocr_mobile_v2.0_cls_infer"

            if det_dir.exists() and (det_dir / "inference.pdmodel").exists():
                kwargs['det_model_dir'] = str(det_dir)
                logger.debug(f"Using local detection model: {det_dir}")

            if rec_dir.exists() and (rec_dir / "inference.pdmodel").exists():
                kwargs['rec_model_dir'] = str(rec_dir)
                logger.debug(f"Using local recognition model: {rec_dir}")

            if cls_dir.exists() and (cls_dir / "inference.pdmodel").exists():
                kwargs['cls_model_dir'] = str(cls_dir)
                logger.debug(f"Using local classifier model: {cls_dir}")

            self._ocr_engine = PaddleOCR(**kwargs)

            logger.info(
                f"Initialized PaddleOCR with language={lang}, use_gpu={self.use_gpu}, "
                f"model_dir={self.model_dir}"
            )

        except ImportError as e:
            missing = getattr(e, 'name', '') or ''
            if missing.startswith('paddle') and missing != 'paddleocr':
                # paddleocr is a thin wrapper; the paddlepaddle runtime ships separately.
                logger.error(
                    "paddlepaddle runtime is missing. Install the GPU build if an "
                    "NVIDIA GPU is present, otherwise the CPU build:\n"
                    "  GPU (CUDA 12.6): uv pip install paddlepaddle-gpu==3.0.0 "
                    "-i https://www.paddlepaddle.org.cn/packages/stable/cu126/\n"
                    "  CPU:             uv pip install paddlepaddle==3.0.0\n"
                    "  Or run:          uv run scripts/install_paddle.py"
                )
                raise ImportError(
                    "paddlepaddle is required by paddleocr but not installed. "
                    "Run: uv run scripts/install_paddle.py"
                ) from e

            logger.error("PaddleOCR not installed. Install with: uv pip install paddleocr")
            raise ImportError("PaddleOCR is required but not installed") from e

    def extract_text(
        self,
        image: Union[str, Path, np.ndarray, Image.Image],
        confidence_threshold: float = 0.5
    ) -> Tuple[List[OCRResult], bool]:
        """Extract text from image.

        Args:
            image: Image path, numpy array, or PIL Image
            confidence_threshold: Minimum confidence to include result

        Returns:
            Tuple of (list of OCRResult objects, success flag)
        """
        if self._ocr_engine is None:
            logger.error("OCR engine not initialized")
            return [], False

        try:
            # Convert image to format PaddleOCR expects
            img_array = self._prepare_image(image)

            # Run OCR
            result = self._ocr_engine.ocr(img_array, cls=True)

            if result is None or len(result) == 0 or result[0] is None:
                logger.warning("OCR returned no results")
                return [], True  # Success but no text found

            # Parse results
            ocr_results = []
            for line in result[0]:
                bbox = line[0]
                text, confidence = line[1]

                if confidence >= confidence_threshold:
                    ocr_results.append(OCRResult(
                        text=text,
                        confidence=confidence,
                        bbox=bbox,
                        language=None  # PaddleOCR doesn't return language per-line
                    ))

            return ocr_results, True

        except Exception as e:
            logger.error(f"OCR extraction failed: {e}")
            return [], False

    def _prepare_image(
        self,
        image: Union[str, Path, np.ndarray, Image.Image]
    ) -> np.ndarray:
        """Prepare image for OCR processing.

        Args:
            image: Image in various formats

        Returns:
            Numpy array in BGR format (OpenCV format)
        """
        if isinstance(image, (str, Path)):
            # Load from file path
            img_array = cv2.imread(str(image))
            if img_array is None:
                raise ValueError(f"Failed to load image from {image}")
            return img_array

        elif isinstance(image, Image.Image):
            # Convert PIL Image to numpy array
            img_array = np.array(image)
            # Convert RGB to BGR
            if len(img_array.shape) == 3 and img_array.shape[2] == 3:
                img_array = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
            return img_array

        elif isinstance(image, np.ndarray):
            return image

        else:
            raise TypeError(f"Unsupported image type: {type(image)}")

    def extract_text_simple(
        self,
        image: Union[str, Path, np.ndarray, Image.Image],
        confidence_threshold: float = 0.5
    ) -> str:
        """Extract text as single concatenated string.

        Args:
            image: Image path, numpy array, or PIL Image
            confidence_threshold: Minimum confidence to include result

        Returns:
            Extracted text as single string
        """
        results, success = self.extract_text(image, confidence_threshold)

        if not success or not results:
            return ""

        # Concatenate all text with newlines
        return "\n".join(result.text for result in results)

    def get_average_confidence(
        self,
        image: Union[str, Path, np.ndarray, Image.Image]
    ) -> float:
        """Get average OCR confidence for image.

        Args:
            image: Image path, numpy array, or PIL Image

        Returns:
            Average confidence score (0-1), or 0.0 if extraction failed
        """
        results, success = self.extract_text(image, confidence_threshold=0.0)

        if not success or not results:
            return 0.0

        return sum(r.confidence for r in results) / len(results)
