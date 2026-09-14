"""Annotation manager for QSearch WebUI.

Handles candidate labeling, query status tracking, and statistics calculation.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from qsearch.webui.db_manager import get_database_manager

logger = logging.getLogger(__name__)


class AnnotationManager:
    """Manages annotation tracking and statistics."""

    def __init__(self, database_path: Path):
        """Initialize annotation manager.

        Args:
            database_path: Path to database directory
        """
        self.database_path = Path(database_path)
        self.annotations_db = self.database_path / "annotations" / "annotations.db"
        self.metadata_path = self.database_path / "metadata.json"

        if not self.annotations_db.exists():
            raise FileNotFoundError(f"Annotations database not found: {self.annotations_db}")

        self.db_manager = get_database_manager(self.annotations_db)

    def label_candidate(
        self,
        query_id: str,
        candidate_id: int,
        label: str,
        notes: Optional[str] = None,
    ) -> None:
        """Label a candidate result.

        Args:
            query_id: Query ID
            candidate_id: Candidate ID
            label: Label value ('hit', 'miss', or 'skip')
            notes: Optional annotation notes

        Raises:
            ValueError: If label is invalid
        """
        valid_labels = {'hit', 'miss', 'skip'}
        if label not in valid_labels:
            raise ValueError(f"Invalid label: {label}. Must be one of {valid_labels}")

        update_query = """
            UPDATE candidates
            SET label = ?, notes = ?, labeled_at = ?
            WHERE candidate_id = ? AND query_id = ?
        """

        self.db_manager.execute_query(
            update_query,
            (label, notes, datetime.utcnow().isoformat() + "Z", candidate_id, query_id),
            fetch_all=False,
        )

        logger.info(f"Labeled candidate {candidate_id} as '{label}'")

        # Query status is automatically updated by trigger

    def get_query_results(
        self, query_id: str, include_history: bool = False
    ) -> Optional[Dict]:
        """Get query with its candidates.

        默认只返回当前结果集内的候选。换配置重搜后掉出 top-N 的候选保留了人工
        标注但不属于当前结果集，混进默认视图会让标注员对着一份越搜越长的列表
        工作，且分不清哪些是本次结果。

        Args:
            query_id: Query ID
            include_history: 为 True 时一并返回历史候选（``in_current_result = 0``）

        Returns:
            Dictionary with query info and candidates list, or None if not found
        """
        # Get query info
        query_sql = "SELECT * FROM queries WHERE query_id = ?"
        query_row = self.db_manager.execute_query(query_sql, (query_id,), fetch_one=True)

        if not query_row:
            return None

        # Get candidates
        if include_history:
            candidates_sql = """
                SELECT * FROM candidates
                WHERE query_id = ?
                ORDER BY in_current_result DESC, match_type, rank
            """
        else:
            candidates_sql = """
                SELECT * FROM candidates
                WHERE query_id = ? AND in_current_result = 1
                ORDER BY match_type, rank
            """
        candidate_rows = self.db_manager.execute_query(candidates_sql, (query_id,))

        # Convert to dictionaries
        query_dict = dict(query_row)
        candidates_list = [dict(row) for row in candidate_rows]

        return {
            "query": query_dict,
            "candidates": candidates_list,
        }

    # 标注进度筛选条件。全部只统计 in_current_result = 1 的候选 —— 历史候选
    # 不属于当前结果集，计入会让「还剩什么没标」这个问题失去意义。
    #
    # 「一个都未标注」额外要求 total > 0：零候选的 Query 标注数同样为 0，若不
    # 加这条它会同时落入两个条件，而 spec 把二者列为并列条件。
    # 「已标注但无命中」要求标注已完成（labeled = total），而非只要有标注。
    # spec 的字面表述是「已有标注且其中没有任何命中」，按字面读部分标注的
    # Query 也会落进来，与 partial 重叠。取严格读法的理由：
    #   1. proposal 把四者列为「按标注进度」的并列条件，进度桶重叠无意义；
    #   2. 「无命中」只有在全部候选都看过之后才是成立的结论 —— 还有候选没标时，
    #      未标的那个可能正是命中，此时报「无命中」是错的。
    PROGRESS_FILTERS = {
        "unlabeled": "total > 0 AND labeled = 0",
        "partial": "labeled > 0 AND labeled < total",
        "no_hit": "total > 0 AND labeled = total AND hits = 0",
        "no_candidates": "total = 0",
    }

    PROGRESS_LABELS = {
        "unlabeled": "一个候选都未标注",
        "partial": "部分候选已标注",
        "no_hit": "已标注但无任何命中",
        "no_candidates": "没有任何候选",
    }

    def list_queries_by_progress(
        self, database_name: str, progress: Optional[str] = None
    ) -> List[Dict]:
        """按标注进度筛选 Query。

        Args:
            database_name: 数据库名
            progress: :attr:`PROGRESS_FILTERS` 的键之一；``None`` 表示不筛选

        Returns:
            Query 字典列表，附带 ``total``/``labeled``/``hits`` 三个计数

        Raises:
            ValueError: 筛选条件未知
        """
        if progress is not None and progress not in self.PROGRESS_FILTERS:
            raise ValueError(f"未知的标注进度筛选条件：{progress}")

        # 先聚合再筛选：条件作用于聚合结果，因此只能落在 HAVING 上。
        having = ""
        if progress:
            having = f"HAVING {self.PROGRESS_FILTERS[progress]}"

        sql = f"""
            SELECT
                q.*,
                COUNT(c.candidate_id) AS total,
                COUNT(CASE WHEN c.label IS NOT NULL THEN c.candidate_id END) AS labeled,
                COUNT(CASE WHEN c.label = 'hit' THEN c.candidate_id END) AS hits
            FROM queries q
            LEFT JOIN candidates c
                ON q.query_id = c.query_id AND c.in_current_result = 1
            WHERE q.database_name = ?
            GROUP BY q.query_id
            {having}
            ORDER BY q.created_at DESC
        """

        rows = self.db_manager.execute_query(sql, (database_name,))
        return [dict(row) for row in rows]

    def get_unlabeled_queries(self, database_name: str) -> List[Dict]:
        """Get queries with unlabeled candidates for annotation queue.

        Args:
            database_name: Database name to filter by

        Returns:
            List of query dictionaries with status='unlabeled' or 'partial'
        """
        query_sql = """
            SELECT * FROM queries
            WHERE database_name = ? AND status IN ('unlabeled', 'partial')
            ORDER BY created_at
        """

        rows = self.db_manager.execute_query(query_sql, (database_name,))
        return [dict(row) for row in rows]

    def list_query_summaries(self, database_name: str) -> List[Dict]:
        """Return every Query with current-result annotation counts.

        This is the read model used by task-based annotation navigation.  It is
        deliberately derived from existing tables and does not persist task
        membership or require a schema migration.
        """
        return self.list_queries_by_progress(database_name)

    def get_statistics(self) -> Dict:
        """Calculate current annotation statistics using views.

        Returns:
            Statistics dictionary
        """
        stats_sql = "SELECT * FROM stats_summary"
        result = self.db_manager.execute_query(stats_sql, fetch_one=True)

        if result:
            return {
                "total_queries": result["total_queries"] or 0,
                "completed_queries": result["completed_queries"] or 0,
                "unlabeled_queries": result["unlabeled_queries"] or 0,
                "total_candidates": result["total_candidates"] or 0,
                "labeled_candidates": result["labeled_candidates"] or 0,
                "hit_candidates": result["hit_candidates"] or 0,
                "miss_candidates": result["miss_candidates"] or 0,
                "hit_rate": float(result["hit_rate"] or 0.0),
            }

        return {
            "total_queries": 0,
            "completed_queries": 0,
            "unlabeled_queries": 0,
            "total_candidates": 0,
            "labeled_candidates": 0,
            "hit_candidates": 0,
            "miss_candidates": 0,
            "hit_rate": 0.0,
        }

    def get_query_statistics(self, query_id: str) -> Optional[Dict]:
        """Get statistics for a specific query.

        Args:
            query_id: Query ID

        Returns:
            Query statistics dictionary or None if not found
        """
        stats_sql = "SELECT * FROM candidate_stats WHERE query_id = ?"
        result = self.db_manager.execute_query(stats_sql, (query_id,), fetch_one=True)

        if result:
            return {
                "query_id": result["query_id"],
                "query_image_path": result["query_image_path"],
                "status": result["status"],
                "created_at": result["created_at"],
                "total_candidates": result["total_candidates"] or 0,
                "labeled_candidates": result["labeled_candidates"] or 0,
                "hits": result["hits"] or 0,
                "misses": result["misses"] or 0,
                "skips": result["skips"] or 0,
                "hit_rate": float(result["hit_rate"]) if result["hit_rate"] is not None else None,
            }

        return None

    def update_database_statistics(self) -> None:
        """Update statistics in metadata.json file.

        Refreshes the statistics field with current data from annotations database.
        """
        import json

        if not self.metadata_path.exists():
            logger.warning(f"Metadata file not found: {self.metadata_path}")
            return

        try:
            # Read current metadata
            with open(self.metadata_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)

            # Get current statistics
            stats = self.get_statistics()

            # Update metadata
            metadata["statistics"] = stats

            # Write back
            with open(self.metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)

            logger.info(f"Updated statistics in {self.metadata_path}")

        except Exception as e:
            logger.error(f"Failed to update database statistics: {e}")

    def delete_query(self, query_id: str) -> None:
        """Delete a query and all its candidates.

        Args:
            query_id: Query ID to delete

        Note:
            Candidates are automatically deleted via CASCADE foreign key.
        """
        delete_sql = "DELETE FROM queries WHERE query_id = ?"
        self.db_manager.execute_query(delete_sql, (query_id,), fetch_all=False)
        logger.info(f"Deleted query {query_id}")

    def get_annotation_queue(
        self,
        database_name: str,
        status_filter: Optional[str] = None,
    ) -> List[Dict]:
        """Get annotation queue with filtering.

        Args:
            database_name: Database name
            status_filter: Optional status filter ('unlabeled', 'partial', 'completed')

        Returns:
            List of query dictionaries sorted by creation date
        """
        if status_filter:
            query_sql = """
                SELECT * FROM queries
                WHERE database_name = ? AND status = ?
                ORDER BY created_at
            """
            rows = self.db_manager.execute_query(query_sql, (database_name, status_filter))
        else:
            query_sql = """
                SELECT * FROM queries
                WHERE database_name = ?
                ORDER BY created_at
            """
            rows = self.db_manager.execute_query(query_sql, (database_name,))

        return [dict(row) for row in rows]

    def get_next_unlabeled_query(
        self,
        database_name: str,
        current_query_id: Optional[str] = None,
    ) -> Optional[Dict]:
        """Get the next query that needs annotation.

        Args:
            database_name: Database name
            current_query_id: Current query ID (to find next after this one)

        Returns:
            Next unlabeled/partial query dictionary, or None if all complete
        """
        if current_query_id:
            # Find next query after current one
            query_sql = """
                SELECT * FROM queries
                WHERE database_name = ?
                  AND status IN ('unlabeled', 'partial')
                  AND created_at > (
                      SELECT created_at FROM queries WHERE query_id = ?
                  )
                ORDER BY created_at
                LIMIT 1
            """
            result = self.db_manager.execute_query(
                query_sql,
                (database_name, current_query_id),
                fetch_one=True,
            )
        else:
            # Get first unlabeled query
            query_sql = """
                SELECT * FROM queries
                WHERE database_name = ? AND status IN ('unlabeled', 'partial')
                ORDER BY created_at
                LIMIT 1
            """
            result = self.db_manager.execute_query(
                query_sql,
                (database_name,),
                fetch_one=True,
            )

        return dict(result) if result else None

    def get_unlabeled_candidates(self, query_id: str) -> List[Dict]:
        """Get unlabeled candidates for a query.

        Args:
            query_id: Query ID

        Returns:
            List of candidate dictionaries with label=NULL
        """
        query_sql = """
            SELECT * FROM candidates
            WHERE query_id = ? AND label IS NULL
            ORDER BY match_type, rank
        """

        rows = self.db_manager.execute_query(query_sql, (query_id,))
        return [dict(row) for row in rows]
