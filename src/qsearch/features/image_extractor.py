"""Image feature extraction from question images.

Extracts perceptual hashes and CNN-based deep features for visual similarity.
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Union

import cv2
import imagehash
import numpy as np
import torch
import torchvision.models as models
import torchvision.transforms as transforms
from PIL import Image

logger = logging.getLogger(__name__)


class ImageFeatureExtractor:
    """Extracts image features including perceptual hashes and CNN embeddings."""

    def __init__(
        self,
        config: Dict,
        use_gpu: bool = True,
        gpu_id: int = 0
    ):
        """Initialize image feature extractor.

        Args:
            config: Configuration dictionary for image features
            use_gpu: Whether to use GPU acceleration
            gpu_id: GPU device ID
        """
        self.config = config
        self.components_config = config.get('components', {})
        self.batch_size = config.get('batch_size', 128)
        self.use_gpu = use_gpu and torch.cuda.is_available()
        self.gpu_id = gpu_id

        self.device = torch.device(f'cuda:{gpu_id}' if self.use_gpu else 'cpu')

        # Initialize CNN model
        self._cnn_model = None
        self._transform = None
        self._initialize_cnn()

    def _initialize_cnn(self):
        """Initialize CNN model for deep feature extraction."""
        deep_features_config = self.components_config.get('deep_features', {})

        if not deep_features_config.get('enabled', False):
            return

        model_name = deep_features_config.get('model', 'efficientnet_b4')
        output_dim = deep_features_config.get('output_dim', 512)

        try:
            if model_name == 'efficientnet_b4':
                from torchvision.models import efficientnet_b4, EfficientNet_B4_Weights
                weights = EfficientNet_B4_Weights.DEFAULT
                model = efficientnet_b4(weights=weights)
                # Remove classifier to get features
                model = torch.nn.Sequential(*list(model.children())[:-1])
                self._transform = weights.transforms()

            elif model_name == 'resnet50':
                from torchvision.models import resnet50, ResNet50_Weights
                weights = ResNet50_Weights.DEFAULT
                model = resnet50(weights=weights)
                # Remove final FC layer
                model = torch.nn.Sequential(*list(model.children())[:-1])
                self._transform = weights.transforms()

            else:
                logger.error(f"Unknown model: {model_name}")
                return

            model = model.to(self.device)
            model.eval()
            self._cnn_model = model

            logger.info(f"Loaded CNN model: {model_name} on {self.device}")

        except Exception as e:
            logger.error(f"Failed to load CNN model: {e}")
            self._cnn_model = None

    def extract(
        self,
        image: Union[str, Path, np.ndarray, Image.Image]
    ) -> Dict:
        """Extract image features.

        Args:
            image: Input image

        Returns:
            Dictionary containing extracted image features
        """
        result = {
            'perceptual_hash': None,
            'hash_algorithm': None,
            'deep_features': None,
            'extraction_success': False,
            'error': None
        }

        try:
            # Load image
            pil_image = self._load_image(image)
            if pil_image is None:
                result['error'] = 'Failed to load image'
                return result

            # Extract perceptual hash if enabled
            hash_config = self.components_config.get('perceptual_hash', {})
            if hash_config.get('enabled', True):
                algorithm = hash_config.get('algorithm', 'dHash')
                hash_size = hash_config.get('hash_size', 16)

                phash = self._compute_perceptual_hash(
                    pil_image,
                    algorithm=algorithm,
                    hash_size=hash_size
                )

                result['perceptual_hash'] = str(phash)
                result['hash_algorithm'] = algorithm

            # Extract deep features if enabled
            deep_config = self.components_config.get('deep_features', {})
            if deep_config.get('enabled', False) and self._cnn_model is not None:
                deep_features = self._extract_cnn_features(pil_image)
                result['deep_features'] = deep_features

            result['extraction_success'] = True

        except Exception as e:
            logger.error(f"Image feature extraction failed: {e}")
            result['error'] = str(e)

        return result

    def _load_image(
        self,
        image: Union[str, Path, np.ndarray, Image.Image]
    ) -> Optional[Image.Image]:
        """Load image as PIL Image.

        Args:
            image: Input image in various formats

        Returns:
            PIL Image or None if loading failed
        """
        try:
            if isinstance(image, (str, Path)):
                return Image.open(image).convert('RGB')
            elif isinstance(image, Image.Image):
                return image.convert('RGB')
            elif isinstance(image, np.ndarray):
                # Convert BGR to RGB if from OpenCV
                if len(image.shape) == 3 and image.shape[2] == 3:
                    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                return Image.fromarray(image)
            else:
                return None
        except Exception as e:
            logger.error(f"Failed to load image: {e}")
            return None

    def _compute_perceptual_hash(
        self,
        image: Image.Image,
        algorithm: str = 'dHash',
        hash_size: int = 16
    ) -> imagehash.ImageHash:
        """Compute perceptual hash of image.

        Args:
            image: PIL Image
            algorithm: Hash algorithm ('dHash', 'pHash', 'aHash')
            hash_size: Hash size (default 16x16 = 256 bits)

        Returns:
            ImageHash object
        """
        if algorithm == 'dHash':
            return imagehash.dhash(image, hash_size=hash_size)
        elif algorithm == 'pHash':
            return imagehash.phash(image, hash_size=hash_size)
        elif algorithm == 'aHash':
            return imagehash.average_hash(image, hash_size=hash_size)
        else:
            raise ValueError(f"Unknown hash algorithm: {algorithm}")

    def _extract_cnn_features(self, image: Image.Image) -> Optional[np.ndarray]:
        """Extract CNN deep features from image.

        Args:
            image: PIL Image

        Returns:
            Feature vector or None if extraction failed
        """
        if self._cnn_model is None or self._transform is None:
            return None

        try:
            # Transform image
            img_tensor = self._transform(image).unsqueeze(0).to(self.device)

            # Extract features
            with torch.no_grad():
                features = self._cnn_model(img_tensor)
                # Flatten and convert to numpy
                features = features.squeeze().cpu().numpy()

            return features

        except Exception as e:
            logger.error(f"CNN feature extraction failed: {e}")
            return None

    def extract_batch(
        self,
        images: List[Union[str, Path, np.ndarray, Image.Image]],
        batch_size: Optional[int] = None
    ) -> List[Dict]:
        """Extract features from multiple images with GPU batching.

        Args:
            images: List of images
            batch_size: Batch size (uses config default if None)

        Returns:
            List of feature dictionaries
        """
        batch_size = batch_size or self.batch_size
        results = []

        # Process in batches for GPU efficiency
        for i in range(0, len(images), batch_size):
            batch = images[i:i + batch_size]

            try:
                batch_results = self._extract_batch_gpu(batch)
                results.extend(batch_results)

            except RuntimeError as e:
                if 'out of memory' in str(e):
                    # OOM - reduce batch size and retry
                    logger.warning(f"OOM error, reducing batch size from {batch_size} to {batch_size // 2}")
                    torch.cuda.empty_cache()

                    # Retry with smaller batch
                    new_batch_size = max(1, batch_size // 2)
                    for j in range(0, len(batch), new_batch_size):
                        sub_batch = batch[j:j + new_batch_size]
                        sub_results = self._extract_batch_gpu(sub_batch)
                        results.extend(sub_results)
                else:
                    # Other error - fall back to sequential
                    logger.error(f"Batch processing error: {e}, falling back to sequential")
                    for image in batch:
                        results.append(self.extract(image))

        return results

    def _extract_batch_gpu(
        self,
        images: List[Union[str, Path, np.ndarray, Image.Image]]
    ) -> List[Dict]:
        """Extract features from batch with GPU acceleration.

        Args:
            images: Batch of images

        Returns:
            List of feature dictionaries
        """
        results = []

        # Load all images
        pil_images = []
        for image in images:
            pil_img = self._load_image(image)
            if pil_img is None:
                results.append({
                    'perceptual_hash': None,
                    'hash_algorithm': None,
                    'deep_features': None,
                    'extraction_success': False,
                    'error': 'Failed to load image'
                })
                pil_images.append(None)
            else:
                pil_images.append(pil_img)

        # Extract perceptual hashes (CPU-based, parallel-friendly)
        hash_config = self.components_config.get('perceptual_hash', {})
        if hash_config.get('enabled', True):
            algorithm = hash_config.get('algorithm', 'dHash')
            hash_size = hash_config.get('hash_size', 16)

            for i, pil_img in enumerate(pil_images):
                if pil_img is not None:
                    if len(results) <= i:
                        results.append({})
                    phash = self._compute_perceptual_hash(pil_img, algorithm, hash_size)
                    results[i]['perceptual_hash'] = str(phash)
                    results[i]['hash_algorithm'] = algorithm

        # Extract CNN features (GPU-batched)
        deep_config = self.components_config.get('deep_features', {})
        if deep_config.get('enabled', False) and self._cnn_model is not None:
            # Prepare batch tensor
            valid_images = [img for img in pil_images if img is not None]
            if valid_images and self._transform is not None:
                try:
                    img_tensors = torch.stack([
                        self._transform(img) for img in valid_images
                    ]).to(self.device)

                    with torch.no_grad():
                        batch_features = self._cnn_model(img_tensors)
                        batch_features = batch_features.squeeze().cpu().numpy()

                    # Assign features to results
                    feature_idx = 0
                    for i, pil_img in enumerate(pil_images):
                        if pil_img is not None:
                            if len(results) <= i:
                                results.append({})
                            if batch_features.ndim == 1:
                                results[i]['deep_features'] = batch_features
                            else:
                                results[i]['deep_features'] = batch_features[feature_idx]
                            feature_idx += 1

                except Exception as e:
                    logger.error(f"Batch CNN extraction failed: {e}")

        # Mark success
        for result in results:
            if 'extraction_success' not in result:
                result['extraction_success'] = result.get('perceptual_hash') is not None
            if 'error' not in result:
                result['error'] = None

        return results
