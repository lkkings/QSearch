"""基于 PID 的单实例锁。

保证全局只有一个调度进程。用锁文件而非 socket 或命名互斥量：跨平台一致，
且文件里留着 PID，便于诊断和抢占陈旧锁。

陈旧锁必须能被抢占。调度器被强杀（任务管理器结束进程、断电）时不会走清理
路径，锁文件会留在盘上；若不抢占，任务队列就此永久停摆。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


class LockHeld(Exception):
    """锁已被另一个存活进程持有。"""

    def __init__(self, pid: int | None):
        """记录持有者。

        Args:
            pid: 持有锁的进程 PID，未知时为 ``None``
        """
        self.pid = pid
        super().__init__(f"锁已被 PID {pid} 持有")


class ProcessLock:
    """写入自身 PID 的建议性锁文件。"""

    def __init__(self, path: Path):
        """初始化锁。

        Args:
            path: 锁文件路径
        """
        self.path = Path(path)
        self.pid = os.getpid()
        self._acquired = False

    def acquire(self) -> None:
        """取锁。

        Raises:
            LockHeld: 锁被另一个存活进程持有
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)

        holder = self._read_holder()

        if holder is not None and holder != self.pid and _pid_alive(holder):
            raise LockHeld(holder)

        if holder is not None and holder != self.pid:
            logger.warning("抢占陈旧锁（原持有者 PID %s 已不存在）", holder)

        # O_EXCL 竞态窗口：两个进程可能同时通过上面的检查。这里用独占创建来
        # 收窄它 —— 失败则重读一次持有者，确认是否真有人在跑。
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            current = self._read_holder()
            if current is not None and current != self.pid and _pid_alive(current):
                raise LockHeld(current) from None

            # 确实是陈旧锁，覆盖写入。
            fd = os.open(self.path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY)

        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(str(self.pid))

        self._acquired = True
        logger.info("已取得调度器锁：%s（PID %d）", self.path, self.pid)

    def release(self) -> None:
        """释放锁。只删自己写的那个。"""
        if not self._acquired:
            return

        if self._read_holder() == self.pid:
            self.path.unlink(missing_ok=True)
            logger.info("已释放调度器锁")

        self._acquired = False

    def holder(self) -> int | None:
        """读出当前持有者。

        Returns:
            持有锁的 PID；无锁或内容损坏时返回 ``None``
        """
        return self._read_holder()

    def is_held_by_live_process(self) -> bool:
        """锁是否被一个存活进程持有。

        Returns:
            是否有存活的持有者
        """
        holder = self._read_holder()
        return holder is not None and _pid_alive(holder)

    def _read_holder(self) -> int | None:
        """解析锁文件里的 PID。

        Returns:
            PID；文件不存在或内容非法时返回 ``None``
        """
        if not self.path.exists():
            return None

        try:
            return int(self.path.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            logger.warning("锁文件内容损坏：%s", self.path)
            return None

    def __enter__(self) -> ProcessLock:
        self.acquire()
        return self

    def __exit__(self, *_exc_info) -> None:
        self.release()


def _pid_alive(pid: int) -> bool:
    """判断进程是否存在。

    Args:
        pid: 进程 ID

    Returns:
        进程是否存在
    """
    if pid <= 0:
        return False

    try:
        import psutil
    except ImportError:
        # Windows 上 os.kill(pid, 0) 不能用于探活，缺 psutil 时保守认为
        # 还在 —— 宁可让调度器少启一个，也不要两个同时消费队列。
        return True

    return psutil.pid_exists(pid)
