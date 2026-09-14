"""批量检索任务的执行体。

worker 只做检索并回传结果，落库由父进程串行完成 —— 十几个进程并发写同一个
SQLite 只会互相撞锁，而父进程本来就要逐条更新进度。
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

import yaml

from qsearch.tasks import settings
from qsearch.tasks.queue import TaskKind, TaskQueue
from qsearch.tasks.runner_common import ProgressReporter
from qsearch.tasks.worker_pool import PoolRegistry, extract_features_job
from qsearch.webui import result_store

logger = logging.getLogger(__name__)


def _cuda_device_count() -> int:
    """Return the available CUDA device count without making CUDA mandatory."""
    try:
        import torch
    except ImportError:
        return 0
    return torch.cuda.device_count() if torch.cuda.is_available() else 0


def run_batch_search(
    task: dict,
    queue: TaskQueue,
    registry: PoolRegistry,
    databases_root: Path,
) -> dict:
    """执行一次批量检索。

    Args:
        task: 任务字典
        queue: 任务队列
        registry: 池注册表
        databases_root: 数据库根目录

    Returns:
        含 ``processed``、``failed`` 的汇总字典

    Raises:
        FileNotFoundError: 数据库或载荷缺失
        ValueError: 载荷为空
        TaskCancelled: 任务被取消
    """
    task_id = task["task_id"]
    database_name = task["database_name"]
    requested_gpus = int(task.get("num_gpus") or 0)
    available_gpus = _cuda_device_count() if requested_gpus > 0 else 0
    num_gpus = min(requested_gpus, available_gpus)
    # GPU 不可用或未请求时，统一走 settings 的 CPU 并行度裁决。
    num_workers = (
        settings.clamp_workers(task.get("num_workers")) if num_gpus == 0 else None
    )
    top_n = int(task["top_n"])
    batch_size = int(task.get("batch_size") or 32)

    db_dir = databases_root / database_name
    annotations_db = db_dir / "annotations" / "annotations.db"
    config_path = db_dir / "config.yaml"

    if not config_path.exists():
        raise FileNotFoundError(f"配置缺失：{config_path}")

    image_paths = queue.read_payload(task)
    if not image_paths:
        raise ValueError("任务载荷为空，没有待检索的图像")

    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

    # 合并任务的 config_yaml 覆盖（如果有）
    if task.get("config_yaml"):
        try:
            override = yaml.safe_load(task["config_yaml"]) or {}
            _deep_merge(config, override)
        except Exception as exc:
            logger.warning("解析 config_yaml 失败，使用默认配置：%s", exc)

    # 断点续跑：last_processed_index 之前的都已入库，从下一个开始。
    start_index = int(task["last_processed_index"]) + 1
    remaining = image_paths[start_index:]

    reporter = ProgressReporter(queue, task_id, total=len(image_paths))
    reporter.processed = start_index
    reporter.failed = int(task["failed_items"])
    reporter.last_index = start_index - 1
    reporter.stage = "启动特征提取 worker"
    reporter.flush()

    if not remaining:
        logger.info("任务 %s 已全部处理完毕", task_id[:8])
        return {"processed": reporter.processed, "failed": reporter.failed}

    if requested_gpus > 0 and num_gpus == 0:
        logger.warning(
            "批量检索 %s 请求 %d 个 GPU，但 CUDA 不可用，回退 CPU worker 池",
            task_id[:8], requested_gpus,
        )
    elif requested_gpus > available_gpus:
        logger.warning(
            "批量检索 %s 请求 %d 个 GPU，实际仅使用 %d 个可用设备",
            task_id[:8], requested_gpus, available_gpus,
        )

    if num_gpus > 0:
        logger.info(
            "批量检索 %s 开始：库 %s，%d 张待处理（共 %d），%d GPU",
            task_id[:8], database_name, len(remaining), len(image_paths), num_gpus,
        )
        from qsearch.features.feature_extractor import FeatureExtractor

        extractor = FeatureExtractor(config, use_gpu=True)
        extracted_features = extractor.extract_batch_gpu_distributed(
            remaining,
            num_gpus=num_gpus,
            show_progress=False,
            batch_size=batch_size,
        )
        reporter.check_cancelled()
        reporter.set_absolute(
            start_index,
            len(image_paths),
            stage=f"提取特征 {len(extracted_features)}/{len(remaining)}",
        )
    else:
        logger.info(
            "批量检索 %s 开始：库 %s，%d 张待处理（共 %d），%d CPU 并行",
            task_id[:8], database_name, len(remaining), len(image_paths), num_workers,
        )

        spec = {
            "kind": TaskKind.BATCH_SEARCH,
            "config": config,
            "database_path": str(db_dir),
            "use_gpu": False,
        }

        pool = registry.acquire(spec, num_workers)
        # 第一阶段只让 worker 做 OCR/编码。索引不会复制到每个进程中。
        # imap 保序，后续仍可按原始下标可靠地落库和更新断点。
        extraction_batches = [
            remaining[start:start + batch_size]
            for start in range(0, len(remaining), batch_size)
        ]
        extracted_features = []
        for batch_result in pool.imap(extract_features_job, extraction_batches):
            reporter.check_cancelled()
            if isinstance(batch_result, list):
                extracted_features.extend(batch_result)
            else:  # Compatibility with custom/test worker pools.
                extracted_features.append(batch_result)
            reporter.set_absolute(
                start_index,
                len(image_paths),
                stage=f"提取特征 {len(extracted_features)}/{len(remaining)}",
            )

    if len(extracted_features) != len(remaining):
        raise RuntimeError(
            "批量特征提取结果数量与输入数量不一致："
            f"{len(extracted_features)} != {len(remaining)}"
        )

    # 第二阶段在调度进程中用一份缓存索引做向量批检索。先滤出提取成功的
    # 条目，批量结果再按位置填回，保证失败项和断点顺序均不丢失。
    outcomes = [None] * len(extracted_features)
    searchable_positions = []
    searchable_features = []
    for position, features in enumerate(extracted_features):
        if features.get("extraction_success"):
            searchable_positions.append(position)
            searchable_features.append(features)
        else:
            outcomes[position] = {
                "image_path": features.get("image_path", remaining[position]),
                "results": None,
                "error": _extraction_error(features),
            }

    reporter.stage = f"向量批检索 0/{len(searchable_features)}"
    reporter.flush()
    reporter.check_cancelled()

    if searchable_features:
        with registry.index_cache.acquire(db_dir, config) as search_engine:
            search_kwargs = {"top_n": top_n}
            if task.get("batch_size") is not None:
                search_kwargs["batch_size"] = batch_size
            batch_results = search_engine.search_features_batch(
                searchable_features, **search_kwargs
            )

        if len(batch_results) != len(searchable_features):
            raise RuntimeError(
                "批量检索结果数量与输入特征数量不一致："
                f"{len(batch_results)} != {len(searchable_features)}"
            )

        for position, features, results in zip(
            searchable_positions, searchable_features, batch_results
        ):
            outcomes[position] = {
                "image_path": features.get("image_path", remaining[position]),
                "results": results,
                "error": None,
            }

    reporter.stage = f"保存结果 0/{len(remaining)}"
    reporter.flush()

    for offset, outcome in enumerate(outcomes):
        reporter.check_cancelled()

        absolute_index = start_index + offset
        failed = outcome["error"] is not None

        if failed:
            logger.error("检索失败 %s：%s", outcome["image_path"], outcome["error"])
        else:
            try:
                result_store.save_query_result(
                    annotations_db=annotations_db,
                    database_name=database_name,
                    query_image_path=outcome["image_path"],
                    results=outcome["results"],
                    top_n=top_n,
                    config_preset=task.get("config_preset"),
                )
            except Exception as exc:
                # 写库失败与检索失败同等对待：这一条没留下痕迹，计入失败数，
                # 但不该让剩下几千张一起停下。
                logger.error("结果落库失败 %s：%s", outcome["image_path"], exc)
                failed = True

        reporter.advance(
            failed=failed,
            index=absolute_index,
            stage=f"检索 {reporter.processed + 1}/{len(image_paths)}",
        )

    reporter.stage = "完成"
    reporter.flush()

    return {"processed": reporter.processed, "failed": reporter.failed}


def _extraction_error(features: dict) -> str:
    """Build a useful error message from a failed feature dictionary."""
    if features.get("error"):
        return str(features["error"])

    errors = []
    for section in ("text_features", "image_features"):
        value = features.get(section)
        if isinstance(value, dict) and value.get("error"):
            errors.append(f"{section}: {value['error']}")
    return "; ".join(errors) or "特征提取失败"


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
