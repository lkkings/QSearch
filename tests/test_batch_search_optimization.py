from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import numpy as np

from qsearch.matching.matchers import ContentMatcher
from qsearch.tasks.index_cache import SearchEngineCache
from qsearch.tasks.runner_interactive import run_interactive_search
from qsearch.tasks.runner_search import run_batch_search
from qsearch.tasks.worker_pool import extract_features_job


class _FakeFaissIndex:
    dimension = 2

    def __init__(self) -> None:
        self.calls: list[np.ndarray] = []

    def search(self, vectors, k, threshold):
        self.calls.append(vectors.copy())
        return [[("candidate.jpg", 0.95)] for _ in vectors]


def test_content_matcher_batches_faiss_queries() -> None:
    faiss_index = _FakeFaissIndex()
    matcher = ContentMatcher(
        faiss_index,
        {
            "candidate.jpg": {
                "text_features": {"full_text": "same question"},
            }
        },
        {
            "enabled": True,
            "stage1": {"top_k": 20, "text_similarity_threshold": 0.5},
            "scoring": {"threshold": 0.0},
        },
    )
    queries = [
        {
            "text_features": {
                "text_embedding": [1.0, float(index)],
                "full_text": "same question",
            }
        }
        for index in range(3)
    ]

    results = matcher.match_batch(queries, top_n=5, batch_size=10)

    assert len(faiss_index.calls) == 1
    assert faiss_index.calls[0].shape == (3, 2)
    assert [batch[0]["image_id"] for batch in results] == [
        "candidate.jpg",
        "candidate.jpg",
        "candidate.jpg",
    ]


def test_index_cache_reuses_then_evicts_after_idle_ttl(tmp_path: Path) -> None:
    now = [0.0]
    engines = []
    extractors = []

    class FakeExtractor:
        pass

    class FakeEngine:
        def __init__(
            self,
            *args,
            index_resources=None,
            feature_extractor=None,
            **kwargs,
        ) -> None:
            self.closed = False
            self.received_resources = index_resources
            self.index_resources = index_resources or (object(), object(), {})
            self.feature_extractor = feature_extractor
            engines.append(self)

        def close(self) -> None:
            self.closed = True

    cache = SearchEngineCache(
        idle_ttl_seconds=1800,
        clock=lambda: now[0],
        engine_factory=FakeEngine,
        extractor_factory=lambda config: extractors.append(FakeExtractor()) or extractors[-1],
    )

    with cache.acquire(tmp_path / "db", {"matching": {}}) as first:
        now[0] = 2000.0
        assert cache.evict_idle() == 0

    now[0] = 2001.0
    with cache.acquire(tmp_path / "db", {"matching": {}}) as second:
        assert second is first
    assert len(engines) == 1

    with cache.acquire(
        tmp_path / "db",
        {"matching": {"content_match": {"enabled": True}}},
        load_feature_extractor=True,
    ) as interactive:
        assert interactive is not first
        assert interactive.received_resources is first.index_resources
    assert len(engines) == 2
    assert len(extractors) == 1

    with cache.acquire(
        tmp_path / "db",
        {"matching": {"content_match": {"enabled": False}}},
        load_feature_extractor=True,
    ) as reconfigured:
        assert reconfigured is not interactive
        assert reconfigured.received_resources is first.index_resources
        assert reconfigured.feature_extractor is interactive.feature_extractor
    assert len(extractors) == 1

    now[0] = 3801.0
    assert cache.evict_idle() == 1
    assert first.closed is True
    assert interactive.closed is True
    assert reconfigured.closed is True
    assert len(cache) == 0


def test_run_batch_search_extracts_all_features_before_batch_lookup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_dir = tmp_path / "db"
    (db_dir / "annotations").mkdir(parents=True)
    (db_dir / "config.yaml").write_text("matching: {}\n", encoding="utf-8")

    events = []
    image_paths = ["q1.jpg", "q2.jpg"]
    extracted = [
        {
            "image_path": path,
            "text_features": {"text_embedding": [1.0, 0.0]},
            "image_features": {},
            "extraction_success": True,
        }
        for path in image_paths
    ]

    class FakeQueue:
        def read_payload(self, task):
            return image_paths

        def update_progress(self, *args, **kwargs):
            pass

        def is_cancel_requested(self, task_id):
            return False

    class FakePool:
        def imap(self, job_fn, items):
            assert job_fn is extract_features_job
            for features in extracted:
                events.append("extract")
                yield features

    class FakeEngine:
        def search_features_batch(self, features, top_n):
            events.append("search")
            assert features == extracted
            return [
                {"exact_matches": [], "content_matches": []}
                for _ in features
            ]

    class FakeCache:
        @contextmanager
        def acquire(self, database_path, config):
            yield FakeEngine()

    class FakeRegistry:
        index_cache = FakeCache()

        def acquire(self, spec, num_workers):
            return FakePool()

    saved = []
    monkeypatch.setattr(
        "qsearch.tasks.runner_search.result_store.save_query_result",
        lambda **kwargs: saved.append(kwargs),
    )
    task = {
        "task_id": "task-1",
        "database_name": "db",
        "num_workers": 2,
        "top_n": 5,
        "last_processed_index": -1,
        "failed_items": 0,
        "config_yaml": None,
        "config_preset": None,
    }

    summary = run_batch_search(task, FakeQueue(), FakeRegistry(), tmp_path)

    assert events == ["extract", "extract", "search"]
    assert [item["query_image_path"] for item in saved] == image_paths
    assert summary == {"processed": 2, "failed": 0}


def test_run_batch_search_uses_requested_gpus(tmp_path: Path, monkeypatch) -> None:
    db_dir = tmp_path / "db"
    (db_dir / "annotations").mkdir(parents=True)
    (db_dir / "config.yaml").write_text("matching: {}\n", encoding="utf-8")
    image_paths = ["q1.jpg", "q2.jpg"]
    calls = {}

    class FakeQueue:
        def read_payload(self, task):
            return image_paths

        def update_progress(self, *args, **kwargs):
            pass

        def is_cancel_requested(self, task_id):
            return False

    class FakeExtractor:
        def __init__(self, config, use_gpu):
            calls["extractor"] = {"config": config, "use_gpu": use_gpu}

        def extract_batch_gpu_distributed(self, paths, **kwargs):
            calls["gpu_extract"] = {"paths": list(paths), **kwargs}
            return [
                {
                    "image_path": path,
                    "text_features": {"text_embedding": [1.0, 0.0]},
                    "image_features": {},
                    "extraction_success": True,
                }
                for path in paths
            ]

    class FakeEngine:
        def search_features_batch(self, features, **kwargs):
            calls["search"] = kwargs
            return [
                {"exact_matches": [], "content_matches": []}
                for _ in features
            ]

    class FakeCache:
        @contextmanager
        def acquire(self, database_path, config):
            yield FakeEngine()

    class FakeRegistry:
        index_cache = FakeCache()

        def acquire(self, spec, num_workers):
            raise AssertionError("GPU mode must not acquire the CPU worker pool")

    saved = []
    monkeypatch.setattr(
        "qsearch.tasks.runner_search._cuda_device_count", lambda: 4
    )
    monkeypatch.setattr(
        "qsearch.features.feature_extractor.FeatureExtractor", FakeExtractor
    )
    monkeypatch.setattr(
        "qsearch.tasks.runner_search.result_store.save_query_result",
        lambda **kwargs: saved.append(kwargs),
    )
    task = {
        "task_id": "gpu-task",
        "database_name": "db",
        "num_workers": 4,
        "num_gpus": 2,
        "batch_size": 7,
        "top_n": 5,
        "last_processed_index": -1,
        "failed_items": 0,
        "config_yaml": None,
        "config_preset": None,
    }

    summary = run_batch_search(task, FakeQueue(), FakeRegistry(), tmp_path)

    assert calls["extractor"]["use_gpu"] is True
    assert calls["gpu_extract"] == {
        "paths": image_paths,
        "num_gpus": 2,
        "show_progress": False,
        "batch_size": 7,
    }
    assert calls["search"] == {"top_n": 5, "batch_size": 7}
    assert [item["query_image_path"] for item in saved] == image_paths
    assert summary == {"processed": 2, "failed": 0}


def test_interactive_search_uses_shared_index_cache(tmp_path: Path, monkeypatch) -> None:
    db_dir = tmp_path / "db"
    (db_dir / "annotations").mkdir(parents=True)
    (db_dir / "config.yaml").write_text("matching: {}\n", encoding="utf-8")

    class FakeQueue:
        def read_payload(self, task):
            return {"query_image_path": "query.jpg"}

        def update_progress(self, *args, **kwargs):
            pass

    class FakeEngine:
        def search_single(self, query_image, top_n):
            return {"exact_matches": [], "content_matches": []}

    calls = []

    class FakeCache:
        @contextmanager
        def acquire(self, database_path, config, load_feature_extractor=False):
            calls.append((database_path, load_feature_extractor))
            yield FakeEngine()

    class FakeRegistry:
        index_cache = FakeCache()

    monkeypatch.setattr(
        "qsearch.tasks.runner_interactive.result_store.save_query_result",
        lambda **kwargs: "query-id",
    )
    task = {
        "task_id": "interactive-1",
        "database_name": "db",
        "top_n": 5,
        "config_yaml": None,
        "config_preset": None,
    }

    run_interactive_search(task, FakeQueue(), FakeRegistry(), tmp_path)

    assert calls == [(db_dir, True)]
