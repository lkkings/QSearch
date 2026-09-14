"""索引构建配置解析的测试。

回归点：详情页曾经用任务队列有无记录来决定是否展示配置，导致索引早已建好但
队列记录被清理（或索引由 CLI 构建）的库错报"尚未构建过索引"。配置必须从库目
录内持久化的文件解析，与任务记录无关。
"""

import pytest
import yaml

from qsearch.webui.ui import _index_config
from qsearch.webui.ui._index_config import (
    SOURCE_DB_CONFIG,
    SOURCE_DEFAULT,
    SOURCE_METADATA,
    resolve_index_config,
    summarize_index_section,
)

_CONFIG_YAML = yaml.safe_dump({"index": {"type": "IVFFlat", "nlist": 100, "nprobe": 10}})


@pytest.fixture
def databases_root(tmp_path):
    """建立一个含单库目录的数据库根目录。"""
    db_dir = tmp_path / "demo"
    db_dir.mkdir()

    return tmp_path


def test_prefers_metadata_snapshot_over_db_config(databases_root):
    """库元数据中的构建快照优先于库配置文件。"""
    # Arrange
    (databases_root / "demo" / "config.yaml").write_text(
        yaml.safe_dump({"index": {"type": "Flat"}}), encoding="utf-8"
    )
    db_info = {"config_yaml": _CONFIG_YAML}

    # Act
    config_yaml, source = resolve_index_config(databases_root, "demo", db_info)

    # Assert
    assert source == SOURCE_METADATA
    assert summarize_index_section(config_yaml)["type"] == "IVFFlat"


def test_falls_back_to_db_config_when_metadata_has_no_snapshot(databases_root):
    """元数据没有快照时读取库目录下的 config.yaml。"""
    # Arrange
    (databases_root / "demo" / "config.yaml").write_text(_CONFIG_YAML, encoding="utf-8")

    # Act
    config_yaml, source = resolve_index_config(databases_root, "demo", {})

    # Assert
    assert source == SOURCE_DB_CONFIG
    assert summarize_index_section(config_yaml)["nlist"] == 100


def test_falls_back_to_project_default_when_db_has_no_config(databases_root, monkeypatch):
    """库自身没有任何配置时回落到项目默认配置。"""
    # Arrange
    default_path = databases_root / "features.yaml"
    default_path.write_text(_CONFIG_YAML, encoding="utf-8")
    monkeypatch.setattr(_index_config, "_DEFAULT_FEATURES_PATH", default_path)

    # Act
    config_yaml, source = resolve_index_config(databases_root, "demo", {})

    # Assert
    assert source == SOURCE_DEFAULT
    assert summarize_index_section(config_yaml)["nprobe"] == 10


def test_returns_none_when_no_config_available(databases_root, monkeypatch):
    """所有来源都缺失时返回 None，由调用方提示。"""
    # Arrange
    monkeypatch.setattr(
        _index_config, "_DEFAULT_FEATURES_PATH", databases_root / "missing.yaml"
    )

    # Act
    config_yaml, _ = resolve_index_config(databases_root, "demo", {})

    # Assert
    assert config_yaml is None


def test_blank_snapshot_is_ignored(databases_root):
    """空白快照视为缺失，继续向下回落。"""
    # Arrange
    (databases_root / "demo" / "config.yaml").write_text(_CONFIG_YAML, encoding="utf-8")

    # Act
    _, source = resolve_index_config(databases_root, "demo", {"config_yaml": "   \n"})

    # Assert
    assert source == SOURCE_DB_CONFIG


def test_summarize_tolerates_malformed_yaml():
    """配置无法解析时概览返回空字典，不抛异常。"""
    # Arrange
    malformed = "index: [unclosed"

    # Act / Assert
    assert summarize_index_section(malformed) == {}
    assert summarize_index_section(None) == {}
    assert summarize_index_section("just-a-string") == {}
