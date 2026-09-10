# Model Setup Guide

QSearch uses local models stored in the `models/` directory to avoid network downloads during runtime.

## Directory Structure

```
models/
├── paddle/                          # PaddleOCR models (18MB)
│   ├── det/ch_PP-OCRv4_det_infer/  # Text detection
│   ├── rec/ch_PP-OCRv4_rec_infer/  # Text recognition
│   └── cls/ch_ppocr_mobile_v2.0_cls_infer/  # Text angle classification
├── chinese-roberta-wwm-ext/         # Chinese BERT encoder (391MB)
└── all-mpnet-base-v2/               # English sentence encoder (419MB)
```

## Download Models

### Option 1: Run the download script (Recommended)

```bash
uv run scripts/download_models.py
```

This downloads the BERT/transformer models into `models/`.

### Option 2: Copy existing PaddleOCR models

If PaddleOCR has already downloaded models to `~/.paddleocr/`, copy them:

```bash
# Windows (Git Bash)
mkdir -p models/paddle/{det,rec,cls}
cp -r ~/.paddleocr/whl/det/ch/ch_PP-OCRv4_det_infer models/paddle/det/
cp -r ~/.paddleocr/whl/rec/ch/ch_PP-OCRv4_rec_infer models/paddle/rec/
cp -r ~/.paddleocr/whl/cls/ch_ppocr_mobile_v2.0_cls_infer models/paddle/cls/

# Linux
mkdir -p models/paddle/{det,rec,cls}
cp -r ~/.paddleocr/whl/det/ch/ch_PP-OCRv4_det_infer models/paddle/det/
cp -r ~/.paddleocr/whl/rec/ch/ch_PP-OCRv4_rec_infer models/paddle/rec/
cp -r ~/.paddleocr/whl/cls/ch_ppocr_mobile_v2.0_cls_infer models/paddle/cls/
```

## How Models Are Loaded

### PaddleOCR (OCREngine)

- **Default location**: `models/paddle/`
- **Fallback**: If local models don't exist, PaddleOCR auto-downloads to `~/.paddleocr/`
- **Custom path**: Pass `model_dir="/path/to/models"` to `OCREngine()`

### Text Encoders (TextFeatureExtractor)

- **Priority**: Local `models/chinese-roberta-wwm-ext` and `models/all-mpnet-base-v2`
- **Fallback**: Download from HuggingFace Hub with `cache_dir=models/`
- **Offline mode**: Set `HF_HUB_OFFLINE=1` to force local-only loading

## Troubleshooting

### PaddleOCR downloads models every run

Check that the models exist at the expected paths:

```bash
ls models/paddle/det/ch_PP-OCRv4_det_infer/inference.pdmodel
ls models/paddle/rec/ch_PP-OCRv4_rec_infer/inference.pdmodel
ls models/paddle/cls/ch_ppocr_mobile_v2.0_cls_infer/inference.pdmodel
```

If missing, run the copy command above or let PaddleOCR download them once (they'll be reused).

### Transformers models timeout

If `download_models.py` fails due to network issues:

1. Set HuggingFace mirror (China):
   ```bash
   export HF_ENDPOINT=https://hf-mirror.com
   uv run scripts/download_models.py
   ```

2. Or download manually and extract to `models/`:
   - https://huggingface.co/hfl/chinese-roberta-wwm-ext
   - https://huggingface.co/sentence-transformers/all-mpnet-base-v2

### "cannot pickle PaddleInferPredictor"

Fixed. `FeatureExtractor` no longer ships its extractors across the process
boundary: `extract_batch` uses a `Pool` initializer so each worker builds its own
OCR engine and encoders, and GPU distribution uses a module-level worker function
(required on Windows, which spawns rather than forks).

### Out-of-memory during batch extraction

Each worker loads its own OCR engine and both text encoders, roughly 1GB resident.
`extract_batch` sizes the pool against available RAM rather than CPU count, so on a
16-core machine with 6GB free it uses 3 workers, not 15. Override explicitly with
`extract_batch(paths, num_workers=N)`.
