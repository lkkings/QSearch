"""索引构建任务的执行体。

特征提取走调度器持有的进程池；索引装配（Faiss / 哈希）留在父进程 —— 那是
纯 numpy 与 faiss 的工作，不需要模型，也无法从多进程再拿到收益。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterator

import yaml

from qsearch.indexing.builder import build_index
from qsearch.tasks.queue import TaskKind, TaskQueue
from qsearch.tasks.runner_common import ProgressReporter
from qsearch.tasks.worker_pool import PoolRegistry, extract_features_job

logger = logging.getLogger(__name__)


def run_index_build(
    task: dict,
    queue: TaskQueue,
    registry: PoolRegistry,
    databases_root: Path,
) -> dict:
    """执行一次索引构建。

    Args:
        task: 任务字典
        queue: 任务队列
        registry: 池注册表，用于复用已加载模型的 worker
        databases_root: 数据库根目录

    Returns:
        索引统计字典

    Raises:
        FileNotFoundError: 数据库目录或配置缺失
        TaskCancelled: 任务被取消
    """
    task_id = task["task_id"]
    database_name = task["database_name"]
    num_workers = task.get("num_workers")
    num_gpus = task.get("num_gpus", 0)
    batch_size = int(task.get("batch_size") or 32)

    db_dir = databases_root / database_name
    config_path = db_dir / "config.yaml"
    image_list_path = db_dir / "image_list.txt"
    output_dir = db_dir / "index"

    if not config_path.exists():
        raise FileNotFoundError(f"配置缺失：{config_path}")
    if not image_list_path.exists():
        raise FileNotFoundError(f"图像列表缺失：{image_list_path}")

    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

    reporter = ProgressReporter(queue, task_id, total=int(task["total_items"]))
    reporter.stage = "启动 worker"
    reporter.flush()

    # 根据 num_gpus 决定是否使用进程池
    if num_gpus and num_gpus > 0:
        # GPU 模式：直接调用 build_index，不使用进程池
        logger.info(
            "索引构建 %s 开始：库 %s，%d GPU(s)",
            task_id[:8], database_name, num_gpus,
        )

        def progress_cb(processed: int, total: int, stage: str) -> None:
            """转发 builder 的进度。"""
            reporter.set_absolute(processed, total, stage)
            reporter.check_cancelled()

        stats = build_index(
            config_path=str(config_path),
            image_list=str(image_list_path),
            output_dir=str(output_dir),
            num_gpus=num_gpus,
            batch_size=batch_size,
            progress_cb=progress_cb,
        )
    else:
        # CPU 模式：使用进程池
        workers = int(num_workers) if num_workers else 4
        logger.info(
            "索引构建 %s 开始：库 %s，%d CPU 并行(s)",
            task_id[:8], database_name, workers,
        )

        spec = {
            "kind": TaskKind.INDEX_BUILD,
            "config": config,
            "database_path": str(db_dir),
            "use_gpu": False,
        }

        pool = registry.acquire(spec, workers)

        def feature_mapper(image_paths: list[str]) -> Iterator[dict]:
            """把提取工作分发给池，逐个产出结果。

            Args:
                image_paths: 待提取的图像路径

            Yields:
                单图特征字典
            """
            reporter.total = len(image_paths)

            batches = [
                image_paths[start:start + batch_size]
                for start in range(0, len(image_paths), batch_size)
            ]
            for batch_result in pool.imap(extract_features_job, batches):
                # 取消检查放在这里而非 for 之后：生成器被 build_index 消费，
                # 只有在产出点才有机会中断，否则要等整批提取完。
                reporter.check_cancelled()
                if isinstance(batch_result, list):
                    yield from batch_result
                else:  # Compatibility with custom/test worker pools.
                    yield batch_result

        def progress_cb(processed: int, total: int, stage: str) -> None:
            """转发 builder 的进度。

            Args:
                processed: 已处理数
                total: 总数
                stage: 阶段描述
            """
            reporter.set_absolute(processed, total, stage)

        logger.info(
            "索引构建 %s 开始：库 %s，%d 并行",
            task_id[:8], database_name, workers,
        )

        stats = build_index(
            config_path=str(config_path),
            image_list=str(image_list_path),
            output_dir=str(output_dir),
            num_workers=workers,
            batch_size=batch_size,
            feature_mapper=feature_mapper,
            progress_cb=progress_cb,
        )

    reporter.stage = "完成"
    reporter.processed = stats["total_images"]
    reporter.total = stats["total_images"]
    reporter.failed = stats.get("features_failed", 0)
    reporter.flush()

    _mark_index_built(db_dir, stats)

    return stats


def _mark_index_built(db_dir: Path, stats: dict) -> None:
    """把 metadata.json 的 index_built 置真。

    Args:
        db_dir: 数据库目录
        stats: 索引统计
    """
    import json

    metadata_path = db_dir / "metadata.json"
    if not metadata_path.exists():
        logger.warning("元数据缺失，跳过 index_built 标记：%s", metadata_path)
        return

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["index_built"] = True
        metadata["index_stats"] = stats
        metadata_path.write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as exc:
        logger.error("更新元数据失败：%s", exc)
