"""Inline annotation controls used by search-result cards.

The component deliberately has no navigation side effects.  It writes the
decision through :class:`AnnotationManager` and lets its parent keep rendering
the current workspace.
"""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping, Optional

import streamlit as st

from qsearch.webui.annotation_manager import AnnotationManager


_ACTIONS = (
    ("hit", "命中", ":material/check_circle:"),
    ("miss", "未命中", ":material/cancel:"),
    ("skip", "跳过", ":material/do_not_disturb_on:"),
)


def render_quick_annotation(
    annotation_manager: Optional[AnnotationManager],
    query_id: Optional[str],
    candidate: Mapping[str, Any],
    *,
    key_prefix: str = "quick_annotation",
    notes: Optional[str] = None,
) -> Optional[str]:
    """Render compact hit/miss/skip controls for one candidate.

    ``None`` is returned when no button was pressed.  If the result has not
    yet been persisted (and consequently has no ``candidate_id``), a readable
    disabled state is shown instead of raising from the rendering pass.
    """
    candidate_id = candidate.get("candidate_id")
    enabled = bool(annotation_manager and query_id and candidate_id is not None)
    current_label = candidate.get("label")

    columns = st.columns(3)
    selected: Optional[str] = None
    for column, (value, caption, icon) in zip(columns, _ACTIONS):
        with column:
            if st.button(
                caption,
                icon=icon,
                key=f"{key_prefix}_{candidate_id or 'pending'}_{value}",
                disabled=not enabled,
                type="primary" if current_label == value else "secondary",
                width="stretch",
                help=None if enabled else "搜索结果尚未写入标注库",
            ):
                selected = value

    if selected is None:
        return None

    try:
        annotation_manager.label_candidate(
            query_id=str(query_id),
            candidate_id=int(candidate_id),
            label=selected,
            notes=notes if notes is not None else candidate.get("notes"),
        )
    except Exception as exc:
        st.error(f"保存标注失败：{exc}")
        return None

    # Search results are commonly held in session state.  Updating a mutable
    # result in place makes the badge consistent during the current rerun too.
    if isinstance(candidate, MutableMapping):
        candidate["label"] = selected
        if notes is not None:
            candidate["notes"] = notes
    st.toast(f"已标注为{dict((v, t) for v, t, _ in _ACTIONS)[selected]}")
    return selected
