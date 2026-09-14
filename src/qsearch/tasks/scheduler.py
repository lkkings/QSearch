"""双车道调度器。

后台车道：索引构建、批量检索（串行）
交互车道：单图查询（可配置并行度）
"""

import logging
import os
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from qsearch.tasks import settings
from qsearch.tasks.index_cache import SearchEngineCache
from qsearch.tasks.lockfile import ProcessLock, LockHeld
from qsearch.tasks.queue import TaskCancelled, TaskKind, TaskQueue, TaskStatus
from qsearch.tasks.worker_pool import PoolRegistry

logger = logging.getLogger(__name__)

# 心跳周期（秒）
HEARTBEAT_INTERVAL_SECONDS = 10.0

# Runner 导入
from qsearch.tasks.runner_index import run_index_build
from qsearch.tasks.runner_search import run_batch_search
from qsearch.tasks.runner_interactive import run_interactive_search

# 任务类型到执行器的映射
_RUNNERS = {
    TaskKind.INDEX_BUILD: run_index_build,
    TaskKind.BATCH_SEARCH: run_batch_search,
    TaskKind.INTERACTIVE_SEARCH: run_interactive_search,
}


class DualLaneScheduler:
    """双车道调度器。

    维护两个独立的执行线程池和 PoolRegistry：
    - 后台车道：并发度=1
    - 交互车道：并发度可配置（默认2）
    """

    def __init__(
        self,
        databases_root: Path,
        queue_root: Path,
        interactive_parallelism: int = 2,
    ):
        """初始化调度器。

        Args:
            databases_root: 数据库根目录
            queue_root: 队列数据目录
            interactive_parallelism: 交互车道并行度
        """
        self.databases_root = Path(databases_root)
        self.queue = TaskQueue(queue_root)
        self.pid = os.getpid()

        # 车道并行度
        self.background_parallelism = 1
        self.interactive_parallelism = max(1, interactive_parallelism)

        # 双线程池
        self._bg_executor = ThreadPoolExecutor(
            max_workers=self.background_parallelism,
            thread_name_prefix="bg-",
        )
        self._int_executor = ThreadPoolExecutor(
            max_workers=self.interactive_parallelism,
            thread_name_prefix="int-",
        )

        # 运行中任务集合（按车道分组）
        self._bg_running_ids: set[str] = set()
        self._int_running_ids: set[str] = set()
        self._running_lock = threading.Lock()

        # 停机事件
        self._stop = threading.Event()

        # 线程局部存储：每个线程独立的 PoolRegistry
        self._local = threading.local()

        # 索引只在调度进程内保留一份，并在空闲 30 分钟后释放。
        self._index_cache = SearchEngineCache()

    def request_stop(self) -> None:
        """请求停机。"""
        logger.info("收到停机信号")
        self._stop.set()

    def _registry(self) -> PoolRegistry:
        """获取当前线程的 PoolRegistry。

        每个车道的每个线程都有独立的 PoolRegistry。
        """
        if not hasattr(self._local, "registry"):
            self._local.registry = PoolRegistry(index_cache=self._index_cache)
        return self._local.registry

    def run(self) -> None:
        """主循环：双车道取任务。"""
        logger.info(
            "双车道调度器启动：PID %d，后台并发=%d，交互并发=%d",
            self.pid, self.background_parallelism, self.interactive_parallelism,
        )

        # 回收孤儿任务
        recovered = self.queue.recover_orphans(live_pids=[self.pid])
        if recovered:
            logger.info("已回收 %d 个孤儿任务", recovered)

        # 启动心跳线程
        heartbeat = threading.Thread(target=self._heartbeat_loop, daemon=True)
        heartbeat.start()

        # 启动清理线程
        cleanup = threading.Thread(target=self._cleanup_loop, daemon=True)
        cleanup.start()

        index_cleanup = threading.Thread(
            target=self._index_cache_cleanup_loop,
            daemon=True,
        )
        index_cleanup.start()

        # 主循环：轮询两个车道
        while not self._stop.is_set():
            # 后台车道
            with self._running_lock:
                bg_slots = self.background_parallelism - len(self._bg_running_ids)

            for _ in range(bg_slots):
                task = self.queue.claim_next(self.pid, lane="background")
                if task:
                    logger.info(
                        "后台车道取到任务 %s（%s）",
                        task["task_id"][:8],
                        TaskKind.LABELS.get(task["kind"], task["kind"]),
                    )
                    with self._running_lock:
                        self._bg_running_ids.add(task["task_id"])
                    self._bg_executor.submit(self._execute, task, "background")

            # 交互车道
            with self._running_lock:
                int_slots = self.interactive_parallelism - len(self._int_running_ids)

            for _ in range(int_slots):
                task = self.queue.claim_next(self.pid, lane="interactive")
                if task:
                    logger.info(
                        "交互车道取到任务 %s（%s）",
                        task["task_id"][:8],
                        TaskKind.LABELS.get(task["kind"], task["kind"]),
                    )
                    with self._running_lock:
                        self._int_running_ids.add(task["task_id"])
                    self._int_executor.submit(self._execute, task, "interactive")

            # 短暂休眠再继续轮询
            self._stop.wait(0.5)

        logger.info("调度器停止，等待任务完成...")
        self._shutdown()

    def _execute(self, task: dict, lane: str) -> None:
        """执行一个任务。

        Args:
            task: 任务字典
            lane: 车道名称
        """
        task_id = task["task_id"]
        kind = task["kind"]
        registry = self._registry()

        try:
            runner = _RUNNERS.get(kind)
            if runner is None:
                raise ValueError(f"没有 {kind} 的执行器")

            runner(task, self.queue, registry, self.databases_root)
            self.queue.finish(task_id, TaskStatus.COMPLETED, stage="完成")

        except TaskCancelled:
            registry.discard()
            self.queue.finish(task_id, TaskStatus.CANCELLED, stage="已取消")
            logger.info("任务 %s 已取消", task_id[:8])

        except Exception as exc:
            registry.discard()
            logger.exception("任务 %s 失败", task_id[:8])
            self.queue.finish(
                task_id, TaskStatus.FAILED, error_message=str(exc), stage="失败"
            )

        finally:
            # 从运行集合中移除
            with self._running_lock:
                if lane == "background":
                    self._bg_running_ids.discard(task_id)
                else:
                    self._int_running_ids.discard(task_id)

    def _heartbeat_loop(self) -> None:
        """心跳线程：定期刷新所有运行中任务的心跳。"""
        while not self._stop.wait(HEARTBEAT_INTERVAL_SECONDS):
            with self._running_lock:
                all_ids = tuple(self._bg_running_ids | self._int_running_ids)

            if all_ids:
                try:
                    self.queue.heartbeat(all_ids)
                except Exception as exc:
                    logger.warning("心跳写入失败：%s", exc)

    def _cleanup_loop(self) -> None:
        """清理线程：定期清理交互车道的过期终态任务。

        每5分钟执行一次清理，删除超过24小时的交互终态任务。
        """
        CLEANUP_INTERVAL_SECONDS = 300.0  # 5分钟

        while not self._stop.wait(CLEANUP_INTERVAL_SECONDS):
            try:
                removed = self.queue.cleanup_interactive_terminal(retention_hours=24)
                if removed > 0:
                    logger.info("已清理 %d 个过期交互任务", removed)
            except Exception as exc:
                logger.warning("交互任务清理失败：%s", exc)

    def _index_cache_cleanup_loop(self) -> None:
        """每分钟释放已连续空闲至少 30 分钟的索引。"""
        while not self._stop.wait(60.0):
            try:
                removed = self._index_cache.evict_idle()
                if removed:
                    logger.info("已释放 %d 个空闲索引缓存", removed)
            except Exception as exc:
                logger.warning("索引缓存清理失败：%s", exc)

    def _shutdown(self) -> None:
        """关闭线程池并等待任务完成。"""
        self._bg_executor.shutdown(wait=True)
        self._int_executor.shutdown(wait=True)

        # 关闭当前线程的池
        if hasattr(self._local, "registry"):
            self._local.registry.close()
        self._index_cache.close()


def main() -> int:
    """入口点。"""
    import argparse

    parser = argparse.ArgumentParser(description="QSearch 双车道任务调度器")
    parser.add_argument(
        "--databases-root",
        type=Path,
        required=True,
        help="数据库根目录",
    )
    parser.add_argument(
        "--queue-root",
        type=Path,
        default=None,
        help="队列目录（默认：数据库根目录）",
    )
    parser.add_argument(
        "--interactive-parallelism",
        type=int,
        default=None,
        help=(
            f"交互车道并行度（1-{settings.INTERACTIVE_WORKERS_CEILING}，"
            f"默认 {settings.INTERACTIVE_WORKERS_DEFAULT}）。"
            f"未指定时读环境变量 {settings.ENV_INTERACTIVE_WORKERS}。"
        ),
    )

    args = parser.parse_args()

    databases_root = args.databases_root.resolve()
    queue_root = (args.queue_root or databases_root).resolve()

    # 并行度有两条入口：service.py 拉起时写环境变量，手工启动时给 CLI 参数。
    # CLI 显式给出时优先 —— 手工启动的人正盯着这个进程。
    requested_interactive = args.interactive_parallelism
    if requested_interactive is None:
        requested_interactive = os.environ.get(settings.ENV_INTERACTIVE_WORKERS)
    interactive_parallelism = settings.clamp_interactive_workers(requested_interactive)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # 单例锁
    lock = ProcessLock(queue_root / "scheduler.lock")

    try:
        lock.acquire()
    except LockHeld as exc:
        logger.info("已有调度器在运行（PID %s），本进程退出", exc.pid)
        return 0

    # 13.2：两车道的池规模必须出现在日志里，否则用户无法确认生效值 ——
    # 尤其是并行数滑块被移除后，这是唯一的确认渠道。
    logger.info(
        "车道池规模：后台 1，交互 %d（每个 worker 约 %.1fGB 常驻）",
        interactive_parallelism,
        settings.WORKER_MEMORY_GB,
    )

    scheduler = DualLaneScheduler(
        databases_root,
        queue_root,
        interactive_parallelism=interactive_parallelism,
    )

    # 注册信号处理
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, lambda *_: scheduler.request_stop())
        except (ValueError, OSError):
            pass

    try:
        scheduler.run()
        return 0
    finally:
        lock.release()


if __name__ == "__main__":
    sys.exit(main())
