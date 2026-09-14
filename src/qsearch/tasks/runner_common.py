"""runner 共用的进度上报与取消检查。

两者都必须节流。批量检索每张图耗时可能只有几十毫秒，而每张图都写一次
SQLite、再读一次取消标志，会让队列库的写入频率超过实际工作量本身 —— 进度
条的刷新精度并不需要这个代价。
"""

from __future__ import annotations

import logging
import time

from qsearch.tasks.queue import TaskCancelled, TaskQueue

logger = logging.getLogger(__name__)

# 进度落库的最小间隔。1 秒足以让 UI 的秒级刷新看到变化。
PROGRESS_INTERVAL_SECONDS = 1.0

# 取消标志的读取间隔。取消是人手动点的，半秒的响应延迟感知不到。
CANCEL_POLL_INTERVAL_SECONDS = 0.5


class ProgressReporter:
    """按时间节流地把进度写进队列，并顺带检查取消。"""

    def __init__(self, queue: TaskQueue, task_id: str, total: int):
        """初始化上报器。

        Args:
            queue: 任务队列
            task_id: 任务 ID
            total: 总条目数
        """
        self.queue = queue
        self.task_id = task_id
        self.total = total

        self.processed = 0
        self.failed = 0
        self.last_index = -1
        self.stage: str | None = None

        self._last_progress_at = 0.0
        self._last_cancel_at = 0.0
        self._cancelled = False

    def advance(
        self,
        failed: bool = False,
        index: int | None = None,
        stage: str | None = None,
    ) -> None:
        """记一个条目已处理。

        Args:
            failed: 该条目是否失败
            index: 该条目在原始列表中的下标，供断点续跑使用
            stage: 当前阶段描述
        """
        self.processed += 1
        if failed:
            self.failed += 1
        if index is not None:
            self.last_index = index
        if stage is not None:
            self.stage = stage

        self._maybe_flush()

    def set_absolute(self, processed: int, total: int, stage: str) -> None:
        """直接设定进度。供 builder 的 progress_cb 使用。

        Args:
            processed: 已处理数
            total: 总数
            stage: 阶段描述
        """
        self.processed = processed
        self.total = total
        self.stage = stage
        self._maybe_flush()

    def _maybe_flush(self) -> None:
        """到点则落库。"""
        now = time.monotonic()
        if now - self._last_progress_at < PROGRESS_INTERVAL_SECONDS:
            return

        self._last_progress_at = now
        self.flush()

    def flush(self) -> None:
        """立即落库。任务收尾时必须调用，否则最后一段进度会丢。"""
        self.queue.update_progress(
            self.task_id,
            processed_items=self.processed,
            failed_items=self.failed,
            last_processed_index=self.last_index if self.last_index >= 0 else None,
            stage=self.stage,
            total_items=self.total,
        )

    def check_cancelled(self) -> None:
        """按间隔检查取消请求。

        Raises:
            TaskCancelled: 已请求取消
        """
        if self._cancelled:
            raise TaskCancelled(self.task_id)

        now = time.monotonic()
        if now - self._last_cancel_at < CANCEL_POLL_INTERVAL_SECONDS:
            return

        self._last_cancel_at = now

        if self.queue.is_cancel_requested(self.task_id):
            self._cancelled = True
            logger.info("任务 %s 收到取消请求，正在停止", self.task_id[:8])
            self.flush()
            raise TaskCancelled(self.task_id)
