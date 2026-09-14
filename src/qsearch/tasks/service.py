"""从 Streamlit 侧拉起并观察调度进程。

调度器必须是独立进程，不能是 Streamlit 里的线程：Streamlit 每次交互都重跑
脚本，线程会随之反复创建；而进程池必须由长活进程持有，否则模型每次重跑都
要重新加载 —— 那正是要消除的开销。

用 ``subprocess`` 而非 ``multiprocessing``：调度器要在 Streamlit 重启后继续
活着，因此它必须与父进程脱钩，不能是父进程的子进程语义。
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

from qsearch.tasks import settings
from qsearch.tasks.lockfile import ProcessLock

logger = logging.getLogger(__name__)

_LOG_FILENAME = "scheduler.log"


def scheduler_status(queue_root: Path | None = None) -> dict:
    """调度器当前是否在跑。

    Args:
        queue_root: 队列数据目录，``None`` 表示取默认

    Returns:
        含 ``running``、``pid``、``log_path`` 的字典
    """
    root = Path(queue_root) if queue_root else settings.queue_root()
    lock = ProcessLock(root / "scheduler.lock")

    return {
        "running": lock.is_held_by_live_process(),
        "pid": lock.holder(),
        "log_path": root / _LOG_FILENAME,
    }


def ensure_scheduler_running(
    databases_root: Path,
    queue_root: Path | None = None,
    max_workers: int | None = None,
    max_concurrent: int | None = None,
    interactive_workers: int | None = None,
) -> dict:
    """确保有且只有一个调度进程在跑。

    幂等：已有存活调度器时直接返回，不重复拉起。锁文件的抢占逻辑负责处理
    上一次被强杀后留下的陈旧锁。

    Args:
        databases_root: 数据库根目录
        queue_root: 队列数据目录
        max_workers: 传给调度器的默认并行数，会被收敛到 CPU 核数以内
        max_concurrent: 同时运行的任务数
        interactive_workers: 交互车道并行度，会被收敛到 [1, 上限]

    Returns:
        :func:`scheduler_status` 的返回值，附加 ``started`` 表示本次是否拉起
    """
    root = Path(queue_root) if queue_root else settings.queue_root()
    root.mkdir(parents=True, exist_ok=True)

    status = scheduler_status(root)

    if status["running"]:
        status["started"] = False
        return status

    env = os.environ.copy()
    env[settings.ENV_QUEUE_ROOT] = str(root)

    if max_workers is not None:
        env[settings.ENV_MAX_WORKERS] = str(settings.clamp_workers(max_workers))

    if max_concurrent is not None:
        env[settings.ENV_MAX_CONCURRENT_TASKS] = str(max_concurrent)

    if interactive_workers is not None:
        env[settings.ENV_INTERACTIVE_WORKERS] = str(
            settings.clamp_interactive_workers(interactive_workers)
        )

    command = [
        sys.executable,
        "-m",
        "qsearch.tasks.scheduler",
        "--databases-root",
        str(Path(databases_root).resolve()),
        "--queue-root",
        str(root),
    ]

    log_path = root / _LOG_FILENAME

    try:
        # 日志重定向到文件而非管道：管道无人读取会在缓冲区填满后把调度器
        # 阻塞在 write 上，而这个进程要跑几个小时。
        log_handle = open(log_path, "a", encoding="utf-8")

        process = subprocess.Popen(
            command,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=env,
            cwd=str(Path(databases_root).resolve().parent),
            **_detach_kwargs(),
        )

        logger.info("已拉起调度进程 PID %d，日志：%s", process.pid, log_path)

    except Exception as exc:
        logger.error("拉起调度进程失败：%s", exc)
        return {"running": False, "pid": None, "log_path": log_path, "started": False,
                "error": str(exc)}

    status = scheduler_status(root)
    status["started"] = True

    # 锁由子进程写入，此刻可能还没落盘。返回乐观结果，UI 下次重跑会拿到真值。
    if not status["running"]:
        status["pid"] = process.pid

    return status


def _detach_kwargs() -> dict:
    """让子进程脱离父进程的控制台与信号组。

    Returns:
        传给 ``subprocess.Popen`` 的平台相关参数
    """
    if sys.platform == "win32":
        # DETACHED_PROCESS 使其不随 Streamlit 的控制台关闭而终止；
        # CREATE_NEW_PROCESS_GROUP 使其不接收发往父进程的 Ctrl+C。
        creation_flags = 0x00000008 | 0x00000200
        return {"creationflags": creation_flags}

    # POSIX：自立会话，避免收到父进程终端的 SIGHUP。
    return {"start_new_session": True}


def stop_scheduler(queue_root: Path | None = None, timeout: float = 10.0) -> bool:
    """请求调度器停机。

    发送终止信号而非直接强杀，让在跑任务有机会写完进度与终态。

    Args:
        queue_root: 队列数据目录
        timeout: 等待退出的秒数

    Returns:
        调度器是否已停止
    """
    root = Path(queue_root) if queue_root else settings.queue_root()
    lock = ProcessLock(root / "scheduler.lock")
    pid = lock.holder()

    if pid is None:
        return True

    try:
        import psutil
    except ImportError:
        logger.warning("缺少 psutil，无法安全停止调度器")
        return False

    if not psutil.pid_exists(pid):
        return True

    try:
        process = psutil.Process(pid)
        process.terminate()
        process.wait(timeout=timeout)
        logger.info("调度进程 %d 已停止", pid)
        return True

    except psutil.TimeoutExpired:
        logger.warning("调度进程 %d 未在 %.0fs 内退出", pid, timeout)
        return False

    except psutil.Error as exc:
        logger.error("停止调度进程失败：%s", exc)
        return False
