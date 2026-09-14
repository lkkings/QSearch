"""标注工作台（横向结果轨道）。

查询图锚定于上，候选卡片在同一横向轨道内排列，点击卡片直接标注。

原实现是「一屏一个候选」的顺序比对：rank 3 之后的候选大多一眼就能否掉，
但仍要走完整流程。横向轨道让一屏内完成多个决策，且标注员能看到本题全貌
（已标了什么、还剩几个）而非只有「3 / 10」这个计数。

键盘是主要输入方式，鼠标是备用 —— 见 ui/shortcuts.py 的双层焦点设计。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from qsearch.tasks.queue import TaskKind, TaskStatus
from qsearch.webui import grid_nav, thumbnails
from qsearch.webui.annotation_manager import AnnotationManager
from qsearch.webui.annotation_tasks import (
    UNASSIGNED_TASK_ID,
    build_annotation_tasks,
    choose_query_id,
    task_at_row,
    task_for_query,
)
from qsearch.webui.database_manager import DatabaseManager
from qsearch.webui.task_manager import TaskManager
from qsearch.webui.ui import components
from qsearch.webui.ui.shortcuts import KEY_HINTS, render_keyboard_bridge

# 相比原五列网格约 233px 的卡片，360px 能保留更多图像细节；横向轨道
# 负责承载溢出，因此结果数量不会再把卡片压窄。
CANDIDATE_CARD_WIDTH = 360

_LABELS = ("hit", "miss", "skip")

_QUERY_STATUS_ICONS = {
    "unlabeled": ":material/radio_button_unchecked:",
    "partial": ":material/pending:",
    "completed": ":material/check_circle:",
    "no_candidates": ":material/remove_circle_outline:",
}


def render_annotation_page(databases_root: Path) -> None:
    """渲染标注页面。

    Args:
        databases_root: 数据库根目录
    """
    databases = DatabaseManager(databases_root).list_databases()
    if not databases:
        st.header(":material/edit: 标注")
        st.info("暂无数据库。请先在「数据库管理」中创建。")
        return

    names = [db["name"] for db in databases]
    current = st.session_state.get("selected_database")
    if current not in names:
        current = names[0]
        st.session_state["selected_database"] = current

    db_path = databases_root / current
    try:
        manager = AnnotationManager(db_path)
    except FileNotFoundError:
        st.error(f"数据库「{current}」缺少标注库文件，无法标注。")
        return

    query_summaries = manager.list_query_summaries(current)
    task_manager = TaskManager(databases_root)
    search_tasks = task_manager.list_tasks(database_name=current)
    annotation_tasks = build_annotation_tasks(
        search_tasks,
        query_summaries,
        task_manager.read_task_payload,
    )
    stats = manager.get_statistics()

    requested_query_id = st.session_state.pop("annotation_query_id", None)
    if requested_query_id:
        requested_task = task_for_query(annotation_tasks, requested_query_id)
        if requested_task:
            st.session_state["qs_annotation_task_id"] = requested_task["task_id"]
            st.session_state["qs_annotation_query_id"] = requested_query_id
        else:
            st.info("所选 Query 不存在于当前数据库的标注结果中。")

    selected_task_id = st.session_state.get("qs_annotation_task_id")
    selected_task = next(
        (task for task in annotation_tasks if task["task_id"] == selected_task_id),
        None,
    )
    if selected_task_id and selected_task is None:
        st.session_state.pop("qs_annotation_task_id", None)
        st.session_state.pop("qs_annotation_query_id", None)
        st.session_state["qs_focus_mode"] = False
        st.info("原标注任务已不可用，请重新选择任务。")

    if selected_task is None:
        _render_task_list(annotation_tasks, current, stats)
        return

    focus_mode = st.session_state.get("qs_focus_mode", False)
    _render_workbench(manager, selected_task, stats, focus_mode)


def _render_task_list(
    annotation_tasks: list[dict], database_name: str, stats: dict
) -> None:
    """Render the task-first entry view for annotation."""
    st.session_state["qs_focus_mode"] = False
    st.header(":material/edit: 标注任务")
    st.caption(f"当前数据库：`{database_name}`（可在侧边栏切换）")

    if not annotation_tasks:
        st.info("暂无查询任务或可标注 Query。请先执行单图或批量查询。")
        return

    st.caption(
        f"全库已完成 {stats['completed_queries']} / {stats['total_queries']} 个 Query · "
        f"已标注 {stats['labeled_candidates']} 个结果"
    )

    rows = []
    for task in annotation_tasks:
        kind = task.get("kind")
        status = task.get("status")
        rows.append(
            {
                "任务": task["task_name"],
                "类型": (
                    "未归档"
                    if task["task_id"] == UNASSIGNED_TASK_ID
                    else TaskKind.LABELS.get(kind, str(kind))
                ),
                "执行状态": (
                    "未归档"
                    if task["task_id"] == UNASSIGNED_TASK_ID
                    else TaskStatus.LABELS.get(status, str(status))
                ),
                "任务输入": int(task.get("total_items") or 0),
                "可标注 Query": task["query_count"],
                "已完成": task["completed_count"],
                "标注进度": task["annotation_progress"],
                "操作": ":material/edit: 进入标注" if task["annotatable"] else None,
            }
        )

    st.dataframe(
        pd.DataFrame(rows),
        column_config={
            "任务": st.column_config.TextColumn("任务", pinned=True),
            "标注进度": st.column_config.ProgressColumn(
                "标注进度", min_value=0.0, max_value=1.0, format="percent"
            ),
            "操作": st.column_config.ButtonColumn(
                "",
                type="primary",
                on_click=_enter_task_from_table,
                args=(annotation_tasks,),
                key="qs_annotation_task_click",
            ),
        },
        hide_index=True,
        width="stretch",
        key="qs_annotation_task_table",
    )

    unavailable = sum(task.get("payload_unavailable", False) for task in annotation_tasks)
    if unavailable:
        st.caption(
            f"{unavailable} 个历史任务的 Query 清单不可读取；相关结果如仍存在，"
            "已归入“未归档查询”。"
        )


def _enter_task_from_table(annotation_tasks: list[dict]) -> None:
    """Handle the transient click emitted by the task dataframe button column."""
    click = st.session_state.get("qs_annotation_task_click")
    if not click:
        return
    task = task_at_row(annotation_tasks, int(click["row"]))
    if not task or not task.get("annotatable"):
        return
    st.session_state["qs_annotation_task_id"] = task["task_id"]
    st.session_state["qs_annotation_query_id"] = choose_query_id(task["queries"])


def _leave_annotation_task() -> None:
    """Return to the task list and clear task-scoped widget state."""
    st.session_state.pop("qs_annotation_task_id", None)
    st.session_state.pop("qs_annotation_query_id", None)
    st.session_state["qs_focus_mode"] = False


def _render_workbench(
    manager: AnnotationManager,
    task: dict,
    stats: dict,
    focus_mode: bool,
) -> None:
    """渲染工作台主体。

    Args:
        manager: AnnotationManager 实例
        task: 当前标注任务投影
        stats: 数据库层面的统计
        focus_mode: 是否专注模式
    """
    queries = task["queries"]
    selected_query_id = choose_query_id(
        queries, st.session_state.get("qs_annotation_query_id")
    )
    if selected_query_id is None:
        st.warning("该任务尚无可标注 Query。")
        return
    st.session_state["qs_annotation_query_id"] = selected_query_id
    q_idx = next(
        index for index, item in enumerate(queries) if item["query_id"] == selected_query_id
    )
    query = queries[q_idx]

    _render_task_toolbar(task, focus_mode)
    _render_query_navigation(task, selected_query_id)

    # 历史候选默认不呈现（任务 10.1）。开关是纯视图偏好，留在 session 而非 URL。
    show_history = st.session_state.get("qs_show_history", False)

    results = manager.get_query_results(
        query["query_id"], include_history=show_history
    )
    if not results:
        st.error("查询结果读取失败")
        return

    candidates = results.get("candidates", [])

    # 开关本身必须在「没有候选」的分支之前渲染 —— 否则当前结果集为空时开关
    # 消失，用户再也回不到历史候选。
    _render_history_toggle(manager, query["query_id"], show_history)

    # 进度只依据当前结果集（任务 10.3）。历史候选即使未标注也不计入分母，
    # 否则重搜越多分母越大，标注永远做不完。
    current = [c for c in candidates if c.get("in_current_result", 1)]
    labeled_here = sum(1 for c in current if c.get("label"))

    # 分母取当前结果集大小，不是网格里渲染的行数 —— 开着历史开关时两者不同。
    _render_topbar(
        task_name=task["task_name"],
        task_completed=task["completed_count"],
        q_idx=q_idx,
        q_total=len(queries),
        labeled_here=labeled_here,
        cand_total=len(current),
        stats=stats,
        focus_mode=focus_mode,
    )

    _render_query_anchor(query, len(current), labeled_here)

    if not candidates:
        st.warning("本道查询没有候选项")
        return

    card_keys, decision_keys = _render_candidate_strip(manager, query, candidates)

    help_key = _render_footer()

    # 键盘桥接放在最后 —— 它需要本次渲染中全部按钮的 key
    render_keyboard_bridge(
        nav_map=grid_nav.nav_map(len(candidates), len(candidates)),
        card_keys=card_keys,
        decision_keys=decision_keys,
        help_key=help_key,
        focus_mode=focus_mode,
    )


def _render_task_toolbar(task: dict, focus_mode: bool) -> None:
    """Render task identity and the always-available return action."""
    with st.container(horizontal=True, vertical_alignment="center"):
        if st.button(
            "返回任务列表",
            icon=":material/arrow_back:",
            key="qs_annotation_back",
        ):
            _leave_annotation_task()
            st.rerun()
        if not focus_mode:
            st.subheader(task["task_name"])
            if st.button(
                "进入专注模式",
                icon=":material/fullscreen:",
                key="qs_annotation_focus",
            ):
                st.session_state["qs_focus_mode"] = True
                st.rerun()


def _render_query_navigation(task: dict, selected_query_id: str) -> None:
    """Render task Queries as directly selectable status buttons."""
    with st.container(key="qs_query_navigation"):
        with st.container(
            horizontal=True,
            wrap=False,
            gap="xsmall",
            key="qs_query_navigation_strip",
        ):
            for index, query in enumerate(task["queries"]):
                query_id = query["query_id"]
                status = query.get("annotation_status") or "unlabeled"
                is_selected = query_id == selected_query_id
                selection = "selected" if is_selected else "idle"
                item_key = f"qsnavitem_{index}_{status}_{selection}"
                filename = Path(query["query_image_path"]).name
                status_text = _status_text(status)
                prefix = "当前 · " if is_selected else ""
                label = f"{prefix}{index + 1}. {filename} · {status_text}"
                help_text = (
                    f"{query['query_image_path']}\n\n"
                    f"状态：{status_text} · "
                    f"已标注 {int(query.get('labeled') or 0)} / "
                    f"{int(query.get('total') or 0)} · "
                    f"命中 {int(query.get('hits') or 0)}"
                )

                with st.container(key=item_key, width=220):
                    if st.button(
                        label,
                        icon=_QUERY_STATUS_ICONS.get(status, ":material/help:"),
                        key=f"qs_query_nav_button_{task['task_id']}_{query_id}",
                        help=help_text,
                        width="stretch",
                        wrap=False,
                    ):
                        st.session_state["qs_annotation_query_id"] = query_id
                        st.rerun()


def _render_topbar(
    *,
    task_name: str,
    task_completed: int,
    q_idx: int,
    q_total: int,
    labeled_here: int,
    cand_total: int,
    stats: dict,
    focus_mode: bool,
) -> None:
    """渲染顶部单行状态条。

    进度、统计、退出通路压在一行内 —— 这些是辅助信息，不该与图像抢
    垂直空间。原实现用三个 st.metric 加一条 st.progress，占掉约 150px。
    """
    bar, actions = st.columns([5, 1])

    with bar:
        st.markdown(
            '<div class="qs-topbar">'
            f'<span><strong>{task_name}</strong></span>'
            f'<span>查询 <strong>{q_idx + 1}</strong> / {q_total}</span>'
            f'<span>任务完成 <strong>{task_completed}</strong> / {q_total}</span>'
            f'<span>本题 <strong>{labeled_here}</strong> / {cand_total}</span>'
            f'<span>已标 <strong>{stats["labeled_candidates"]}</strong></span>'
            f'<span>命中率 <strong>{stats["hit_rate"]:.1%}</strong></span>'
            "</div>",
            unsafe_allow_html=True,
        )

    with actions:
        if focus_mode:
            if st.button("退出专注", width='stretch'):
                st.session_state["qs_focus_mode"] = False
                st.rerun()
        else:
            st.caption("左右滑动浏览结果")


def _render_history_toggle(
    manager: AnnotationManager, query_id: str, show_history: bool
) -> None:
    """历史候选开关。

    历史候选是「曾经在结果集里、换配置后掉出去」的候选。它们保留了人工标注，
    因此不能删；但混进默认视图会让标注员对着一份越搜越长的列表工作。开关只在
    确实存在历史候选时出现 —— 没有历史时它是一个永远无效的控件。

    Args:
        manager: 标注数据访问层
        query_id: 当前 Query ID
        show_history: 当前开关状态
    """
    full = manager.get_query_results(query_id, include_history=True)
    if not full:
        return

    history_count = sum(
        1 for c in full["candidates"] if not c.get("in_current_result", 1)
    )
    if history_count == 0:
        return

    st.toggle(
        f"显示 {history_count} 个历史候选",
        value=show_history,
        key="qs_show_history",
        help="历史候选曾在结果集内，换配置重搜后掉出。其人工标注已保留，"
             "但不计入本题的标注进度。",
    )


def _render_query_anchor(query: dict, cand_total: int, labeled_here: int) -> None:
    """渲染锚定的查询图。

    容器 key 使 CSS 能给它加 position: sticky —— 焦点在网格内移动时查询图
    保持位置不变，眼睛不必重新定位。任务 3.1 实测确认 sticky 在 Streamlit
    的容器结构下生效。
    """
    with st.container(key="qsanchor"):
        left, right = st.columns([1, 2])

        with left:
            _render_image(query["query_image_path"], thumbnails.QUERY_LONG_EDGE)

        with right:
            st.markdown("**查询图**")
            st.progress(
                labeled_here / cand_total if cand_total else 0.0,
                text=f"本题进度 {labeled_here} / {cand_total}",
            )
            st.caption(f"路径：{query['query_image_path']}")
            status = query.get("annotation_status") or query.get("status")
            st.caption(f"状态：{_status_text(status)}")


def _render_image(path: str, long_edge: int) -> None:
    """渲染一张图像，不可读时降级为占位标识。

    某张候选图坏掉不应让整页失败，但标注员需要知道那一格为什么是空的 ——
    否则会误以为界面卡了。
    """
    try:
        st.image(thumbnails.get_thumbnail(path, long_edge), width='stretch')
    except thumbnails.ThumbnailError as exc:
        st.markdown(
            f'<div class="qs-img-missing">图像不可用<br>'
            f'<span>{exc}</span></div>',
            unsafe_allow_html=True,
        )


def _status_text(status: str | None) -> str:
    """查询状态的中文文案。"""
    return {
        "unlabeled": "未标注",
        "partial": "部分完成",
        "completed": "已完成",
        "no_candidates": "无候选",
    }.get(status or "", status or "未知")


def _render_candidate_strip(
    manager: AnnotationManager,
    query: dict,
    candidates: list[dict],
) -> tuple[list[str], dict[str, list[str]]]:
    """在单行横向滚动轨道中渲染全部候选卡片。

    Returns:
        ``(card_keys, decision_keys)``，两者均与候选索引对齐，供键盘桥接
        按索引定位 DOM 元素。
    """
    card_keys: list[str] = []
    decision_keys: dict[str, list[str]] = {k: [] for k in _LABELS}

    with st.container(
        horizontal=True,
        wrap=False,
        gap="small",
        key="qscandidate_strip",
    ):
        for idx, candidate in enumerate(candidates):
            keys = _render_card(manager, query, candidate, idx)
            card_keys.append(keys["card"])
            for label in _LABELS:
                decision_keys[label].append(keys[label])

    return card_keys, decision_keys


def _render_card(
    manager: AnnotationManager,
    query: dict,
    candidate: dict,
    idx: int,
) -> dict[str, str]:
    """渲染单个候选卡片。

    标注状态编码进容器 key（``qscard_<idx>_lbl_<label>``）—— Python 无法给
    Streamlit 生成的容器加任意 class，这是在不引入自定义组件的前提下把状态
    带到 CSS 的可行路径。

    Returns:
        本卡片各元素的 key，键为 ``card`` 与三个标注值
    """
    label = candidate.get("label") or "none"
    is_history = not candidate.get("in_current_result", 1)
    # 历史身份进 key，因此 CSS 能把这些卡片压暗，与当前候选区分开。
    card_key = f"qscard_{idx}_lbl_{label}" + ("_hist" if is_history else "")
    keys = {"card": card_key}

    with st.container(key=card_key, width=CANDIDATE_CARD_WIDTH):
        if is_history:
            # 文字标记是主通道：压暗只是颜色差异，色觉受限或对比度不足时不可靠。
            st.caption("历史候选 · 不在当前结果集")

        _render_image(candidate["candidate_image_path"], thumbnails.DEFAULT_LONG_EDGE)

        # 评分行 —— rank、综合分、置信 chip 同处一行。原实现用三列
        # markdown 铺了 8 行，占掉的是图像的空间。
        st.markdown(
            '<div class="qs-card-meta">'
            f'<span class="qs-card-rank">#{candidate["rank"]}</span>'
            f'<span class="qs-card-score">{candidate["overall_score"]:.3f}</span>'
            f'{components.confidence_chip(candidate["confidence_level"])}'
            "</div>",
            unsafe_allow_html=True,
        )

        st.markdown(
            f'<div class="qs-card-label">{components.label_badge(candidate.get("label"))}</div>',
            unsafe_allow_html=True,
        )

        _render_detail_popover(manager, query, candidate, idx)

        # 决策按钮。键位写在按钮上，不藏在侧栏。
        # 图标与文本同时呈现：图标缺失时文本仍说明动作（任务 11.5、11.7），
        # 三个字形形状互不相同（任务 11.6）。
        b_hit, b_miss, b_skip = st.columns(3)
        specs = (
            (b_hit, "hit", "命中 1", ":material/check_circle:", "标注为命中（快捷键 1）"),
            (b_miss, "miss", "未命中 0", ":material/cancel:", "标注为未命中（快捷键 0）"),
            (b_skip, "skip", "跳过 S", ":material/do_not_disturb_on:", "跳过该候选（快捷键 S）"),
        )
        for col, value, caption, icon, description in specs:
            key = f"qsdec_{value}_{idx}"
            keys[value] = key
            with col:
                if st.button(
                    caption, icon=icon, key=key, width='stretch', help=description
                ):
                    _apply_label(manager, query, candidate, value)

    return keys


def _render_detail_popover(
    manager: AnnotationManager,
    query: dict,
    candidate: dict,
    idx: int,
) -> None:
    """详细评分与备注放入 popover。

    满足「可查但不占图像空间」：文本分、视觉分、哈希距离是辅助信息，
    平铺出来会把图像挤小。popover 也是 Streamlit 原生浮层，毛玻璃的
    正当落点之一。
    """
    with st.popover("详情", width='stretch'):
        st.markdown(f"**排名** {candidate['rank']}")
        st.markdown(f"**匹配类型** {components.match_type_text(candidate['match_type'])}")
        st.markdown(f"**综合评分** {candidate['overall_score']:.4f}")

        for field, caption in (
            ("text_score", "文本评分"),
            ("visual_score", "视觉评分"),
        ):
            value = candidate.get(field)
            if value is not None:
                st.markdown(f"**{caption}** {value:.4f}")

        if candidate.get("hash_distance") is not None:
            st.markdown(f"**哈希距离** {candidate['hash_distance']}")

        st.caption(f"路径：{candidate['candidate_image_path']}")

        notes = st.text_area(
            "备注（可选）",
            value=candidate.get("notes") or "",
            key=f"qsnote_{idx}",
        )
        if st.button("保存备注", key=f"qsnotesave_{idx}"):
            # 备注可独立于标注保存。未标注时以 skip 落库 —— label 列有
            # CHECK 约束，不接受空串。
            _apply_label(
                manager, query, candidate,
                candidate.get("label") or "skip",
                notes=notes,
            )


def _apply_label(
    manager: AnnotationManager,
    query: dict,
    candidate: dict,
    label: str,
    notes: str | None = None,
) -> None:
    """写入标注并重新渲染。

    对已标注项施加新标注时直接替换 —— label_candidate 是 UPSERT 语义，
    labeled_at 随之更新。
    """
    manager.label_candidate(
        query_id=query["query_id"],
        candidate_id=candidate["candidate_id"],
        label=label,
        notes=notes if notes else candidate.get("notes"),
    )
    st.rerun()


def _render_footer() -> str:
    """渲染底部快捷键速查，不再提供顺序翻题控件。"""
    help_key = "qshelp"

    with st.container(horizontal=True, horizontal_alignment="right"):
        with st.container(key=help_key):
            with st.popover("快捷键 ?", width='stretch'):
                for key, description in KEY_HINTS:
                    st.markdown(
                        f'<span class="qs-key">{key}</span> {description}',
                        unsafe_allow_html=True,
                    )

    return help_key
