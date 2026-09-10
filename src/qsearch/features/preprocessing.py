"""Image preprocessing pipeline for OCR enhancement.

Applies various preprocessing techniques to improve OCR accuracy.
"""

import cv2
import numpy as np
from typing import Tuple


class ImagePreprocessor:
    """Preprocesses images to improve OCR accuracy."""

    def __init__(
        self,
        target_size: Tuple[int, int] = None,
        apply_denoise: bool = True,
        apply_clahe: bool = True,
        clahe_clip_limit: float = 2.0,
        clahe_tile_size: int = 8
    ):
        """Initialize preprocessor.

        Args:
            target_size: Target size (width, height) for resizing. None to skip resizing.
            apply_denoise: Whether to apply denoising
            apply_clahe: Whether to apply CLAHE contrast enhancement
            clahe_clip_limit: CLAHE clip limit for contrast limiting
            clahe_tile_size: CLAHE tile grid size
        """
        self.target_size = target_size
        self.apply_denoise = apply_denoise
        self.apply_clahe = apply_clahe
        self.clahe_clip_limit = clahe_clip_limit
        self.clahe_tile_size = clahe_tile_size

    def preprocess(self, image: np.ndarray) -> np.ndarray:
        """Apply full preprocessing pipeline.

        Args:
            image: Input image as numpy array

        Returns:
            Preprocessed image
        """
        img = image.copy()

        # Convert to grayscale if color
        if len(img.shape) == 3:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Denoise
        if self.apply_denoise:
            img = self.denoise(img)

        # CLAHE contrast enhancement
        if self.apply_clahe:
            img = self.enhance_contrast(img)

        # Resize
        if self.target_size is not None:
            img = self.resize(img, self.target_size)

        return img

    def denoise(self, image: np.ndarray) -> np.ndarray:
        """Apply denoising filter.

        Args:
            image: Grayscale image

        Returns:
            Denoised image
        """
        # Use Non-local Means Denoising
        return cv2.fastNlMeansDenoising(image, None, h=10, templateWindowSize=7, searchWindowSize=21)

    def enhance_contrast(self, image: np.ndarray) -> np.ndarray:
        """Apply CLAHE (Contrast Limited Adaptive Histogram Equalization).

        Args:
            image: Grayscale image

        Returns:
            Contrast-enhanced image
        """
        clahe = cv2.createCLAHE(
            clipLimit=self.clahe_clip_limit,
            tileGridSize=(self.clahe_tile_size, self.clahe_tile_size)
        )
        return clahe.apply(image)

    def resize(self, image: np.ndarray, target_size: Tuple[int, int]) -> np.ndarray:
        """Resize image to target size.

        Args:
            image: Input image
            target_size: Target (width, height)

        Returns:
            Resized image
        """
        return cv2.resize(image, target_size, interpolation=cv2.INTER_CUBIC)

    def binarize(self, image: np.ndarray, method: str = 'otsu') -> np.ndarray:
        """Convert image to binary (black and white).

        Args:
            image: Grayscale image
            method: Binarization method ('otsu', 'adaptive')

        Returns:
            Binary image
        """
        if method == 'otsu':
            _, binary = cv2.threshold(image, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            return binary
        elif method == 'adaptive':
            return cv2.adaptiveThreshold(
                image, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, 11, 2
            )
        else:
            raise ValueError(f"Unknown binarization method: {method}")

    def remove_borders(self, image: np.ndarray, border_size: int = 10) -> np.ndarray:
        """Remove borders from image.

        Args:
            image: Input image
            border_size: Border size in pixels to remove

        Returns:
            Image with borders removed
        """
        h, w = image.shape[:2]
        return image[border_size:h-border_size, border_size:w-border_size]

    def deskew(self, image: np.ndarray) -> np.ndarray:
        """Deskew (straighten) image.

        Args:
            image: Grayscale image

        Returns:
            Deskewed image
        """
        # Compute skew angle
        coords = np.column_stack(np.where(image > 0))
        angle = cv2.minAreaRect(coords)[-1]

        # Adjust angle
        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle

        # Rotate to deskew
        if abs(angle) > 0.5:  # Only deskew if angle is significant
            (h, w) = image.shape[:2]
            center = (w // 2, h // 2)
            M = cv2.getRotationMatrix2D(center, angle, 1.0)
            rotated = cv2.warpAffine(
                image, M, (w, h),
                flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_REPLICATE
            )
            return rotated

        return image
