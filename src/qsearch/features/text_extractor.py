"""Text feature extraction from question images.

Extracts configurable text features including stem, options, and formulas,
with BERT/RoBERTa encoding for semantic similarity.
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Union

import numpy as np
import torch
from PIL import Image
from transformers import AutoModel, AutoTokenizer

from .ocr_engine import OCREngine
from .preprocessing import ImagePreprocessor
from .question_parser import QuestionParser
from .formula_extractor import FormulaExtractor
from ..utils.text_normalization import normalize_text, normalize_options

logger = logging.getLogger(__name__)


class TextFeatureExtractor:
    """Extracts text features from question images."""

    def __init__(
        self,
        config: Dict,
        ocr_engine: Optional[OCREngine] = None,
        preprocessor: Optional[ImagePreprocessor] = None,
        parser: Optional[QuestionParser] = None,
        formula_extractor: Optional[FormulaExtractor] = None
    ):
        """Initialize text feature extractor.

        Args:
            config: Configuration dictionary for text features
            ocr_engine: OCR engine instance (creates default if None)
            preprocessor: Image preprocessor (creates default if None)
            parser: Question parser (creates default if None)
            formula_extractor: Formula extractor (creates default if None)
        """
        self.config = config
        self.components_config = config.get('components', {})
        self.encoding_config = config.get('encoding', {})

        # Initialize components
        self.ocr_engine = ocr_engine or OCREngine()
        self.preprocessor = preprocessor or ImagePreprocessor()
        self.parser = parser or QuestionParser()
        self.formula_extractor = formula_extractor

        # Initialize text encoders
        self._chinese_encoder = None
        self._english_encoder = None
        self._chinese_tokenizer = None
        self._english_tokenizer = None

        self._initialize_encoders()

    def _initialize_encoders(self):
        """Initialize BERT/RoBERTa encoders for text embedding."""
        from pathlib import Path

        # src/qsearch/features/text_extractor.py -> project root is 3 levels up
        project_root = Path(__file__).resolve().parents[3]
        models_dir = project_root / "models"

        # Chinese model
        chinese_model = self.encoding_config.get('chinese_model', 'hfl/chinese-roberta-wwm-ext')
        chinese_local = models_dir / "chinese-roberta-wwm-ext"

        # Try local first, fall back to HuggingFace with local cache
        chinese_path = str(chinese_local) if chinese_local.exists() else chinese_model

        try:
            self._chinese_tokenizer = AutoTokenizer.from_pretrained(
                chinese_path,
                cache_dir=str(models_dir) if chinese_path == chinese_model else None
            )
            self._chinese_encoder = AutoModel.from_pretrained(
                chinese_path,
                cache_dir=str(models_dir) if chinese_path == chinese_model else None
            )
            self._chinese_encoder.eval()
            logger.info(f"Loaded Chinese encoder from: {chinese_path}")
        except Exception as e:
            logger.error(f"Failed to load Chinese encoder: {e}")

        # English model
        english_model = self.encoding_config.get('english_model', 'sentence-transformers/all-mpnet-base-v2')
        english_local = models_dir / "all-mpnet-base-v2"

        english_path = str(english_local) if english_local.exists() else english_model

        try:
            self._english_tokenizer = AutoTokenizer.from_pretrained(
                english_path,
                cache_dir=str(models_dir) if english_path == english_model else None
            )
            self._english_encoder = AutoModel.from_pretrained(
                english_path,
                cache_dir=str(models_dir) if english_path == english_model else None
            )
            self._english_encoder.eval()
            logger.info(f"Loaded English encoder from: {english_path}")
        except Exception as e:
            logger.error(f"Failed to load English encoder: {e}")

    def extract(
        self,
        image: Union[str, Path, np.ndarray, Image.Image]
    ) -> Dict:
        """Extract text features from question image.

        Args:
            image: Input image

        Returns:
            Dictionary containing extracted text features
        """
        result = {
            'stem': None,
            'stem_embedding': None,
            'options': {},
            'options_normalized': [],
            'formulas': [],
            'question_type': 'unknown',
            'weights': {},
            'ocr_confidence': 0.0,
            'extraction_success': False,
            'warnings': []
        }

        # Preprocess image
        img_array = self._load_image(image)
        if img_array is None:
            result['warnings'].append('Failed to load image')
            return result

        preprocessed = self.preprocessor.preprocess(img_array)

        # Extract text via OCR
        ocr_results, ocr_success = self.ocr_engine.extract_text(preprocessed)
        if not ocr_success:
            result['warnings'].append('OCR extraction failed')
            return result

        if not ocr_results:
            result['warnings'].append('No text detected')
            return result

        # Compute average OCR confidence
        avg_confidence = sum(r.confidence for r in ocr_results) / len(ocr_results)
        result['ocr_confidence'] = avg_confidence

        if avg_confidence < 0.5:
            result['warnings'].append(f'Low OCR confidence: {avg_confidence:.2f}')

        # Concatenate OCR text
        full_text = '\n'.join(r.text for r in ocr_results)

        # Parse question structure
        parsed = self.parser.parse(full_text)
        result['question_type'] = parsed['question_type']

        # Extract stem if enabled
        if self.components_config.get('stem', {}).get('enabled', True):
            result['stem'] = parsed['stem']
            result['weights']['stem'] = self.components_config.get('stem', {}).get('weight', 0.6)

            # Generate stem embedding
            if result['stem']:
                result['stem_embedding'] = self._encode_text(result['stem'])

        # Extract options if enabled
        if self.components_config.get('options', {}).get('enabled', True):
            result['options'] = parsed['options']
            result['weights']['options'] = self.components_config.get('options', {}).get('weight', 0.3)

            # Normalize options
            if result['options']:
                normalization_rules = self.components_config.get('options', {}).get('normalization', [])
                option_values = list(result['options'].values())
                result['options_normalized'] = normalize_options(option_values, normalization_rules)

        # Extract formulas if enabled
        if self.components_config.get('formulas', {}).get('enabled', False):
            if self.formula_extractor:
                # Extract formulas from image regions (simplified - would need region detection)
                formulas = self.parser.extract_formulas(full_text)
                result['formulas'] = formulas
                result['weights']['formulas'] = self.components_config.get('formulas', {}).get('weight', 0.1)
            else:
                result['warnings'].append('Formula extraction enabled but extractor not initialized')

        result['extraction_success'] = parsed['parse_success']

        return result

    def _load_image(self, image: Union[str, Path, np.ndarray, Image.Image]) -> Optional[np.ndarray]:
        """Load image into numpy array format."""
        try:
            if isinstance(image, (str, Path)):
                import cv2
                img = cv2.imread(str(image))
                return img
            elif isinstance(image, Image.Image):
                import cv2
                img_array = np.array(image)
                if len(img_array.shape) == 3:
                    img_array = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
                return img_array
            elif isinstance(image, np.ndarray):
                return image
            else:
                return None
        except Exception as e:
            logger.error(f"Failed to load image: {e}")
            return None

    def _encode_text(self, text: str, language: str = 'auto') -> Optional[np.ndarray]:
        """Encode text to embedding vector.

        Args:
            text: Input text
            language: Language hint ('auto', 'zh', 'en')

        Returns:
            768-dim embedding vector or None if encoding failed
        """
        if not text:
            return None

        # Detect language if auto
        if language == 'auto':
            language = self._detect_language(text)

        # Select encoder
        if language == 'zh' and self._chinese_encoder is not None:
            encoder = self._chinese_encoder
            tokenizer = self._chinese_tokenizer
        elif language == 'en' and self._english_encoder is not None:
            encoder = self._english_encoder
            tokenizer = self._english_tokenizer
        else:
            logger.warning(f"No encoder available for language: {language}")
            return None

        try:
            # Tokenize
            inputs = tokenizer(
                text,
                return_tensors='pt',
                truncation=True,
                max_length=512,
                padding=True
            )

            # Encode
            with torch.no_grad():
                outputs = encoder(**inputs)
                # Use [CLS] token embedding
                embedding = outputs.last_hidden_state[:, 0, :].squeeze().numpy()

            return embedding

        except Exception as e:
            logger.error(f"Text encoding failed: {e}")
            return None

    def _detect_language(self, text: str) -> str:
        """Detect language from text.

        Args:
            text: Input text

        Returns:
            Language code ('zh' or 'en')
        """
        # Simple heuristic: if contains Chinese characters, use Chinese model
        chinese_chars = sum(1 for c in text if '一' <= c <= '鿿')
        total_chars = len(text)

        if total_chars == 0:
            return 'en'

        chinese_ratio = chinese_chars / total_chars
        return 'zh' if chinese_ratio > 0.1 else 'en'

    def extract_batch(
        self,
        images: List[Union[str, Path, np.ndarray, Image.Image]]
    ) -> List[Dict]:
        """Extract features from multiple images.

        Args:
            images: List of images

        Returns:
            List of feature dictionaries
        """
        results = []
        for image in images:
            features = self.extract(image)
            results.append(features)
        return results
