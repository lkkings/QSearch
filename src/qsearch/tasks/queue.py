"""全局任务队列。

单个 SQLite 文件承载所有库的任务。写入走 WAL + ``BEGIN IMMEDIATE``，因为
Streamlit 进程（入队、取消）与调度进程（取任务、写进度）并发访问同一文件。
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

logger = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"

# 心跳超过这个秒数且调度进程已不存在，判定为孤儿任务。
HEARTBEAT_TIMEOUT_SECONDS = 90.0


class TaskKind:
    """任务类型常量。"""

    INDEX_BUILD = "index_build"
    BATCH_SEARCH = "batch_search"
    INTERACTIVE_SEARCH = "interactive_search"

    ALL = (INDEX_BUILD, BATCH_SEARCH, INTERACTIVE_SEARCH)

    LABELS = {
        INDEX_BUILD: "索引构建",
        BATCH_SEARCH: "批量检索",
        INTERACTIVE_SEARCH: "单图查询",
    }


class TaskStatus:
    """任务状态常量。"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    TERMINAL = (COMPLETED, FAILED, CANCELLED)
    ALL = (PENDING, RUNNING, COMPLETED, FAILED, CANCELLED)

    LABELS = {
        PENDING: "排队中",
        RUNNING: "运行中",
        COMPLETED: "已完成",
        FAILED: "失败",
        CANCELLED: "已取消",
    }


class TaskCancelled(Exception):
    """任务被请求取消时由 runner 抛出，不是错误。"""


def _utcnow() -> str:
    """当前 UTC 时间的 ISO 字符串。

    Returns:
        形如 ``2026-09-01T12:00:00+00:00`` 的字符串
    """
    return datetime.now(timezone.utc).isoformat()


class TaskQueue:
    """任务队列的读写入口。

    实例本身不持有连接，每次操作短连接进出 —— Streamlit 会反复重跑脚本，
    长连接在这种模型下只会积累半开状态。
    """

    def __init__(self, queue_root: Path, timeout: float = 30.0):
        """初始化队列。

        Args:
            queue_root: 队列数据目录，存放 ``queue.db`` 与 ``payloads/``
            timeout: SQLite 锁等待秒数
        """
        self.queue_root = Path(queue_root)
        self.db_path = self.queue_root / "queue.db"
        self.payload_dir = self.queue_root / "payloads"
        self.timeout = timeout

        self.payload_dir.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        """建库建表。幂等。"""
        if not _SCHEMA_PATH.exists():
            raise FileNotFoundError(f"队列 schema 缺失：{_SCHEMA_PATH}")

        schema_sql = _SCHEMA_PATH.read_text(encoding="utf-8")

        with self._connect() as conn:
            conn.executescript(schema_sql)
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(task_queue)")
            }
            if "batch_size" not in columns:
                conn.execute(
                    "ALTER TABLE task_queue ADD COLUMN batch_size INTEGER NOT NULL DEFAULT 32"
                )
            conn.commit()

    @contextmanager
    def _connect(self, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        """打开一个连接。

        Args:
            immediate: 是否以 ``BEGIN IMMEDIATE`` 开启写事务。需要"读-改-写"
                原子性的操作（取任务）必须为 True，否则两个调度器可能取到同
                一行。

        Yields:
            已配置 row_factory 的连接
        """
        conn = sqlite3.connect(
            self.db_path,
            timeout=self.timeout,
            isolation_level=None,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row

        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")

            if immediate:
                conn.execute("BEGIN IMMEDIATE")

            yield conn

            if immediate:
                conn.execute("COMMIT")

        except Exception:
            if immediate:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
            raise

        finally:
            conn.close()

    # ---------- 入队 ----------

    def enqueue(
        self,
        kind: str,
        task_name: str,
        database_name: str,
        lane: str = "background",
        total_items: int = 0,
        num_workers: int | None = None,
        num_gpus: int = 0,
        top_n: int = 10,
        config_preset: str | None = None,
        config_yaml: str | None = None,
        payload: Any = None,
        batch_size: int = 32,
    ) -> str:
        """写入一个 pending 任务。

        Args:
            kind: :class:`TaskKind` 之一
            task_name: 可读任务名
            database_name: 目标数据库名
            lane: 车道名称，'background'（索引构建、批量检索）或 'interactive'（单图查询）
            total_items: 待处理条目数，用于进度百分比
            num_workers: CPU 工作进程数，None 表示自动
            num_gpus: GPU 数量，0 表示仅使用 CPU
            batch_size: 文本和图片特征提取的批大小
            top_n: 批量检索的每查询返回数
            config_preset: 配置预设名
            config_yaml: 自定义配置 YAML
            payload: 需落盘的载荷（如图像路径列表），JSON 可序列化

        Returns:
            任务 ID

        Raises:
            ValueError: 任务类型非法
        """
        if kind not in TaskKind.ALL:
            raise ValueError(f"未知任务类型：{kind}")
        num_gpus = int(num_gpus)
        if num_gpus < 0:
            raise ValueError(f"num_gpus must be at least 0, got {num_gpus}")
        batch_size = int(batch_size)
        if batch_size < 1:
            raise ValueError(f"batch_size must be at least 1, got {batch_size}")

        task_id = str(uuid.uuid4())
        payload_path = self._write_payload(task_id, payload) if payload is not None else None

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO task_queue (
                    task_id, kind, task_name, database_name, status, lane,
                    total_items, num_workers, num_gpus, batch_size, top_n,
                    config_preset, config_yaml, payload_path, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id, kind, task_name, database_name, TaskStatus.PENDING, lane,
                    total_items, num_workers, num_gpus, batch_size, top_n,
                    config_preset, config_yaml,
                    str(payload_path) if payload_path else None,
                    _utcnow(),
                ),
            )
            conn.commit()

        logger.info(
            "已入队 %s 任务 %s（库 %s，%d 条目，车道 %s）",
            TaskKind.LABELS.get(kind, kind), task_id[:8], database_name,
            total_items, lane,
        )
        return task_id

    def _write_payload(self, task_id: str, payload: Any) -> Path:
        """把载荷写到独立 JSON 文件。

        几万条图像路径塞进 TEXT 列会让每次 ``SELECT *`` 都拖着几 MB 走，
        而任务列表页每秒都在查。

        Args:
            task_id: 任务 ID
            payload: JSON 可序列化对象

        Returns:
            载荷文件路径
        """
        path = self.payload_dir / f"{task_id}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def read_payload(self, task: dict) -> Any:
        """读回任务载荷。

        Args:
            task: 任务字典

        Returns:
            载荷对象；无载荷时返回 ``None``
        """
        payload_path = task.get("payload_path")
        if not payload_path:
            return None

        path = Path(payload_path)
        if not path.exists():
            logger.warning("任务 %s 的载荷文件缺失：%s", task["task_id"][:8], path)
            return None

        return json.loads(path.read_text(encoding="utf-8"))

    # ---------- 调度侧 ----------

    def claim_next(self, scheduler_pid: int, lane: str = "background") -> dict | None:
        """原子地取出并占用最早的 pending 任务。

        读与写在同一个 ``BEGIN IMMEDIATE`` 事务内，否则两个调度器可能同时
        看到同一行 pending 并各自把它标成 running。

        Args:
            scheduler_pid: 调度进程 PID，写入行内供孤儿检测使用
            lane: 车道名称，'background' 或 'interactive'

        Returns:
            任务字典；无待执行任务时返回 ``None``
        """
        with self._connect(immediate=True) as conn:
            row = conn.execute(
                """
                SELECT * FROM task_queue
                WHERE status = ? AND cancel_requested = 0 AND lane = ?
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (TaskStatus.PENDING, lane),
            ).fetchone()

            if row is None:
                return None

            now = _utcnow()
            conn.execute(
                """
                UPDATE task_queue
                SET status = ?, started_at = COALESCE(started_at, ?),
                    heartbeat_at = ?, scheduler_pid = ?, error_message = NULL
                WHERE task_id = ?
                """,
                (TaskStatus.RUNNING, now, now, scheduler_pid, row["task_id"]),
            )

            task = dict(row)

        task["status"] = TaskStatus.RUNNING
        return task

    def update_progress(
        self,
        task_id: str,
        processed_items: int,
        failed_items: int = 0,
        last_processed_index: int | None = None,
        stage: str | None = None,
        total_items: int | None = None,
    ) -> None:
        """写入进度。

        Args:
            task_id: 任务 ID
            processed_items: 已处理数
            failed_items: 失败数
            last_processed_index: 断点续跑用的下标
            stage: 当前阶段的可读描述
            total_items: 修正后的总数（扫描后才知道真实数量的场景）
        """
        sets = [
            "processed_items = ?",
            "failed_items = ?",
            "heartbeat_at = ?",
        ]
        params: list[Any] = [processed_items, failed_items, _utcnow()]

        if total_items is not None:
            sets.append("total_items = ?")
            params.append(total_items)

        if last_processed_index is not None:
            sets.append("last_processed_index = ?")
            params.append(last_processed_index)

        if stage is not None:
            sets.append("stage = ?")
            params.append(stage)

        # 百分比由总数派生，避免调用方各算一遍算出不一致的值。
        #
        # 必须用绑定参数而非裸列名：UPDATE 的所有 SET 表达式读的都是本行的
        # 旧值，写成 processed_items * 100.0 / total_items 会拿上一次的
        # processed_items 去算，进度永远慢一拍（首次更新恒为 0）。
        # 右侧的 total_items 引用旧值是对的 —— 仅当本次也改它时才用参数。
        sets.append(
            "progress_percentage = CASE WHEN COALESCE(?, total_items) > 0"
            " THEN MIN(100.0, ? * 100.0 / COALESCE(?, total_items)) ELSE 0.0 END"
        )
        params.extend([total_items, processed_items, total_items])

        params.append(task_id)

        with self._connect() as conn:
            conn.execute(
                f"UPDATE task_queue SET {', '.join(sets)} WHERE task_id = ?",
                tuple(params),
            )
            conn.commit()

    def heartbeat(self, task_ids: Sequence[str]) -> None:
        """刷新心跳。

        Args:
            task_ids: 需要刷新的任务 ID
        """
        if not task_ids:
            return

        placeholders = ",".join("?" * len(task_ids))

        with self._connect() as conn:
            conn.execute(
                f"UPDATE task_queue SET heartbeat_at = ? WHERE task_id IN ({placeholders})",
                (_utcnow(), *task_ids),
            )
            conn.commit()

    def finish(
        self,
        task_id: str,
        status: str,
        error_message: str | None = None,
        stage: str | None = None,
    ) -> None:
        """把任务写入终态。

        Args:
            task_id: 任务 ID
            status: :class:`TaskStatus` 中的终态之一
            error_message: 失败原因
            stage: 收尾阶段描述

        Raises:
            ValueError: 状态不是终态
        """
        if status not in TaskStatus.TERMINAL:
            raise ValueError(f"{status} 不是终态")

        # 完成时把百分比钉到 100，避免因 total_items 估算偏差停在 99.7%。
        pct_sql = "100.0" if status == TaskStatus.COMPLETED else "progress_percentage"

        with self._connect() as conn:
            conn.execute(
                f"""
                UPDATE task_queue
                SET status = ?, completed_at = ?, error_message = ?,
                    stage = COALESCE(?, stage), progress_percentage = {pct_sql}
                WHERE task_id = ?
                """,
                (status, _utcnow(), error_message, stage, task_id),
            )
            conn.commit()

        logger.info("任务 %s 进入终态 %s", task_id[:8], status)

    # ---------- 查询与取消 ----------

    def get_task(self, task_id: str) -> dict | None:
        """按 ID 取任务。

        Args:
            task_id: 任务 ID

        Returns:
            任务字典；不存在时返回 ``None``
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM task_queue WHERE task_id = ?", (task_id,)
            ).fetchone()

        return dict(row) if row else None

    def list_tasks(
        self,
        database_name: str | None = None,
        status: str | None = None,
        kind: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        """列出任务，新的在前。

        Args:
            database_name: 按库筛选，``None`` 表示不筛选
            status: 按状态筛选
            kind: 按类型筛选
            limit: 返回上限

        Returns:
            任务字典列表
        """
        clauses: list[str] = []
        params: list[Any] = []

        if database_name:
            clauses.append("database_name = ?")
            params.append(database_name)

        if status:
            clauses.append("status = ?")
            params.append(status)

        if kind:
            clauses.append("kind = ?")
            params.append(kind)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM task_queue {where}
                ORDER BY
                    CASE status WHEN 'running' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END,
                    created_at DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()

        return [dict(row) for row in rows]

    def queue_position(self, task_id: str) -> int | None:
        """某个 pending 任务前面还排着几个。

        Args:
            task_id: 任务 ID

        Returns:
            0 表示下一个就是它；非 pending 任务返回 ``None``
        """
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS ahead FROM task_queue
                WHERE status = ? AND cancel_requested = 0
                  AND created_at < (SELECT created_at FROM task_queue WHERE task_id = ?)
                """,
                (TaskStatus.PENDING, task_id),
            ).fetchone()

            task = conn.execute(
                "SELECT status FROM task_queue WHERE task_id = ?", (task_id,)
            ).fetchone()

        if not task or task["status"] != TaskStatus.PENDING:
            return None

        return int(row["ahead"]) if row else None

    def request_cancel(self, task_id: str) -> str:
        """请求取消。

        pending 任务当场进入 cancelled；running 任务只置标志位，由 runner 在
        条目边界察觉后停下 —— 直接杀进程会留下半写的索引文件。

        Args:
            task_id: 任务 ID

        Returns:
            ``'cancelled'`` 已立即取消，``'requested'`` 已请求，
            ``'noop'`` 任务不存在或已在终态
        """
        with self._connect(immediate=True) as conn:
            row = conn.execute(
                "SELECT status FROM task_queue WHERE task_id = ?", (task_id,)
            ).fetchone()

            if row is None or row["status"] in TaskStatus.TERMINAL:
                return "noop"

            conn.execute(
                "UPDATE task_queue SET cancel_requested = 1 WHERE task_id = ?",
                (task_id,),
            )

            if row["status"] == TaskStatus.PENDING:
                conn.execute(
                    """
                    UPDATE task_queue
                    SET status = ?, completed_at = ?, stage = '排队中被取消'
                    WHERE task_id = ?
                    """,
                    (TaskStatus.CANCELLED, _utcnow(), task_id),
                )
                return "cancelled"

        return "requested"

    def is_cancel_requested(self, task_id: str) -> bool:
        """runner 在条目边界调用，判断是否该停下。

        Args:
            task_id: 任务 ID

        Returns:
            是否已请求取消
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT cancel_requested FROM task_queue WHERE task_id = ?", (task_id,)
            ).fetchone()

        return bool(row["cancel_requested"]) if row else False

    def counts_by_status(self, database_name: str | None = None) -> dict[str, int]:
        """各状态的任务数。

        Args:
            database_name: 按库筛选

        Returns:
            状态到数量的映射，未出现的状态为 0
        """
        where = "WHERE database_name = ?" if database_name else ""
        params = (database_name,) if database_name else ()

        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT status, COUNT(*) AS n FROM task_queue {where} GROUP BY status",
                params,
            ).fetchall()

        counts = {status: 0 for status in TaskStatus.ALL}
        for row in rows:
            counts[row["status"]] = int(row["n"])

        return counts

    # ---------- 孤儿回收 ----------

    def recover_orphans(self, live_pids: Iterable[int] = ()) -> int:
        """把调度进程已死的 running 任务放回队列。

        断电或强杀调度器后，行还停在 running。这些任务重新入队而非判失败：
        批量检索有断点，索引构建重跑也只是重做一次，都比留个假的"运行中"好。

        Args:
            live_pids: 仍存活的调度进程 PID

        Returns:
            被回收的任务数
        """
        live = set(live_pids)
        now = datetime.now(timezone.utc)
        recovered = 0

        with self._connect() as conn:
            rows = conn.execute(
                "SELECT task_id, scheduler_pid, heartbeat_at FROM task_queue WHERE status = ?",
                (TaskStatus.RUNNING,),
            ).fetchall()

            for row in rows:
                pid = row["scheduler_pid"]

                if pid in live:
                    continue

                # PID 仍存在但不在 live 集合里也可能是别的进程复用了号，
                # 因此再看心跳：新鲜心跳说明确有人在跑，不动它。
                if pid and _pid_alive(pid) and _heartbeat_fresh(row["heartbeat_at"], now):
                    continue

                conn.execute(
                    """
                    UPDATE task_queue
                    SET status = ?, scheduler_pid = NULL, started_at = NULL,
                        stage = '调度进程中断，已重新排队'
                    WHERE task_id = ?
                    """,
                    (TaskStatus.PENDING, row["task_id"]),
                )
                recovered += 1
                logger.warning("回收孤儿任务 %s（PID %s）", row["task_id"][:8], pid)

            conn.commit()

        return recovered

    def clear_terminal(self, database_name: str | None = None) -> int:
        """清理终态任务记录及其载荷文件。

        Args:
            database_name: 按库筛选，``None`` 表示全部

        Returns:
            删除的记录数
        """
        placeholders = ",".join("?" * len(TaskStatus.TERMINAL))
        params: list[Any] = list(TaskStatus.TERMINAL)
        where = f"status IN ({placeholders})"

        if database_name:
            where += " AND database_name = ?"
            params.append(database_name)

        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT task_id, payload_path FROM task_queue WHERE {where}",
                tuple(params),
            ).fetchall()

            conn.execute(f"DELETE FROM task_queue WHERE {where}", tuple(params))
            conn.commit()

        for row in rows:
            if row["payload_path"]:
                Path(row["payload_path"]).unlink(missing_ok=True)

        return len(rows)

    def cleanup_interactive_terminal(self, retention_hours: int = 24) -> int:
        """清理交互车道的过期终态任务。

        删除条件（三者同时满足）：
        1. lane = 'interactive'
        2. status 为终态（completed/failed/cancelled）
        3. completed_at 超过保留窗口

        后台车道的终态任务永久保留。
        排队中和运行中的交互任务不被删除。

        Args:
            retention_hours: 保留窗口（小时）

        Returns:
            删除的任务数
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=retention_hours)
        cutoff_str = cutoff.isoformat()

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT task_id, payload_path FROM task_queue
                WHERE lane = ?
                  AND status IN (?, ?, ?)
                  AND completed_at < ?
                """,
                (
                    "interactive",
                    TaskStatus.COMPLETED,
                    TaskStatus.FAILED,
                    TaskStatus.CANCELLED,
                    cutoff_str,
                ),
            ).fetchall()

            if not rows:
                return 0

            task_ids = [row["task_id"] for row in rows]
            placeholders = ",".join("?" * len(task_ids))

            conn.execute(
                f"DELETE FROM task_queue WHERE task_id IN ({placeholders})",
                task_ids,
            )
            conn.commit()

        # 删除载荷文件
        for row in rows:
            if row["payload_path"]:
                Path(row["payload_path"]).unlink(missing_ok=True)

        logger.info("清理了 %d 个交互车道过期任务", len(rows))
        return len(rows)


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
        # os.kill(pid, 0) 在 Windows 上不可用于探活，缺 psutil 时只能保守
        # 认为进程还在，让心跳新鲜度去做判定。
        return True

    return psutil.pid_exists(pid)


def _heartbeat_fresh(heartbeat_at: str | None, now: datetime) -> bool:
    """心跳是否仍在超时窗口内。

    Args:
        heartbeat_at: 心跳时间戳
        now: 当前时间

    Returns:
        心跳是否新鲜；无心跳记录视为不新鲜
    """
    if not heartbeat_at:
        return False

    try:
        stamp = datetime.fromisoformat(heartbeat_at)
    except ValueError:
        return False

    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)

    return (now - stamp).total_seconds() < HEARTBEAT_TIMEOUT_SECONDS
