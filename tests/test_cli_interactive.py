from __future__ import annotations

import yaml

from scripts import index_database, search_queries


def _answers(values):
    iterator = iter(values)
    return lambda _prompt: next(iterator)


def test_index_wizard_builds_webui_compatible_config(tmp_path) -> None:
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    args = index_database.create_parser().parse_args([])

    options = index_database.collect_index_wizard(
        args,
        input_fn=_answers(["demo", str(image_dir), *([""] * 17)]),
        output_fn=lambda _message: None,
    )

    assert options["database_name"] == "demo"
    assert options["batch_size"] == 128
    assert options["config"]["text"]["encoding"]["batch_size"] == 128
    assert options["config"]["image"]["batch_size"] == 128
    assert options["config"]["index"] == {"type": "Flat"}
    assert "matching" in options["config"]


def test_search_wizard_derives_query_parameters_from_database(tmp_path) -> None:
    database_dir = tmp_path / "databases" / "demo"
    index_dir = database_dir / "index"
    query_dir = tmp_path / "queries"
    index_dir.mkdir(parents=True)
    query_dir.mkdir()
    (query_dir / "query.jpg").write_bytes(b"image")
    for name in ("features.pkl", "text_index.faiss", "text_index_ids.pkl", "hash_index.pkl"):
        (index_dir / name).write_bytes(b"")

    config = index_database.default_feature_config()
    (database_dir / "config.yaml").write_text(
        yaml.safe_dump(config, allow_unicode=True), encoding="utf-8"
    )
    args = search_queries.create_parser().parse_args([])

    options = search_queries.collect_search_wizard(
        args,
        input_fn=_answers([
            str(tmp_path / "databases"),
            "",  # database
            "",  # task name
            "",  # folder mode
            str(query_dir),
            *([""] * 9),
        ]),
        output_fn=lambda _message: None,
    )

    assert options["database_name"] == "demo"
    assert options["query_paths"] == [(query_dir / "query.jpg").resolve()]
    assert options["top_n"] == 10
    assert options["batch_size"] == 32
    queued_config = yaml.safe_load(options["config_yaml"])
    assert queued_config["matching"]["content_match"]["enabled"] is True
    assert "output_file" not in options
    assert options["num_gpus"] == 0


def test_legacy_index_arguments_remain_non_interactive(monkeypatch, tmp_path) -> None:
    called = []
    monkeypatch.setattr(
        index_database,
        "_run_direct_build",
        lambda args: called.append(args) or {"total_images": 0},
    )

    exit_code = index_database.main([
        "--image-dir", str(tmp_path),
        "--output-dir", str(tmp_path / "index"),
        "--batch-size", "16",
    ])

    assert exit_code == 0
    assert called[0].batch_size == 16


def test_search_arguments_remain_non_interactive(monkeypatch, tmp_path) -> None:
    options = {
        "output_file": tmp_path / "results.json",
        "query_paths": [],
        "database_name": "demo",
        "top_n": 10,
        "batch_size": 8,
        "num_gpus": 2,
    }
    monkeypatch.setattr(search_queries, "_direct_options", lambda args, parser: options)
    monkeypatch.setattr(search_queries, "run_search", lambda value: ([], {"total_queries": 0}))
    monkeypatch.setattr(search_queries, "_save_results", lambda *args: None)

    exit_code = search_queries.main([
        "--query-dir", str(tmp_path),
        "--index-dir", str(tmp_path),
        "--output-file", str(tmp_path / "results.json"),
    ])

    assert exit_code == 0


def test_managed_index_build_is_enqueued(monkeypatch, tmp_path) -> None:
    calls = []
    monkeypatch.setattr(
        index_database,
        "_enqueue_managed_build",
        lambda options: calls.append(options) or (
            "index-task-id",
            {"pid": 123, "log_path": tmp_path / "scheduler.log"},
        ),
    )

    exit_code = index_database.main([
        "--image-dir", str(tmp_path),
        "--database-name", "demo",
        "--databases-root", str(tmp_path / "databases"),
        "--batch-size", "16",
        "--non-interactive",
    ])

    assert exit_code == 0
    assert calls[0]["database_name"] == "demo"
    assert calls[0]["batch_size"] == 16


def test_managed_search_is_enqueued(monkeypatch, tmp_path) -> None:
    options = {
        "database_name": "demo",
        "databases_root": tmp_path / "databases",
        "query_paths": [tmp_path / "query.jpg"],
        "task_name": "batch demo",
        "config_yaml": None,
        "top_n": 10,
        "batch_size": 8,
    }
    calls = []
    monkeypatch.setattr(
        search_queries,
        "_managed_queue_options",
        lambda args, parser: options,
    )
    monkeypatch.setattr(
        search_queries,
        "_enqueue_managed_search",
        lambda value: calls.append(value) or (
            "search-task-id",
            {"pid": 123, "log_path": tmp_path / "scheduler.log"},
        ),
    )
    monkeypatch.setattr(
        search_queries,
        "run_search",
        lambda _value: (_ for _ in ()).throw(AssertionError("must use scheduler")),
    )

    exit_code = search_queries.main([
        "--query-dir", str(tmp_path),
        "--database-name", "demo",
        "--databases-root", str(tmp_path / "databases"),
        "--non-interactive",
    ])

    assert exit_code == 0
    assert calls == [options]


def test_managed_search_forwards_gpu_count_to_task_manager(
    monkeypatch, tmp_path
) -> None:
    calls = {}

    class FakeTaskManager:
        def __init__(self, databases_root):
            calls["databases_root"] = databases_root

        def enqueue_batch_search(self, **kwargs):
            calls["enqueue"] = kwargs
            return "task-id"

        def scheduler_status(self):
            return {"pid": 123, "log_path": tmp_path / "scheduler.log"}

    monkeypatch.setattr(search_queries, "TaskManager", FakeTaskManager)
    options = {
        "database_name": "demo",
        "databases_root": tmp_path / "databases",
        "query_paths": [tmp_path / "query.jpg"],
        "task_name": "batch demo",
        "config_yaml": None,
        "top_n": 10,
        "batch_size": 8,
        "num_gpus": 2,
    }

    task_id, _status = search_queries._enqueue_managed_search(options)

    assert task_id == "task-id"
    assert calls["enqueue"]["num_gpus"] == 2


def test_terminal_search_passes_batch_size_to_extraction_and_matching(
    monkeypatch, tmp_path
) -> None:
    calls = {}

    class FakeFaiss:
        def __init__(self, **kwargs):
            pass

        def load(self, *args):
            pass

        def apply_search_params(self):
            pass

    class FakeHash:
        def load(self, *args, **kwargs):
            pass

    class FakeExtractor:
        def __init__(self, config, use_gpu):
            calls["use_gpu"] = use_gpu

        def load_features(self, *args, **kwargs):
            return []

        def extract_batch(self, paths, **kwargs):
            calls["extract"] = kwargs
            return [
                {
                    "image_path": str(path),
                    "text_features": {},
                    "image_features": {},
                    "extraction_success": True,
                }
                for path in paths
            ]

    class FakeMatcher:
        def __init__(self, *args):
            pass

        def match_batch(self, features, **kwargs):
            calls["match"] = kwargs
            return [{"matches": [], "top_k": 0} for _ in features]

    monkeypatch.setattr(search_queries, "FaissIndexBuilder", FakeFaiss)
    monkeypatch.setattr(search_queries, "HashIndex", FakeHash)
    monkeypatch.setattr(search_queries, "FeatureExtractor", FakeExtractor)
    monkeypatch.setattr(search_queries, "ExactMatcher", lambda *args: object())
    monkeypatch.setattr(search_queries, "ContentMatcher", lambda *args: object())
    monkeypatch.setattr(search_queries, "QuestionMatcher", FakeMatcher)

    results, _stats = search_queries.run_search({
        "index_dir": tmp_path,
        "config": {},
        "num_gpus": 0,
        "query_paths": [tmp_path / "a.jpg", tmp_path / "b.jpg"],
        "batch_size": 7,
        "top_n": 5,
    })

    assert len(results) == 2
    assert calls["use_gpu"] is False
    assert calls["extract"]["batch_size"] == 7
    assert calls["match"] == {"top_n": 5, "vector_batch_size": 7}
