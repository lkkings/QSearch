from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import torch
from PIL import Image

from qsearch.features.feature_extractor import FeatureExtractor
from qsearch.features.image_extractor import ImageFeatureExtractor
from qsearch.features.text_extractor import TextFeatureExtractor
from qsearch.tasks.queue import TaskKind, TaskQueue
from qsearch.webui.task_manager import TaskManager


class _BatchExtractor:
    def __init__(self, feature_name: str) -> None:
        self.feature_name = feature_name
        self.calls = []

    def extract_batch(self, images, batch_size):
        self.calls.append((list(images), batch_size))
        return [
            {self.feature_name: str(image), "extraction_success": True}
            for image in images
        ]


def test_feature_extractor_batches_text_and_images_together() -> None:
    text = _BatchExtractor("text")
    image = _BatchExtractor("image")
    extractor = FeatureExtractor({}, text_extractor=text, image_extractor=image)

    results = extractor.extract_batch(
        ["a.jpg", "b.jpg", "c.jpg"],
        num_workers=1,
        show_progress=False,
        batch_size=2,
    )

    assert text.calls == [(["a.jpg", "b.jpg"], 2), (["c.jpg"], 2)]
    assert image.calls == [(["a.jpg", "b.jpg"], 2), (["c.jpg"], 2)]
    assert [result["image_path"] for result in results] == [
        "a.jpg",
        "b.jpg",
        "c.jpg",
    ]


def test_text_models_are_moved_to_selected_gpu(monkeypatch) -> None:
    devices = []

    class FakeModel:
        def to(self, device):
            devices.append(str(device))
            return self

        def eval(self):
            return self

    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(
        "qsearch.features.text_extractor.AutoTokenizer.from_pretrained",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        "qsearch.features.text_extractor.AutoModel.from_pretrained",
        lambda *args, **kwargs: FakeModel(),
    )

    extractor = TextFeatureExtractor(
        {},
        ocr_engine=object(),
        preprocessor=object(),
        use_gpu=True,
        gpu_id=2,
    )

    assert str(extractor.device) == "cuda:2"
    assert devices == ["cuda:2", "cuda:2"]


def test_text_encoder_uses_one_forward_pass_for_a_batch() -> None:
    calls = []

    class FakeTokenizer:
        def __call__(self, texts, **kwargs):
            calls.append(list(texts))
            return {"input_ids": torch.ones((len(texts), 2), dtype=torch.long)}

    class FakeEncoder:
        def __call__(self, **inputs):
            count = inputs["input_ids"].shape[0]
            values = torch.arange(count * 6, dtype=torch.float32).reshape(count, 2, 3)
            return SimpleNamespace(last_hidden_state=values)

    extractor = TextFeatureExtractor.__new__(TextFeatureExtractor)
    extractor.device = torch.device("cpu")
    extractor.max_length = 16
    extractor._english_tokenizer = FakeTokenizer()
    extractor._english_encoder = FakeEncoder()
    extractor._chinese_tokenizer = None
    extractor._chinese_encoder = None

    embeddings = extractor._encode_text_batch(["one", "two", "three"], "en")

    assert calls == [["one", "two", "three"]]
    assert len(embeddings) == 3
    np.testing.assert_array_equal(embeddings[1], np.array([6, 7, 8]))


def test_image_batch_preserves_failed_input_position() -> None:
    extractor = ImageFeatureExtractor.__new__(ImageFeatureExtractor)
    extractor.components_config = {
        "perceptual_hash": {"enabled": True, "algorithm": "dHash", "hash_size": 8},
        "deep_features": {"enabled": False},
    }
    extractor._cnn_model = None
    extractor._transform = None
    extractor._load_image = lambda value: None if value == "bad" else Image.new("RGB", (2, 2))
    extractor._compute_perceptual_hash = lambda *args, **kwargs: "hash"

    results = extractor._extract_batch_gpu(["good-1", "bad", "good-2"])

    assert len(results) == 3
    assert results[0]["perceptual_hash"] == "hash"
    assert results[1]["error"] == "Failed to load image"
    assert results[1]["extraction_success"] is False
    assert results[2]["perceptual_hash"] == "hash"


def test_task_queue_round_trips_batch_size(tmp_path) -> None:
    queue = TaskQueue(tmp_path / "queue")
    task_id = queue.enqueue(
        TaskKind.BATCH_SEARCH,
        "batch",
        "db",
        batch_size=17,
    )

    assert queue.get_task(task_id)["batch_size"] == 17


def test_task_manager_round_trips_batch_search_gpu_count(
    tmp_path, monkeypatch
) -> None:
    databases_root = tmp_path / "databases"
    manager = TaskManager(databases_root, queue_root=tmp_path / "queue")
    monkeypatch.setattr(manager, "ensure_scheduler", lambda **_kwargs: {})

    task_id = manager.enqueue_batch_search(
        database_name="db",
        image_paths=[tmp_path / "query.jpg"],
        num_workers=4,
        num_gpus=2,
        batch_size=17,
    )

    task = manager.get_task_status(task_id)
    assert task["num_gpus"] == 2
    assert task["num_workers"] is None
    assert task["batch_size"] == 17
