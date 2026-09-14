"""Interactive search UI components for QSearch WebUI."""

import tempfile
import uuid
from pathlib import Path
from typing import Optional

import streamlit as st

from qsearch.tasks.queue import TaskStatus
from qsearch.webui.annotation_manager import AnnotationManager
from qsearch.webui.database_manager import DatabaseManager
from qsearch.webui.db_manager import get_database_manager
from qsearch.webui.task_manager import TaskManager
from qsearch.webui.workspace_state import ANNOTATION_VIEW, activate_workspace_view
from qsearch.webui.ui import components
from qsearch.webui.ui import search_params_ui

SEARCH_TAB_LABELS = ("单图搜索", "批量搜索", "Query 筛选")


def _enqueue_batch_search(
    databases_root: Path,
    database_name: str,
    image_paths: tuple[Path, ...],
    top_n: int,
    batch_size: int,
    num_gpus: int,
    task_name: str,
    config_yaml: Optional[str],
) -> None:
    """Button callback that persists the enqueue outcome across the rerun."""
    try:
        task_manager = TaskManager(databases_root)
        task_id = task_manager.enqueue_batch_search(
            database_name=database_name,
            image_paths=image_paths,
            top_n=top_n,
            batch_size=batch_size,
            num_gpus=num_gpus,
            task_name=task_name,
            config_yaml=config_yaml,
        )
        st.session_state["batch_queued"] = (
            "ok",
            (task_id, len(image_paths), database_name),
        )
        st.session_state["qs_batch_task_id"] = task_id
    except Exception as exc:
        st.session_state["batch_queued"] = (
            "err",
            (str(exc), database_name),
        )


def _is_indexed(databases_root: Path, database_name: str) -> bool:
    """该库是否已建索引。

    Args:
        databases_root: 数据库根目录
        database_name: 数据库名

    Returns:
        已建索引为 True；库不存在或元数据不可读时为 False
    """
    try:
        info = DatabaseManager(databases_root).get_database_info(database_name)
    except Exception:
        return False

    return bool(info.get("index_built"))


def _materialize_query_image(query_image) -> str:
    """把查询图输入转成 worker 进程可解析的路径或 URL。

    上传件是调用方进程内的内存对象，worker 是独立进程 —— 必须先落盘。
    本地路径与 URL 本身即可跨进程传递，原样返回。

    Args:
        query_image: 上传件、本地路径字符串或 URL 字符串

    Returns:
        路径字符串或 URL 字符串
    """
    if isinstance(query_image, str):
        return query_image

    suffix = Path(getattr(query_image, "name", "upload.png")).suffix or ".png"
    tmp_dir = Path(tempfile.gettempdir()) / "qsearch_uploads"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir / f"{uuid.uuid4().hex}{suffix}"

    data = query_image.getvalue() if hasattr(query_image, "getvalue") else query_image.read()
    tmp_path.write_bytes(data)

    return str(tmp_path)


def _load_result_from_annotations(
    databases_root: Path, database_name: str, query_image_path: str
) -> Optional[dict]:
    """从标注库读回一次查询的结果。

    交互任务的结果只存在标注库里（队列行只承载状态机），因此呈现前必须回读。
    只取 ``in_current_result = 1`` 的候选 —— 历史候选不属于本次结果集。

    Args:
        databases_root: 数据库根目录
        database_name: 数据库名
        query_image_path: 查询图路径

    Returns:
        结果字典；查询行不存在时返回 ``None``
    """
    annotations_db = databases_root / database_name / "annotations" / "annotations.db"
    if not annotations_db.exists():
        return None

    db_manager = get_database_manager(annotations_db)

    query_row = db_manager.execute_query(
        "SELECT * FROM queries WHERE database_name = ? AND query_image_path = ?",
        (database_name, query_image_path),
        fetch_one=True,
    )
    if query_row is None:
        return None

    candidate_rows = db_manager.execute_query(
        """
        SELECT * FROM candidates
        WHERE query_id = ? AND in_current_result = 1
        ORDER BY rank
        """,
        (query_row["query_id"],),
        fetch_all=True,
    ) or []

    results = {
        "query_id": query_row["query_id"],
        "query_image": query_image_path,
        "query": dict(query_row),
        # sqlite3.Row 没有 .get()，且该列可为 NULL。
        "processing_time_ms": query_row["processing_time_ms"] or 0,
        "exact_matches": [],
        "content_matches": [],
    }

    for row in candidate_rows:
        candidate = {
            "candidate_id": row["candidate_id"],
            "image_path": row["candidate_image_path"],
            "candidate_image_path": row["candidate_image_path"],
            "rank": row["rank"],
            "match_type": row["match_type"],
            "confidence_level": row["confidence_level"],
            "overall_score": row["overall_score"],
            "text_score": row["text_score"],
            "visual_score": row["visual_score"],
            "hash_distance": row["hash_distance"],
            "label": row["label"],
            "notes": row["notes"],
            "labeled_at": row["labeled_at"],
            "in_current_result": row["in_current_result"],
        }
        bucket = "exact_matches" if row["match_type"] == "exact" else "content_matches"
        results[bucket].append(candidate)

    return results


@st.fragment(run_every=0.4)
def render_interactive_search_status(
    databases_root: Path, task_id: str, database_name: str
) -> None:
    """轮询交互查询任务，终态后停止轮询。

    ``run_every`` 在 fragment 创建时就已固定，清 session key 并不能让它停下 ——
    必须让整页 rerun 一次，使外层不再创建这个 fragment。因此终态分支写入
    outcome 后调用 ``st.rerun(scope="app")``。

    Args:
        databases_root: 数据库根目录
        task_id: 待轮询的任务 ID
        database_name: 数据库名
    """
    task_manager = TaskManager(databases_root)
    task = task_manager.get_task_status(task_id)

    def _settle(outcome: tuple) -> None:
        """记录终态并停止轮询。"""
        st.session_state['qs_ia_outcome'] = outcome
        st.session_state.pop('qs_ia_task_id', None)
        st.rerun(scope="app")

    if task is None:
        _settle(('err', "任务不存在或已被清理"))
        return

    status = task["status"]

    if status == TaskStatus.PENDING:
        ahead = task_manager.queue_position(task_id)
        position = f"，前面还有 {ahead} 个" if ahead else ""
        st.info(f"查询已提交，等待执行{position}", icon=":material/schedule:")
        return

    if status == TaskStatus.RUNNING:
        st.info(task.get("stage") or "查询执行中", icon=":material/sync:")
        return

    if status == TaskStatus.COMPLETED:
        payload = task_manager.queue.read_payload(task) or {}
        query_image_path = payload.get("query_image_path")

        try:
            results = _load_result_from_annotations(
                databases_root, database_name, query_image_path
            )
        except Exception as exc:
            _settle(('err', f"加载结果失败：{exc}"))
            return

        if results is None:
            _settle(('err', "任务已完成，但标注库中没有对应的查询记录"))
        else:
            _settle(('ok', results))
        return

    if status == TaskStatus.FAILED:
        _settle(('err', f"查询失败：{task.get('error_message') or '未知错误'}"))
        return

    if status == TaskStatus.CANCELLED:
        _settle(('cancelled', "查询已取消"))


def _render_interactive_outcome(databases_root: Path) -> None:
    """呈现上一次交互查询的终态结果。

    结果留在 session 里而非按钮分支内 —— 分支只在点击那一次 rerun 中执行，
    写在里面的呈现会一闪而过。

    Args:
        databases_root: 数据库根目录
    """
    outcome = st.session_state.get('qs_ia_outcome')
    if not outcome:
        return

    kind, payload = outcome

    if kind == 'ok':
        st.success(
            f"查询完成，耗时 {payload['processing_time_ms']:.0f}ms",
            icon=":material/check_circle:",
        )
    elif kind == 'cancelled':
        st.warning(payload, icon=":material/block:")
    else:
        st.error(payload, icon=":material/error:")


def render_search_page(databases_root: Path):
    """Render search, results, batch tools and query filters in one lane.

    Args:
        databases_root: Root directory for databases
    """
    st.header(":material/search: 搜索")

    db_manager = DatabaseManager(databases_root)
    databases = db_manager.list_databases()

    if not databases:
        st.warning("暂无数据库。请先在「数据库管理」中创建。")
        return

    db_names = [db['name'] for db in databases]
    selected_db = st.session_state.get("selected_database")
    if selected_db not in db_names:
        selected_db = db_names[0]
        st.session_state["selected_database"] = selected_db

    st.caption(f"当前数据库：`{selected_db}`（可在侧边栏切换）")

    single_tab, batch_tab, filter_tab = st.tabs(SEARCH_TAB_LABELS)

    with single_tab:
        from qsearch.webui.ui.components import (
            render_results_grid,
            render_search_panel,
        )

        render_search_panel(databases_root, selected_db, expanded=True)

        if "qs_ia_task_id" in st.session_state:
            render_interactive_search_status(
                databases_root,
                st.session_state["qs_ia_task_id"],
                st.session_state.get("qs_ia_task_db", selected_db),
            )

        active_outcome = st.session_state.get("qs_ia_outcome")
        if active_outcome and active_outcome[0] == "ok":
            st.session_state["search_results"] = active_outcome[1]
            st.session_state["search_results_database"] = selected_db
        _render_interactive_outcome(databases_root)

        results = st.session_state.get("search_results")
        results_database = st.session_state.get("search_results_database")
        if results and results_database == selected_db:
            try:
                manager = AnnotationManager(databases_root / selected_db)
            except FileNotFoundError:
                manager = None
            render_results_grid(
                results,
                annotation_manager=manager,
                columns=st.session_state.get("grid_columns", 3),
                key_prefix="workspace_results",
            )

    with batch_tab:
        render_batch_search_tab(databases_root, selected_db)
    with filter_tab:
        render_query_filter_tab(databases_root, selected_db)


def render_single_search_tab(databases_root: Path, database_name: str):
    """Render single image search tab.

    Args:
        databases_root: Root directory for databases
        database_name: Selected database name
    """
    st.subheader("单图搜索")

    # Input mode selection
    input_mode = st.radio(
        "输入模式",
        options=["upload", "path", "url"],
        format_func=lambda x: {
            "upload": ":material/upload: 上传图像",
            "path": ":material/folder: 本地文件路径",
            "url": ":material/link: 图像 URL",
        }[x],
        horizontal=True,
    )

    query_image = None

    if input_mode == "upload":
        uploaded_file = st.file_uploader(
            "上传查询图像",
            type=['jpg', 'jpeg', 'png', 'bmp'],
        )
        if uploaded_file:
            query_image = uploaded_file

    elif input_mode == "path":
        image_path = st.text_input("图像文件路径")
        if image_path and Path(image_path).exists():
            query_image = image_path
        elif image_path:
            st.error("文件不存在")

    elif input_mode == "url":
        image_url = st.text_input("图像 URL")
        if image_url:
            query_image = image_url

    # 检索参数配置
    param_values, config_yaml = search_params_ui.render_search_params_panel(
        databases_root=databases_root,
        database_name=database_name,
        key_prefix="single",
    )

    # top_n 从参数面板获取
    top_n = param_values.get("top_n", 10)

    # 未建索引的库不受理检索。索引缺失时 SearchEngine 构造即失败，让它走到
    # worker 里再失败只是把一句可读提示换成一条任务错误。
    indexed = _is_indexed(databases_root, database_name)
    if not indexed:
        st.warning(
            "该数据集尚未构建索引，暂不能检索。可在「数据集详情」触发构建，"
            "并在主页的「任务监控」查看进度。",
            icon=":material/build:",
        )

    submit_disabled = (query_image is None) or (not indexed)

    if st.button(
        "搜索",
        type="primary",
        disabled=submit_disabled,
        icon=":material/search:",
        key="qs_single_submit",
    ):
        try:
            # 上传是内存对象，worker 是独立进程，读不到调用方的内存。落到临时
            # 文件再入队，路径才是跨进程可解析的。URL 与本地路径本身即可传递。
            query_path = _materialize_query_image(query_image)

            task_manager = TaskManager(databases_root)
            task_id = task_manager.enqueue_interactive_search(
                database_name=database_name,
                query_image_path=query_path,
                top_n=top_n,
                config_yaml=config_yaml or None,
            )

            st.session_state['qs_ia_task_id'] = task_id
            st.session_state['qs_ia_task_db'] = database_name
            st.session_state.pop('qs_ia_outcome', None)

        except Exception as exc:
            st.session_state['qs_ia_outcome'] = ('err', f"提交查询失败：{exc}")

        st.rerun()

    # 轮询只在有在途任务时挂载。终态由 fragment 内写入 outcome 后触发整页
    # rerun，此处条件转假，fragment 不再被创建 —— run_every 随之停止。
    if 'qs_ia_task_id' in st.session_state:
        render_interactive_search_status(
            databases_root,
            st.session_state['qs_ia_task_id'],
            st.session_state.get('qs_ia_task_db', database_name),
        )

    _render_interactive_outcome(databases_root)


def render_batch_search_tab(databases_root: Path, database_name: str):
    """Render batch search tab.

    Args:
        databases_root: Root directory for databases
        database_name: Selected database name
    """
    st.subheader("批量搜索")

    # Task name
    task_name = st.text_input(
        "任务名称",
        value=f"批量搜索 {database_name}",
        help="此批量任务的可读名称",
    )

    # Input mode
    batch_mode = st.radio(
        "批量输入模式",
        options=["folder", "file_list"],
        format_func=lambda x: {
            "folder": ":material/folder: 文件夹（递归）",
            "file_list": ":material/description: 文件列表上传",
        }[x],
        horizontal=True,
    )

    image_paths = []
    # 「用户给了输入」与「输入解析出图像」是两件事。只看 image_paths 是否为空
    # 分不清「还没填」和「填了但一张都没找到」，前者不该报错，后者必须报错。
    has_input = False
    input_problem: Optional[str] = None

    if batch_mode == "folder":
        folder_path = st.text_input("文件夹路径", key="qs_batch_folder")
        has_input = bool(folder_path)

        if folder_path:
            folder = Path(folder_path)
            if not folder.exists():
                input_problem = f"文件夹不存在：{folder_path}"
            elif not folder.is_dir():
                input_problem = f"该路径不是文件夹：{folder_path}"
            else:
                image_extensions = {'.jpg', '.jpeg', '.png', '.bmp'}
                seen: set[Path] = set()
                for ext in image_extensions:
                    for pattern in (f"*{ext}", f"*{ext.upper()}"):
                        for found in folder.rglob(pattern):
                            # Windows 下大小写不敏感，两个 pattern 会撞同一文件。
                            if found not in seen:
                                seen.add(found)
                                image_paths.append(found)

                if image_paths:
                    st.info(f"找到 {len(image_paths):,} 张图像", icon=":material/image:")
                else:
                    input_problem = "该文件夹（含子目录）中没有支持的图像文件。"

    elif batch_mode == "file_list":
        uploaded_list = st.file_uploader(
            "上传文件列表",
            type=['txt'],
            help="文本文件，每行一个图像路径",
            key="qs_batch_list",
        )
        has_input = uploaded_list is not None

        if uploaded_list is not None:
            content = uploaded_list.getvalue().decode('utf-8', errors='replace')
            missing = 0
            for line in content.splitlines():
                line = line.strip()
                if not line:
                    continue
                if Path(line).exists():
                    image_paths.append(Path(line))
                else:
                    missing += 1

            if image_paths:
                note = f"已加载 {len(image_paths):,} 个有效图像路径"
                if missing:
                    note += f"，{missing:,} 个路径不存在已跳过"
                st.info(note, icon=":material/image:")
            else:
                input_problem = "文件列表中没有存在的图像路径。"

    # 检索参数配置
    param_values, config_yaml = search_params_ui.render_search_params_panel(
        databases_root=databases_root,
        database_name=database_name,
        key_prefix="batch",
    )

    # top_n 从参数面板获取
    top_n = param_values.get("top_n", 10)

    batch_size = st.number_input(
        "特征提取批大小",
        min_value=1,
        max_value=512,
        value=32,
        step=1,
        key="qs_batch_feature_batch_size",
        help="文本编码和图片深度特征每次处理的图片数",
    )

    num_gpus = st.number_input(
        "GPU 数量",
        min_value=0,
        max_value=8,
        value=0,
        step=1,
        key="qs_batch_num_gpus",
        help="用于查询特征提取的 GPU 数量；0 使用 CPU worker 池。",
    )

    if num_gpus > 0:
        st.caption("任务进入队列，由调度进程使用 GPU 分布式提取查询特征。")
    else:
        st.caption(
            "任务进入队列，由调度进程执行。同一批任务复用同一组 CPU worker，"
            "模型只加载一次。"
        )

    # 空批量输入不予受理。只在用户确实给过输入时报错，避免进页面就一片红。
    if has_input and input_problem:
        st.warning(input_problem, icon=":material/warning:")

    # 回调先完成入队、再由 Streamlit 自然重跑。结果保留在 session state，
    # 用户切换 Tab 后再回来仍能确认任务确实已经创建。
    queued = st.session_state.get('batch_queued')
    if queued:
        kind, payload = queued
        if kind == 'ok':
            task_id, count, *rest = payload
            queued_database = rest[0] if rest else database_name
            if queued_database == database_name:
                st.success(
                    f"批量检索已入队（任务 {task_id[:8]}，{count:,} 张图像）。"
                    "进度见「任务监控」。"
                )
        else:
            if isinstance(payload, tuple):
                message, queued_database = payload
            else:
                message, queued_database = payload, database_name
            if queued_database == database_name:
                st.error(f"入队失败：{message}")

    st.button(
        "加入检索队列",
        type="primary",
        disabled=len(image_paths) == 0,
        icon=":material/playlist_add:",
        key="qs_batch_submit",
        on_click=_enqueue_batch_search,
        args=(
            Path(databases_root),
            database_name,
            tuple(image_paths),
            int(top_n),
            int(batch_size),
            int(num_gpus),
            task_name,
            config_yaml or None,
        ),
    )


def render_query_filter_tab(databases_root: Path, database_name: str) -> None:
    """按标注进度筛选已有 Query，并支持直接进入标注。

    用途是「找出还没人看过的那些」—— 数据集里积累几百条 Query 后，靠翻列表
    找未标注的条目不可行。

    Args:
        databases_root: 数据库根目录
        database_name: 所选数据库名
    """
    st.subheader("按标注进度筛选")

    options = ["all", *AnnotationManager.PROGRESS_FILTERS]

    def _label_of(key: str) -> str:
        if key == "all":
            return "全部"
        return AnnotationManager.PROGRESS_LABELS[key]

    progress = st.selectbox(
        "标注进度",
        options=options,
        format_func=_label_of,
        key="qs_filter_progress",
        help="统计只依据当前结果集内的候选，历史候选不参与",
    )

    try:
        manager = AnnotationManager(databases_root / database_name)
        rows = manager.list_queries_by_progress(
            database_name, None if progress == "all" else progress
        )
    except Exception as exc:
        st.error(f"读取标注库失败：{exc}", icon=":material/error:")
        return

    if not rows:
        # 空结果必须说明「为什么空」，否则用户分不清是筛没了还是页面坏了。
        st.info(
            f"该数据集下没有符合「{_label_of(progress)}」的 Query。",
            icon=":material/filter_alt_off:",
        )
        return

    st.caption(f"共 {len(rows):,} 条")

    for row in rows:
        query_id = row["query_id"]
        cols = st.columns([5, 2, 2, 1.4])

        with cols[0]:
            st.markdown(f"`{Path(row['query_image_path']).name}`")
            st.caption(row["query_image_path"])

        with cols[1]:
            st.markdown(f"候选 {row['labeled']}/{row['total']}")

        with cols[2]:
            st.markdown(f"命中 {row['hits']}")

        with cols[3]:
            # 带上 db 与 query 两个参数，标注页据此定位，无需重新选数据集。
            if st.button(
                "标注",
                key=f"qs_filter_goto_{query_id}",
                width="stretch",
                icon=":material/edit:",
            ):
                activate_workspace_view(
                    st.session_state,
                    ANNOTATION_VIEW,
                    database_name=database_name,
                    query_id=query_id,
                )
                st.rerun()

        st.divider()


def render_search_results(results: dict):
    """Render search results.

    Args:
        results: Search results dictionary
    """
    st.divider()
    st.subheader("搜索结果")

    # Query image info
    st.markdown(f"**查询图像：** `{results['query_image']}`")
    st.caption(f"处理时间：{results['processing_time_ms']:.0f}ms")

    # Exact matches
    exact_matches = results.get('exact_matches', [])
    if exact_matches:
        st.markdown(f"### :material/target: 完全匹配 ({len(exact_matches)})")
        render_candidate_list(exact_matches, "exact")

    # Content matches
    content_matches = results.get('content_matches', [])
    if content_matches:
        st.markdown(f"### :material/description: 内容匹配 ({len(content_matches)})")
        render_candidate_list(content_matches, "content")

    # No matches
    if not exact_matches and not content_matches:
        st.info(":material/search: 本查询未找到匹配项")


def render_candidate_list(candidates: list, match_type: str):
    """Render list of candidate results.

    Args:
        candidates: List of candidate dictionaries
        match_type: Match type ('exact' or 'content')
    """
    for idx, candidate in enumerate(candidates, 1):
        with st.container():
            col1, col2, col3 = st.columns([1, 3, 2])

            with col1:
                st.markdown(f"**排名 {idx}**")
                # 置信度是机器输出，走低饱和信息寄存器。原为 emoji 圆点，
                # 与「命中」的决策绿在颜色上无法区分。
                components.render(
                    components.confidence_chip(candidate['confidence_level'])
                )

            with col2:
                st.markdown(f"**图像：** `{Path(candidate['image_path']).name}`")
                st.caption(f"路径：{candidate['image_path']}")

            with col3:
                st.metric("综合评分", f"{candidate['overall_score']:.3f}")
                if candidate.get('text_score') is not None:
                    st.caption(f"文本：{candidate['text_score']:.3f}")
                if candidate.get('visual_score') is not None:
                    st.caption(f"视觉：{candidate['visual_score']:.3f}")
                if candidate.get('hash_distance') is not None:
                    st.caption(f"哈希距离：{candidate['hash_distance']}")

            st.divider()
