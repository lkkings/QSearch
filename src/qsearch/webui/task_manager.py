"""WebUI 侧的任务入口。

原实现每个任务 ``multiprocessing.Process`` 起一个进程，在进程里现场构造
SearchEngine —— 每个任务重新加载一遍 OCR 引擎与编码器，且没有并发上限，
同时提交两个任务就是两套模型常驻。

现在这里只负责入队与查询：真正的执行在 :mod:`qsearch.tasks.scheduler` 的
单一长活进程里，它持有可复用的进程池，模型只加载一次。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from qsearch.tasks import settings
from qsearch.tasks.queue import TaskKind, TaskQueue, TaskStatus
from qsearch.tasks.service import ensure_scheduler_running, scheduler_status

logger = logging.getLogger(__name__)


class TaskManager:
    """入队、查询、取消任务。不执行任务。"""

    def __init__(self, databases_root: Path, queue_root: Optional[Path] = None):
        """初始化。

        Args:
            databases_root: 数据库根目录
            queue_root: 队列数据目录，``None`` 表示取默认
        """
        self.databases_root = Path(databases_root)
        self.queue_root = Path(queue_root) if queue_root else settings.queue_root()
        self.queue = TaskQueue(self.queue_root)

    # ---------- 调度进程 ----------

    def ensure_scheduler(self, max_workers: Optional[int] = None) -> Dict:
        """确保调度进程在跑。

        Args:
            max_workers: 传给调度器的默认并行数

        Returns:
            调度器状态字典
        """
        return ensure_scheduler_running(
            databases_root=self.databases_root,
            queue_root=self.queue_root,
            max_workers=max_workers,
        )

    def scheduler_status(self) -> Dict:
        """调度进程状态。

        Returns:
            含 ``running``、``pid``、``log_path`` 的字典
        """
        return scheduler_status(self.queue_root)

    # ---------- 入队 ----------

    def enqueue_index_build(
        self,
        database_name: str,
        num_workers: Optional[int] = None,
        num_gpus: int = 0,
        config_preset: Optional[str] = None,
        config_yaml: Optional[str] = None,
        task_name: Optional[str] = None,
        batch_size: int = 32,
    ) -> str:
        """把索引构建放进队列。

        Args:
            database_name: 数据库名
            num_workers: CPU 并行进程数，None 表示自动，超过 CPU 核数会被收敛
            num_gpus: GPU 数量，0 表示仅使用 CPU，> 0 时将忽略 num_workers
            batch_size: 文本和图片特征提取的批大小
            config_preset: 配置预设名
            config_yaml: 自定义配置 YAML
            task_name: 可读任务名，默认按库名生成

        Returns:
            任务 ID

        Raises:
            FileNotFoundError: 图像列表缺失，说明该库尚未正确创建
        """
        db_dir = self.databases_root / database_name
        image_list = db_dir / "image_list.txt"

        if not image_list.exists():
            raise FileNotFoundError(f"图像列表缺失：{image_list}")

        total = sum(
            1 for line in image_list.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )

        workers = settings.clamp_workers(num_workers) if num_workers is not None else None

        task_id = self.queue.enqueue(
            kind=TaskKind.INDEX_BUILD,
            task_name=task_name or f"构建索引 {database_name}",
            database_name=database_name,
            lane="background",
            total_items=total,
            num_workers=workers,
            num_gpus=num_gpus,
            batch_size=batch_size,
            config_preset=config_preset,
            config_yaml=config_yaml,
        )

        self.ensure_scheduler(max_workers=workers)
        return task_id

    def enqueue_batch_search(
        self,
        database_name: str,
        image_paths: Sequence[Path],
        top_n: int = 10,
        num_workers: Optional[int] = None,
        num_gpus: int = 0,
        task_name: Optional[str] = None,
        config_preset: Optional[str] = None,
        config_yaml: Optional[str] = None,
        batch_size: int = 32,
    ) -> str:
        """把批量检索放进队列。

        Args:
            database_name: 数据库名
            image_paths: 查询图路径
            top_n: 每个查询返回数
            num_workers: 并行进程数，超过 CPU 核数会被收敛
            num_gpus: GPU 数量，0 表示仅使用 CPU，> 0 时将忽略 num_workers
            batch_size: 文本和图片特征提取的批大小
            task_name: 可读任务名
            config_preset: 配置预设名
            config_yaml: 自定义配置 YAML

        Returns:
            任务 ID

        Raises:
            ValueError: 图像列表为空
        """
        if not image_paths:
            raise ValueError("没有待检索的图像")

        num_gpus = int(num_gpus)
        if num_gpus < 0:
            raise ValueError(f"num_gpus 不能小于 0，当前为 {num_gpus}")

        workers = (
            settings.clamp_workers(num_workers)
            if num_gpus == 0 and num_workers is not None
            else None
        )

        task_id = self.queue.enqueue(
            kind=TaskKind.BATCH_SEARCH,
            task_name=task_name or f"批量检索 {database_name}",
            database_name=database_name,
            lane="background",
            total_items=len(image_paths),
            num_workers=workers,
            num_gpus=num_gpus,
            batch_size=batch_size,
            top_n=top_n,
            config_preset=config_preset,
            config_yaml=config_yaml,
            payload=[str(path) for path in image_paths],
        )

        self.ensure_scheduler(max_workers=workers)
        return task_id

    def enqueue_interactive_search(
        self,
        database_name: str,
        query_image_path: str,
        top_n: int = 10,
        config_preset: Optional[str] = None,
        config_yaml: Optional[str] = None,
        batch_size: int = 1,
    ) -> str:
        """把单图查询放进交互车道。

        Args:
            database_name: 数据库名
            query_image_path: 查询图路径
            top_n: 返回结果数
            batch_size: 特征提取批大小（单图查询通常为 1）
            config_preset: 配置预设名
            config_yaml: 自定义配置 YAML

        Returns:
            任务 ID
        """
        task_id = self.queue.enqueue(
            kind=TaskKind.INTERACTIVE_SEARCH,
            task_name=f"单图查询 {Path(query_image_path).name}",
            database_name=database_name,
            lane="interactive",
            total_items=1,
            top_n=top_n,
            batch_size=batch_size,
            config_preset=config_preset,
            config_yaml=config_yaml,
            payload={"query_image_path": query_image_path},
        )

        self.ensure_scheduler()
        return task_id

    # ---------- 查询与取消 ----------

    def get_task_status(self, task_id: str, database_name: str = "") -> Optional[Dict]:
        """取任务状态。

        Args:
            task_id: 任务 ID
            database_name: 保留参数，现队列为全局，不再需要按库定位

        Returns:
            任务字典；不存在时返回 ``None``
        """
        return self.queue.get_task(task_id)

    def list_tasks(
        self,
        database_name: Optional[str] = None,
        status_filter: Optional[str] = None,
        kind: Optional[str] = None,
    ) -> List[Dict]:
        """列出任务。

        Args:
            database_name: 按库筛选
            status_filter: 按状态筛选
            kind: 按类型筛选

        Returns:
            任务字典列表
        """
        return self.queue.list_tasks(
            database_name=database_name, status=status_filter, kind=kind
        )

    def read_task_payload(self, task: Dict) -> object:
        """Read a task's input payload for read-only result projection."""
        return self.queue.read_payload(task)

    def cancel_task(self, task_id: str, database_name: str = "") -> bool:
        """请求取消任务。

        排队中的任务立即取消；运行中的任务在条目边界停下 —— 直接杀进程会留下
        半写的索引文件。

        Args:
            task_id: 任务 ID
            database_name: 保留参数

        Returns:
            是否已取消或已受理取消请求
        """
        outcome = self.queue.request_cancel(task_id)
        return outcome in ("cancelled", "requested")

    def queue_position(self, task_id: str) -> Optional[int]:
        """排队中的任务前面还有几个。

        Args:
            task_id: 任务 ID

        Returns:
            前面的任务数；非排队状态返回 ``None``
        """
        return self.queue.queue_position(task_id)

    def counts_by_status(self, database_name: Optional[str] = None) -> Dict[str, int]:
        """各状态任务数。

        Args:
            database_name: 按库筛选

        Returns:
            状态到数量的映射
        """
        return self.queue.counts_by_status(database_name)

    def clear_history(self, database_name: Optional[str] = None) -> int:
        """清理终态任务记录。

        Args:
            database_name: 按库筛选

        Returns:
            删除的记录数
        """
        return self.queue.clear_terminal(database_name)

    def recover_orphans(self) -> int:
        """回收调度进程已死的运行中任务。

        Returns:
            被回收的任务数
        """
        return self.queue.recover_orphans()
