"""检索参数配置 UI。"""

import streamlit as st
import yaml
from pathlib import Path
from typing import Dict, List, Any

from qsearch.webui import search_params


def render_search_params_panel(
    databases_root: Path,
    database_name: str,
    key_prefix: str = "sp",
) -> tuple[Dict[str, Any], str]:
    """渲染检索参数配置面板（折叠）。

    Args:
        databases_root: 数据库根目录
        database_name: 数据库名
        key_prefix: Streamlit 控件 key 的前缀，避免同页多实例冲突

    Returns:
        元组 ``(values, config_yaml)``。``values`` 是各参数的当前值字典，
        键为 ``spec.key``；``config_yaml`` 是序列化后的 YAML 字符串，
        可直接传给任务队列的 ``config_yaml`` 参数。
    """
    build_config = search_params.load_build_config(databases_root, database_name)
    specs = search_params.build_param_specs(build_config)

    if not specs:
        st.info(
            "该库无可调的检索参数（可能索引尚未构建，或配置文件无法读取）",
            icon=":material/tune:",
        )
        return {}, ""

    with st.expander(":material/tune: 检索参数", expanded=False):
        st.caption(
            "根据该库的构建配置动态生成。查询时才会改变结果的项在此可调，"
            "索引结构与特征模型一经构建即已固定，因此不在其中。"
        )

        values: Dict[str, Any] = {}
        groups = _group_specs(specs)

        for group_label, group_specs in groups.items():
            st.markdown(f"**{group_label}**")
            cols = st.columns(min(len(group_specs), 3))

            for i, spec in enumerate(group_specs):
                col = cols[i % len(cols)]

                with col:
                    val = _render_param(spec, key_prefix)
                    values[spec.key] = val

                    if spec.note:
                        st.caption(spec.note)

            st.divider()

        # 导出为 YAML
        config_dict = search_params.build_search_config(specs, values)
        config_yaml = yaml.safe_dump(
            config_dict, allow_unicode=True, default_flow_style=False
        )

        with st.expander("配置预览 (YAML)", expanded=False):
            st.code(config_yaml, language="yaml")

    return values, config_yaml


def _group_specs(specs: List[search_params.ParamSpec]) -> Dict[str, List]:
    """按 group 分组。

    Args:
        specs: 参数规格列表

    Returns:
        ``{group_label: [spec, ...]`` 字典，保持原顺序
    """
    groups: Dict[str, List] = {}

    for spec in specs:
        if spec.group not in groups:
            groups[spec.group] = []
        groups[spec.group].append(spec)

    return groups


def _render_param(spec: search_params.ParamSpec, key_prefix: str) -> Any:
    """渲染一个参数控件。

    Args:
        spec: 参数规格
        key_prefix: key 前缀

    Returns:
        用户填值
    """
    key = f"{key_prefix}_{spec.key}"

    if spec.kind == "bool":
        return st.checkbox(
            spec.label,
            value=bool(spec.default),
            help=spec.help,
            key=key,
        )

    if spec.kind == "int":
        return st.number_input(
            spec.label,
            value=int(spec.default),
            min_value=int(spec.min_value) if spec.min_value is not None else None,
            max_value=int(spec.max_value) if spec.max_value is not None else None,
            step=int(spec.step) if spec.step else 1,
            help=spec.help,
            key=key,
        )

    if spec.kind == "float":
        return st.number_input(
            spec.label,
            value=float(spec.default),
            min_value=float(spec.min_value) if spec.min_value is not None else None,
            max_value=float(spec.max_value) if spec.max_value is not None else None,
            step=float(spec.step) if spec.step else 0.01,
            format="%.2f",
            help=spec.help,
            key=key,
        )

    return spec.default
