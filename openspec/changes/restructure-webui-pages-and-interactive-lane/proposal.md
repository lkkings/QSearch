## Why

单图查询目前在 Streamlit 进程内就地构造 `SearchEngine`，模型随会话驻留：每个并发会话各占一套约 1.5GB 的 OCR 与编码器副本，且推理与页面渲染抢同一份 CPU。同时四个页面共处 `st.tabs`，Streamlit 每次 rerun 会执行全部标签页的 body，一次查询连带重跑标注与任务监控。

标注列表则缺少稳定身份：`queries.query_id` 是每次搜索新生成的 uuid4，同一张 Query 图重复检索会产出多条看似重复的行；而 `result_store.save_query_result` 在 ID 相撞时走 `DELETE ... CASCADE`，会连带删除已有的人工标注。人工判断比机器的一次排序更昂贵，不该被一次重搜抹掉。

## What Changes

### 页面结构

- 以 `st.navigation` / `st.Page` 取代顶层 `st.tabs`，只执行当前页面的 body。
- 主页仅保留两个标签页：数据集管理、任务监控。
- 数据集管理含创建表单与列表两部分；列表数据字段居中呈现，行内操作仅保留详情、搜索、标注三个跳转按钮。
- **BREAKING** 删除操作从列表行移入详情页面。
- 创建数据集成功后清空表单，并提示可前往任务监控查看索引构建进度。
- 索引构建任务在数据集创建成功后自动入队，不再由复选框控制。
- 可分享状态（数据库名、query_id）进入 URL 查询参数；纯视图偏好（网格列数、专注模式）留在 session state。

### 图标

- **BREAKING** 移除界面中的 emoji 文字图标，改用 Material Symbols：部件走 `icon=":material/xxx:"`，自拼 HTML 的 chip/badge 走 Material Symbols 字体加 CSS。
- 保留「状态不得仅依赖颜色」的无障碍冗余：每个状态的图标必须在字形形状上互相区分，不得退化为仅颜色不同的同一图标。

### 任务车道

- 任务队列引入 `lane` 维度：`background`（索引构建、批量检索）与 `interactive`（单图查询）。
- 调度进程为两个车道各跑一个取任务循环、各持一个进程池，互不可见，长时间索引构建无法饿死交互查询。
- 新增任务类型 `interactive_search`：不做断点续跑，结果写入 `annotations.db`，队列行只承载状态机。
- 交互车道的终态行超过保留窗口后由调度器自动清理；后台车道行保留供用户查阅历史。
- 单图查询在 UI 上仍是同步观感：入队后以 `st.fragment` 轮询该任务状态，终态后停止轮询并渲染结果，脚本本身不阻塞。

### 进程池与并行度

- **BREAKING** 删除 `task_queue.num_workers` 列；并行度不再随任务入队，改由启动参数决定。
- **BREAKING** 移除 UI 中三处并行数滑块（创建数据库、构建索引、批量检索）。
- 启动脚本新增两个非对称参数：`--max-workers`（后台车道池大小）与 `--interactive-workers`（交互车道池大小，默认 2，上限 4）。
- 进程池键从 `(kind, spec_hash, num_workers)` 改为 `(kind, model_config_hash)`，不再包含 `database_path`：换库不再销毁并重建池。
- worker 内改为两层缓存：`FeatureExtractor` 按模型配置缓存（容量 1），索引与 matcher 按数据库路径 LRU 缓存（容量 4）。

### 标注列表身份与筛选

- **BREAKING** `queries` 表加 `UNIQUE(database_name, query_image_path)`，`candidates` 表加 `UNIQUE(query_id, candidate_image_path)`：标注条目由 Query 图路径与 Match 图路径唯一关联。
- **BREAKING** 写入语义由「删除重建」改为 upsert：候选的 `label`、`notes`、`labeled_at` 在重搜时一律不被覆盖。
- 新增 `candidates.in_current_result` 列。重搜后掉出结果集的候选保留其人工标注，并标记为不在当前结果集。
- 查询筛选器支持按标注进度筛选，初始集合为：一个候选都未标注、部分标注、已标注但无命中、无候选。
- 提供 `annotations.db` 迁移：合并现有重复的 `(database_name, query_image_path)` 分组，label 冲突取 `labeled_at` 最新的非空值，支持 dry-run 报告。

### 非目标

- 不引入独立的推理服务进程；交互查询复用现有队列加车道隔离。
- 不改变匹配算法、索引格式与配置预设语义。
- 不实现多用户认证或会话隔离之外的访问控制。

## Capabilities

### New Capabilities

`openspec/specs/` 当前为空 —— 此前的 `streamlit-webui` 与 `redesign-webui-dark-workbench` 均未 sync 回主 spec。因此本 change 的全部 capability 都以新建方式落笔，路径沿用那两个 change 建立的 `webui/<capability>` 组织方式，archive 时生成对应主 spec。

- `webui/page-navigation`: 页面路由与主页结构、URL 承载的可分享状态、页面间跳转
- `webui/task-lanes`: 任务车道划分、交互查询任务类型、车道级并发与饥饿隔离、交互行清理
- `webui/worker-pools`: 进程池键与两层模型缓存、启动参数决定的并行度、内存预算与降级
- `webui/interactive-search`: 单图与批量查询的提交路径、结果呈现、按标注进度筛选 Query
- `webui/result-annotation`: 标注条目的唯一身份、重搜时人工标注的保全、结果集归属标记
- `webui/database-management`: 数据集创建与列表、行内跳转操作、详情页承载删除
- `webui/async-tasks`: 队列的车道维度、任务生命周期、进度与取消
- `webui/design-system`: 图标体系与状态呈现的无障碍冗余

### Modified Capabilities

无 —— `openspec/specs/` 为空，没有既有 requirement 可改。

## Impact

### 数据库迁移

- `src/qsearch/webui/schema.sql`：`queries` 与 `candidates` 加唯一约束，`candidates` 加 `in_current_result` 列，`update_query_status` 触发器需排除不在当前结果集的行。
- `src/qsearch/tasks/schema.sql`：`task_queue` 加 `lane` 列，`kind` 的 CHECK 增加 `interactive_search`，删除 `num_workers` 列。
- 现有 `annotations.db` 几乎必然含重复 Query 行，加唯一约束前必须先合并。

### 源码

- `src/qsearch/webui/app.py`：tabs 改 navigation，页面注册与 URL 参数解析。
- `src/qsearch/webui/ui/`：`database_ui.py`、`search_ui.py`、`annotation_ui.py`、`task_ui.py`、`components.py` 均需改动；新增详情页与标注筛选器。
- `src/qsearch/webui/search_engine.py`：拆分共享提取器与按库索引，`search_single` 接受注入的提取器。
- `src/qsearch/webui/result_store.py`：DELETE-CASCADE 改 upsert。
- `src/qsearch/tasks/`：`queue.py`（车道感知的 `claim_next`、入队签名）、`scheduler.py`（双循环双池）、`worker_pool.py`（池键与两层缓存）、`settings.py`（交互并行度裁决）；新增 `runner_interactive.py`。
- `scripts/start_webui.py`：新增 `--interactive-workers`，内存预算校验与降级提示。
- `src/qsearch/webui/styles/`：引入 Material Symbols 字体与图标 CSS。

### 依赖

- 需要 Material Symbols 字体资源（自托管，避免运行期依赖外部 CDN）。
- 无新增 Python 包。

### 并存的未完成 change

`redesign-webui-dark-workbench` 尚有 10.1-10.6 六项验证任务未完成（对比度核算、灰度可辨性、动效时长、键盘全流程、补丁版本启动、交互延迟基线）。本 change 会重画相关页面，那些验证若先做会失效，故并入本 change 的验证阶段一次完成。
