"""QSearch 任务队列。

索引构建与批量检索都作为任务进入同一个队列，由单个调度进程串行取出执行，
任务内部用进程池并行。这样模型只在 worker 首次使用时加载一次，之后被后续
任务复用 —— 而不是每个任务各起一个进程重新加载一遍。

公开接口：

- :class:`~qsearch.tasks.queue.TaskQueue` 入队、查询、取消
- :func:`~qsearch.tasks.service.ensure_scheduler_running` 确保调度进程存活
- :mod:`~qsearch.tasks.settings` 并行度裁决
"""

from qsearch.tasks.queue import TaskKind, TaskQueue, TaskStatus
from qsearch.tasks.settings import CPU_COUNT, clamp_workers, default_max_workers

__all__ = [
    "CPU_COUNT",
    "TaskKind",
    "TaskQueue",
    "TaskStatus",
    "clamp_workers",
    "default_max_workers",
]
