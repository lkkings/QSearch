"""交互式单图查询 runner。

执行单图检索并将结果写入 annotations.db，不记录断点位置。
"""

import logging
from pathlib import Path

from qsearch.tasks.queue import TaskQueue
from qsearch.tasks.worker_pool import PoolRegistry
from qsearch.webui import result_store

logger = logging.getLogger(__name__)


def run_interactive_search(
    task: dict,
    queue: TaskQueue,
    registry: PoolRegistry,
    databases_root: Path,
) -> None:
    """执行单图查询任务。

    与批量检索不同：
    - 只查询一张图
    - 结果直接写入 annotations.db
    - 不记录断点（last_processed_index）
    - 失败时不写入任何数据

    Args:
        task: 任务字典，payload 应包含：
            - query_image_path: 查询图像路径
            - top_n: 返回结果数
        queue: 任务队列
        registry: 池注册表（本 runner 不使用进程池）
        databases_root: 数据库根目录

    Raises:
        ValueError: 参数错误
        RuntimeError: 执行失败
    """
    task_id = task["task_id"]
    database_name = task["database_name"]
    database_path = databases_root / database_name

    if not database_path.exists():
        raise ValueError(f"数据库不存在：{database_path}")

    # 读取 payload
    payload = queue.read_payload(task)
    if not payload:
        raise ValueError("缺少 payload")

    query_image_path = payload.get("query_image_path")
    if not query_image_path:
        raise ValueError("缺少 query_image_path")

    top_n = task.get("top_n", 10)
    batch_size = int(task.get("batch_size") or 1)

    logger.info(
        "交互查询 %s：%s (top_n=%d)",
        task_id[:8],
        query_image_path,
        top_n,
    )

    # 更新阶段
    queue.update_progress(task_id, 0, stage="加载索引")

    # 加载库配置并合并任务级配置覆盖
    config_path = database_path / "config.yaml"
    if not config_path.exists():
        raise RuntimeError(f"数据库配置缺失：{config_path}")

    try:
        import yaml
        base_config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        raise RuntimeError(f"加载数据库配置失败：{exc}") from exc

    # 合并任务的 config_yaml 覆盖（如果有）
    if task.get("config_yaml"):
        try:
            override = yaml.safe_load(task["config_yaml"]) or {}
            _deep_merge(base_config, override)
        except Exception as exc:
            logger.warning("解析 config_yaml 失败，使用默认配置：%s", exc)

    # 更新阶段
    queue.update_progress(task_id, 0, stage="执行查询")

    # 使用与批量检索共享的索引缓存。单图查询仍保留自己的特征提取器，
    # 但 FAISS、哈希索引与特征库不会重复从磁盘加载。
    try:
        with registry.index_cache.acquire(
            database_path,
            base_config,
            load_feature_extractor=True,
        ) as search_engine:
            search_kwargs = {
                "query_image": query_image_path,
                "top_n": top_n,
            }
            if task.get("batch_size") is not None:
                search_kwargs["batch_size"] = batch_size
            results = search_engine.search_single(**search_kwargs)
    except Exception as exc:
        raise RuntimeError(f"查询失败：{exc}") from exc

    # 更新阶段
    queue.update_progress(task_id, 0, stage="保存结果")

    # 将结果持久化到 annotations.db。
    #
    # search_single 只做检索与格式化，不落库 —— 落库是 result_store 的职责。
    # 写入必须在检索成功之后：失败路径在上面已经 raise，因此失败时标注库不会
    # 出现半条记录（spec: 交互任务失败不写入）。
    annotations_db = database_path / "annotations" / "annotations.db"

    try:
        query_id = result_store.save_query_result(
            annotations_db=annotations_db,
            database_name=database_name,
            query_image_path=str(query_image_path),
            results=results,
            top_n=top_n,
            config_preset=task.get("config_preset"),
            config_yaml=task.get("config_yaml"),
        )
    except Exception as exc:
        raise RuntimeError(f"结果落库失败：{exc}") from exc

    candidate_count = (
        len(results.get("exact_matches", [])) + len(results.get("content_matches", []))
    )

    logger.info(
        "交互查询 %s 完成：query_id=%s，%d 个候选",
        task_id[:8],
        query_id[:8],
        candidate_count,
    )

    # 标记为已处理（total_items=1）
    queue.update_progress(
        task_id,
        processed_items=1,
        total_items=1,
        stage="完成",
    )


def _deep_merge(base: dict, override: dict) -> None:
    """深度合并 override 到 base，原地修改 base。

    Args:
        base: 待合并的基础字典
        override: 覆盖字典
    """
    for key, val in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(val, dict):
            _deep_merge(base[key], val)
        else:
            base[key] = val
