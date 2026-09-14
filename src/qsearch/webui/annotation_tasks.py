"""Read-only task projection for the annotation workbench.

Search tasks and annotation results intentionally live in separate databases.  This
module joins them at render time through the query paths stored in task payloads, so
the annotation UI does not need a schema migration or a historical backfill.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

from qsearch.tasks.queue import TaskKind

UNASSIGNED_TASK_ID = "__unassigned__"
QUERY_TASK_KINDS = frozenset({TaskKind.BATCH_SEARCH, TaskKind.INTERACTIVE_SEARCH})


def query_status(query: dict[str, Any]) -> str:
    """Return the four-state annotation status derived from current candidates."""
    total = int(query.get("total", query.get("total_candidates", 0)) or 0)
    labeled = int(query.get("labeled", query.get("labeled_candidates", 0)) or 0)
    if total == 0:
        return "no_candidates"
    if labeled == 0:
        return "unlabeled"
    if labeled < total:
        return "partial"
    return "completed"


def query_paths_from_payload(task: dict[str, Any], payload: Any) -> list[str]:
    """Normalize supported search payloads into de-duplicated query paths."""
    kind = task.get("kind")
    if kind == TaskKind.BATCH_SEARCH and isinstance(payload, list):
        values = payload
    elif kind == TaskKind.INTERACTIVE_SEARCH and isinstance(payload, dict):
        values = [payload.get("query_image_path")]
    else:
        return []

    paths: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, (str, Path)):
            continue
        path = str(value)
        if path and path not in seen:
            seen.add(path)
            paths.append(path)
    return paths


def _decorate_query(query: dict[str, Any]) -> dict[str, Any]:
    decorated = dict(query)
    decorated["annotation_status"] = query_status(decorated)
    return decorated


def _summarize_task(task: dict[str, Any], queries: list[dict[str, Any]]) -> dict[str, Any]:
    projected = dict(task)
    completed = sum(q["annotation_status"] == "completed" for q in queries)
    projected.update(
        {
            "queries": queries,
            "query_count": len(queries),
            "completed_count": completed,
            "annotation_progress": completed / len(queries) if queries else 0.0,
            "annotatable": bool(queries),
        }
    )
    return projected


def build_annotation_tasks(
    tasks: Iterable[dict[str, Any]],
    queries: Iterable[dict[str, Any]],
    payload_reader: Callable[[dict[str, Any]], Any],
) -> list[dict[str, Any]]:
    """Build annotation task rows without mutating either source collection."""
    decorated_queries = [_decorate_query(query) for query in queries]
    queries_by_path = {str(query["query_image_path"]): query for query in decorated_queries}
    matched_query_ids: set[str] = set()
    projected_tasks: list[dict[str, Any]] = []

    for task in tasks:
        if task.get("kind") not in QUERY_TASK_KINDS:
            continue

        payload_error = False
        try:
            payload = payload_reader(task)
        except (OSError, ValueError, TypeError):
            payload = None
            payload_error = True

        task_queries: list[dict[str, Any]] = []
        for path in query_paths_from_payload(task, payload):
            query = queries_by_path.get(path)
            if query is None:
                continue
            task_queries.append(dict(query))
            matched_query_ids.add(str(query["query_id"]))

        projected = _summarize_task(task, task_queries)
        projected["payload_unavailable"] = payload_error or payload is None
        projected_tasks.append(projected)

    unassigned = [
        dict(query)
        for query in decorated_queries
        if str(query["query_id"]) not in matched_query_ids
    ]
    if unassigned:
        projected_tasks.append(
            _summarize_task(
                {
                    "task_id": UNASSIGNED_TASK_ID,
                    "task_name": "未归档查询",
                    "kind": "unassigned",
                    "status": "unassigned",
                    "total_items": len(unassigned),
                    "created_at": "",
                    "payload_unavailable": False,
                },
                unassigned,
            )
        )

    return projected_tasks


def choose_query_id(
    queries: Sequence[dict[str, Any]], preferred_id: str | None = None
) -> str | None:
    """Keep a valid selection, otherwise choose unfinished then first Query."""
    if preferred_id and any(query.get("query_id") == preferred_id for query in queries):
        return preferred_id
    for query in queries:
        if query_status(query) != "completed":
            return str(query["query_id"])
    return str(queries[0]["query_id"]) if queries else None


def task_for_query(
    tasks: Sequence[dict[str, Any]], query_id: str
) -> dict[str, Any] | None:
    """Return the newest real task containing a Query, then the fallback group."""
    matches = [
        task
        for task in tasks
        if any(query.get("query_id") == query_id for query in task.get("queries", []))
    ]
    if not matches:
        return None
    real = [task for task in matches if task.get("task_id") != UNASSIGNED_TASK_ID]
    if real:
        return max(real, key=lambda task: str(task.get("created_at") or ""))
    return matches[0]


def query_id_for_selected_row(
    queries: Sequence[dict[str, Any]], selected_rows: Sequence[int]
) -> str | None:
    """Map a dataframe selection back to its stable Query identity."""
    if not selected_rows:
        return None
    row = int(selected_rows[0])
    if row < 0 or row >= len(queries):
        return None
    return str(queries[row]["query_id"])


def task_at_row(
    tasks: Sequence[dict[str, Any]], row: int
) -> dict[str, Any] | None:
    """Resolve a task-table button click while rejecting invalid client input."""
    return tasks[row] if 0 <= row < len(tasks) else None
