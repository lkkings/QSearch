"""搜索面板组件 - 集成在主界面的可折叠搜索区域。"""

from pathlib import Path
import uuid
import tempfile

import streamlit as st

from qsearch.webui.database_manager import DatabaseManager
from qsearch.webui.task_manager import TaskManager
from qsearch.webui.ui import search_params_ui


def _materialize_query_image(query_image) -> str:
    """将查询图输入转成 worker 进程可解析的路径或 URL。

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


def _is_indexed(databases_root: Path, database_name: str) -> bool:
    """检查数据库是否已建索引。

    Args:
        databases_root: 数据库根目录
        database_name: 数据库名

    Returns:
        已建索引为 True
    """
    try:
        info = DatabaseManager(databases_root).get_database_info(database_name)
    except Exception:
        return False

    return bool(info.get("index_built"))


def render_search_panel(
    databases_root: Path,
    database_name: str,
    expanded: bool = True
) -> None:
    """渲染搜索面板组件。

    Args:
        databases_root: 数据库根目录
        database_name: 当前选择的数据库名
        expanded: 是否默认展开

    Task state is written to ``st.session_state`` so the polling fragment can
    survive Streamlit reruns.
    """
    with st.expander("🔍 搜索配置", expanded=expanded):
        # 输入模式选择
        input_mode = st.radio(
            "输入方式",
            options=["upload", "path", "url"],
            format_func=lambda x: {
                "upload": "📤 上传图像",
                "path": "📁 本地路径",
                "url": "🔗 图像 URL",
            }[x],
            horizontal=True,
            key="search_panel_input_mode"
        )

        query_image = None

        # 输入区域
        if input_mode == "upload":
            uploaded_file = st.file_uploader(
                "上传查询图像",
                type=['jpg', 'jpeg', 'png', 'bmp'],
                key="search_panel_upload"
            )
            if uploaded_file:
                query_image = uploaded_file
                # 预览
                col1, col2 = st.columns([1, 3])
                with col1:
                    st.image(uploaded_file, caption="查询图像", width="stretch")

        elif input_mode == "path":
            image_path = st.text_input(
                "图像文件路径",
                key="search_panel_path"
            )
            if image_path:
                path_obj = Path(image_path)
                if path_obj.exists():
                    query_image = image_path
                    # 预览
                    col1, col2 = st.columns([1, 3])
                    with col1:
                        st.image(str(path_obj), caption="查询图像", width="stretch")
                else:
                    st.error("❌ 文件不存在")

        elif input_mode == "url":
            image_url = st.text_input(
                "图像 URL",
                key="search_panel_url"
            )
            if image_url:
                query_image = image_url
                # 预览
                try:
                    col1, col2 = st.columns([1, 3])
                    with col1:
                        st.image(image_url, caption="查询图像", width="stretch")
                except Exception:
                    st.warning("⚠️ 无法预览图像")

        # 检索参数配置
        st.divider()
        st.markdown("#### ⚙️ 检索参数")

        param_values, config_yaml = search_params_ui.render_search_params_panel(
            databases_root=databases_root,
            database_name=database_name,
            key_prefix="search_panel",
        )

        top_n = param_values.get("top_n", 10)

        # 检查索引状态
        indexed = _is_indexed(databases_root, database_name)
        if not indexed:
            st.warning(
                "⚠️ 该数据集尚未构建索引，暂不能检索。可在「数据库管理」触发构建。",
                icon="🔨"
            )

        submit_disabled = (query_image is None) or (not indexed)

        # 搜索按钮
        col1, col2, col3 = st.columns([1, 1, 2])
        with col1:
            search_clicked = st.button(
                "🔍 开始搜索",
                type="primary",
                disabled=submit_disabled,
                width="stretch",
                key="search_panel_submit"
            )

        with col2:
            if st.button(
                "🔄 重置",
                width="stretch",
                key="search_panel_reset"
            ):
                # 清除搜索相关状态
                for key in list(st.session_state.keys()):
                    if key.startswith('search_panel_'):
                        del st.session_state[key]
                st.rerun()

        # 处理搜索提交
        if search_clicked:
            try:
                query_path = _materialize_query_image(query_image)

                task_manager = TaskManager(databases_root)
                task_id = task_manager.enqueue_interactive_search(
                    database_name=database_name,
                    query_image_path=query_path,
                    top_n=top_n,
                    config_yaml=config_yaml or None,
                )

                # 保存到 session state
                st.session_state['qs_ia_task_id'] = task_id
                st.session_state['qs_ia_task_db'] = database_name
                st.session_state['qs_ia_outcome'] = None
                st.session_state['search_results'] = None
                st.session_state['search_results_database'] = None

                st.success(f"✅ 搜索任务已提交（ID: {task_id[:8]}...）")
                st.rerun()

            except Exception as exc:
                st.error(f"❌ 提交查询失败：{exc}")
