"""索引构建配置的解析。

配置的权威来源是库目录内持久化的文件，而不是任务队列。任务记录会被清理，
索引也可能由 CLI 直接构建，因此按队列有无记录来决定是否展示配置，会在索引
早已建好的库上错报"尚未构建过索引"。
"""

from pathlib import Path
from typing import Optional

import yaml

# _index_config.py -> src/qsearch/webui/ui -> 项目根在 4 层之上
_DEFAULT_FEATURES_PATH = Path(__file__).resolve().parents[4] / "config" / "features.yaml"

# 配置来源标签，用于在页面上说明这份配置是从哪里读出来的。
SOURCE_METADATA = "库元数据（构建时快照）"
SOURCE_DB_CONFIG = "库配置文件 config.yaml"
SOURCE_DEFAULT = "项目默认配置 config/features.yaml"


def resolve_index_config(
    databases_root: Path,
    database_name: str,
    db_info: dict,
) -> tuple[Optional[str], str]:
    """按优先级解析某个库的索引构建配置。

    优先级：库元数据里的构建快照 → 库目录下的 config.yaml → 项目默认配置。
    前两者反映这个库实际使用的配置，最后一个是尚未构建时的预期配置。

    Args:
        databases_root: 数据库根目录
        database_name: 数据库名
        db_info: 库元数据字典

    Returns:
        (config_yaml, source_label)，配置全部缺失时 config_yaml 为 ``None``
    """
    snapshot = db_info.get("config_yaml")

    if snapshot and str(snapshot).strip():
        return str(snapshot), SOURCE_METADATA

    db_config_path = Path(databases_root) / database_name / "config.yaml"

    if db_config_path.exists():
        text = db_config_path.read_text(encoding="utf-8")

        if text.strip():
            return text, SOURCE_DB_CONFIG

    if _DEFAULT_FEATURES_PATH.exists():
        text = _DEFAULT_FEATURES_PATH.read_text(encoding="utf-8")

        if text.strip():
            return text, SOURCE_DEFAULT

    return None, SOURCE_DEFAULT


def summarize_index_section(config_yaml: Optional[str]) -> dict:
    """从配置 YAML 中取出索引相关的关键项，供页面做概览展示。

    Args:
        config_yaml: 配置 YAML 字符串

    Returns:
        形如 ``{"type": "IVFFlat", "nlist": 100, "nprobe": 10}`` 的字典，
        解析失败时返回空字典
    """
    if not config_yaml:
        return {}

    try:
        parsed = yaml.safe_load(config_yaml)
    except yaml.YAMLError:
        return {}

    if not isinstance(parsed, dict):
        return {}

    index_section = parsed.get("index")

    return index_section if isinstance(index_section, dict) else {}
