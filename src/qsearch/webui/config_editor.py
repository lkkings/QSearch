"""索引构建配置编辑器。

提供配置的加载、显示和编辑功能。
"""

import logging
import yaml
from pathlib import Path
from typing import Dict, Optional, Tuple

import streamlit as st

logger = logging.getLogger(__name__)


class ConfigEditor:
    """索引构建配置编辑器。"""

    def __init__(self, config_root: Path):
        """初始化配置编辑器。

        Args:
            config_root: 配置根目录（包含 features.yaml）
        """
        self.config_root = Path(config_root)
        self.features_yaml_path = self.config_root / "features.yaml"

    def load_default_config(self) -> Dict:
        """加载默认配置（features.yaml）。

        Returns:
            配置字典
        """
        if not self.features_yaml_path.exists():
            raise FileNotFoundError(f"默认配置文件不存在：{self.features_yaml_path}")

        with open(self.features_yaml_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    def render_config_form(
        self,
        database_name: str,
        current_config_yaml: Optional[str] = None,
    ) -> Tuple[Optional[Dict], Optional[int], Optional[int]]:
        """渲染配置编辑表单。

        Args:
            database_name: 数据库名称
            current_config_yaml: 当前配置 YAML 字符串（如果有）

        Returns:
            (config_dict, num_workers, num_gpus) 元组
            - config_dict: 配置字典（如果启用了自定义）
            - num_workers: CPU 工作线程数
            - num_gpus: GPU 数量
        """
        st.subheader(":material/tune: 配置索引构建参数")

        # 硬件配置
        st.markdown("**硬件配置**")
        col1, col2 = st.columns(2)

        with col1:
            num_workers = st.number_input(
                "CPU 工作线程数",
                min_value=1,
                max_value=32,
                value=4,
                help="并行处理的进程数。设置为 CPU 核心数的 50-75% 较为合适。"
            )

        with col2:
            num_gpus = st.number_input(
                "GPU 数量",
                min_value=0,
                max_value=8,
                value=0,
                help="使用 GPU 加速。设置为 0 表示仅使用 CPU。"
            )

        st.divider()

        # 配置选择
        st.markdown("**索引配置**")

        use_custom = st.checkbox(
            "使用自定义配置",
            value=bool(current_config_yaml),
            help="启用后可以编辑完整的配置 YAML。不勾选则使用默认配置。"
        )

        config_dict = None

        if use_custom:
            # 自定义配置编辑
            st.info("💡 编辑下方 YAML 来自定义索引构建配置")

            # 提供当前配置或默认配置作为起点
            try:
                if current_config_yaml:
                    default_yaml = current_config_yaml
                else:
                    default_config = self.load_default_config()
                    default_yaml = yaml.dump(default_config, allow_unicode=True, sort_keys=False)
            except Exception:
                default_yaml = ""

            custom_yaml_text = st.text_area(
                "配置 YAML",
                value=default_yaml,
                height=400,
                help="编辑完整的配置 YAML。保存后将应用到索引构建。"
            )

            # 验证 YAML
            try:
                config_dict = yaml.safe_load(custom_yaml_text)
                st.success("✓ YAML 格式有效")

                # 显示关键参数
                with st.expander("关键参数预览", expanded=False):
                    # 索引类型
                    index_type = config_dict.get('index', {}).get('type', 'Flat')
                    st.write(f"- 索引类型：`{index_type}`")

                    # 文本编码模型
                    text_config = config_dict.get('text', {})
                    chinese_model = text_config.get('encoding', {}).get('chinese_model', '未配置')
                    st.write(f"- 中文模型：`{chinese_model}`")

                    # 图像特征模型
                    image_config = config_dict.get('image', {})
                    deep_features = image_config.get('components', {}).get('deep_features', {})
                    if deep_features.get('enabled'):
                        model = deep_features.get('model', '未配置')
                        st.write(f"- 图像模型：`{model}`")

            except yaml.YAMLError as e:
                st.error(f"✗ YAML 格式错误：{e}")
                config_dict = None

        else:
            # 使用默认配置
            st.info("📋 使用默认配置 (`config/features.yaml`)")

            # 显示默认配置概览
            with st.expander("查看默认配置", expanded=False):
                try:
                    default_config = self.load_default_config()

                    # 显示关键参数
                    st.markdown("**关键参数**")

                    # 索引类型
                    index_type = default_config.get('index', {}).get('type', 'Flat')
                    st.write(f"- 索引类型：`{index_type}`")

                    # 文本编码模型
                    text_config = default_config.get('text', {})
                    chinese_model = text_config.get('encoding', {}).get('chinese_model', '未配置')
                    st.write(f"- 中文模型：`{chinese_model}`")

                    # 图像特征模型
                    image_config = default_config.get('image', {})
                    deep_features = image_config.get('components', {}).get('deep_features', {})
                    if deep_features.get('enabled'):
                        model = deep_features.get('model', '未配置')
                        st.write(f"- 图像模型：`{model}`")

                    # 完整配置 YAML
                    st.divider()
                    st.markdown("**完整配置**")
                    st.code(yaml.dump(default_config, allow_unicode=True, sort_keys=False), language="yaml")

                except Exception as e:
                    st.error(f"无法加载配置：{e}")

        st.divider()

        # 返回配置
        return config_dict, int(num_workers), int(num_gpus)

    def display_task_config(self, task: Dict) -> None:
        """显示任务的配置信息（只读）。

        Args:
            task: 任务字典
        """
        st.markdown("**硬件配置**")

        config_col1, config_col2 = st.columns(2)

        with config_col1:
            num_workers = task.get('num_workers')
            st.metric("CPU 工作线程", num_workers if num_workers else "自动")

        with config_col2:
            num_gpus = task.get('num_gpus', 0)
            st.metric("GPU 数量", num_gpus)

        st.divider()

        # 显示配置
        st.markdown("**索引配置**")

        config_yaml = task.get('config_yaml')

        if config_yaml:
            st.info("使用自定义配置")

            with st.expander("查看完整配置 YAML", expanded=False):
                st.code(config_yaml, language="yaml")
        else:
            st.info("使用默认配置 (`config/features.yaml`)")

        # 显示任务元信息
        st.divider()
        st.markdown("**任务信息**")

        detail_col1, detail_col2 = st.columns(2)

        with detail_col1:
            st.write(f"- 任务ID：`{task['task_id'][:8]}`")
            st.write(f"- 状态：{task['status']}")
            st.write(f"- 创建时间：{task['created_at'][:19]}")

        with detail_col2:
            if task.get('started_at'):
                st.write(f"- 开始时间：{task['started_at'][:19]}")
            if task.get('completed_at'):
                st.write(f"- 完成时间：{task['completed_at'][:19]}")
            if task.get('stage'):
                st.write(f"- 当前阶段：{task['stage']}")

