"""Shared status presentation helpers used across workbench sections."""

from html import escape

import streamlit as st


_CONFIDENCE = {
    "HIGH": ("qs-chip--conf-high", "高"),
    "MEDIUM": ("qs-chip--conf-mid", "中"),
    "LOW": ("qs-chip--conf-low", "低"),
}

_LABEL = {
    "hit": ("qs-badge--hit", "qs-icon--hit", "命中"),
    "miss": ("qs-badge--miss", "qs-icon--miss", "未命中"),
    "skip": ("qs-badge--skip", "qs-icon--skip", "跳过"),
}

_TASK = {
    "pending": ("qs-chip--task-pending", "qs-icon--task-pending", "等待中"),
    "running": ("qs-chip--task-running", "qs-icon--task-running", "运行中"),
    "completed": ("qs-chip--task-done", "qs-icon--task-done", "已完成"),
    "failed": ("qs-chip--task-failed", "qs-icon--task-failed", "失败"),
    "cancelled": ("qs-chip--task-cancelled", "qs-icon--task-cancelled", "已取消"),
}

_MATCH_TYPE = {"exact": "精确", "content": "内容"}


def confidence_chip(level: str) -> str:
    """Return a low-saturation confidence chip."""
    css_class, text = _CONFIDENCE.get(
        (level or "").upper(), ("qs-chip--conf-unknown", "未知")
    )
    return f'<span class="qs-chip {css_class}">{escape(text)}</span>'


def label_badge(label: str | None) -> str:
    """Return a human-decision badge with text and icon redundancy."""
    if not label:
        return (
            '<span class="qs-badge qs-badge--unlabeled qs-icon '
            'qs-icon--unlabeled">未标注</span>'
        )
    css_class, icon_class, text = _LABEL.get(
        label.lower(),
        ("qs-badge--unlabeled", "qs-icon--unlabeled", "未标注"),
    )
    return (
        f'<span class="qs-badge {css_class} qs-icon {icon_class}">'
        f"{escape(text)}</span>"
    )


def task_status_chip(status: str) -> str:
    """Return a machine-task status chip."""
    css_class, icon_class, text = _TASK.get(
        (status or "").lower(),
        ("qs-chip--task-pending", "qs-icon--task-unknown", "未知"),
    )
    return (
        f'<span class="qs-chip {css_class} qs-icon {icon_class}">'
        f"{escape(text)}</span>"
    )


def index_status(built: bool) -> str:
    """Return the index status with icon and text."""
    if built:
        return (
            '<span class="qs-chip qs-chip--index-built qs-icon '
            'qs-icon--index-built">索引已建</span>'
        )
    return (
        '<span class="qs-chip qs-chip--index-missing qs-icon '
        'qs-icon--index-missing">索引未建</span>'
    )


def match_type_text(match_type: str) -> str:
    """Return a localized match-type label."""
    return _MATCH_TYPE.get((match_type or "").lower(), match_type or "未知")


def scheduler_badge(status: dict) -> str:
    """Return the scheduler process status badge."""
    if status.get("running"):
        pid = status.get("pid")
        suffix = f" · PID {pid}" if pid else ""
        return (
            '<span class="qs-chip qs-chip--index-built qs-icon '
            f'qs-icon--index-built">调度器运行中{suffix}</span>'
        )
    return (
        '<span class="qs-chip qs-chip--index-missing qs-icon '
        'qs-icon--index-missing">调度器未运行</span>'
    )


def render(html: str) -> None:
    """Render trusted HTML produced by this module."""
    st.markdown(html, unsafe_allow_html=True)
