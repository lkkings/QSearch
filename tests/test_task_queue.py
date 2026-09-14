"""任务队列的行为测试。

覆盖入队、取任务的原子性、进度算法、取消语义、断点字段与孤儿回收。
"""

import os

import pytest

from qsearch.tasks.queue import TaskKind, TaskQueue, TaskStatus


@pytest.fixture
def queue(tmp_path):
    """指向临时目录的队列，不触碰真实项目队列。"""
    return TaskQueue(tmp_path / "queue")


class TestEnqueue:
    """入队与载荷。"""

    def test_enqueue_starts_pending(self, queue):
        """新任务处于 pending，进度为零。"""
        task_id = queue.enqueue(
            kind=TaskKind.INDEX_BUILD,
            task_name="建索引",
            database_name="db1",
            num_workers=4,
            total_items=100,
        )

        task = queue.get_task(task_id)

        assert task["status"] == TaskStatus.PENDING
        assert task["total_items"] == 100
        assert task["processed_items"] == 0
        assert task["num_workers"] == 4
        assert task["last_processed_index"] == -1
        assert task["started_at"] is None

    def test_rejects_unknown_kind(self, queue):
        """未知任务类型必须当场拒绝，而不是入队后由调度器失败。"""
        with pytest.raises(ValueError, match="未知任务类型"):
            queue.enqueue(
                kind="not_a_kind",
                task_name="x",
                database_name="db1",
                num_workers=1,
            )

    def test_payload_roundtrips_off_row(self, queue):
        """载荷落盘而非入行，避免列表查询拖着几 MB 走。"""
        paths = [f"img_{i}.jpg" for i in range(500)]

        task_id = queue.enqueue(
            kind=TaskKind.BATCH_SEARCH,
            task_name="批量",
            database_name="db1",
            num_workers=2,
            total_items=len(paths),
            payload=paths,
        )

        task = queue.get_task(task_id)

        assert task["payload_path"] is not None
        assert queue.read_payload(task) == paths

    def test_missing_payload_file_is_tolerated(self, queue):
        """载荷文件被外部删掉时返回 None，不抛异常。"""
        task_id = queue.enqueue(
            kind=TaskKind.BATCH_SEARCH,
            task_name="批量",
            database_name="db1",
            num_workers=1,
            payload=["a.jpg"],
        )

        task = queue.get_task(task_id)
        os.unlink(task["payload_path"])

        assert queue.read_payload(task) is None


class TestClaim:
    """取任务。"""

    def test_claims_fifo(self, queue):
        """先入队的先执行。"""
        first = queue.enqueue(TaskKind.INDEX_BUILD, "a", "db1", num_workers=1)
        second = queue.enqueue(TaskKind.INDEX_BUILD, "b", "db1", num_workers=1)

        assert queue.claim_next(os.getpid())["task_id"] == first
        assert queue.claim_next(os.getpid())["task_id"] == second
        assert queue.claim_next(os.getpid()) is None

    def test_claim_marks_running_with_pid(self, queue):
        """取任务时写入调度器 PID，供孤儿检测使用。"""
        task_id = queue.enqueue(TaskKind.INDEX_BUILD, "a", "db1", num_workers=1)

        queue.claim_next(4242)
        task = queue.get_task(task_id)

        assert task["status"] == TaskStatus.RUNNING
        assert task["scheduler_pid"] == 4242
        assert task["started_at"] is not None
        assert task["heartbeat_at"] is not None

    def test_claim_skips_cancelled(self, queue):
        """已请求取消的排队任务不该被取出执行。"""
        skipped = queue.enqueue(TaskKind.INDEX_BUILD, "a", "db1", num_workers=1)
        wanted = queue.enqueue(TaskKind.INDEX_BUILD, "b", "db1", num_workers=1)

        queue.request_cancel(skipped)

        assert queue.claim_next(os.getpid())["task_id"] == wanted

    def test_queue_position_counts_only_ahead(self, queue):
        """队列位置只算前面的排队任务。"""
        first = queue.enqueue(TaskKind.INDEX_BUILD, "a", "db1", num_workers=1)
        second = queue.enqueue(TaskKind.INDEX_BUILD, "b", "db1", num_workers=1)
        third = queue.enqueue(TaskKind.INDEX_BUILD, "c", "db1", num_workers=1)

        assert queue.queue_position(first) == 0
        assert queue.queue_position(second) == 1
        assert queue.queue_position(third) == 2

        # 取走第一个后，它不再是排队状态。
        queue.claim_next(os.getpid())
        assert queue.queue_position(first) is None
        assert queue.queue_position(second) == 0


class TestProgress:
    """进度算法。"""

    def test_percentage_uses_new_values(self, queue):
        """百分比必须反映本次写入的值。

        UPDATE 的所有 SET 表达式读的都是旧行值，若百分比表达式引用裸列名
        ``processed_items``，算出的是上一次的进度 —— 首次更新恒为 0。
        """
        task_id = queue.enqueue(
            TaskKind.INDEX_BUILD, "a", "db1", num_workers=1, total_items=10
        )
        queue.claim_next(os.getpid())

        queue.update_progress(task_id, processed_items=5)

        assert queue.get_task(task_id)["progress_percentage"] == 50.0

    def test_percentage_follows_corrected_total(self, queue):
        """总数被修正时，百分比按新总数计算。"""
        task_id = queue.enqueue(
            TaskKind.INDEX_BUILD, "a", "db1", num_workers=1, total_items=10
        )
        queue.claim_next(os.getpid())

        queue.update_progress(task_id, processed_items=5, total_items=20)

        task = queue.get_task(task_id)
        assert task["total_items"] == 20
        assert task["progress_percentage"] == 25.0

    def test_zero_total_does_not_divide(self, queue):
        """总数为零时百分比为 0，不能抛除零错误。"""
        task_id = queue.enqueue(TaskKind.INDEX_BUILD, "a", "db1", num_workers=1)
        queue.claim_next(os.getpid())

        queue.update_progress(task_id, processed_items=0)

        assert queue.get_task(task_id)["progress_percentage"] == 0.0

    def test_completion_pins_percentage_to_full(self, queue):
        """完成时百分比钉到 100，避免因总数估算偏差停在 99.x%。"""
        task_id = queue.enqueue(
            TaskKind.INDEX_BUILD, "a", "db1", num_workers=1, total_items=1000
        )
        queue.claim_next(os.getpid())
        queue.update_progress(task_id, processed_items=997)

        queue.finish(task_id, TaskStatus.COMPLETED)

        assert queue.get_task(task_id)["progress_percentage"] == 100.0

    def test_failure_preserves_partial_percentage(self, queue):
        """失败时保留已完成的进度，便于判断卡在何处。"""
        task_id = queue.enqueue(
            TaskKind.INDEX_BUILD, "a", "db1", num_workers=1, total_items=100
        )
        queue.claim_next(os.getpid())
        queue.update_progress(task_id, processed_items=30)

        queue.finish(task_id, TaskStatus.FAILED, error_message="磁盘满")

        task = queue.get_task(task_id)
        assert task["progress_percentage"] == 30.0
        assert task["error_message"] == "磁盘满"

    def test_checkpoint_index_persists(self, queue):
        """断点下标必须落库，否则续跑无从下手。"""
        task_id = queue.enqueue(
            TaskKind.BATCH_SEARCH, "a", "db1", num_workers=1, total_items=100
        )
        queue.claim_next(os.getpid())

        queue.update_progress(task_id, processed_items=42, last_processed_index=41)

        assert queue.get_task(task_id)["last_processed_index"] == 41

    def test_finish_rejects_non_terminal_status(self, queue):
        """finish 只接受终态。"""
        task_id = queue.enqueue(TaskKind.INDEX_BUILD, "a", "db1", num_workers=1)

        with pytest.raises(ValueError, match="不是终态"):
            queue.finish(task_id, TaskStatus.RUNNING)


class TestCancel:
    """取消语义。"""

    def test_pending_cancels_immediately(self, queue):
        """排队中的任务无需等调度器，当场进入 cancelled。"""
        task_id = queue.enqueue(TaskKind.INDEX_BUILD, "a", "db1", num_workers=1)

        assert queue.request_cancel(task_id) == "cancelled"
        assert queue.get_task(task_id)["status"] == TaskStatus.CANCELLED

    def test_running_only_flags(self, queue):
        """运行中的任务只置标志，由 runner 在条目边界停下。

        直接改状态或杀进程会留下半写的索引文件。
        """
        task_id = queue.enqueue(TaskKind.INDEX_BUILD, "a", "db1", num_workers=1)
        queue.claim_next(os.getpid())

        assert queue.request_cancel(task_id) == "requested"

        task = queue.get_task(task_id)
        assert task["status"] == TaskStatus.RUNNING
        assert task["cancel_requested"] == 1
        assert queue.is_cancel_requested(task_id) is True

    def test_terminal_cancel_is_noop(self, queue):
        """已完成的任务不能被取消。"""
        task_id = queue.enqueue(TaskKind.INDEX_BUILD, "a", "db1", num_workers=1)
        queue.claim_next(os.getpid())
        queue.finish(task_id, TaskStatus.COMPLETED)

        assert queue.request_cancel(task_id) == "noop"
        assert queue.get_task(task_id)["status"] == TaskStatus.COMPLETED

    def test_unknown_task_cancel_is_noop(self, queue):
        """不存在的任务 ID 不该抛异常。"""
        assert queue.request_cancel("no-such-task") == "noop"


class TestListing:
    """筛选与统计。"""

    def test_filters_compose(self, queue):
        """库、状态、类型三个筛选条件可叠加。"""
        queue.enqueue(TaskKind.INDEX_BUILD, "a", "db1", num_workers=1)
        queue.enqueue(TaskKind.BATCH_SEARCH, "b", "db1", num_workers=1)
        queue.enqueue(TaskKind.INDEX_BUILD, "c", "db2", num_workers=1)

        assert len(queue.list_tasks(database_name="db1")) == 2
        assert len(queue.list_tasks(kind=TaskKind.INDEX_BUILD)) == 2
        assert len(
            queue.list_tasks(database_name="db1", kind=TaskKind.BATCH_SEARCH)
        ) == 1

    def test_running_sorts_first(self, queue):
        """运行中的任务排在最前 —— 那是用户最需要看到的。"""
        queue.enqueue(TaskKind.INDEX_BUILD, "first", "db1", num_workers=1)
        second = queue.enqueue(TaskKind.INDEX_BUILD, "second", "db1", num_workers=1)

        # 取走第二个，使其成为 running 而非队首。
        queue.request_cancel(
            queue.list_tasks(status=TaskStatus.PENDING)[0]["task_id"]
        )
        queue.claim_next(os.getpid())

        tasks = queue.list_tasks()
        assert tasks[0]["task_id"] == second
        assert tasks[0]["status"] == TaskStatus.RUNNING

    def test_counts_cover_all_statuses(self, queue):
        """统计包含所有状态键，未出现的为 0。"""
        queue.enqueue(TaskKind.INDEX_BUILD, "a", "db1", num_workers=1)

        counts = queue.counts_by_status()

        assert counts[TaskStatus.PENDING] == 1
        assert counts[TaskStatus.FAILED] == 0
        assert set(counts) == set(TaskStatus.ALL)

    def test_clear_terminal_keeps_active(self, queue):
        """清理历史只删终态任务，不动排队与运行中的。"""
        done = queue.enqueue(TaskKind.INDEX_BUILD, "done", "db1", num_workers=1)
        queue.claim_next(os.getpid())
        queue.finish(done, TaskStatus.COMPLETED)

        queue.enqueue(TaskKind.INDEX_BUILD, "waiting", "db1", num_workers=1)

        assert queue.clear_terminal() == 1
        assert queue.get_task(done) is None
        assert len(queue.list_tasks()) == 1

    def test_clear_terminal_removes_payload_file(self, queue):
        """清理历史时载荷文件一并删除，否则磁盘只增不减。"""
        task_id = queue.enqueue(
            TaskKind.BATCH_SEARCH, "a", "db1", num_workers=1, payload=["x.jpg"]
        )
        payload_path = queue.get_task(task_id)["payload_path"]
        queue.claim_next(os.getpid())
        queue.finish(task_id, TaskStatus.COMPLETED)

        queue.clear_terminal()

        assert not os.path.exists(payload_path)


class TestOrphanRecovery:
    """孤儿回收。"""

    def test_dead_scheduler_task_requeued(self, queue):
        """调度进程已死的运行中任务重新排队，而非判失败。

        批量检索有断点，索引构建重跑也只是重做一次；留个假的"运行中"最糟。
        """
        task_id = queue.enqueue(
            TaskKind.BATCH_SEARCH, "a", "db1", num_workers=1, total_items=100
        )
        queue.claim_next(999_999)  # 几乎不可能存在的 PID
        queue.update_progress(task_id, processed_items=40, last_processed_index=39)

        assert queue.recover_orphans() == 1

        task = queue.get_task(task_id)
        assert task["status"] == TaskStatus.PENDING
        assert task["scheduler_pid"] is None
        # 断点保留，续跑才能从第 40 条继续。
        assert task["last_processed_index"] == 39

    def test_live_scheduler_task_untouched(self, queue):
        """自己在跑的任务不该被自己回收。"""
        task_id = queue.enqueue(TaskKind.INDEX_BUILD, "a", "db1", num_workers=1)
        queue.claim_next(os.getpid())

        assert queue.recover_orphans(live_pids=[os.getpid()]) == 0
        assert queue.get_task(task_id)["status"] == TaskStatus.RUNNING

    def test_pending_tasks_not_affected(self, queue):
        """排队中的任务不参与孤儿回收。"""
        task_id = queue.enqueue(TaskKind.INDEX_BUILD, "a", "db1", num_workers=1)

        assert queue.recover_orphans() == 0
        assert queue.get_task(task_id)["status"] == TaskStatus.PENDING
