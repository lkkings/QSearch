"""
Model download and verification script for QSearch.
Downloads and verifies pretrained models needed for the system.
Models are saved to the project's models/ directory.
"""
import sys
import os
from pathlib import Path
from transformers import AutoTokenizer, AutoModel
from sentence_transformers import SentenceTransformer

# Get project root (parent of scripts directory)
PROJECT_ROOT = Path(__file__).parent.parent
MODELS_DIR = PROJECT_ROOT / "models"

def download_models():
    """Download and verify all required pretrained models."""

    # Create models directory
    MODELS_DIR.mkdir(exist_ok=True)
    print(f"Models will be saved to: {MODELS_DIR}")

    # Chinese RoBERTa model path
    chinese_model_path = MODELS_DIR / "chinese-roberta-wwm-ext"

    print("\nDownloading Chinese RoBERTa model...")
    try:
        tokenizer_ch = AutoTokenizer.from_pretrained(
            'hfl/chinese-roberta-wwm-ext',
            cache_dir=str(MODELS_DIR)
        )
        model_ch = AutoModel.from_pretrained(
            'hfl/chinese-roberta-wwm-ext',
            cache_dir=str(MODELS_DIR)
        )

        # Save to local directory
        tokenizer_ch.save_pretrained(str(chinese_model_path))
        model_ch.save_pretrained(str(chinese_model_path))

        print("✓ Chinese RoBERTa model downloaded and saved")
        print(f"  Location: {chinese_model_path}")
        print(f"  Model hidden size: {model_ch.config.hidden_size}")
    except Exception as e:
        print(f"✗ Failed to load Chinese RoBERTa: {e}")
        return False

    # English sentence transformer model path
    english_model_path = MODELS_DIR / "all-mpnet-base-v2"

    print("\nDownloading English sentence transformer model...")
    try:
        model_en = SentenceTransformer(
            'sentence-transformers/all-mpnet-base-v2',
            cache_folder=str(MODELS_DIR)
        )

        # Save to local directory
        model_en.save(str(english_model_path))

        print("✓ English sentence transformer downloaded and saved")
        print(f"  Location: {english_model_path}")
        print(f"  Embedding dimension: {model_en.get_embedding_dimension()}")
    except Exception as e:
        print(f"✗ Failed to load English model: {e}")
        return False

    print("\nAll models downloaded and verified successfully!")
    print(f"Total models saved in: {MODELS_DIR}")
    return True

if __name__ == "__main__":
    success = download_models()
    sys.exit(0 if success else 1)
