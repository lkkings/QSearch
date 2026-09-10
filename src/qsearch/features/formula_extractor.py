"""LaTeX-OCR integration for mathematical formula extraction.

Wraps pix2tex (LaTeX-OCR) for extracting LaTeX formulas from images.
"""

import logging
from pathlib import Path
from typing import List, Optional, Union

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


class FormulaExtractor:
    """Extracts mathematical formulas in LaTeX format from images."""

    def __init__(self, use_gpu: bool = True):
        """Initialize formula extractor.

        Args:
            use_gpu: Whether to use GPU acceleration
        """
        self.use_gpu = use_gpu
        self._model = None
        self._initialize_model()

    def _initialize_model(self):
        """Initialize LaTeX-OCR model."""
        try:
            from pix2tex.cli import LatexOCR

            self._model = LatexOCR()
            logger.info("Initialized LaTeX-OCR model")

        except ImportError as e:
            logger.error("pix2tex not installed. Install with: pip install pix2tex[api]")
            raise ImportError("pix2tex is required but not installed") from e
        except Exception as e:
            logger.error(f"Failed to initialize LaTeX-OCR: {e}")
            self._model = None

    def extract(
        self,
        image: Union[str, Path, np.ndarray, Image.Image]
    ) -> Optional[str]:
        """Extract LaTeX formula from image.

        Args:
            image: Image path, numpy array, or PIL Image

        Returns:
            LaTeX formula string, or None if extraction failed
        """
        if self._model is None:
            logger.error("LaTeX-OCR model not initialized")
            return None

        try:
            # Convert to PIL Image if needed
            if isinstance(image, (str, Path)):
                img = Image.open(image)
            elif isinstance(image, np.ndarray):
                img = Image.fromarray(image)
            elif isinstance(image, Image.Image):
                img = image
            else:
                logger.error(f"Unsupported image type: {type(image)}")
                return None

            # Extract LaTeX
            latex = self._model(img)
            return latex

        except Exception as e:
            logger.error(f"Formula extraction failed: {e}")
            return None

    def extract_multiple(
        self,
        images: List[Union[str, Path, np.ndarray, Image.Image]]
    ) -> List[Optional[str]]:
        """Extract formulas from multiple images.

        Args:
            images: List of images

        Returns:
            List of LaTeX formulas (None for failed extractions)
        """
        results = []
        for image in images:
            latex = self.extract(image)
            results.append(latex)
        return results

    def is_valid_latex(self, latex: str) -> bool:
        """Check if LaTeX string appears valid.

        Args:
            latex: LaTeX string

        Returns:
            True if string looks like valid LaTeX
        """
        if not latex or not latex.strip():
            return False

        # Check for common LaTeX patterns
        latex_indicators = [
            '\\frac', '\\sqrt', '\\sum', '\\int', '\\prod',
            '\\alpha', '\\beta', '\\gamma', '\\delta',
            '^', '_', '=', '+', '-', '*', '/',
        ]

        return any(indicator in latex for indicator in latex_indicators)

    def normalize_latex(self, latex: str) -> str:
        """Normalize LaTeX string for comparison.

        Args:
            latex: LaTeX string

        Returns:
            Normalized LaTeX string
        """
        if not latex:
            return ""

        normalized = latex.strip()

        # Remove extra whitespace
        normalized = ' '.join(normalized.split())

        # Normalize common variations
        replacements = {
            '\\left(': '(',
            '\\right)': ')',
            '\\left[': '[',
            '\\right]': ']',
            '\\left\\{': '\\{',
            '\\right\\}': '\\}',
            '\\,': ' ',
            '\\;': ' ',
            '\\quad': ' ',
            '\\qquad': ' ',
        }

        for old, new in replacements.items():
            normalized = normalized.replace(old, new)

        # Normalize spacing around operators
        operators = ['+', '-', '=', '<', '>', '\\leq', '\\geq']
        for op in operators:
            normalized = normalized.replace(f' {op} ', f'{op}')
            normalized = normalized.replace(f'{op} ', op)
            normalized = normalized.replace(f' {op}', op)

        return normalized.strip()

    def compare_formulas(self, latex1: str, latex2: str) -> float:
        """Compare two LaTeX formulas for similarity.

        Args:
            latex1: First LaTeX string
            latex2: Second LaTeX string

        Returns:
            Similarity score (0-1)
        """
        if not latex1 or not latex2:
            return 0.0

        # Normalize both
        norm1 = self.normalize_latex(latex1)
        norm2 = self.normalize_latex(latex2)

        # Exact match after normalization
        if norm1 == norm2:
            return 1.0

        # Character-level similarity (Jaccard)
        set1 = set(norm1)
        set2 = set(norm2)

        if not set1 or not set2:
            return 0.0

        intersection = len(set1 & set2)
        union = len(set1 | set2)

        return intersection / union if union > 0 else 0.0
