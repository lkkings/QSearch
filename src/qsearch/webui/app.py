"""QSearch single-page Streamlit workbench."""

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from qsearch.tasks.queue import TaskStatus
from qsearch.webui.system_monitor import format_memory_size, get_system_resources
from qsearch.webui.task_manager import TaskManager
from qsearch.webui.ui.styles import inject_css
from qsearch.webui.workspace_state import (
    ANNOTATION_VIEW,
    DETAILS_VIEW,
    HOME_VIEW,
    SEARCH_VIEW,
    activate_workspace_view,
    resolve_workspace_view,
)


def setup_session_state(databases_root: Path) -> None:
    """Initialize state shared by the integrated workbench components."""
    defaults = {
        "databases_root": str(databases_root),
        "selected_database": None,
        "search_results": None,
        "search_results_database": None,
        "selected_image": None,
        "annotation_query_id": None,
        "workspace_view": HOME_VIEW,
        "grid_columns": 3,
        "focus_mode": False,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def _clear_database_scoped_state(database_name: str | None) -> None:
    """Discard data that belongs to a database other than the active one."""
    if st.session_state.get("search_results_database") != database_name:
        st.session_state["search_results"] = None
        st.session_state["search_results_database"] = None

    if st.session_state.get("qs_ia_task_db") != database_name:
        for key in ("qs_ia_task_id", "qs_ia_task_db", "qs_ia_outcome"):
            st.session_state.pop(key, None)

    st.session_state["annotation_query_id"] = None
    st.session_state.pop("qs_annotation_task_id", None)
    st.session_state.pop("qs_annotation_query_id", None)
    st.session_state["qs_focus_mode"] = False


def setup_sidebar(databases_root: Path) -> None:
    """Render the persistent selector, queue overview and resource status."""
    from qsearch.webui.database_manager import DatabaseManager

    with st.sidebar:
        st.markdown("### :material/database: 数据库")
        try:
            databases = DatabaseManager(databases_root).list_databases()
        except Exception as exc:
            databases = []
            st.error(f"数据库列表加载失败：{exc}")

        names = [item["name"] for item in databases]
        previous = st.session_state.get("selected_database")
        pending = st.session_state.pop("_pending_database", None)

        if names:
            current = pending if pending in names else previous
            if current not in names:
                current = names[0]

            # Programmatic selections are applied before the widget is created;
            # mutating an instantiated widget key would raise StreamlitAPIException.
            widget_value = st.session_state.get("workspace_database")
            if pending in names or widget_value not in names:
                st.session_state["workspace_database"] = current

            selected = st.selectbox(
                "当前数据库",
                names,
                index=names.index(current),
                key="workspace_database",
            )
            if selected != previous:
                _clear_database_scoped_state(selected)
            st.session_state["selected_database"] = selected
        else:
            if previous is not None:
                _clear_database_scoped_state(None)
            st.session_state["selected_database"] = None
            st.info("暂无数据库，请先创建数据库。")

        st.divider()
        st.markdown("### :material/analytics: 系统信息")
        st.metric("数据库数量", len(databases))
        st.metric("图像总数", f"{sum(item.get('image_count', 0) for item in databases):,}")
        st.metric(
            "查询总数",
            sum(item.get("statistics", {}).get("total_queries", 0) for item in databases),
        )

        st.divider()
        st.markdown("### :material/checklist: 队列概览")
        try:
            counts = TaskManager(databases_root).counts_by_status()
            left, right = st.columns(2)
            left.metric("排队中", counts.get(TaskStatus.PENDING, 0))
            left.metric("成功", counts.get(TaskStatus.COMPLETED, 0))
            right.metric("运行中", counts.get(TaskStatus.RUNNING, 0))
            right.metric("失败", counts.get(TaskStatus.FAILED, 0))
        except Exception as exc:
            st.caption(f"队列信息不可用：{exc}")

        st.divider()
        st.markdown("### :material/monitor_heart: 资源监控")
        try:
            resources = get_system_resources()
            st.metric(
                f"CPU ({resources['cpu_count']} 核)",
                f"{resources['cpu_percent']:.1f}%",
            )
            st.metric(
                "内存",
                f"{resources['memory_percent']:.1f}%",
                delta=(
                    f"{format_memory_size(resources['memory_used_gb'])} / "
                    f"{format_memory_size(resources['memory_total_gb'])}"
                ),
            )
            gpu = resources.get("gpu")
            if gpu:
                st.metric("GPU 负载", f"{gpu['load_percent']:.1f}%")
                st.caption(gpu.get("name", "GPU"))
        except Exception as exc:
            st.caption(f"资源监控不可用：{exc}")

        if st.button("刷新数据", icon=":material/refresh:", width="stretch"):
            st.cache_data.clear()
            st.rerun()


def main() -> None:
    """Run the integrated single-page application."""
    st.set_page_config(
        page_title="QSearch",
        page_icon=":material/search:",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    inject_css()

    databases_root = Path(os.environ.get("QSEARCH_DATABASES_ROOT", "./databases"))
    databases_root.mkdir(parents=True, exist_ok=True)
    setup_session_state(databases_root)

    if not st.session_state.get("scheduler_started"):
        try:
            manager = TaskManager(databases_root)
            manager.ensure_scheduler()
            recovered = manager.recover_orphans()
            st.session_state["scheduler_started"] = True
            if recovered:
                st.info(f"已重新排队 {recovered} 个中断任务。")
        except Exception as exc:
            st.warning(f"调度进程启动失败：{exc}")

    setup_sidebar(databases_root)
    selected = st.session_state.get("selected_database")
    active_view = resolve_workspace_view(
        st.session_state.get("workspace_view"), selected
    )
    st.session_state["workspace_view"] = active_view

    st.title(":material/search: QSearch 工作台")
    st.caption("在同一页面完成数据库管理、图像搜索、结果标注和任务监控。")

    from qsearch.webui.ui.annotation_ui import render_annotation_page
    from qsearch.webui.ui.database_ui import render_database_management_page
    from qsearch.webui.ui.details_ui import render_details_page
    from qsearch.webui.ui.search_ui import render_search_page
    from qsearch.webui.ui.task_ui import render_task_monitor_page

    if active_view == HOME_VIEW:
        management, monitoring = st.tabs(
            [":material/database: 数据库管理", ":material/monitor_heart: 任务监控"]
        )
        with management:
            render_database_management_page(databases_root)
        with monitoring:
            render_task_monitor_page(databases_root)
        return

    if st.button("返回主页", icon=":material/arrow_back:"):
        activate_workspace_view(st.session_state, HOME_VIEW)
        st.rerun()

    if active_view == DETAILS_VIEW:
        render_details_page(databases_root, selected)
    elif active_view == SEARCH_VIEW:
        render_search_page(databases_root)
    elif active_view == ANNOTATION_VIEW:
        render_annotation_page(databases_root)


if __name__ == "__main__":
    main()
