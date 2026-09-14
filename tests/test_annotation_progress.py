"""标注身份、结果集归属与进度筛选。

覆盖 schema 约束（3.4-3.7）、upsert 写入语义（6.1-6.4）、进度筛选（9.8）
与历史候选的默认隐藏（10.1-10.3）。

这些行为的共同前提是「人工标注不能被一次重搜抹掉」，因此断言集中在
label / notes / labeled_at 三列在重搜前后是否保持不变。
"""

from __future__ import annotations

import itertools
import sqlite3
from pathlib import Path

import pytest

from qsearch.webui.annotation_manager import AnnotationManager
from qsearch.webui.result_store import save_query_result

_SCHEMA = Path(__file__).parent.parent / "src" / "qsearch" / "webui" / "schema.sql"

DB_NAME = "db1"
QUERY_IMG = "/img/query.png"


def _make_db(tmp_path: Path) -> tuple[Path, Path]:
    """建一个空标注库。

    Returns:
        ``(database_dir, annotations_db_path)``
    """
    db_dir = tmp_path / DB_NAME
    (db_dir / "annotations").mkdir(parents=True)
    db_path = db_dir / "annotations" / "annotations.db"

    conn = sqlite3.connect(db_path)
    conn.executescript(_SCHEMA.read_text(encoding="utf-8"))
    conn.commit()
    conn.close()

    return db_dir, db_path


def _results(*paths: str, elapsed: float = 12.0) -> dict:
    """构造一份检索结果，候选按传入顺序排名。"""
    return {
        "query_image": QUERY_IMG,
        "processing_time_ms": elapsed,
        "exact_matches": [],
        "content_matches": [
            {
                "image_path": path,
                "confidence_level": "HIGH",
                "overall_score": 0.9 - idx * 0.1,
                "text_score": 0.8,
                "visual_score": 0.7,
                "hash_distance": 3,
            }
            for idx, path in enumerate(paths)
        ],
    }


def _label(db_path: Path, candidate_path: str, label: str, notes: str = "看过了") -> None:
    """给一个候选打标注。"""
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        UPDATE candidates
        SET label = ?, notes = ?, labeled_at = '2026-01-01T00:00:00+00:00'
        WHERE candidate_image_path = ?
        """,
        (label, notes, candidate_path),
    )
    conn.commit()
    conn.close()


def _rows(db_path: Path) -> dict[str, sqlite3.Row]:
    """按候选图路径取回候选行。"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM candidates").fetchall()
    conn.close()
    return {row["candidate_image_path"]: row for row in rows}


# ---------- 3.4 / 6.1：Query 身份唯一 ----------


def test_reseach_keeps_single_query_row(tmp_path: Path) -> None:
    """同一 Query 图重搜后标注库中仍只有一行，且 query_id 不变。"""
    db_dir, db_path = _make_db(tmp_path)

    first = save_query_result(db_path, DB_NAME, QUERY_IMG, _results("/c1.png"), top_n=10)
    second = save_query_result(db_path, DB_NAME, QUERY_IMG, _results("/c1.png"), top_n=20)

    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM queries").fetchone()[0]
    top_n = conn.execute("SELECT top_n FROM queries").fetchone()[0]
    conn.close()

    assert count == 1
    # 命中 ON CONFLICT 时保留既有行的 ID —— 候选必须挂在存活的那一行上。
    assert first == second
    assert top_n == 20


# ---------- 6.2：重搜不覆盖人工标注 ----------


def test_reseach_preserves_human_label(tmp_path: Path) -> None:
    """已标注的候选在重搜后评分被更新，而 label / notes / labeled_at 不变。"""
    db_dir, db_path = _make_db(tmp_path)

    save_query_result(db_path, DB_NAME, QUERY_IMG, _results("/c1.png", "/c2.png"))
    _label(db_path, "/c1.png", "hit")

    before = _rows(db_path)["/c1.png"]

    # 重搜：同一候选换了排名与评分。
    save_query_result(db_path, DB_NAME, QUERY_IMG, _results("/c2.png", "/c1.png"))

    after = _rows(db_path)["/c1.png"]

    assert after["label"] == before["label"] == "hit"
    assert after["notes"] == before["notes"]
    assert after["labeled_at"] == before["labeled_at"]
    # 机器输出该更新：/c1.png 从 rank 1 掉到 rank 2。
    assert after["rank"] == 2


# ---------- 6.3：结果集归属可翻转 ----------


def test_dropped_candidate_keeps_label_and_is_marked(tmp_path: Path) -> None:
    """掉出结果集的候选保留标注并标记为 0，重新命中后标记回 1。"""
    db_dir, db_path = _make_db(tmp_path)

    save_query_result(db_path, DB_NAME, QUERY_IMG, _results("/c1.png", "/c2.png"))
    _label(db_path, "/c2.png", "miss")

    # 换配置重搜，/c2.png 掉出结果集。
    save_query_result(db_path, DB_NAME, QUERY_IMG, _results("/c1.png"))
    dropped = _rows(db_path)["/c2.png"]
    assert dropped["in_current_result"] == 0
    assert dropped["label"] == "miss", "掉出结果集不等于标注失效"

    # 再次重搜，/c2.png 重新命中。归属标记是可翻转的，不是软删除。
    save_query_result(db_path, DB_NAME, QUERY_IMG, _results("/c1.png", "/c2.png"))
    revived = _rows(db_path)["/c2.png"]
    assert revived["in_current_result"] == 1
    assert revived["label"] == "miss"


# ---------- 6.4：新候选以未标注状态进入 ----------


def test_new_candidate_enters_unlabeled(tmp_path: Path) -> None:
    """重搜引入的新候选 label 为空。"""
    db_dir, db_path = _make_db(tmp_path)

    save_query_result(db_path, DB_NAME, QUERY_IMG, _results("/c1.png"))
    _label(db_path, "/c1.png", "hit")
    save_query_result(db_path, DB_NAME, QUERY_IMG, _results("/c1.png", "/new.png"))

    assert _rows(db_path)["/new.png"]["label"] is None


# ---------- 9.8：四个进度筛选条件 ----------


@pytest.fixture()
def progress_db(tmp_path: Path) -> Path:
    """构造覆盖全部进度状态的库。

    Returns:
        数据集目录
    """
    db_dir, db_path = _make_db(tmp_path)
    conn = sqlite3.connect(db_path)

    def add_query(qid: str, day: int) -> None:
        conn.execute(
            """
            INSERT INTO queries (query_id, query_image_path, database_name,
                                 top_n, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (qid, f"/{qid}.png", DB_NAME, 10, "unlabeled", f"2026-01-{day:02d}"),
        )

    def add_cand(qid: str, path: str, label: str | None, rank: int, current: int = 1) -> None:
        conn.execute(
            """
            INSERT INTO candidates (query_id, rank, candidate_image_path, match_type,
                                    confidence_level, overall_score, label, in_current_result)
            VALUES (?, ?, ?, 'content', 'HIGH', 0.9, ?, ?)
            """,
            (qid, rank, path, label, current),
        )

    add_query("q_unlabeled", 1)
    add_cand("q_unlabeled", "/a1.png", None, 1)
    add_cand("q_unlabeled", "/a2.png", None, 2)

    add_query("q_partial", 2)
    add_cand("q_partial", "/b1.png", "miss", 1)
    add_cand("q_partial", "/b2.png", None, 2)

    add_query("q_nohit", 3)
    add_cand("q_nohit", "/c1.png", "miss", 1)
    add_cand("q_nohit", "/c2.png", "skip", 2)

    add_query("q_nocands", 4)

    add_query("q_done_hit", 5)
    add_cand("q_done_hit", "/d1.png", "hit", 1)

    # 当前结果集已标完，但存在一个未标注的历史候选。
    add_query("q_history", 6)
    add_cand("q_history", "/e1.png", "hit", 1)
    add_cand("q_history", "/e_old.png", None, 9, current=0)

    conn.commit()
    conn.close()
    return db_dir


@pytest.mark.parametrize(
    "progress,expected",
    [
        ("unlabeled", {"q_unlabeled"}),
        ("partial", {"q_partial"}),
        ("no_hit", {"q_nohit"}),
        ("no_candidates", {"q_nocands"}),
    ],
)
def test_progress_filter_matches_expectation(
    progress_db: Path, progress: str, expected: set[str]
) -> None:
    """四个条件各自返回的 Query 集合与手工构造的预期一致。"""
    manager = AnnotationManager(progress_db)
    got = {row["query_id"] for row in manager.list_queries_by_progress(DB_NAME, progress)}
    assert got == expected


def test_progress_filters_are_disjoint(progress_db: Path) -> None:
    """四个进度桶互不重叠。

    「已标注但无命中」按字面读会包含部分标注的 Query，与 partial 重叠；
    进度桶重叠会让筛选失去分流作用，故取「标注已完成且无命中」的严格读法。
    """
    manager = AnnotationManager(progress_db)
    buckets = {
        key: {row["query_id"] for row in manager.list_queries_by_progress(DB_NAME, key)}
        for key in AnnotationManager.PROGRESS_FILTERS
    }

    for left, right in itertools.combinations(buckets, 2):
        assert not (buckets[left] & buckets[right]), f"{left} 与 {right} 重叠"


def test_unknown_progress_filter_rejected(progress_db: Path) -> None:
    """未知筛选条件应显式报错，而非静默返回全部。"""
    manager = AnnotationManager(progress_db)
    with pytest.raises(ValueError):
        manager.list_queries_by_progress(DB_NAME, "nope")


# ---------- 10.1 / 10.2 / 10.3：历史候选 ----------


def test_history_candidate_hidden_by_default(progress_db: Path) -> None:
    """默认视图不含历史候选，开关打开后一并呈现且可辨识。"""
    manager = AnnotationManager(progress_db)

    default = manager.get_query_results("q_history")["candidates"]
    assert [c["candidate_image_path"] for c in default] == ["/e1.png"]

    full = manager.get_query_results("q_history", include_history=True)["candidates"]
    paths = [c["candidate_image_path"] for c in full]
    assert "/e_old.png" in paths
    # 历史身份由 in_current_result 承载，排序上也沉到当前候选之后。
    assert paths[-1] == "/e_old.png"
    assert {c["candidate_image_path"]: c["in_current_result"] for c in full}["/e_old.png"] == 0


def test_progress_counts_ignore_history(progress_db: Path) -> None:
    """标注进度只依据当前结果集：未标注的历史候选不拖住进度。"""
    manager = AnnotationManager(progress_db)
    row = next(
        r for r in manager.list_queries_by_progress(DB_NAME) if r["query_id"] == "q_history"
    )

    assert row["total"] == 1
    assert row["labeled"] == 1


def test_query_summaries_include_zero_candidate_queries(progress_db: Path) -> None:
    """Task navigation needs all Query rows, including the no-candidate state."""
    manager = AnnotationManager(progress_db)
    rows = {row["query_id"]: row for row in manager.list_query_summaries(DB_NAME)}

    assert rows["q_nocands"]["total"] == 0
    assert rows["q_nocands"]["labeled"] == 0
    assert rows["q_history"]["total"] == 1
    assert rows["q_history"]["labeled"] == 1


def test_trigger_ignores_stale_unlabeled_candidate(tmp_path: Path) -> None:
    """当前结果集标完即 completed，尽管有一个未标注的候选掉在结果集外。

    这是 3.6 的核心场景：旧触发器按「label IS NULL 的候选数为 0」判定，掉出
    结果集的未标注候选会让 query 永远停在 partial —— 一个做不完的任务。
    """
    db_dir, db_path = _make_db(tmp_path)

    save_query_result(db_path, DB_NAME, QUERY_IMG, _results("/keep.png", "/drops.png"))
    # 只标 /keep.png，/drops.png 始终未标注。
    _label(db_path, "/keep.png", "hit")

    # 重搜后 /drops.png 掉出结果集，且仍是未标注状态。
    save_query_result(db_path, DB_NAME, QUERY_IMG, _results("/keep.png"))

    rows = _rows(db_path)
    assert rows["/drops.png"]["in_current_result"] == 0
    assert rows["/drops.png"]["label"] is None

    # 触发器只在 label 更新时开火，因此重新标一次当前候选以驱动状态重算。
    _label(db_path, "/keep.png", "hit")

    conn = sqlite3.connect(db_path)
    status = conn.execute("SELECT status FROM queries").fetchone()[0]
    conn.close()

    assert status == "completed"


def test_trigger_completes_query_despite_unlabeled_history(tmp_path: Path) -> None:
    """当前结果集内候选全部标注时 query 变 completed，即使存在未标注历史候选。"""
    db_dir, db_path = _make_db(tmp_path)

    save_query_result(db_path, DB_NAME, QUERY_IMG, _results("/c1.png", "/c2.png"))
    _label(db_path, "/c1.png", "hit")
    _label(db_path, "/c2.png", "miss")

    # /c2.png 掉出结果集，且新候选 /c3.png 进来后被标注。
    save_query_result(db_path, DB_NAME, QUERY_IMG, _results("/c1.png", "/c3.png"))
    _label(db_path, "/c3.png", "miss")

    conn = sqlite3.connect(db_path)
    status = conn.execute("SELECT status FROM queries").fetchone()[0]
    stale = conn.execute(
        "SELECT COUNT(*) FROM candidates WHERE in_current_result = 0 AND label IS NOT NULL"
    ).fetchone()[0]
    conn.close()

    assert status == "completed", "历史候选不该让 query 永远停在 partial"
    assert stale == 1
