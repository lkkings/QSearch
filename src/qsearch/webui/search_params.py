"""检索参数：由数据库的构建配置派生出查询时可调的参数。

索引建好之后，查询时还能改变的只有两件事：匹配判定的阈值，以及向量索引的
查询行为。特征提取模型、哈希算法、索引结构都由构建时的配置固定，改了也不会
对已有索引生效，因此这里一律不暴露。

参数集是**按库派生**的，不是固定清单：没开感知哈希的库没有精确匹配阈值，
Flat 索引没有 nprobe。派生逻辑集中在 :func:`build_param_specs`。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# 与 matchers.py 内的兜底值保持一致 —— 库配置里没写 matching 时，UI 显示的
# 默认值必须就是实际生效的那个，否则面板会撒谎。
DEFAULT_TOP_N = 10
DEFAULT_HASH_MAX_DISTANCE = 5
DEFAULT_TEXT_THRESHOLD = 0.75
DEFAULT_STAGE1_TOP_K = 100
DEFAULT_FINAL_THRESHOLD = 0.85
DEFAULT_NPROBE = 10
DEFAULT_EF_SEARCH = 32

#: search_single 对 top_n 的硬校验区间
TOP_N_RANGE = (1, 20)

GROUP_OUTPUT = "输出"
GROUP_EXACT = "精确匹配"
GROUP_CONTENT = "内容匹配"
GROUP_INDEX = "向量索引查询"


@dataclass(frozen=True)
class ParamSpec:
    """一个查询时可调参数的声明。

    Attributes:
        key: 稳定标识，同时用作 session_state key 后缀
        label: 控件标签
        group: 所属分组，用于 UI 分栏
        kind: ``'int'`` | ``'float'`` | ``'bool'``
        default: 当前生效值（已从库配置读出，不是写死的出厂值）
        help: 参数描述，说明调大调小的后果
        min_value: 下界，bool 无此项
        max_value: 上界，bool 无此项
        step: 步进，bool 无此项
        config_path: 写回配置时的嵌套路径，如 ``('matching', 'output', 'top_k')``
        note: 附加说明，例如上界来自库的构建参数
    """

    key: str
    label: str
    group: str
    kind: str
    default: Any
    help: str
    config_path: tuple
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    step: Optional[float] = None
    note: Optional[str] = None


def load_build_config(databases_root: Path, database_name: str) -> Dict[str, Any]:
    """读取某个库的构建配置。

    Args:
        databases_root: 数据库根目录
        database_name: 数据库名

    Returns:
        配置字典；文件缺失或不可解析时返回空字典
    """
    config_path = Path(databases_root) / database_name / "config.yaml"

    if not config_path.exists():
        return {}

    try:
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}

    return loaded if isinstance(loaded, dict) else {}


def _dig(config: Dict[str, Any], path: tuple, fallback: Any) -> Any:
    """按嵌套路径取值。

    Args:
        config: 配置字典
        path: 键路径
        fallback: 缺失时的返回值

    Returns:
        路径对应的值；任一层缺失或类型不符时返回 ``fallback``
    """
    node: Any = config

    for key in path:
        if not isinstance(node, dict) or key not in node:
            return fallback
        node = node[key]

    return fallback if node is None else node


def build_param_specs(build_config: Dict[str, Any]) -> List[ParamSpec]:
    """从库的构建配置派生出可调的检索参数。

    只包含查询时真正会改变结果的项。索引结构、特征模型、哈希算法一经构建即已
    固定，因此不在其中；相应地，构建时关闭的能力也不会出现对应参数。

    Args:
        build_config: 该库 config.yaml 的内容

    Returns:
        参数声明列表，按分组顺序排列
    """
    matching = build_config.get("matching") or {}
    image_components = _dig(build_config, ("image", "components"), {}) or {}
    index_config = build_config.get("index") or {}

    specs: List[ParamSpec] = [
        ParamSpec(
            key="top_n",
            label="返回结果数 (Top-N)",
            group=GROUP_OUTPUT,
            kind="int",
            default=int(_dig(matching, ("output", "top_k"), DEFAULT_TOP_N)),
            min_value=TOP_N_RANGE[0],
            max_value=TOP_N_RANGE[1],
            step=1,
            config_path=("matching", "output", "top_k"),
            help=(
                "每次查询返回的候选上限，精确匹配与内容匹配合并去重后截断。"
                "调大能看到更多边缘候选，标注工作量也随之增加。"
            ),
        ),
    ]

    specs.extend(_exact_specs(matching, image_components))
    specs.extend(_content_specs(matching))
    specs.extend(_index_specs(index_config))

    return specs


def _exact_specs(
    matching: Dict[str, Any], image_components: Dict[str, Any]
) -> List[ParamSpec]:
    """派生精确匹配相关参数。

    构建时未开启感知哈希的库没有哈希索引，精确匹配无从进行，此时返回空列表。

    Args:
        matching: 库配置里的 matching 段
        image_components: 库配置里的 image.components 段

    Returns:
        参数声明列表
    """
    hash_component = image_components.get("perceptual_hash") or {}

    if not hash_component.get("enabled", True):
        return []

    # 哈希位数 = hash_size²，它决定汉明距离的实际取值范围。用 16 兜底与
    # features.yaml 的默认一致。
    hash_size = int(hash_component.get("hash_size", 16) or 16)
    max_bits = hash_size * hash_size

    return [
        ParamSpec(
            key="exact_enabled",
            label="启用精确匹配",
            group=GROUP_EXACT,
            kind="bool",
            default=bool(_dig(matching, ("exact_match", "enabled"), True)),
            config_path=("matching", "exact_match", "enabled"),
            help=(
                "通过感知哈希找出与查询图几乎逐像素相同的图。关闭后只做内容匹配，"
                "适合查询图是重新拍摄或重新排版的场景。"
            ),
        ),
        ParamSpec(
            key="hash_max_distance",
            label="哈希汉明距离上限",
            group=GROUP_EXACT,
            kind="int",
            default=int(
                _dig(
                    matching,
                    ("exact_match", "criteria", "perceptual_hash", "max_distance"),
                    DEFAULT_HASH_MAX_DISTANCE,
                )
            ),
            min_value=0,
            max_value=max_bits,
            step=1,
            config_path=(
                "matching", "exact_match", "criteria", "perceptual_hash", "max_distance",
            ),
            note=f"该库 hash_size={hash_size}，哈希共 {max_bits} 位",
            help=(
                "两张图哈希值允许相差的位数。0 表示要求哈希完全相同；调大可容忍"
                "轻微裁剪或压缩，但过大会把版式相似的不同题也算作同一张。"
            ),
        ),
    ]


def _content_specs(matching: Dict[str, Any]) -> List[ParamSpec]:
    """派生内容匹配相关参数。

    Args:
        matching: 库配置里的 matching 段

    Returns:
        参数声明列表
    """
    return [
        ParamSpec(
            key="content_enabled",
            label="启用内容匹配",
            group=GROUP_CONTENT,
            kind="bool",
            default=bool(_dig(matching, ("content_match", "enabled"), True)),
            config_path=("matching", "content_match", "enabled"),
            help=(
                "基于 OCR 文本的语义向量检索改写题、换序题。关闭后只保留精确匹配，"
                "查询会明显变快但召回大幅下降。"
            ),
        ),
        ParamSpec(
            key="stage1_threshold",
            label="一阶段向量相似度下限",
            group=GROUP_CONTENT,
            kind="float",
            default=float(
                _dig(
                    matching,
                    ("content_match", "stage1", "text_similarity_threshold"),
                    DEFAULT_TEXT_THRESHOLD,
                )
            ),
            min_value=0.0,
            max_value=1.0,
            step=0.01,
            config_path=("matching", "content_match", "stage1", "text_similarity_threshold"),
            help=(
                "向量召回阶段的余弦相似度门槛，低于此值的候选直接丢弃，不进入二阶段。"
                "调低召回更多但二阶段计算量上升；调高可能漏掉改写幅度较大的题。"
            ),
        ),
        ParamSpec(
            key="stage1_top_k",
            label="一阶段候选数 (top_k)",
            group=GROUP_CONTENT,
            kind="int",
            default=int(
                _dig(matching, ("content_match", "stage1", "top_k"), DEFAULT_STAGE1_TOP_K)
            ),
            min_value=1,
            max_value=1000,
            step=10,
            config_path=("matching", "content_match", "stage1", "top_k"),
            help=(
                "向量检索取回多少个候选交给二阶段做文本校验。应明显大于返回结果数，"
                "否则真正的匹配可能在召回阶段就被截掉。"
            ),
        ),
        ParamSpec(
            key="final_threshold",
            label="综合评分下限",
            group=GROUP_CONTENT,
            kind="float",
            default=float(
                _dig(
                    matching,
                    ("content_match", "scoring", "threshold"),
                    DEFAULT_FINAL_THRESHOLD,
                )
            ),
            min_value=0.0,
            max_value=1.0,
            step=0.01,
            config_path=("matching", "content_match", "scoring", "threshold"),
            help=(
                "二阶段综合评分（0.7×向量相似度 + 0.3×文本编辑距离相似度）的入选门槛。"
                "这是决定内容匹配严格程度的主要开关：查不到结果时先降这个值。"
            ),
        ),
    ]


def _index_specs(index_config: Dict[str, Any]) -> List[ParamSpec]:
    """派生向量索引的查询期参数。

    索引类型在构建时已固定，各类型只有自己的查询参数可调：Flat 是穷举检索，
    没有任何可调项；IVF 系可调 nprobe；HNSW 可调 efSearch。

    Args:
        index_config: 库配置里的 index 段

    Returns:
        参数声明列表；Flat 索引返回空列表
    """
    index_type = str(index_config.get("type", "Flat"))

    if index_type in ("IVFFlat", "IVFPQ"):
        nlist = int(index_config.get("nlist", 100) or 100)
        return [
            ParamSpec(
                key="nprobe",
                label="检索单元数 (nprobe)",
                group=GROUP_INDEX,
                kind="int",
                default=int(index_config.get("nprobe", DEFAULT_NPROBE) or DEFAULT_NPROBE),
                min_value=1,
                max_value=nlist,
                step=1,
                config_path=("index", "nprobe"),
                note=f"该库为 {index_type} 索引，nlist={nlist}",
                help=(
                    "每次查询访问的倒排单元数。调大召回更完整但更慢；等于 nlist 时"
                    "退化为全库穷举，精度最高。只影响本次查询，不改动索引文件。"
                ),
            ),
        ]

    if index_type == "HNSW":
        return [
            ParamSpec(
                key="ef_search",
                label="查询候选数 (efSearch)",
                group=GROUP_INDEX,
                kind="int",
                default=int(
                    index_config.get("ef_search", DEFAULT_EF_SEARCH) or DEFAULT_EF_SEARCH
                ),
                min_value=1,
                max_value=512,
                step=8,
                config_path=("index", "ef_search"),
                note="该库为 HNSW 索引",
                help=(
                    "图搜索时维护的候选列表长度。调大召回更好也更慢；应不小于返回"
                    "结果数。只影响本次查询，不改动索引文件。"
                ),
            ),
        ]

    return []


def _set_nested(config: Dict[str, Any], path: tuple, value: Any) -> None:
    """按嵌套路径写值，中间路径不存在时创建 dict 节点。

    Args:
        config: 待写入的配置字典（原地修改）
        path: 键路径
        value: 待写入的值
    """
    node = config

    for key in path[:-1]:
        if key not in node:
            node[key] = {}
        node = node[key]

    node[path[-1]] = value


def build_search_config(specs: List[ParamSpec], values: Dict[str, Any]) -> Dict[str, Any]:
    """从参数规格与用户填值构建检索配置覆盖。

    返回的字典可序列化为 YAML 后作为 ``config_yaml`` 传给任务队列，runner
    将其与库配置合并再构造 SearchEngine。

    Args:
        specs: 参数规格列表
        values: 用户填值，键为 spec.key

    Returns:
        嵌套的配置字典，只含 matching 与 index 段
    """
    config: Dict[str, Any] = {}

    for spec in specs:
        val = values.get(spec.key)

        if val is None:
            continue

        _set_nested(config, spec.config_path, val)

    return config
