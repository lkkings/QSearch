"""Streamlit-facing checks for task-based annotation navigation."""

from __future__ import annotations

from streamlit.testing.v1 import AppTest

from qsearch.webui.ui import annotation_ui


def _task(status: str = "unlabeled") -> dict:
    query = {
        "query_id": "q1",
        "query_image_path": "/queries/q1.png",
        "total": 2,
        "labeled": 0,
        "hits": 0,
        "annotation_status": status,
    }
    return {
        "task_id": "task-1",
        "task_name": "第一批查询",
        "kind": "batch_search",
        "status": "completed",
        "total_items": 1,
        "query_count": 1,
        "completed_count": 0,
        "annotation_progress": 0.0,
        "annotatable": True,
        "payload_unavailable": False,
        "queries": [query],
    }


def test_task_list_renders_annotation_summary() -> None:
    script = f"""
from qsearch.webui.ui.annotation_ui import _render_task_list
_render_task_list({[_task()]!r}, 'demo', {{
    'completed_queries': 0,
    'total_queries': 1,
    'labeled_candidates': 0,
}})
"""
    app = AppTest.from_string(script).run()

    assert not app.exception
    assert len(app.dataframe) == 1
    frame = app.dataframe[0].value
    assert frame.loc[0, "任务"] == "第一批查询"
    assert frame.loc[0, "可标注 Query"] == 1
    assert frame.loc[0, "操作"] == ":material/edit: 进入标注"


def test_task_without_available_queries_has_no_entry_action() -> None:
    task = _task()
    task.update(
        {
            "query_count": 0,
            "completed_count": 0,
            "annotation_progress": 0.0,
            "annotatable": False,
            "queries": [],
        }
    )
    script = f"""
from qsearch.webui.ui.annotation_ui import _render_task_list
_render_task_list({[task]!r}, 'demo', {{
    'completed_queries': 0,
    'total_queries': 0,
    'labeled_candidates': 0,
}})
"""
    app = AppTest.from_string(script).run()

    assert not app.exception
    assert app.dataframe[0].value.loc[0, "操作"] is None


def test_enter_task_chooses_first_unfinished_query() -> None:
    task = _task()
    task["queries"].insert(
        0,
        {
            "query_id": "done",
            "query_image_path": "/queries/done.png",
            "total": 1,
            "labeled": 1,
            "hits": 1,
            "annotation_status": "completed",
        },
    )
    script = f"""
import streamlit as st
from qsearch.webui.ui.annotation_ui import _enter_task_from_table
st.session_state['qs_annotation_task_click'] = {{'row': 0, 'label': '进入标注'}}
_enter_task_from_table({[task]!r})
"""
    app = AppTest.from_string(script).run()

    assert not app.exception
    assert app.session_state["qs_annotation_task_id"] == "task-1"
    assert app.session_state["qs_annotation_query_id"] == "q1"


def test_query_navigation_renders_direct_status_buttons() -> None:
    task = _task()
    task["queries"] = [
        {
            "query_id": f"q{index}",
            "query_image_path": f"/queries/q{index}.png",
            "total": 0 if status == "no_candidates" else 2,
            "labeled": 2 if status == "completed" else int(status == "partial"),
            "hits": int(status in {"partial", "completed"}),
            "annotation_status": status,
        }
        for index, status in enumerate(
            ("unlabeled", "partial", "completed", "no_candidates"), start=1
        )
    ]
    script = f"""
import streamlit as st
from qsearch.webui.ui.annotation_ui import _render_query_navigation
selected = st.session_state.get('qs_annotation_query_id', 'q1')
_render_query_navigation({task!r}, selected)
"""
    app = AppTest.from_string(script).run()

    assert not app.exception
    assert not app.dataframe
    labels = {button.label for button in app.button}
    assert labels == {
        "当前 · 1. q1.png · 未标注",
        "2. q2.png · 部分完成",
        "3. q3.png · 已完成",
        "4. q4.png · 无候选",
    }


def test_query_navigation_button_switches_query_by_id() -> None:
    task = _task()
    task["queries"].append(
        {
            "query_id": "q2",
            "query_image_path": "/queries/q2.png",
            "total": 1,
            "labeled": 0,
            "hits": 0,
            "annotation_status": "unlabeled",
        }
    )
    script = f"""
import streamlit as st
from qsearch.webui.ui.annotation_ui import _render_query_navigation
selected = st.session_state.get('qs_annotation_query_id', 'q1')
_render_query_navigation({task!r}, selected)
"""
    app = AppTest.from_string(script).run()

    app.button(key="qs_query_nav_button_task-1_q2").click().run()

    assert not app.exception
    assert app.session_state["qs_annotation_query_id"] == "q2"
    assert any(button.label.startswith("当前 · 2. q2.png") for button in app.button)


def test_footer_has_no_sequential_query_controls() -> None:
    script = """
from qsearch.webui.ui.annotation_ui import _render_footer
_render_footer()
"""
    app = AppTest.from_string(script).run()

    assert not app.exception
    labels = {button.label for button in app.button}
    assert "上一题" not in labels
    assert "下一题 ⏎" not in labels
    assert "跳至未标注" not in labels


def test_candidate_strip_uses_one_non_wrapping_horizontal_row(monkeypatch) -> None:
    calls = []

    class Container:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def container(**kwargs):
        calls.append(kwargs)
        return Container()

    def render_card(_manager, _query, _candidate, idx):
        return {
            "card": f"card-{idx}",
            "hit": f"hit-{idx}",
            "miss": f"miss-{idx}",
            "skip": f"skip-{idx}",
        }

    monkeypatch.setattr(annotation_ui.st, "container", container)
    monkeypatch.setattr(annotation_ui, "_render_card", render_card)

    card_keys, decisions = annotation_ui._render_candidate_strip(
        object(), {"query_id": "q1"}, [{}, {}, {}]
    )

    assert calls[0] == {
        "horizontal": True,
        "wrap": False,
        "gap": "small",
        "key": "qscandidate_strip",
    }
    assert card_keys == ["card-0", "card-1", "card-2"]
    assert decisions["hit"] == ["hit-0", "hit-1", "hit-2"]


def test_candidate_strip_keeps_all_per_result_annotation_actions() -> None:
    candidates = [
        {
            "candidate_id": index,
            "candidate_image_path": f"/candidates/{index}.png",
            "rank": index,
            "overall_score": 0.9,
            "confidence_level": "high",
            "label": None,
            "in_current_result": 1,
        }
        for index in range(1, 4)
    ]
    script = f"""
from qsearch.webui.ui import annotation_ui
annotation_ui._render_image = lambda *_args: None
annotation_ui._render_detail_popover = lambda *_args: None
annotation_ui._render_candidate_strip(
    object(), {{'query_id': 'q1'}}, {candidates!r}
)
"""
    app = AppTest.from_string(script).run()

    assert not app.exception
    labels = [button.label for button in app.button]
    assert labels.count("命中 1") == 3
    assert labels.count("未命中 0") == 3
    assert labels.count("跳过 S") == 3


def test_workbench_keeps_task_and_query_navigation_for_zero_candidates() -> None:
    task = _task(status="no_candidates")
    task["queries"][0].update({"total": 0, "labeled": 0})
    script = f"""
from qsearch.webui.ui.annotation_ui import _render_workbench

class Manager:
    def get_query_results(self, query_id, include_history=False):
        return {{'query': {{}}, 'candidates': []}}

_render_workbench(Manager(), {task!r}, {{
    'labeled_candidates': 0,
    'hit_rate': 0.0,
}}, False)
"""
    app = AppTest.from_string(script).run()

    assert not app.exception
    assert not app.dataframe
    assert any(button.label == "返回任务列表" for button in app.button)
    assert any("没有候选项" in warning.value for warning in app.warning)
