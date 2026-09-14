"""Reusable search-results grid for the single-page workbench."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Optional

import streamlit as st

from qsearch.webui.annotation_manager import AnnotationManager
from qsearch.webui.thumbnails import ThumbnailError, get_thumbnail

from .detail_modal import show_detail_modal
from .quick_annotation import render_quick_annotation


def _path(candidate: Mapping[str, Any]) -> Optional[str]:
    return candidate.get("candidate_image_path") or candidate.get("image_path")


def _candidates(results: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Normalize both matcher buckets and persisted candidate lists."""
    if "candidates" in results:
        return [
            item if isinstance(item, dict) else dict(item)
            for item in results.get("candidates") or []
        ]

    normalized: list[dict[str, Any]] = []
    for bucket, match_type in (("exact_matches", "exact"), ("content_matches", "content")):
        for rank, raw in enumerate(results.get(bucket) or [], 1):
            item = raw if isinstance(raw, dict) else dict(raw)
            item.setdefault("match_type", match_type)
            item.setdefault("rank", rank)
            normalized.append(item)
    return normalized


def _render_image(path: Optional[str]) -> None:
    if not path:
        st.info("无图像")
        return
    try:
        source = path if path.startswith(("http://", "https://")) else get_thumbnail(path)
        st.image(source, width="stretch")
    except (ThumbnailError, OSError, ValueError) as exc:
        st.warning(f"无法预览：{exc}")


def render_results_grid(
    results: Mapping[str, Any],
    *,
    annotation_manager: Optional[AnnotationManager] = None,
    columns: int = 3,
    key_prefix: str = "results",
) -> None:
    """Render matcher results as cards with inline annotation and details.

    The accepted result shape is the existing ``exact_matches`` /
    ``content_matches`` dictionary.  Persisted ``{"query": ..., "candidates":
    [...]}`` results are accepted as well, which keeps the component useful
    after a rerun reloads data from the annotation database.
    """
    candidates = _candidates(results)
    if not candidates:
        st.info("本次查询没有找到匹配结果。", icon=":material/search:")
        return

    columns = max(1, min(int(columns), 6))
    query = results.get("query") if isinstance(results.get("query"), Mapping) else {}
    query_id = results.get("query_id") or query.get("query_id")

    st.caption(f"共 {len(candidates)} 个结果")
    for start in range(0, len(candidates), columns):
        row = st.columns(columns)
        for offset, candidate in enumerate(candidates[start : start + columns]):
            index = start + offset
            path = _path(candidate)
            with row[offset]:
                with st.container(border=True):
                    _render_image(path)
                    rank = candidate.get("rank", index + 1)
                    score = candidate.get("overall_score")
                    score_text = f" · {score:.3f}" if isinstance(score, (int, float)) else ""
                    st.markdown(f"**#{rank} {Path(path).name if path else '未知图像'}**{score_text}")
                    confidence = candidate.get("confidence_level")
                    match_type = candidate.get("match_type")
                    if confidence or match_type:
                        st.caption(" · ".join(str(v) for v in (match_type, confidence) if v))

                    render_quick_annotation(
                        annotation_manager,
                        query_id,
                        candidate,
                        key_prefix=f"{key_prefix}_{index}",
                    )
                    if st.button(
                        "查看详情",
                        icon=":material/info:",
                        key=f"{key_prefix}_{index}_detail",
                        width="stretch",
                    ):
                        show_detail_modal(
                            candidate,
                            query=query,
                            query_id=query_id,
                            annotation_manager=annotation_manager,
                            key_prefix=f"{key_prefix}_{index}_detail",
                        )
