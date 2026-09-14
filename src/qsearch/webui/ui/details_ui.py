"""数据集详情页 UI 组件。"""

import os
import streamlit as st
from pathlib import Path

from qsearch.webui.workspace_state import (
    ANNOTATION_VIEW,
    HOME_VIEW,
    SEARCH_VIEW,
    activate_workspace_view,
)


def _is_indexed(db_info: dict) -> bool:
    """该库是否已建索引。

    Args:
        db_info: 数据库元数据字典

    Returns:
        元数据 index_built 为真时返回 True
    """
    return bool(db_info.get("index_built"))


def _indexed_image_counts(db_info: dict) -> tuple[int, int]:
    """索引中成功与失败的图像数。

    builder 的 features_extracted 统计的是"尝试过的图像"，其中含提取失败的条目，
    因此成功数需要减去 features_failed。

    Args:
        db_info: 数据库元数据字典

    Returns:
        (成功建立索引的图像数, 提取失败的图像数)
    """
    index_stats = db_info.get("index_stats") or {}
    attempted = int(index_stats.get("features_extracted", 0) or 0)
    failed = int(index_stats.get("features_failed", 0) or 0)

    return max(attempted - failed, 0), failed


def render_details_page(databases_root: Path, selected_db: str):
    """渲染数据集详情页。

    Args:
        databases_root: 数据库根目录
        selected_db: 选中的数据库名
    """
    from qsearch.webui.database_manager import DatabaseManager

    st.title(f":material/analytics: 数据集详情：{selected_db}")

    db_manager = DatabaseManager(databases_root)

    try:
        databases = db_manager.list_databases()
        db_info = next((db for db in databases if db['name'] == selected_db), None)

        if not db_info:
            st.error("无法加载数据库信息")
            return

        # 显示基本信息
        image_count = db_info.get('image_count', 0)
        indexed_count, failed_count = _indexed_image_counts(db_info)

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric("图像数量", image_count)

        with col2:
            st.metric(
                "已索引图像",
                f"{indexed_count} / {image_count}" if image_count else indexed_count,
                delta=f"-{failed_count} 失败" if failed_count else None,
                delta_color="inverse",
                help="特征提取成功并写入索引的图像数；失败的图像无法被检索到",
            )

        with col3:
            index_status = "已索引" if _is_indexed(db_info) else "未索引"
            st.metric("索引状态", index_status)

        with col4:
            stats = db_info.get('statistics', {})
            hit_rate = stats.get('hit_rate', 0)
            st.metric("命中率", f"{hit_rate:.1f}%")

        st.divider()

        # 统计信息
        st.subheader(":material/trending_up: 统计信息")

        col1, col2 = st.columns(2)

        with col1:
            st.write("**查询统计**")
            st.write(f"- 总查询数：{stats.get('total_queries', 0)}")
            st.write(f"- 已标注查询：{stats.get('labeled_queries', 0)}")
            st.write(f"- 部分标注：{stats.get('partial_queries', 0)}")

        with col2:
            st.write("**候选统计**")
            st.write(f"- 总候选数：{stats.get('total_candidates', 0)}")
            st.write(f"- 命中数：{stats.get('hits', 0)}")
            st.write(f"- 未命中数：{stats.get('misses', 0)}")

        st.divider()

        # 操作区域
        st.subheader(":material/settings: 数据集操作")

        col1, col2, col3 = st.columns(3)

        with col1:
            if st.button("搜索", icon=":material/search:", width="stretch"):
                activate_workspace_view(st.session_state, SEARCH_VIEW)
                st.rerun()

        with col2:
            if st.button("标注", icon=":material/edit:", width="stretch"):
                activate_workspace_view(st.session_state, ANNOTATION_VIEW)
                st.rerun()

        with col3:
            if st.button("关闭详情", icon=":material/close:", width="stretch"):
                activate_workspace_view(st.session_state, HOME_VIEW)
                st.rerun()

        st.divider()

        # 索引构建配置
        st.subheader(":material/settings: 索引构建配置")

        from qsearch.webui.ui._index_config import (
            SOURCE_DEFAULT,
            resolve_index_config,
            summarize_index_section,
        )

        config_yaml, config_source = resolve_index_config(
            databases_root, selected_db, db_info
        )

        if config_yaml:
            if config_source == SOURCE_DEFAULT and not _is_indexed(db_info):
                st.caption(f"该库尚未建立索引，以下为将要使用的配置（来源：{config_source}）")
            else:
                st.caption(f"配置来源：{config_source}")

            index_section = summarize_index_section(config_yaml)

            summary_col1, summary_col2, summary_col3 = st.columns(3)

            with summary_col1:
                st.metric("索引类型", index_section.get("type") or "默认")

            with summary_col2:
                st.metric("nlist", index_section.get("nlist", "默认"))

            with summary_col3:
                st.metric("nprobe", index_section.get("nprobe", "默认"))

            with st.expander("查看完整配置 YAML", expanded=False):
                st.code(config_yaml, language="yaml")
        else:
            st.warning("未找到任何索引配置（库配置与项目默认配置均不可用）")

        # 任务队列只用来补充构建时的硬件参数与任务元信息。队列记录可能已被清理，
        # 或索引由 CLI 直接构建，这些情况下配置本身仍然照常展示。
        try:
            from qsearch.tasks.queue import TaskQueue, TaskKind
            queue = TaskQueue(databases_root / ".tasks")

            tasks = queue.list_tasks(
                database_name=selected_db,
                kind=TaskKind.INDEX_BUILD,
                limit=1
            )
        except Exception as e:
            tasks = []
            st.caption(f"无法读取构建任务记录：{e}")

        if tasks:
            task = tasks[0]

            with st.expander("最近一次构建任务", expanded=False):
                hw_col1, hw_col2, hw_col3 = st.columns(3)

                with hw_col1:
                    st.metric("CPU 工作线程", task.get('num_workers') or "自动")

                with hw_col2:
                    st.metric("GPU 数量", task.get('num_gpus', 0))

                with hw_col3:
                    st.metric("任务状态", task.get('status') or "未知")

                detail_col1, detail_col2 = st.columns(2)

                with detail_col1:
                    st.write(f"- 任务ID：`{task['task_id'][:8]}`")
                    st.write(f"- 创建时间：{task['created_at'][:19]}")

                with detail_col2:
                    if task.get('started_at'):
                        st.write(f"- 开始时间：{task['started_at'][:19]}")
                    if task.get('completed_at'):
                        st.write(f"- 完成时间：{task['completed_at'][:19]}")
                    if task.get('stage'):
                        st.write(f"- 当前阶段：{task['stage']}")
        else:
            st.caption("无构建任务记录（索引可能由命令行构建，或记录已被清理）")

        st.divider()

        # 索引管理
        st.subheader(":material/inventory_2: 索引管理")

        if _is_indexed(db_info):
            st.success("索引已建立")

            if st.button(
                "重建索引", icon=":material/refresh:", width="stretch"
            ):
                try:
                    from qsearch.webui.task_manager import TaskManager
                    task_manager = TaskManager(databases_root)

                    task_id = task_manager.enqueue_index_build(
                        database_name=selected_db,
                        task_name=f"重建索引：{selected_db}"
                    )

                    st.success(f"索引重建任务已入队：{task_id[:8]}")
                    st.info("可在主页「任务监控」标签查看进度")

                except Exception as e:
                    st.error(f"入队失败：{e}")
        else:
            st.warning("索引未建立")

            if st.button(
                "建立索引",
                icon=":material/build:",
                type="primary",
                width="stretch",
            ):
                try:
                    from qsearch.webui.task_manager import TaskManager
                    task_manager = TaskManager(databases_root)

                    task_id = task_manager.enqueue_index_build(
                        database_name=selected_db,
                        task_name=f"建立索引：{selected_db}"
                    )

                    st.success(f"索引构建任务已入队：{task_id[:8]}")
                    st.info("可在主页「任务监控」标签查看进度")

                except Exception as e:
                    st.error(f"入队失败：{e}")

        st.divider()

        # 删除数据集
        st.subheader(":material/warning: 危险操作")

        db_path = databases_root / selected_db

        with st.expander("删除数据集", expanded=False):
            st.warning(
                f"**删除后将无法恢复！**\n\n"
                f"将被删除的内容：\n"
                f"- 数据库目录：`{db_path}`\n"
                f"- {db_info.get('image_count', 0)} 张图像\n"
                f"- 索引文件（如果存在）\n"
                f"- {stats.get('total_queries', 0)} 个查询记录\n"
                f"- {stats.get('total_candidates', 0)} 个标注记录"
            )

            confirm_text = st.text_input(
                f"输入数据库名称 `{selected_db}` 确认删除：",
                key="delete_confirm"
            )

            if st.button(
                "确认删除",
                icon=":material/delete:",
                type="primary",
                disabled=(confirm_text != selected_db),
            ):
                try:
                    import shutil

                    if not db_path.exists():
                        st.error(f"数据库目录不存在：{db_path}")
                    elif not os.access(db_path, os.W_OK):
                        st.error(f"没有删除权限：{db_path}")
                    else:
                        shutil.rmtree(db_path)
                        st.success(f"数据库 `{selected_db}` 已删除")
                        st.session_state["selected_database"] = None
                        activate_workspace_view(st.session_state, HOME_VIEW)
                        st.session_state["search_results"] = None
                        st.session_state["search_results_database"] = None
                        st.rerun()

                except PermissionError:
                    st.error("删除失败：没有足够的权限删除该目录")
                    st.info(f"数据集 `{selected_db}` 仍然存在")
                except OSError as e:
                    st.error(f"删除失败：{e}")
                    st.info(f"数据集 `{selected_db}` 仍然存在")
                except Exception as e:
                    st.error(f"删除失败：{e}")
                    st.info(f"数据集 `{selected_db}` 仍然存在")

    except Exception as e:
        st.error(f"加载数据库信息失败：{e}")
        if st.button("关闭详情"):
            activate_workspace_view(st.session_state, HOME_VIEW)
            st.rerun()
