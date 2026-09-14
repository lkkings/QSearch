"""检索结果落库 - Upsert 语义。

重搜同一 Query 时：
- queries: upsert（更新 top_n/config/processing_time_ms）
- candidates: upsert（更新 rank/scores，保留 label/notes/labeled_at）
- 结果集归属：本次未出现的候选置 in_current_result=0，重新出现的置回1
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from qsearch.webui.db_manager import get_database_manager

logger = logging.getLogger(__name__)

# queries 表的 upsert
_QUERY_UPSERT = """
    INSERT INTO queries (
        query_id, query_image_path, database_name, top_n,
        config_preset, config_yaml, status, created_at, processing_time_ms
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(database_name, query_image_path) DO UPDATE SET
        top_n = excluded.top_n,
        config_preset = excluded.config_preset,
        config_yaml = excluded.config_yaml,
        processing_time_ms = excluded.processing_time_ms,
        status = excluded.status
"""

# candidates 表的 upsert
# 只更新排名和评分相关字段，保留标注字段
_CANDIDATE_UPSERT = """
    INSERT INTO candidates (
        query_id, rank, candidate_image_path, match_type,
        confidence_level, overall_score, text_score, visual_score, hash_distance,
        in_current_result
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
    ON CONFLICT(query_id, candidate_image_path) DO UPDATE SET
        rank = excluded.rank,
        match_type = excluded.match_type,
        confidence_level = excluded.confidence_level,
        overall_score = excluded.overall_score,
        text_score = excluded.text_score,
        visual_score = excluded.visual_score,
        hash_distance = excluded.hash_distance,
        in_current_result = 1
    WHERE candidates.query_id = excluded.query_id
      AND candidates.candidate_image_path = excluded.candidate_image_path
"""

# 将不在本次结果中的候选标记为 in_current_result=0
_MARK_STALE_CANDIDATES = """
    UPDATE candidates
    SET in_current_result = 0
    WHERE query_id = ?
      AND candidate_image_path NOT IN ({placeholders})
"""


def save_query_result(
    annotations_db: Path,
    database_name: str,
    query_image_path: str,
    results: dict,
    top_n: int | None = None,
    config_preset: str | None = None,
    config_yaml: str | None = None,
    query_id: str | None = None,
) -> str:
    """保存或更新查询结果（upsert 语义）。

    对于已存在的 Query：
    - 更新 queries 表的配置和处理时间
    - upsert candidates，更新评分但保留标注
    - 将本次未出现的候选标记为 in_current_result=0

    Args:
        annotations_db: 标注库路径
        database_name: 数据库名
        query_image_path: 查询图像路径
        results: 搜索结果字典
        top_n: 本次请求的返回数，``None`` 时回退到结果字典或默认 10
        config_preset: 配置预设名
        config_yaml: 配置 YAML
        query_id: 新建行时使用的 ID。已存在的 Query 保留其原有 ID，此参数被忽略

    Returns:
        该 ``(database_name, query_image_path)`` 实际对应的 query_id
    """
    db_manager = get_database_manager(annotations_db)

    # 身份由 UNIQUE(database_name, query_image_path) 决定，query_id 只是新建
    # 行时的初值。调用方不再需要自己造 ID，造了也只在插入分支生效。
    new_query_id = query_id or results.get("query_id") or str(uuid.uuid4())

    if top_n is None:
        top_n = results.get("top_n", 10)

    logger.info(f"保存查询结果：{query_image_path}，库={database_name}")

    # 1. Upsert queries
    db_manager.execute_query(
        _QUERY_UPSERT,
        (
            new_query_id,
            query_image_path,
            database_name,
            top_n,
            config_preset,
            config_yaml,
            'unlabeled',
            datetime.now(timezone.utc).isoformat(),
            results.get("processing_time_ms"),
        ),
        fetch_all=False,
    )

    # 读回该路径对的实际 query_id。命中 ON CONFLICT 时保留的是既有行的 ID，
    # 不是上面刚生成的 new_query_id —— 候选必须挂在存活的那一行上，否则外键
    # 指向不存在的父行，重搜后标注全部失联。
    row = db_manager.execute_query(
        "SELECT query_id FROM queries WHERE database_name = ? AND query_image_path = ?",
        (database_name, query_image_path),
        fetch_one=True,
    )
    if row is None:
        raise RuntimeError(
            f"upsert 后未能读回 query 行：{database_name} / {query_image_path}"
        )
    query_id = row["query_id"]

    # 2. 收集本次结果的所有候选
    candidate_rows = []
    current_candidate_paths = []

    for match_type in ("exact", "content"):
        for rank, candidate in enumerate(results.get(f"{match_type}_matches", []), start=1):
            candidate_path = candidate["image_path"]
            current_candidate_paths.append(candidate_path)

            candidate_rows.append((
                query_id,
                rank,
                candidate_path,
                match_type,
                candidate["confidence_level"],
                candidate["overall_score"],
                candidate.get("text_score"),
                candidate.get("visual_score"),
                candidate.get("hash_distance"),
            ))

    # 3. Upsert candidates
    if candidate_rows:
        db_manager.execute_many(_CANDIDATE_UPSERT, candidate_rows)

    # 4. 标记不在本次结果中的候选为 in_current_result=0
    if current_candidate_paths:
        placeholders = ",".join("?" * len(current_candidate_paths))
        mark_stale_sql = _MARK_STALE_CANDIDATES.format(placeholders=placeholders)
        db_manager.execute_query(
            mark_stale_sql,
            (query_id, *current_candidate_paths),
            fetch_all=False,
        )
    else:
        # 本次没有候选，将所有旧候选标记为 0
        db_manager.execute_query(
            "UPDATE candidates SET in_current_result = 0 WHERE query_id = ?",
            (query_id,),
            fetch_all=False,
        )

    logger.info(f"已保存查询 {query_id[:8]}，{len(candidate_rows)} 个候选")
    return query_id
