from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest
import torch

from qsearch.features import ocr_engine as ocr_module
from qsearch.features.ocr_engine import OCREngine


class FakeProcessor:
    def __init__(self, text="中文\nEnglish"):
        self.text = text
        self.saved_to = None
        self.last_image = None

    def __call__(self, *, images, return_tensors):
        self.last_image = images
        assert return_tensors == "pt"
        return {
            "input_ids": torch.tensor([[7, 8]]),
            "pixel_values": torch.zeros((1, 3, 4, 6)),
        }

    def batch_decode(self, token_ids, skip_special_tokens):
        assert skip_special_tokens is True
        return [self.text]

    def save_pretrained(self, path):
        self.saved_to = path


class FakeModel:
    def __init__(self):
        self.saved_to = None
        self.moved_to = None
        self.eval_called = False

    def save_pretrained(self, path, safe_serialization):
        self.saved_to = path
        assert safe_serialization is True

    def to(self, device):
        self.moved_to = device
        return self

    def eval(self):
        self.eval_called = True
        return self

    def generate(self, **kwargs):
        logits = torch.tensor([[0.0, 4.0, 0.0]])
        return SimpleNamespace(
            sequences=torch.tensor([[7, 8, 1, 1]]),
            scores=(logits, logits),
        )

    def get_input_embeddings(self):
        return SimpleNamespace(weight=torch.zeros(1))


def install_fake_transformers(monkeypatch, processor, model):
    processor_loader = MagicMock(return_value=processor)
    model_loader = MagicMock(return_value=model)
    monkeypatch.setattr(ocr_module.AutoProcessor, "from_pretrained", processor_loader)
    monkeypatch.setattr(
        ocr_module.AutoModelForImageTextToText,
        "from_pretrained",
        model_loader,
    )
    return processor_loader, model_loader


def test_downloads_saves_and_runs_ocr_on_cpu(monkeypatch, tmp_path):
    processor = FakeProcessor()
    model = FakeModel()
    processor_loader, model_loader = install_fake_transformers(monkeypatch, processor, model)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)

    model_dir = tmp_path / "models" / "ocr"
    engine = OCREngine(use_gpu=True, model_dir=str(model_dir), model_name="org/ocr")

    processor_loader.assert_called_once_with("org/ocr", cache_dir=str(engine.models_root))
    assert model_loader.call_args.args == ("org/ocr",)
    assert model_loader.call_args.kwargs["torch_dtype"] == torch.float32
    assert processor.saved_to == str(model_dir)
    assert model.saved_to == str(model_dir)
    assert model.moved_to == torch.device("cpu")

    # QSearch passes OpenCV BGR arrays. The processor must receive RGB.
    image = np.zeros((4, 6, 3), dtype=np.uint8)
    image[0, 0] = [10, 20, 30]
    results, success = engine.extract_text(image, confidence_threshold=0.5)

    assert success is True
    assert [result.text for result in results] == ["中文", "English"]
    assert [result.language for result in results] == ["ch", "en"]
    assert results[0].bbox == [[0, 0], [6, 0], [6, 4], [0, 4]]
    assert processor.last_image.getpixel((0, 0)) == (30, 20, 10)
    assert results[0].confidence > 0.9


def test_existing_model_uses_transformers_auto_device_map(monkeypatch, tmp_path):
    model_dir = tmp_path / "got-ocr-2.0-hf"
    model_dir.mkdir()
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    processor = FakeProcessor()
    model = FakeModel()
    processor_loader, model_loader = install_fake_transformers(monkeypatch, processor, model)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "device_count", lambda: 2)

    OCREngine(use_gpu=True, gpu_id=1, model_dir=str(model_dir))

    processor_loader.assert_called_once_with(str(model_dir))
    assert model_loader.call_args.kwargs["device_map"] == "auto"
    assert model_loader.call_args.kwargs["torch_dtype"] == torch.float16
    assert model.moved_to is None
    assert processor.saved_to is None


def test_multi_gpu_can_be_pinned_for_a_data_parallel_worker(monkeypatch, tmp_path):
    model_dir = tmp_path / "got-ocr-2.0-hf"
    model_dir.mkdir()
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    processor = FakeProcessor()
    model = FakeModel()
    _, model_loader = install_fake_transformers(monkeypatch, processor, model)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "device_count", lambda: 2)

    OCREngine(use_gpu=True, gpu_id=1, model_dir=str(model_dir), multi_gpu=False)

    assert "device_map" not in model_loader.call_args.kwargs
    assert model.moved_to == torch.device("cuda:1")


def test_invalid_gpu_id_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "device_count", lambda: 1)

    with pytest.raises(ValueError, match="gpu_id 2"):
        OCREngine(use_gpu=True, gpu_id=2, model_dir=str(tmp_path))
