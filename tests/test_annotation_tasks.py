"""Task-based annotation projection and navigation contracts."""

from __future__ import annotations

from copy import deepcopy

import pytest

from qsearch.tasks.queue import TaskKind
from qsearch.webui.annotation_tasks import (
    UNASSIGNED_TASK_ID,
    build_annotation_tasks,
    choose_query_id,
    query_id_for_selected_row,
    query_paths_from_payload,
    query_status,
    task_at_row,
    task_for_query,
)


def _query(
    query_id: str,
    path: str,
    *,
    total: int = 2,
    labeled: int = 0,
    hits: int = 0,
) -> dict:
    return {
        "query_id": query_id,
        "query_image_path": path,
        "total": total,
        "labeled": labeled,
        "hits": hits,
    }


def _task(task_id: str, kind: str, *, created_at: str = "2026-01-01") -> dict:
    return {
        "task_id": task_id,
        "task_name": task_id,
        "kind": kind,
        "status": "completed",
        "total_items": 2,
        "created_at": created_at,
    }


@pytest.mark.parametrize(
    "total,labeled,expected",
    [
        (0, 0, "no_candidates"),
        (2, 0, "unlabeled"),
        (2, 1, "partial"),
        (2, 2, "completed"),
    ],
)
def test_query_status_has_four_states(total: int, labeled: int, expected: str) -> None:
    assert query_status({"total": total, "labeled": labeled}) == expected


def test_payload_normalization_supports_both_search_kinds_and_deduplicates() -> None:
    batch = _task("batch", TaskKind.BATCH_SEARCH)
    interactive = _task("single", TaskKind.INTERACTIVE_SEARCH)

    assert query_paths_from_payload(batch, ["/a.png", "/a.png", "/b.png"]) == [
        "/a.png",
        "/b.png",
    ]
    assert query_paths_from_payload(interactive, {"query_image_path": "/q.png"}) == [
        "/q.png"
    ]
    assert query_paths_from_payload(batch, {"wrong": "shape"}) == []


def test_projection_filters_non_search_tasks_and_does_not_mutate_sources() -> None:
    tasks = [
        _task("index", TaskKind.INDEX_BUILD),
        _task("batch", TaskKind.BATCH_SEARCH),
    ]
    queries = [_query("q1", "/q1.png")]
    original_tasks, original_queries = deepcopy(tasks), deepcopy(queries)

    projected = build_annotation_tasks(
        tasks,
        queries,
        lambda task: ["/q1.png"] if task["task_id"] == "batch" else None,
    )

    assert [task["task_id"] for task in projected] == ["batch"]
    assert projected[0]["queries"][0]["query_id"] == "q1"
    assert tasks == original_tasks
    assert queries == original_queries


def test_projection_keeps_empty_task_and_collects_unassigned_queries() -> None:
    tasks = [_task("batch", TaskKind.BATCH_SEARCH)]
    queries = [_query("q1", "/q1.png"), _query("old", "/old.png", total=0)]

    projected = build_annotation_tasks(tasks, queries, lambda task: ["/missing.png"])

    assert projected[0]["query_count"] == 0
    assert projected[0]["annotatable"] is False
    assert projected[1]["task_id"] == UNASSIGNED_TASK_ID
    assert [q["query_id"] for q in projected[1]["queries"]] == ["q1", "old"]
    assert projected[1]["completed_count"] == 0


def test_missing_or_invalid_payload_never_guesses_membership() -> None:
    tasks = [_task("missing", TaskKind.BATCH_SEARCH)]
    queries = [_query("q1", "/q1.png")]

    def fail(_task):
        raise ValueError("invalid json")

    projected = build_annotation_tasks(tasks, queries, fail)

    assert projected[0]["payload_unavailable"] is True
    assert projected[0]["queries"] == []
    assert projected[1]["task_id"] == UNASSIGNED_TASK_ID


def test_same_query_can_be_referenced_by_multiple_tasks() -> None:
    tasks = [
        _task("old", TaskKind.BATCH_SEARCH, created_at="2026-01-01"),
        _task("new", TaskKind.INTERACTIVE_SEARCH, created_at="2026-01-02"),
    ]
    queries = [_query("q1", "/q1.png", total=2, labeled=2, hits=1)]

    def read(task):
        if task["kind"] == TaskKind.BATCH_SEARCH:
            return ["/q1.png"]
        return {"query_image_path": "/q1.png"}

    projected = build_annotation_tasks(tasks, queries, read)

    assert [task["query_count"] for task in projected] == [1, 1]
    assert all(task["completed_count"] == 1 for task in projected)
    assert task_for_query(projected, "q1")["task_id"] == "new"


def test_projection_recomputes_task_progress_from_current_query_counts() -> None:
    tasks = [_task("batch", TaskKind.BATCH_SEARCH)]
    payload = lambda task: ["/q1.png"]

    before = build_annotation_tasks(
        tasks, [_query("q1", "/q1.png", total=1, labeled=0)], payload
    )[0]
    after = build_annotation_tasks(
        tasks, [_query("q1", "/q1.png", total=1, labeled=1)], payload
    )[0]

    assert (before["completed_count"], before["annotation_progress"]) == (0, 0.0)
    assert (after["completed_count"], after["annotation_progress"]) == (1, 1.0)


def test_default_query_prefers_current_then_first_unfinished_then_first() -> None:
    queries = [
        _query("done", "/done.png", total=1, labeled=1),
        _query("partial", "/partial.png", total=2, labeled=1),
    ]
    assert choose_query_id(queries, "done") == "done"
    assert choose_query_id(queries) == "partial"
    assert choose_query_id([queries[0]]) == "done"
    assert choose_query_id([]) is None


def test_selection_helpers_reject_invalid_client_rows() -> None:
    queries = [_query("q1", "/q1.png"), _query("q2", "/q2.png")]
    tasks = [_task("task", TaskKind.BATCH_SEARCH)]

    assert query_id_for_selected_row(queries, [1]) == "q2"
    assert query_id_for_selected_row(queries, []) is None
    assert query_id_for_selected_row(queries, [9]) is None
    assert task_at_row(tasks, 0)["task_id"] == "task"
    assert task_at_row(tasks, -1) is None
