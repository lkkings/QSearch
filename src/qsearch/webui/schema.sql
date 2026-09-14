-- QSearch WebUI Database Schema
-- SQLite schema for annotation tracking and task management

-- Queries table: stores search queries and their metadata
CREATE TABLE IF NOT EXISTS queries (
    query_id TEXT PRIMARY KEY,
    query_image_path TEXT NOT NULL,
    database_name TEXT NOT NULL,
    top_n INTEGER NOT NULL DEFAULT 10,
    config_preset TEXT,
    config_yaml TEXT,
    status TEXT NOT NULL CHECK(status IN ('unlabeled', 'partial', 'completed')) DEFAULT 'unlabeled',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    processing_time_ms REAL,
    -- 标注条目的身份是「哪个库的哪张 Query 图」，不是每次搜索新生成的 uuid。
    -- query_id 仍为主键（外键与 URL 标识都依赖它），语义唯一性由这条约束保证。
    UNIQUE(database_name, query_image_path)
);

-- Candidates table: stores matching candidates for each query
CREATE TABLE IF NOT EXISTS candidates (
    candidate_id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_id TEXT NOT NULL,
    rank INTEGER NOT NULL,
    candidate_image_path TEXT NOT NULL,
    match_type TEXT NOT NULL CHECK(match_type IN ('exact', 'content')),
    confidence_level TEXT NOT NULL CHECK(confidence_level IN ('HIGH', 'MEDIUM', 'LOW')),
    overall_score REAL NOT NULL,
    text_score REAL,
    visual_score REAL,
    hash_distance INTEGER,
    label TEXT CHECK(label IN ('hit', 'miss', 'skip', NULL)),
    notes TEXT,
    labeled_at TEXT,
    -- 是否属于当前结果集。换配置重搜后掉出 top-N 的候选置 0 但保留其人工标注 ——
    -- 人的判断比机器的一次排序昂贵，不该被一次重搜抹掉。可在下次重搜翻回 1，
    -- 因此这是归属标记，不是软删除。
    in_current_result INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (query_id) REFERENCES queries(query_id) ON DELETE CASCADE,
    -- 候选身份是「这次查询的哪张 Match 图」，据此 upsert 才能保住 label。
    UNIQUE(query_id, candidate_image_path)
);

-- Tasks table: stores batch search tasks and their progress
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    task_name TEXT NOT NULL,
    database_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending', 'running', 'completed', 'failed', 'cancelled')) DEFAULT 'pending',
    total_items INTEGER NOT NULL DEFAULT 0,
    processed_items INTEGER NOT NULL DEFAULT 0,
    failed_items INTEGER NOT NULL DEFAULT 0,
    progress_percentage REAL NOT NULL DEFAULT 0.0,
    last_processed_index INTEGER DEFAULT -1,
    config_preset TEXT,
    config_yaml TEXT,
    top_n INTEGER NOT NULL DEFAULT 10,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    started_at TEXT,
    completed_at TEXT,
    process_id INTEGER
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_queries_database ON queries(database_name);
CREATE INDEX IF NOT EXISTS idx_queries_status ON queries(status);
CREATE INDEX IF NOT EXISTS idx_queries_created_at ON queries(created_at);

CREATE INDEX IF NOT EXISTS idx_candidates_query ON candidates(query_id);
CREATE INDEX IF NOT EXISTS idx_candidates_label ON candidates(label);
CREATE INDEX IF NOT EXISTS idx_candidates_match_type ON candidates(match_type);

CREATE INDEX IF NOT EXISTS idx_tasks_database ON tasks(database_name);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at);

-- Views for statistics

-- Stats summary view: overall database statistics
CREATE VIEW IF NOT EXISTS stats_summary AS
SELECT
    COUNT(DISTINCT q.query_id) AS total_queries,
    COUNT(DISTINCT CASE WHEN q.status = 'completed' THEN q.query_id END) AS completed_queries,
    COUNT(DISTINCT CASE WHEN q.status = 'unlabeled' THEN q.query_id END) AS unlabeled_queries,
    COUNT(c.candidate_id) AS total_candidates,
    COUNT(CASE WHEN c.label IS NOT NULL THEN c.candidate_id END) AS labeled_candidates,
    COUNT(CASE WHEN c.label = 'hit' THEN c.candidate_id END) AS hit_candidates,
    COUNT(CASE WHEN c.label = 'miss' THEN c.candidate_id END) AS miss_candidates,
    CASE
        WHEN COUNT(CASE WHEN c.label IS NOT NULL THEN c.candidate_id END) > 0
        THEN CAST(COUNT(CASE WHEN c.label = 'hit' THEN c.candidate_id END) AS REAL) /
             COUNT(CASE WHEN c.label IS NOT NULL THEN c.candidate_id END)
        ELSE 0.0
    END AS hit_rate
FROM queries q
LEFT JOIN candidates c ON q.query_id = c.query_id;

-- Candidate stats view: per-query statistics
CREATE VIEW IF NOT EXISTS candidate_stats AS
SELECT
    q.query_id,
    q.query_image_path,
    q.status,
    q.created_at,
    COUNT(c.candidate_id) AS total_candidates,
    COUNT(CASE WHEN c.label IS NOT NULL THEN c.candidate_id END) AS labeled_candidates,
    COUNT(CASE WHEN c.label = 'hit' THEN c.candidate_id END) AS hits,
    COUNT(CASE WHEN c.label = 'miss' THEN c.candidate_id END) AS misses,
    COUNT(CASE WHEN c.label = 'skip' THEN c.candidate_id END) AS skips,
    CASE
        WHEN COUNT(CASE WHEN c.label IS NOT NULL THEN c.candidate_id END) > 0
        THEN CAST(COUNT(CASE WHEN c.label = 'hit' THEN c.candidate_id END) AS REAL) /
             COUNT(CASE WHEN c.label IS NOT NULL THEN c.candidate_id END)
        ELSE NULL
    END AS hit_rate
FROM queries q
-- 统计只计入当前结果集。历史候选（in_current_result = 0）计进去会让进度分母
-- 随重搜次数单调增长，用户看到一个越做越多的任务。
LEFT JOIN candidates c
    ON q.query_id = c.query_id AND c.in_current_result = 1
GROUP BY q.query_id;

-- Trigger to update query status based on candidate labels
CREATE TRIGGER IF NOT EXISTS update_query_status
AFTER UPDATE OF label ON candidates
BEGIN
    UPDATE queries
    SET
        status = CASE
            -- 进度只看当前结果集。掉出结果集的未标注候选若参与判定，query 会
            -- 永远停在 partial —— 一个做不完的任务。
            WHEN (SELECT COUNT(*) FROM candidates
                  WHERE query_id = NEW.query_id
                    AND in_current_result = 1
                    AND label IS NULL) = 0
            THEN 'completed'
            WHEN (SELECT COUNT(*) FROM candidates
                  WHERE query_id = NEW.query_id
                    AND in_current_result = 1
                    AND label IS NOT NULL) > 0
            THEN 'partial'
            ELSE 'unlabeled'
        END,
        updated_at = datetime('now')
    WHERE query_id = NEW.query_id;
END;

-- Trigger to update query timestamp on any change
CREATE TRIGGER IF NOT EXISTS update_query_timestamp
AFTER UPDATE ON queries
FOR EACH ROW
WHEN NEW.updated_at = OLD.updated_at
BEGIN
    UPDATE queries SET updated_at = datetime('now') WHERE query_id = NEW.query_id;
END;
