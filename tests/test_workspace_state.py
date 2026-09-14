import pytest

from qsearch.webui.workspace_state import (
    ANNOTATION_VIEW,
    DETAILS_VIEW,
    HOME_VIEW,
    SEARCH_VIEW,
    activate_workspace_view,
    resolve_workspace_view,
)


def test_dataset_views_are_only_activated_explicitly():
    state = {"workspace_view": HOME_VIEW}

    activate_workspace_view(state, SEARCH_VIEW, database_name="demo")

    assert state == {
        "workspace_view": SEARCH_VIEW,
        "_pending_database": "demo",
    }


def test_annotation_activation_preserves_dataset_and_query_context():
    state = {"workspace_view": SEARCH_VIEW}

    activate_workspace_view(
        state,
        ANNOTATION_VIEW,
        database_name="demo",
        query_id="query-1",
    )

    assert state["workspace_view"] == ANNOTATION_VIEW
    assert state["_pending_database"] == "demo"
    assert state["annotation_query_id"] == "query-1"


@pytest.mark.parametrize("view", [DETAILS_VIEW, SEARCH_VIEW, ANNOTATION_VIEW])
def test_dataset_views_fall_back_home_without_a_selected_database(view):
    assert resolve_workspace_view(view, None) == HOME_VIEW


def test_unknown_workspace_view_falls_back_home():
    assert resolve_workspace_view("unknown", "demo") == HOME_VIEW


def test_unknown_workspace_view_cannot_be_activated():
    with pytest.raises(ValueError, match="Unknown workspace view"):
        activate_workspace_view({}, "unknown")
