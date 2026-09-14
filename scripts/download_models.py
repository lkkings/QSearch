"""Download all QSearch models into the project-local ``models`` folder."""

from __future__ import annotations

import sys
from pathlib import Path

from sentence_transformers import SentenceTransformer
from transformers import AutoModel, AutoTokenizer

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = PROJECT_ROOT / "models"


def download_transformers_model(repo_id: str, save_path: Path) -> bool:
    """Download and persist a text encoder in Transformers format."""
    print(f"\nDownloading {repo_id} -> {save_path}")
    try:
        tokenizer = AutoTokenizer.from_pretrained(repo_id, cache_dir=str(MODELS_DIR))
        model = AutoModel.from_pretrained(repo_id, cache_dir=str(MODELS_DIR))
        save_path.mkdir(parents=True, exist_ok=True)
        tokenizer.save_pretrained(str(save_path))
        model.save_pretrained(str(save_path), safe_serialization=True)
        return True
    except Exception as exc:
        print(f"Failed to download {repo_id}: {exc}")
        return False


def download_sentence_transformer(repo_id: str, save_path: Path) -> bool:
    """Download and persist a SentenceTransformer model."""
    print(f"\nDownloading {repo_id} -> {save_path}")
    try:
        model = SentenceTransformer(repo_id, cache_folder=str(MODELS_DIR))
        save_path.mkdir(parents=True, exist_ok=True)
        model.save(str(save_path))
        return True
    except Exception as exc:
        print(f"Failed to download {repo_id}: {exc}")
        return False


def download_ocr_model() -> bool:
    """Download the Transformers OCR model to ``models/got-ocr-2.0-hf``."""
    print("\nDownloading Transformers OCR model")
    try:
        # Import after the text models so this script remains useful when only
        # diagnosing an OCR dependency problem.
        from qsearch.features.ocr_engine import OCREngine

        engine = OCREngine(use_gpu=False)
        print(f"OCR model is ready at {engine.model_dir}")
        return True
    except Exception as exc:
        print(f"Failed to download the OCR model: {exc}")
        return False


def download_models() -> bool:
    """Download all required models and return whether every download worked."""
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    jobs = [
        download_transformers_model(
            "hfl/chinese-roberta-wwm-ext",
            MODELS_DIR / "chinese-roberta-wwm-ext",
        ),
        download_sentence_transformer(
            "sentence-transformers/all-mpnet-base-v2",
            MODELS_DIR / "all-mpnet-base-v2",
        ),
        download_ocr_model(),
    ]
    succeeded = sum(jobs)
    print(f"\nModels ready: {succeeded}/{len(jobs)} in {MODELS_DIR}")
    return succeeded == len(jobs)


if __name__ == "__main__":
    sys.exit(0 if download_models() else 1)
