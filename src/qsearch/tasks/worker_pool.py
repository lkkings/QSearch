"""可复用进程池与 worker 侧模型单例。

防止模型重复加载靠两层缓存：

1. **worker 内第一层**：FeatureExtractor 按模型配置哈希缓存，容量 1。
   同一模型配置的不同数据集任务共享提取器，无需重新加载模型。
2. **worker 内第二层**：索引与 matcher 按 database_path LRU 缓存，容量 4。
   访问多个数据集时保持热门库的索引驻留，避免重复加载。
3. **调度器内**：:class:`PoolRegistry` 按 (kind, model_config_hash) 缓存池。
   连续任务只要模型配置一致就复用同一个池，worker 无需重启。

worker 函数必须是模块级函数 —— spawn 启动方式要把它们 pickle 过去。
"""

from __future__ import annotations

import hashlib
import json
import logging
import multiprocessing as mp
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterator

from qsearch.tasks.queue import TaskKind

if TYPE_CHECKING:
    from qsearch.tasks.index_cache import SearchEngineCache

logger = logging.getLogger(__name__)

# worker 进程内的状态。父进程里这些变量始终为空。
_SPEC: dict | None = None

# 第一层缓存：FeatureExtractor 按模型配置哈希缓存，容量 1
_EXTRACTOR_CACHE: dict[str, Any] = {}

# 第二层缓存：索引与 matcher 按 database_path LRU 缓存，容量 4
_DATABASE_CACHE: dict[str, Any] = {}
_DATABASE_CACHE_LIMIT = 4


def _init_worker(spec: dict) -> None:
    """worker 进程初始化。

    只记下规格，不建模型 —— 建模型放到首次调用时，这样加载失败会作为任务
    错误浮现，而不是变成池构造期的一个难以定位的异常。

    Args:
        spec: 任务规格，含 ``kind``、``config``、``database_path``
    """
    global _SPEC
    _SPEC = spec

    logging.basicConfig(
        level=logging.WARNING,
        format="[worker] %(levelname)s: %(message)s",
    )


def _spec_key(spec: dict) -> str:
    """规格的稳定摘要，用作缓存键。

    Args:
        spec: 任务规格

    Returns:
        16 位十六进制摘要
    """
    blob = json.dumps(spec, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _model_config_hash(config: dict) -> str:
    """计算模型配置哈希（用于池键和第一层缓存）。

    只哈希影响模型加载的配置项，排除 database_path 等数据集特定字段。

    Args:
        config: 配置字典

    Returns:
        SHA256 前 16 位十六进制
    """
    # 提取模型相关配置
    model_config = {
        # 文本侧只有两个模块影响模型加载：OCR 与语义编码
        "text": config.get("text", {}),
        "image": config.get("image", {}),
        # matching 配置会影响特征提取
        "matching": config.get("matching", {}),
    }

    blob = json.dumps(model_config, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


# ---------- worker 侧模型 ----------


def _get_model():
    """取本 worker 的模型，使用两层缓存。

    第一层：FeatureExtractor 按模型配置哈希缓存（容量1）
    第二层：索引与 matcher 按 database_path LRU 缓存（容量4）

    Returns:
        与 ``spec['kind']`` 对应的模型对象

    Raises:
        RuntimeError: 池未正确初始化
    """
    if _SPEC is None:
        raise RuntimeError("worker 未初始化，_init_worker 未被调用")

    kind = _SPEC["kind"]
    config = _SPEC.get("config", {})
    database_path = _SPEC.get("database_path")

    # 第一层缓存：FeatureExtractor（只依赖模型配置）
    if kind == TaskKind.INDEX_BUILD:
        model_hash = _model_config_hash(config)

        if model_hash in _EXTRACTOR_CACHE:
            logger.debug("命中第一层缓存：FeatureExtractor (%s)", model_hash)
            return _EXTRACTOR_CACHE[model_hash]

        # 未命中，构建新提取器
        logger.info("构建 FeatureExtractor：%s", model_hash)
        from qsearch.features.feature_extractor import FeatureExtractor
        extractor = FeatureExtractor(
            config, use_gpu=bool(_SPEC.get("use_gpu", True))
        )

        # 容量1，直接替换
        _EXTRACTOR_CACHE.clear()
        _EXTRACTOR_CACHE[model_hash] = extractor

        return extractor

    # 第二层缓存：SearchEngine（依赖 database_path）
    elif kind in (TaskKind.BATCH_SEARCH, TaskKind.INTERACTIVE_SEARCH):
        if database_path is None:
            raise RuntimeError("batch_search/interactive_search 需要 database_path")

        # 规范化路径作为键
        db_key = str(Path(database_path).resolve())

        if db_key in _DATABASE_CACHE:
            logger.debug("命中第二层缓存：SearchEngine (%s)", database_path)
            # LRU：移到末尾
            searcher = _DATABASE_CACHE.pop(db_key)
            _DATABASE_CACHE[db_key] = searcher
            return searcher

        # 未命中，构建新 SearchEngine
        logger.info("构建 SearchEngine：%s", database_path)
        from qsearch.webui.search_engine import SearchEngine
        searcher = SearchEngine(Path(database_path), config=config)

        # LRU 淘汰
        if len(_DATABASE_CACHE) >= _DATABASE_CACHE_LIMIT:
            evicted_key = next(iter(_DATABASE_CACHE))
            _DATABASE_CACHE.pop(evicted_key)
            logger.info("淘汰第二层缓存：%s", evicted_key)

        _DATABASE_CACHE[db_key] = searcher
        return searcher

    else:
        raise RuntimeError(f"未知规格类型：{kind}")


def _get_extractor():
    """Return the process-local extractor independently of the task kind."""
    if _SPEC is None:
        raise RuntimeError("worker 未初始化，_init_worker 未被调用")

    config = _SPEC.get("config", {})
    model_hash = _model_config_hash(config)
    if model_hash in _EXTRACTOR_CACHE:
        return _EXTRACTOR_CACHE[model_hash]

    from qsearch.features.feature_extractor import FeatureExtractor

    extractor = FeatureExtractor(
        config, use_gpu=bool(_SPEC.get("use_gpu", True))
    )
    _EXTRACTOR_CACHE.clear()
    _EXTRACTOR_CACHE[model_hash] = extractor
    return extractor


def extract_features_job(image_path: str | list[str]) -> dict | list[dict]:
    """worker 入口：提取单图特征。

    Args:
        image_path: 单个图像路径或一批路径

    Returns:
        特征字典；失败时带 ``error`` 键
    """
    try:
        if isinstance(image_path, (list, tuple)):
            return _get_extractor().extract_batch(
                list(image_path),
                num_workers=1,
                show_progress=False,
                batch_size=len(image_path),
            )
        return _get_extractor().extract(image_path)
    except Exception as exc:  # 单图失败不该带走整个任务
        import traceback
        traceback.print_exc()
        logger.error("提取失败 %s：%s", image_path, exc)
        failed_paths = image_path if isinstance(image_path, (list, tuple)) else [image_path]
        failures = [
            {
                "image_path": str(path),
                "text_features": None,
                "image_features": None,
                "extraction_success": False,
                "error": str(exc),
            }
            for path in failed_paths
        ]
        return failures if isinstance(image_path, (list, tuple)) else failures[0]


def search_job(job: dict) -> dict:
    """worker 入口：单图检索。

    结果只回传父进程，不在 worker 里写库 —— 十几个进程并发写同一个 SQLite
    只会互相撞锁，而父进程本来就要串行更新进度。

    Args:
        job: 含 ``image_path`` 与 ``top_n``

    Returns:
        含 ``image_path``、``results``/``error`` 的字典
    """
    image_path = job["image_path"]

    try:
        results = _get_model().search_single(image_path, top_n=job.get("top_n"))
        return {"image_path": image_path, "results": results, "error": None}
    except Exception as exc:
        logger.error("检索失败 %s：%s", image_path, exc)
        return {"image_path": image_path, "results": None, "error": str(exc)}


# ---------- 池 ----------


class WorkerPool:
    """一个进程池，绑定一份任务规格。

    不设 ``maxtasksperchild``：worker 必须跨任务存活，否则每批任务结束都会
    回收进程，下一批重新加载模型 —— 那正是要避免的开销。
    """

    def __init__(self, spec: dict, num_workers: int):
        """构造池并启动 worker。

        Args:
            spec: 任务规格，会被 pickle 到每个 worker
            num_workers: 进程数，调用方须已过 ``clamp_workers``
        """
        self.spec = spec
        self.num_workers = num_workers

        # 池键：(kind, model_config_hash)
        # 不再包含 num_workers，同配置不同并行数可以复用池
        config = spec.get("config", {})
        model_hash = _model_config_hash(config)
        self.key = (spec["kind"], model_hash)

        # 显式 spawn：fork 与 CUDA / Transformers 的线程状态不兼容，
        # 在 Linux 上会得到偶发死锁而非明确报错。
        ctx = mp.get_context("spawn")
        self._pool = ctx.Pool(
            processes=num_workers,
            initializer=_init_worker,
            initargs=(spec,),
        )

        logger.info("已启动 %d 个 worker（%s）", num_workers, spec["kind"])

    def imap(self, job_fn: Callable, items: list) -> Iterator:
        """按序流式返回结果。

        保序是必需的：批量检索靠 ``last_processed_index`` 断点续跑，乱序完成
        会让这个下标失去意义。

        Args:
            job_fn: 模块级 worker 函数
            items: 待处理条目

        Yields:
            每个条目的结果
        """
        return self._pool.imap(job_fn, items, chunksize=1)

    def close(self) -> None:
        """正常关闭，等待 worker 退出。"""
        try:
            self._pool.close()
            self._pool.join()
        except Exception as exc:
            logger.warning("关闭池时出错：%s", exc)

    def terminate(self) -> None:
        """强制终止。取消任务或出错时用。"""
        try:
            self._pool.terminate()
            self._pool.join()
        except Exception as exc:
            logger.warning("终止池时出错：%s", exc)


class PoolRegistry:
    """调度进程内的池缓存。

    只缓存一个池。每个池占用 ``num_workers × 约 1GB``，多缓存一个就多一份
    常驻内存；而连续任务通常规格相同，缓存一个已能命中绝大多数复用机会。
    """

    def __init__(self, index_cache: "SearchEngineCache | None" = None):
        self._pool: WorkerPool | None = None
        if index_cache is None:
            from qsearch.tasks.index_cache import SearchEngineCache

            index_cache = SearchEngineCache()
        self.index_cache = index_cache

    def acquire(self, spec: dict, num_workers: int) -> WorkerPool:
        """取一个匹配规格的池，可复用则复用。

        池键：(kind, model_config_hash)
        只要模型配置一致，即使 database_path 或 num_workers 不同也会复用池。

        Args:
            spec: 任务规格
            num_workers: 需要的并行数

        Returns:
            就绪的 WorkerPool
        """
        config = spec.get("config", {})
        model_hash = _model_config_hash(config)
        key = (spec["kind"], model_hash)

        if self._pool is not None and self._pool.key == key:
            logger.info("复用现有池（%s, %s），worker 内缓存命中", spec["kind"], model_hash)
            return self._pool

        self.close()
        self._pool = WorkerPool(spec, num_workers)
        return self._pool

    def discard(self) -> None:
        """丢弃当前池（强制终止）。

        任务被取消或抛异常后调用：此时池里可能还有在途条目，
        继续复用会把上一个任务的残留结果混进下一个任务。
        """
        if self._pool is not None:
            self._pool.terminate()
            self._pool = None

    def close(self) -> None:
        """正常关闭当前池。"""
        if self._pool is not None:
            self._pool.close()
            self._pool = None
