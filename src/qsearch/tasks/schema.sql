-- QSearch 全局任务队列
--
-- 与 webui/schema.sql 里那张按库分片的 tasks 表不同，这里是单一全局队列：
-- 调度器只需轮询一个文件，跨库任务也能有确定的先后顺序。

CREATE TABLE IF NOT EXISTS task_queue (
    task_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK(kind IN ('index_build', 'batch_search', 'interactive_search')),
    task_name TEXT NOT NULL,
    database_name TEXT NOT NULL,
    status TEXT NOT NULL
        CHECK(status IN ('pending', 'running', 'completed', 'failed', 'cancelled'))
        DEFAULT 'pending',
    lane TEXT NOT NULL DEFAULT 'background'
        CHECK(lane IN ('background', 'interactive')),

    -- 进度
    total_items INTEGER NOT NULL DEFAULT 0,
    processed_items INTEGER NOT NULL DEFAULT 0,
    failed_items INTEGER NOT NULL DEFAULT 0,
    progress_percentage REAL NOT NULL DEFAULT 0.0,
    last_processed_index INTEGER NOT NULL DEFAULT -1,
    stage TEXT,

    -- 执行参数
    num_workers INTEGER,
    num_gpus INTEGER NOT NULL DEFAULT 0,
    batch_size INTEGER NOT NULL DEFAULT 32,
    top_n INTEGER NOT NULL DEFAULT 10,
    config_preset TEXT,
    config_yaml TEXT,

    -- 大体积载荷（图像路径列表）落盘，不塞进行内
    payload_path TEXT,

    -- 生命周期
    error_message TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    heartbeat_at TEXT,
    scheduler_pid INTEGER
);

CREATE INDEX IF NOT EXISTS idx_queue_status ON task_queue(status);
CREATE INDEX IF NOT EXISTS idx_queue_database ON task_queue(database_name);
CREATE INDEX IF NOT EXISTS idx_queue_kind ON task_queue(kind);
CREATE INDEX IF NOT EXISTS idx_queue_created ON task_queue(created_at);

-- 待执行队列的取任务顺序：FIFO。
CREATE INDEX IF NOT EXISTS idx_queue_pending ON task_queue(status, created_at);

-- 按车道取任务的索引
CREATE INDEX IF NOT EXISTS idx_queue_lane_status ON task_queue(lane, status, created_at);
