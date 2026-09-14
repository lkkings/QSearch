"""Non-navigating candidate detail dialog for the integrated workspace."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Optional

import streamlit as st

from qsearch.webui.annotation_manager import AnnotationManager
from qsearch.webui.thumbnails import ThumbnailError, get_thumbnail

from .quick_annotation import render_quick_annotation


def _image_path(candidate: Mapping[str, Any]) -> Optional[str]:
    return candidate.get("candidate_image_path") or candidate.get("image_path")


def _show_image(path: Optional[str]) -> None:
    if not path:
        st.info("该结果没有图像路径。")
        return
    try:
        if path.startswith(("http://", "https://")):
            st.image(path, width="stretch")
        else:
            st.image(get_thumbnail(path, long_edge=900), width="stretch")
    except (ThumbnailError, OSError, ValueError) as exc:
        st.warning(f"无法预览图像：{exc}")


@st.dialog("图像详情", width="large")
def show_detail_modal(
    candidate: Mapping[str, Any],
    *,
    query: Optional[Mapping[str, Any]] = None,
    query_id: Optional[str] = None,
    annotation_manager: Optional[AnnotationManager] = None,
    key_prefix: str = "detail",
) -> None:
    """Show image, matcher metadata, annotation and notes in a dialog."""
    st.session_state["selected_image"] = dict(candidate)
    path = _image_path(candidate)
    resolved_query_id = query_id or (query or {}).get("query_id")

    image_col, metadata_col = st.columns([3, 2])
    with image_col:
        _show_image(path)
    with metadata_col:
        st.markdown(f"**文件**  `{Path(path).name if path else '未知'}`")
        st.caption(path or "无路径")
        for field, caption, digits in (
            ("rank", "排名", 0),
            ("overall_score", "综合评分", 4),
            ("text_score", "文本评分", 4),
            ("visual_score", "视觉评分", 4),
            ("hash_distance", "哈希距离", 0),
        ):
            value = candidate.get(field)
            if value is not None:
                shown = f"{value:.{digits}f}" if isinstance(value, float) else str(value)
                st.markdown(f"**{caption}**  {shown}")
        if candidate.get("confidence_level"):
            st.markdown(f"**置信等级**  {candidate['confidence_level']}")
        if candidate.get("match_type"):
            st.markdown(f"**匹配类型**  {candidate['match_type']}")

    st.divider()
    current = candidate.get("label") or "未标注"
    labeled_at = candidate.get("labeled_at")
    st.markdown(f"**当前标注**  {current}")
    if labeled_at:
        st.caption(f"最近标注时间：{labeled_at}")

    notes = st.text_area(
        "备注",
        value=candidate.get("notes") or "",
        key=f"{key_prefix}_{candidate.get('candidate_id', 'pending')}_notes",
    )
    render_quick_annotation(
        annotation_manager,
        resolved_query_id,
        candidate,
        key_prefix=f"{key_prefix}_decision",
        notes=notes,
    )
