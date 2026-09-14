"""State helpers for the workbench's user-activated views."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

HOME_VIEW = "home"
DETAILS_VIEW = "details"
SEARCH_VIEW = "search"
ANNOTATION_VIEW = "annotation"

WORKSPACE_VIEWS = frozenset(
    {HOME_VIEW, DETAILS_VIEW, SEARCH_VIEW, ANNOTATION_VIEW}
)
_DATABASE_VIEWS = frozenset({DETAILS_VIEW, SEARCH_VIEW, ANNOTATION_VIEW})


def activate_workspace_view(
    state: MutableMapping[str, Any],
    view: str,
    *,
    database_name: str | None = None,
    query_id: str | None = None,
) -> None:
    """Activate a view in response to an explicit user action."""
    if view not in WORKSPACE_VIEWS:
        raise ValueError(f"Unknown workspace view: {view}")

    if database_name is not None:
        state["_pending_database"] = database_name
    if query_id is not None:
        state["annotation_query_id"] = query_id

    state["workspace_view"] = view


def resolve_workspace_view(view: object, selected_database: object) -> str:
    """Return a safe renderable view for the current dataset selection."""
    if view not in WORKSPACE_VIEWS:
        return HOME_VIEW
    if view in _DATABASE_VIEWS and not selected_database:
        return HOME_VIEW
    return str(view)
