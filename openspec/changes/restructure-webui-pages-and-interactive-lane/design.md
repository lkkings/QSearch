## Context

动机见 proposal.md「Why」。此处只记录塑造方案的现状约束。

**现有任务链已经可用。** `tasks/queue.py`（全局 SQLite 队列，WAL + `BEGIN IMMEDIATE`）、`scheduler.py`（锁文件保证单例，`ThreadPoolExecutor`）、`worker_pool.py`（spawn 池 + worker 内模块级模型缓存）三者构成的后台链条已经在跑索引构建与批量检索，且不阻塞界面。本 change 不重写它，而是在其上开一条车道。

**四处硬约束：**

1. `PoolRegistry` 只缓存一个池，键为 `(kind, _spec_key(spec), num_workers)`，而 `spec` 含 `database_path`。换库即键不匹配，触发 `close()` 后重新 `WorkerPool(...)` —— 销毁进程、重新加载模型。
2. `SearchEngine.__init__` 把两类资源混在一个构造函数里：`FeatureExtractor(self.config)`（重，约 1.5GB，只依赖模型配置）与 `_build_matcher()`（读 `features.pkl`、`text_index.faiss`、`hash_index.pkl`，只依赖数据集）。
3. `result_store.save_query_result` 在 `query_id` 命中已有行时执行 `DELETE FROM queries`，而 `candidates` 有 `ON DELETE CASCADE` —— 连带删除人工标注。当前 `query_id` 是 `uuid4()`，实际永不命中，所以这条路径尚未造成损失；一旦改为路径派生的稳定键，它立刻变成数据丢失路径。
4. `st.tabs` 的四个 body 在每次 rerun 全量执行。`search_ui.py:36-38` 的注释记录了由此产生的部件 ID 冲突，靠给 selectbox 加 `key` 绕过。

**多用户是真实场景。** 需求明确要求「不能阻塞别的用户使用该页面」，因此模型不能驻留在 Streamlit 进程内。

## Goals / Non-Goals

**Goals:**

- 把推理搬出 Streamlit 进程，使模型副本数与浏览器会话数解耦。
- 让交互查询与后台任务在资源上隔离，长任务无法饿死短查询。
- 让模型在换任务、换数据集时都不重新加载。
- 把并行度的决定权收敛到启动时一处。
- 给标注数据一个稳定身份，使人工判断在重搜后不丢失。

**Non-Goals:**

- 不引入独立推理服务进程（见「决策 1」的取舍）。
- 不追求交互查询的极低延迟；接受入队与轮询带来的约 0.3 秒固定开销。
- 不实现跨机器分布式执行。
- 不改动匹配算法、索引格式、配置预设语义。
- 不实现用户认证；「多用户」仅指多个匿名浏览器会话。

## Decisions

### 决策 1：交互查询走队列的独立车道，而非独立服务进程

**选择**：在 `task_queue` 上加 `lane` 维度，调度进程为两条车道各跑一个取任务循环、各持一个 `PoolRegistry`。

```
+-- Streamlit 进程（每会话一个 ScriptRunner 线程）------------+
|   提交查询 --> enqueue(lane='interactive')                 |
|   st.fragment(run_every=0.4) 轮询该 task_id 的 status      |
|   terminal --> 从 annotations.db 读结果 --> 渲染           |
|   进程内不驻留任何模型                                      |
+------------------------------------------------------------+
                    |  data/queue/tasks.db (WAL)
                    v
+-- 调度进程（锁文件单例）------------------------------------+
|                                                            |
|  背景循环                      交互循环                     |
|  claim_next('background')     claim_next('interactive')    |
|  max_concurrent = 1           max_concurrent = M           |
|  PoolRegistry_bg              PoolRegistry_ia              |
|      |                            |                        |
|      v  N workers                 v  M workers             |
|  extractor 池                 searcher 池                  |
|                                                            |
|  两个循环各自独立 claim，互不可见 --> 无饥饿                |
+------------------------------------------------------------+
```

**为什么不用独立服务进程**：探索阶段两个方案都成立，服务进程在延迟上更优（无入队与轮询开销）。选队列方案的理由是复用面：`lockfile.py` 的单例保证、`queue.py` 的孤儿回收与心跳、`task_ui.py` 的进度呈现、取消语义，四者已经存在且经过调试。服务进程要把这四样在一套平行机制里重做一遍。代价是延迟下限约 0.3 秒（一次 SQLite 写 + 平均 0.2 秒轮询），对「提交单图后看结果」这个交互而言可以接受。

**为什么不是在单车道里加优先级排序**：`claim_next` 改成按优先级取，仍受 `max_concurrent = 1` 制约 —— 一个跑两小时的索引构建占满唯一额度，高优先级的查询依然要等两小时。要解决必须允许并发，而并发又需要独立的池，于是自然落到「两个循环、两个池」。优先级排序在单额度下解决不了饥饿，这是它被排除的原因。

**取舍**：调度进程从单循环变双循环，`_running_ids` 与心跳逻辑要按车道分组。这是本 change 里 `scheduler.py` 的主要复杂度增量。

### 决策 2：池键降维到模型配置，worker 内做两层缓存

**选择**：池键从 `(kind, spec_hash, num_workers)` 改为 `(kind, model_config_hash)`；worker 内分两层缓存。

```
池键 = (kind, model_config_hash)        不含 database_path，不含 num_workers
        |
        v  worker 进程内
   第一层  FeatureExtractor      按 model_config_hash 缓存，容量 1
           约 1.5GB。同配置的所有数据集共用一份
   第二层  索引 + matcher        按 database_path LRU 缓存，容量 4
           features.pkl + FAISS + hash 索引，每库几十至几百 MB
```

**为什么**：模型只依赖配置中与模型相关的部分，索引只依赖数据集。混在一个哈希里，等于让「换库」这个轻量操作触发「重建进程 + 重载模型」这个最重的操作。两个会话交替查不同库时，这比就地推理更慢 —— 会退化到每次查询都付一次模型加载。

`_MODEL_CACHE_LIMIT = 2` 救不了这个问题：那是 worker 内的缓存，而池被 `close()` 时整个进程组连缓存一起消失。

**为什么第二层容量取 4**：索引比模型小一到两个数量级，多缓存几个的边际成本低；4 覆盖「同时使用少数几个数据集」这一实际形态，超出后 LRU 淘汰的代价只是重读索引文件，不涉及模型。

**为什么不合并两条车道的 extractor 池**：配置相同时，索引构建与交互查询用的是同一个 `FeatureExtractor`，理论上可共享进程组以省一份模型。不做是因为共享即耦合 —— 一旦共享，索引构建占满进程时交互查询又开始等待，决策 1 争取到的隔离被抵消。用一份额外内存换隔离，是自觉的取舍。

**连带修复**：池键去掉 `num_workers` 后，「用户在不同页面拖了不同并行数导致连续任务各自重建池」这一既有浪费随之消失。

**要改的结构**：`SearchEngine` 拆为「共享提取器」与「按库索引」两部分，`search_single` 接受注入的提取器。这是本 change 中唯一触及检索路径的结构性改动，需保证匹配结果与改动前逐字节一致 —— 验证阶段以同一组查询比对新旧结果。

### 决策 3：两个非对称的并行度参数

**选择**：`--max-workers`（后台，默认沿用现有 `default_max_workers()` 推算）与 `--interactive-workers`（交互，默认 2，上限 4）。

| | 后台车道 | 交互车道 |
|---|---|---|
| 工作单元 | 数万张图 | 1 张图 |
| 优化目标 | 吞吐 | 延迟 |
| 增加 worker 的收益 | 近线性提速 | 只增并发人数，单次不变快 |
| 内存驻留期 | 任务执行期间 | 永久（复用模型即不能回收） |

**为什么非对称**：交互 worker 永久驻留，其数量该由「同时使用的人数」决定，而非 CPU 核数。给交互车道 8 个进程是用 12GB 常驻内存换一个不存在的并发需求。上限定在 4，是因为再高说明该走真正的服务化，不该靠堆常驻进程解决。

**为什么不是一个参数劈成两半**：`N/2` 各分一半会让后台吞吐直接腰斩，而后台是这个系统的主要负载。

**内存降级策略**：启动时估算 `(N + M) × WORKER_MEMORY_GB`，超出可用内存时降 M 不降 N —— 降 N 是可感知的吞吐退化，降 M 只在多人并发时排队。降级必须打印原因与降级后的值，不静默。

**裁决点**：`settings.py` 保持单一裁决点，新增 `clamp_interactive_workers`，与 `clamp_workers` 共享 `CPU_COUNT` 上限但各有默认值与天花板。

### 决策 4：标注身份改为路径对，写入语义改 upsert

**选择**：

```sql
queries    UNIQUE(database_name, query_image_path)
candidates UNIQUE(query_id, candidate_image_path)
candidates ADD COLUMN in_current_result INTEGER NOT NULL DEFAULT 1
```

写入语义三段式：

```
queries      ON CONFLICT DO UPDATE   更新 top_n / config / processing_time_ms
candidates   ON CONFLICT DO UPDATE   只更新 rank / match_type /
                                     confidence_level / *_score / hash_distance
                                     label、notes、labeled_at 不在 SET 列表中
本次未命中的  UPDATE in_current_result = 0
本次重新命中的 UPDATE in_current_result = 1
```

**为什么保留而非删除掉出结果集的候选**（已确认的决定）：人工判断的获取成本远高于机器的一次排序。换配置重搜后某张图掉出 top-N，不意味着「之前判它 miss」这件事失效了。删除等于丢失不可再生的数据；保留只是让列表变长，而列表长度可以用筛选解决。

**`in_current_result` 而非软删除标记**：语义是「是否属于当前结果集」，不是「是否已删除」。它可以在下一次重搜中翻回 1，软删除语义不支持这种复活。

**触发器必须同步改**：现有 `update_query_status` 按「`label IS NULL` 的候选数为 0」判 completed。不改则一条掉出结果集的未标注候选会让 query 永远停在 partial —— 用户看到一个永远做不完的任务。新条件需排除 `in_current_result = 0` 的行。

**`query_id` 保留为主键**：不改为复合主键。`query_id` 仍是 uuid，但由 `(database_name, query_image_path)` 的唯一约束保证语义唯一性。这样 `candidates.query_id` 外键、`ON DELETE CASCADE`、以及 URL 中的查询标识都不需要变形为复合键。

### 决策 5：交互任务的结果经 annotations.db 交付

**选择**：交互任务的结果写入数据集的 `annotations.db`，`task_queue` 行只承载状态机。

**为什么不在队列行里存结果**：结果无论如何都要进标注列表（需求明确要求「查询成功的都需要添加到标注列表中去」）。存两份就要处理两份之间的一致性。队列行只留状态，UI 拿到 terminal 状态后按 `query_id` 从标注库读，是唯一数据源。

**交互行的清理**：交互任务以「每次查询一行」的速度堆积，若不清理，任务监控会被单图查询淹没，`task_queue` 也会无界增长。规则是删除 `lane='interactive'` 且处于终态且超过保留窗口的行；后台行永久保留。清理必须跳过非终态行。

**失败时不留半条记录**：查询失败则不向 `annotations.db` 写入，避免标注列表出现没有候选、也没有有效元数据的空 Query。

### 决策 6：页面化用框架原生路由，URL 只承载对象标识

**选择**：`st.navigation` / `st.Page`（Streamlit 1.63.0 已支持）取代顶层 `st.tabs`。

```
主页 /              st.tabs([数据集管理, 任务监控])
详情 ?db=X
搜索 ?db=X
标注 ?db=X&query=Y
```

**URL 承载什么**：标识「看的是哪个对象」的进 URL（`db`、`query`）；纯视图偏好留 session（`qs_grid_cols`、`qs_focus_mode`）。判据是「换个人打开这个链接，他想看到同一个东西吗」—— 对象是，个人偏好不是。

**连带收益**：只执行当前页面的 body，修掉 `search_ui.py:36-38` 记录的部件 ID 冲突根因；一次查询不再连带重跑标注页与任务监控页。

**参数校验**：`?db=` 或 `?query=` 指向不存在的对象时，给可读提示并回主页，不抛未捕获异常 —— URL 是用户可编辑的输入，属于系统边界。

### 决策 7：图标分两条通道落地

`st.markdown` 不解析 `:material/xxx:` 语法，该语法只在部件参数中生效。因此：

- 部件（`st.button`、`st.Page`、`st.tabs`、`st.info` 等）用 `icon=":material/xxx:"`。
- `components.py` 的 chip / badge 是自拼 HTML 经 `st.markdown(unsafe_allow_html=True)` 输出，改为挂 CSS class，字形由自托管的 Material Symbols 字体经 `::before` 注入。

**字体自托管**：不引 CDN。离线环境必须能正常呈现图标，且外部资源会在每次页面加载引入一次不可控的网络等待。

**必须守住的约束**：`components.py` 现有的 `✓ ✗ ▲ ◷ ◔ ⊘` 不是随手写的装饰 —— 文件头注释与 design-system spec 都要求「状态不得仅依赖颜色」，图标是给红绿色盲（男性约 8%）的冗余通道。换成 Material 图标可以，但同一状态族内各取值必须字形不同，不能退化成「同一个圆点，只有颜色不同」。这条已写入 spec 的 `状态图标字形互相区分`。

## Risks / Trade-offs

**[两套模型常驻，内存占用近乎翻倍]** → 8 核默认 `(7 + 2) × 1.5GB = 13.5GB`。启动时估算并在超出可用内存时降 M 不降 N，且打印原因。这是为换取车道隔离而自觉接受的成本，已与用户确认。

**[`SearchEngine` 拆分可能改变检索结果]** → 拆分触及唯一的检索路径。验证阶段以同一组查询图在改动前后比对结果，要求候选集合、排名与各项评分完全一致。发现不一致即视为拆分错误，不接受「差异很小」。

**[标注库迁移不可逆]** → 现有库几乎必然含重复 Query 行，合并涉及 label 冲突取舍。缓解：迁移强制先出报告（将合并 N 组、M 条冲突）；执行前备份 `annotations.db`；迁移幂等，重复执行无额外影响。

**[双循环调度器的并发缺陷更难察觉]** → 单循环时 `_running_ids` 与心跳只有一条路径，双循环后有两条。缓解：车道状态按车道分组隔离，两个循环不共享 `PoolRegistry`（池非线程安全，共享会让 `imap` 结果错位）；针对「后台跑长任务时交互查询仍能被取走」写显式测试。

**[轮询给 SQLite 带来额外读压力]** → 每个等待中的查询每 0.4 秒读一次 `task_queue`。队列是 WAL 模式，读不阻塞写；且交互并行度上限 4 意味着并发轮询数有界。终态后立即停止轮询。

**[交互行清理可能误删]** → 清理条件必须同时满足「lane 为 interactive」「状态为终态」「超过保留窗口」。缺任一条件都可能删掉在跑任务的行，使其变成孤儿。针对三个条件各写一个反例测试。

**[框架补丁升级冲掉自定义样式]** → 图标改造引入新的 CSS 依赖面（Material Symbols 字体 + `::before` 注入），扩大了对框架 DOM 结构的依赖。缓解：沿用既有的 `st-key-*` 稳定标识机制挂样式；在相邻补丁版本上启动验证（继承自 `redesign-webui-dark-workbench` 的 10.5）。

**[并行数滑块移除是可感知的功能回退]** → 习惯按任务调并行数的用户会失去这个控制点。这是需求明确要求的方向（并行度改由启动参数决定），且换来池复用率提升。任务监控需如实呈现「实际并行度」，不让用户对生效值产生疑问。

## Migration Plan

**顺序有依赖，不可重排：**

1. **备份**：`annotations.db` 与 `data/queue/tasks.db`。
2. **`tasks.db` 迁移**：加 `lane` 列（默认 `background`，使既有行自动归入后台车道）、`kind` 的 CHECK 增加 `interactive_search`、删除 `num_workers` 列。既有 pending 行的旧并行度值一律忽略，改用启动参数 —— 无需数据迁移，删列即可。
3. **`annotations.db` 报告**：以报告模式运行迁移，得到将合并的分组数与 label 冲突数。分组数为 0 说明库是干净的，可直接进第 5 步。
4. **`annotations.db` 合并**：按 `(database_name, query_image_path)` 分组，保留 `created_at` 最早的 `query_id` 为主行（早的更可能已被标注），其余行的候选按 `candidate_image_path` 归并；label 冲突取 `labeled_at` 最新的非空值；删除被归并的 query 行。
5. **加约束与列**：建唯一约束、加 `in_current_result` 列、重建 `update_query_status` 触发器与 `candidate_stats` 视图。
6. **代码切换**：池键与两层缓存 → 车道与交互 runner → 页面化 → 图标。前两步是后两步的前提（页面化后的搜索页要调用交互车道）。

**回滚**：第 2 至 5 步靠备份回滚。代码回滚需连同 schema 一起退回 —— 加了唯一约束的 `annotations.db` 在旧代码下仍可读写（旧代码用 uuid 主键，不会撞唯一约束），但 `in_current_result` 列旧代码不认，会把历史候选一并当作当前结果呈现。因此回滚代码时应同时恢复数据库备份。

**验证并入**：`redesign-webui-dark-workbench` 未完成的 10.1-10.6（对比度核算、灰度可辨、动效时长、键盘全流程、相邻补丁版本、交互延迟基线）在本 change 的验证阶段一次完成。那些页面会被本 change 重画，先做会失效。
