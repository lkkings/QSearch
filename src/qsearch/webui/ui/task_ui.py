"""任务监控页面。

自动刷新用 ``st.fragment(run_every=...)``，不用 ``time.sleep`` + ``st.rerun``。

原实现有两个独立缺陷：``time.sleep(interval)`` 阻塞服务端线程，使刷新等待期
间整个应用无法响应其他用户的操作；``st.rerun()`` 重跑整个脚本，而 ``st.tabs``
的所有分支都是全量执行的 —— 于是标注员正在标注时，页面每 5 秒被强制刷新一
次，焦点、未提交的备注、滚动位置全部丢失。

fragment 同时解决两者：只重跑被装饰的函数，且不阻塞。

队列是全局的（跨库单一队列），因此这里默认展示全部库的任务 —— 调度器串行
执行，用户需要看到的是整条队列，而不是当前选中库的切片。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import streamlit as st

from qsearch.tasks.queue import TaskKind, TaskStatus
from qsearch.webui.task_manager import TaskManager
from qsearch.webui.ui import components

_REFRESH_OPTIONS = (0, 1, 5, 10, 30)

_ALL = "__all__"

_STATUS_OPTIONS = (_ALL, *TaskStatus.ALL)
_KIND_OPTIONS = (_ALL, *TaskKind.ALL)


def render_task_monitor_page(databases_root: Path) -> None:
    """渲染任务监控页面。

    Args:
        databases_root: 数据库根目录
    """
    st.header(":material/analytics: 任务监控")

    task_manager = TaskManager(databases_root)

    _render_scheduler_bar(task_manager)

    databases = sorted({
        task["database_name"] for task in task_manager.list_tasks()
    })

    col_db, col_kind, col_status, col_refresh = st.columns([2, 1.6, 1.6, 1.4])

    with col_db:
        # key 是必需的，不是可选的美化。search_ui 也有一个标签与选项完全相同的
        # selectbox；两者都不带 key 时 Streamlit 生成同一个自动 ID 并抛
        # StreamlitDuplicateElementId。因 st.tabs 全量执行，该异常会污染整页 ——
        # 标注页也会被连带打成错误页。
        selected_db = st.selectbox(
            "数据库",
            options=[_ALL, *databases],
            format_func=lambda name: "全部" if name == _ALL else name,
            key="qs_task_db",
        )

    with col_kind:
        kind_filter = st.selectbox(
            "任务类型",
            options=_KIND_OPTIONS,
            format_func=lambda k: "全部" if k == _ALL else TaskKind.LABELS[k],
            key="qs_task_kind",
        )

    with col_status:
        status_filter = st.selectbox(
            "状态",
            options=_STATUS_OPTIONS,
            format_func=lambda s: "全部" if s == _ALL else TaskStatus.LABELS[s],
            key="qs_task_status",
        )

    with col_refresh:
        interval = st.selectbox(
            "自动刷新",
            options=_REFRESH_OPTIONS,
            index=_REFRESH_OPTIONS.index(5),
            format_func=lambda s: "关闭" if s == 0 else f"{s} 秒",
            key="qs_task_interval",
        )

    filters = {
        "database_name": None if selected_db == _ALL else selected_db,
        "kind": None if kind_filter == _ALL else kind_filter,
        "status_filter": None if status_filter == _ALL else status_filter,
    }

    # 有未完成任务才需要周期刷新。全部进入终态后再刷新一个不会变化的列表
    # 只是白耗服务端。排队中的任务也算 —— 它随时会被调度器取走。
    active = task_manager.list_tasks(
        database_name=filters["database_name"], status_filter=TaskStatus.RUNNING
    ) + task_manager.list_tasks(
        database_name=filters["database_name"], status_filter=TaskStatus.PENDING
    )
    run_every = interval if (interval and active) else None

    @st.fragment(run_every=run_every)
    def _live_section() -> None:
        """只有这个函数会被自动重跑，标注页不受影响。"""
        _render_tasks(task_manager, filters)

    _live_section()

    if not interval:
        if st.button("立即刷新", icon=":material/refresh:"):
            st.rerun()


def _render_scheduler_bar(task_manager: TaskManager) -> None:
    """渲染调度进程状态与队列概览。

    调度器不运行时任务只会堆在队列里不动，这个状态必须显式可见 —— 否则用户
    看到的是「一直排队中」，无从判断是慢还是根本没在跑。

    Args:
        task_manager: TaskManager 实例
    """
    status = task_manager.scheduler_status()
    counts = task_manager.counts_by_status()

    col_state, col_counts, col_action = st.columns([2, 3, 1.2])

    with col_state:
        components.render(components.scheduler_badge(status))

    with col_counts:
        st.markdown(
            '<div class="qs-td">'
            f'排队 {counts[TaskStatus.PENDING]} · '
            f'运行 {counts[TaskStatus.RUNNING]} · '
            f'完成 {counts[TaskStatus.COMPLETED]} · '
            f'失败 {counts[TaskStatus.FAILED]}'
            '</div>',
            unsafe_allow_html=True,
        )

    with col_action:
        if not status.get("running"):
            if st.button("启动调度器", key="qs_start_scheduler", type="primary"):
                task_manager.ensure_scheduler()
                st.rerun()

    if not status.get("running") and counts[TaskStatus.PENDING]:
        st.warning(
            f"有 {counts[TaskStatus.PENDING]} 个任务在排队，但调度进程未运行 —— "
            "它们不会被执行。点击「启动调度器」。"
        )

    st.divider()


def _render_tasks(task_manager: TaskManager, filters: dict) -> None:
    """渲染任务列表与运行中任务的浮层进度。

    Args:
        task_manager: TaskManager 实例
        filters: 含 ``database_name``、``kind``、``status_filter`` 的筛选条件
    """
    tasks = task_manager.list_tasks(**filters)

    if not tasks:
        st.info("没有符合条件的任务。")
        return

    running = [t for t in tasks if t["status"] == TaskStatus.RUNNING]
    pending = [t for t in tasks if t["status"] == TaskStatus.PENDING]
    others = [t for t in tasks if t["status"] in TaskStatus.TERMINAL]

    # 浮层进度。玻璃使其下方内容保持可见，pointer-events 使其不拦截操作 ——
    # 长任务可能跑很久，期间标注员要能继续工作。
    if running:
        _render_progress_overlay(running)

        st.subheader(":material/sync: 运行中")
        for task in running:
            _render_task_row(task, task_manager, cancellable=True)

    if pending:
        st.subheader(f":material/hourglass_empty: 排队中（{len(pending)}）")
        for task in pending:
            _render_task_row(task, task_manager, cancellable=True)

    if others:
        st.subheader(":material/history: 历史记录")
        for task in others:
            _render_task_row(task, task_manager, cancellable=False)

        if st.button(
            "清理历史记录",
            icon=":material/cleaning_services:",
            key="qs_clear_history",
        ):
            removed = task_manager.clear_history(filters.get("database_name"))
            st.session_state['task_cleared'] = removed
            st.rerun()

    cleared = st.session_state.pop('task_cleared', None)
    if cleared is not None:
        st.success(f"已清理 {cleared} 条历史记录")


def _render_progress_overlay(running: list[dict]) -> None:
    """渲染浮于内容之上的进度浮层。

    Args:
        running: 运行中的任务列表
    """
    rows = []
    for task in running:
        pct = task["progress_percentage"]
        stage = task.get("stage") or TaskKind.LABELS.get(task["kind"], "")
        rows.append(
            '<div class="qs-progress-row">'
            f'<span class="qs-progress-name">{task["task_name"]}</span>'
            f'<span class="qs-progress-count">'
            f'{task["processed_items"]:,} / {task["total_items"]:,}'
            f'</span>'
            f'<span class="qs-progress-pct">{pct:.1f}%</span>'
            f'<span class="qs-progress-track">'
            f'<span class="qs-progress-fill" style="width:{min(100.0, max(0.0, pct)):.1f}%"></span>'
            "</span>"
            f'<span class="qs-progress-count">{stage}</span>'
            "</div>"
        )

    st.markdown(
        f'<div class="qs-progress-overlay">{"".join(rows)}</div>',
        unsafe_allow_html=True,
    )


def _render_task_row(task: dict, task_manager: TaskManager, cancellable: bool) -> None:
    """渲染单个任务行。

    Args:
        task: 任务字典
        task_manager: TaskManager 实例
        cancellable: 是否显示取消按钮
    """
    with st.container(key=f"qsrow_task_{task['task_id']}"):
        cols = st.columns([2.6, 1.3, 1.5, 1.1, 1, 1.4, 1])

        with cols[0]:
            st.markdown(
                f'<div class="qs-td qs-td--name">{task["task_name"]}'
                f'<span class="qs-td-sub">{task["database_name"]} · '
                f'{task["task_id"][:8]}</span></div>',
                unsafe_allow_html=True,
            )

        with cols[1]:
            st.markdown(
                f'<div class="qs-td">{TaskKind.LABELS.get(task["kind"], task["kind"])}</div>',
                unsafe_allow_html=True,
            )

        with cols[2]:
            # 任务状态是机器输出，走低饱和信息寄存器 —— 不占用决策色
            chip = components.task_status_chip(task["status"])
            extra = _position_text(task, task_manager)
            sub = f'<span class="qs-td-sub">{extra}</span>' if extra else ""
            st.markdown(
                f'<div class="qs-td">{chip}{sub}</div>',
                unsafe_allow_html=True,
            )

        with cols[3]:
            st.markdown(
                f'<div class="qs-td qs-td--num">{task["processed_items"]:,}'
                f' / {task["total_items"]:,}</div>',
                unsafe_allow_html=True,
            )

        with cols[4]:
            failed = task["failed_items"]
            st.markdown(
                f'<div class="qs-td qs-td--num">{failed:,}</div>'
                if failed
                else '<div class="qs-td qs-td--num">—</div>',
                unsafe_allow_html=True,
            )

        with cols[5]:
            if task["status"] == TaskStatus.RUNNING:
                detail = _eta_text(task)
            else:
                detail = task["created_at"][:16].replace("T", " ")

            # 显示车道与实际并行度（从调度器配置读取，不再读已删除的 num_workers 列）
            lane_label = "交互" if task.get("lane") == "interactive" else "后台"
            st.markdown(
                f'<div class="qs-td qs-td--num">{detail}'
                f'<span class="qs-td-sub">{lane_label}车道</span></div>',
                unsafe_allow_html=True,
            )

        with cols[6]:
            if cancellable:
                if st.button(
                    "取消",
                    icon=":material/stop_circle:",
                    key=f"qscancel_{task['task_id']}",
                ):
                    task_manager.cancel_task(task["task_id"])
                    st.rerun()

        if task["status"] == TaskStatus.FAILED and task.get("error_message"):
            st.error(f"错误：{task['error_message']}")

        if task.get("cancel_requested") and task["status"] == TaskStatus.RUNNING:
            st.caption("已请求取消，正在当前条目结束后停止…")


def _position_text(task: dict, task_manager: TaskManager) -> str:
    """排队中任务的队列位置文案。

    Args:
        task: 任务字典
        task_manager: TaskManager 实例

    Returns:
        形如 ``前面还有 2 个`` 的文案；非排队状态返回阶段描述
    """
    if task["status"] != TaskStatus.PENDING:
        return task.get("stage") or ""

    ahead = task_manager.queue_position(task["task_id"])

    if ahead is None:
        return ""
    if ahead == 0:
        return "下一个执行"

    return f"前面还有 {ahead} 个"


def _eta_text(task: dict) -> str:
    """估算剩余时间。

    Args:
        task: 任务字典

    Returns:
        形如 ``剩 12 分`` 的文案；无法估算时返回 ``—``
    """
    processed = task["processed_items"]
    started = task.get("started_at")
    if not processed or not started:
        return "—"

    try:
        start = datetime.fromisoformat(started.replace("Z", "+00:00"))
    except ValueError:
        return "—"

    now = datetime.now(start.tzinfo)
    elapsed = (now - start).total_seconds()
    if elapsed <= 0:
        return "—"

    rate = processed / elapsed
    remaining = task["total_items"] - processed
    if rate <= 0 or remaining <= 0:
        return "—"

    minutes = int(remaining / rate / 60)
    return f"剩 {minutes} 分" if minutes else "即将完成"
