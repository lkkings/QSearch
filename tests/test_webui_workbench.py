"""Contracts introduced by the single-page WebUI integration."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from qsearch.webui.ui.components.results_grid import _candidates
from qsearch.webui.ui.search_ui import SEARCH_TAB_LABELS


def test_search_modes_are_peer_tabs():
    assert SEARCH_TAB_LABELS[:2] == ("单图搜索", "批量搜索")


def test_result_grid_normalizes_matcher_buckets_without_copying_cards():
    exact = {"image_path": "exact.jpg", "overall_score": 1.0}
    content = {"image_path": "content.jpg", "overall_score": 0.8}

    normalized = _candidates(
        {"exact_matches": [exact], "content_matches": [content]}
    )

    assert normalized == [exact, content]
    assert normalized[0] is exact
    assert normalized[1] is content
    assert exact["match_type"] == "exact"
    assert content["match_type"] == "content"


def test_result_grid_accepts_persisted_candidate_shape():
    candidate = {
        "candidate_id": 7,
        "candidate_image_path": "candidate.jpg",
        "label": "hit",
    }

    normalized = _candidates({"query": {"query_id": "q1"}, "candidates": [candidate]})

    assert normalized == [candidate]
    assert normalized[0] is candidate


def test_batch_search_button_enqueues_task(tmp_path: Path) -> None:
    image_dir = tmp_path / "queries"
    image_dir.mkdir()
    (image_dir / "query.jpg").write_bytes(b"image")
    queue_root = tmp_path / "queue"

    script = f"""
import os
from pathlib import Path
from qsearch.webui.ui import search_ui

os.environ['QSEARCH_QUEUE_ROOT'] = {str(queue_root)!r}
search_ui.TaskManager.ensure_scheduler = lambda self, max_workers=None: {{'running': True}}
search_ui.search_params_ui.render_search_params_panel = lambda **kwargs: ({{'top_n': 5}}, '')
search_ui.render_batch_search_tab(Path({str(tmp_path)!r}), 'test')
"""

    app = AppTest.from_string(script).run()
    assert not app.exception

    app.text_input(key="qs_batch_folder").set_value(str(image_dir)).run()
    app.number_input(key="qs_batch_num_gpus").set_value(2).run()
    assert app.button(key="qs_batch_submit").disabled is False

    app.button(key="qs_batch_submit").click().run()
    assert not app.exception
    assert app.session_state["qs_batch_task_id"]
    assert app.success
    assert "批量检索已入队" in app.success[0].value

    from qsearch.tasks.queue import TaskKind, TaskQueue

    tasks = TaskQueue(queue_root).list_tasks()
    assert len(tasks) == 1
    assert tasks[0]["kind"] == TaskKind.BATCH_SEARCH
    assert tasks[0]["num_gpus"] == 2
