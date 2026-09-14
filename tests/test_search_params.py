"""检索参数派生与配置构建的测试。"""

import yaml
import pytest

from qsearch.webui import search_params


@pytest.fixture
def flat_build_config() -> dict:
    """Flat 索引 + 感知哈希开启的库配置。"""
    return {
        "image": {
            "components": {
                "perceptual_hash": {"enabled": True, "hash_size": 16},
            }
        },
        "index": {"type": "Flat"},
    }


@pytest.fixture
def ivf_build_config() -> dict:
    """IVFFlat 索引的库配置。"""
    return {
        "image": {
            "components": {
                "perceptual_hash": {"enabled": True, "hash_size": 8},
            }
        },
        "index": {"type": "IVFFlat", "nlist": 256, "nprobe": 16},
    }


def _keys(specs) -> set:
    """取参数 key 集合。"""
    return {spec.key for spec in specs}


def test_flat_index_exposes_no_index_params(flat_build_config):
    # Arrange / Act
    specs = search_params.build_param_specs(flat_build_config)

    # Assert
    assert "nprobe" not in _keys(specs)
    assert "ef_search" not in _keys(specs)


def test_ivf_index_exposes_nprobe_bounded_by_nlist(ivf_build_config):
    # Arrange / Act
    specs = search_params.build_param_specs(ivf_build_config)
    nprobe = next(s for s in specs if s.key == "nprobe")

    # Assert
    assert nprobe.default == 16
    assert nprobe.max_value == 256


def test_hnsw_index_exposes_ef_search():
    # Arrange
    config = {"index": {"type": "HNSW", "ef_search": 64}}

    # Act
    specs = search_params.build_param_specs(config)
    ef = next(s for s in specs if s.key == "ef_search")

    # Assert
    assert ef.default == 64
    assert "nprobe" not in _keys(specs)


def test_disabled_perceptual_hash_drops_exact_match_params():
    # Arrange
    config = {
        "image": {"components": {"perceptual_hash": {"enabled": False}}},
        "index": {"type": "Flat"},
    }

    # Act
    specs = search_params.build_param_specs(config)

    # Assert
    assert "exact_enabled" not in _keys(specs)
    assert "hash_max_distance" not in _keys(specs)


def test_hash_distance_upper_bound_follows_hash_size(ivf_build_config):
    # Arrange: hash_size=8 -> 64 位
    # Act
    specs = search_params.build_param_specs(ivf_build_config)
    dist = next(s for s in specs if s.key == "hash_max_distance")

    # Assert
    assert dist.max_value == 64
    assert "hash_size=8" in dist.note


def test_defaults_come_from_database_matching_config(flat_build_config):
    # Arrange: 库里写了非默认的阈值
    flat_build_config["matching"] = {
        "content_match": {
            "stage1": {"text_similarity_threshold": 0.6, "top_k": 50},
            "scoring": {"threshold": 0.7},
        },
        "output": {"top_k": 5},
    }

    # Act
    specs = search_params.build_param_specs(flat_build_config)
    by_key = {s.key: s for s in specs}

    # Assert
    assert by_key["stage1_threshold"].default == 0.6
    assert by_key["stage1_top_k"].default == 50
    assert by_key["final_threshold"].default == 0.7
    assert by_key["top_n"].default == 5


def test_every_spec_carries_a_description(flat_build_config):
    # Arrange / Act
    specs = search_params.build_param_specs(flat_build_config)

    # Assert
    assert specs
    for spec in specs:
        assert spec.help.strip(), f"{spec.key} 缺少参数描述"


def test_build_search_config_nests_values_by_config_path(flat_build_config):
    # Arrange
    specs = search_params.build_param_specs(flat_build_config)
    values = {
        "top_n": 8,
        "exact_enabled": False,
        "hash_max_distance": 3,
        "content_enabled": True,
        "stage1_threshold": 0.55,
        "stage1_top_k": 200,
        "final_threshold": 0.65,
    }

    # Act
    config = search_params.build_search_config(specs, values)

    # Assert
    assert config["matching"]["output"]["top_k"] == 8
    assert config["matching"]["exact_match"]["enabled"] is False
    assert (
        config["matching"]["exact_match"]["criteria"]["perceptual_hash"]["max_distance"]
        == 3
    )
    assert config["matching"]["content_match"]["stage1"]["top_k"] == 200
    assert config["matching"]["content_match"]["scoring"]["threshold"] == 0.65


def test_build_search_config_is_yaml_round_trippable(ivf_build_config):
    # Arrange
    specs = search_params.build_param_specs(ivf_build_config)
    values = {spec.key: spec.default for spec in specs}

    # Act
    config = search_params.build_search_config(specs, values)
    restored = yaml.safe_load(yaml.safe_dump(config, allow_unicode=True))

    # Assert
    assert restored == config
    assert restored["index"]["nprobe"] == 16


def test_build_search_config_skips_missing_values(flat_build_config):
    # Arrange
    specs = search_params.build_param_specs(flat_build_config)

    # Act: 只给一个值
    config = search_params.build_search_config(specs, {"top_n": 12})

    # Assert
    assert config == {"matching": {"output": {"top_k": 12}}}


def test_load_build_config_returns_empty_dict_when_missing(tmp_path):
    # Arrange / Act
    config = search_params.load_build_config(tmp_path, "no_such_db")

    # Assert
    assert config == {}


def test_load_build_config_reads_database_yaml(tmp_path):
    # Arrange
    db_dir = tmp_path / "demo"
    db_dir.mkdir()
    (db_dir / "config.yaml").write_text(
        yaml.safe_dump({"index": {"type": "HNSW"}}), encoding="utf-8"
    )

    # Act
    config = search_params.load_build_config(tmp_path, "demo")

    # Assert
    assert config["index"]["type"] == "HNSW"
