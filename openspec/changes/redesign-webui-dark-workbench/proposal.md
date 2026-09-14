## Why

标注是 QSearch 中唯一高频、长时间、需要持续视觉判断的工作，但当前 WebUI 把它当作与「数据库管理」「搜索」「任务监控」平级的一个标签页来对待：共享同一套宽松边距与 1400px 宽度上限，装饰性渐变占据视觉注意力，而**候选图像根本没有渲染**——`annotation_ui.py:94` 与 `:119` 只把文件路径当 caption 打出来。一个依赖肉眼比对图像相似度的工具，现在让标注员看两行路径文字。

同时，界面在深色模式下是破损的而非缺失的：`app.py` 的自定义 CSS 全为硬编码亮色值（`background: white`、`color: #2c3e50`、亮色侧边栏渐变、亮色系 badge），一旦系统或浏览器切到深色，界面即呈现亮暗混杂。项目中不存在 `.streamlit/config.toml`，主题完全跟随浏览器，无基线可控。

此外三个非样式缺陷会直接否决任何视觉重构的成效：任务页每 5 秒强制重跑整个应用（`task_ui.py:82-85` 的阻塞式 `time.sleep` + `st.rerun`，配合 `st.tabs` 全量执行，标注过程被周期性打断）；删库这一不可逆操作只是一段可被滚走的折叠区（`database_ui.py:143` 用 `st.expander` 而非 `st.dialog`）；键盘流从未接线（`create_annotation_shortcuts` 定义于 `shortcuts.py:93` 但全项目无调用，且其 fallback 试图用 `postMessage` 写 `st.session_state`，这不是 Streamlit 组件协议的工作方式）。对以吞吐量为核心指标的标注工具而言，键盘可用性比视觉层更值钱。

## What Changes

**视觉体系（暗色单一模式）**

- 建立 `.streamlit/config.toml` 并锁定 `base="dark"`，先在原生主题层定下基线，再叠加自定义 CSS，消除二者互相打架
- 引入五级表面令牌（`surface-0` 至 `surface-4`）。深色模式下**高度以表面明度表达，而非阴影堆叠**——这一条同时满足 Flat 2.0 的「主体零阴影零渐变」与 Material 的「清晰层级」，阴影仅保留给真正的浮层
- 决策色与系统信息色**分离为两套**：高饱和色（荧光绿/鲜红）只可能表示人给出的判断，机器输出的置信度走低饱和冷调。二者同色会让标注员分不清「这是我判的」与「这是机器猜的」，对标注质量是直接损害
- 任何状态不得仅靠颜色区分（绿/红对红绿色盲不可靠），图标或形状为必要冗余
- 移除装饰性渐变：h1 渐变裁字（`app.py:186-192`）、主按钮紫渐变（`:63-67`）、进度条渐变（`:161-164`）、标签条选中态渐变（`:109-126`）、侧边栏渐变（`:144-146`）
- 圆角差异化而非全局统一：表格行 2px、控件 6px、卡片 10px、模态 14px。统一半径会浪费横向空间
- 毛玻璃**仅用于三处浮层**：长任务进度 toast、快捷键速查 popover、危险操作确认 dialog。三者共同点是「背后有内容值得透出」；卡片、表格、侧栏一律不用，半透明降对比度与「减少视觉疲劳 + 高信息密度」直接对撞

**标注工作台（网格模式）**

- 重构为单一网格视图：查询图锚定在上，候选网格在下，卡片自带评分与标注状态，**点击卡片直接标注，不设逐个细看模式**
- 评分数据从当前占据 8 行垂直空间的三列 markdown（`annotation_ui.py:99-117`）压缩进卡片本体，垂直空间归还给图像
- **BREAKING** 键盘模型由线性推进改为二维网格导航：方向键移动网格焦点（而非顺序前进/后退），`1`/`0`/`S` 标注当前焦点卡片，`Enter` 进入下一题。原「上/左=上一个候选、下/右=下一个候选」的线性语义不再成立
- 补齐 `st.image` 图像渲染（全项目当前零处使用）
- 标注进入「专注模式」：侧栏收起、边距压缩、放开 1400px 宽度上限，图像取得最大可用空间
- 快捷键提示移至按钮本体与 `?` 唤出的浮层，不再仅存于侧栏文字（`annotation_ui.py:220-227`）

**行为缺陷修复**

- 任务页自动刷新改为非阻塞，且不得重跑标注页
- 删除数据库确认改为 `st.dialog` 真模态
- 接通 `create_annotation_shortcuts`，替换走不通的 `postMessage` fallback

**技术前提**

- 全面弃用 Streamlit 生成的哈希类名（`app.py:129` 的 `.css-1r6slb0`），改用 `data-testid` 选择器
- 将 `streamlit>=1.30.0`（`requirements.txt:43`）钉为确定版本——哈希类名与 DOM 结构随版本漂移
- 统一 UI 文案语言：`app.py` 为中文，四个 UI 模块全为英文

## Capabilities

> 说明：`openspec/specs/` 当前为零文件——`streamlit-webui`、`fix-index-build-and-docs`、`configurable-question-matcher` 三个变更均为 complete 但**未归档**，故不存在任何 base spec。因此下列四项全部登记为 New Capabilities：MODIFIED/REMOVED delta 需要 base spec 才能套用，在空 specs 目录上会失败或产出畸形结果。四条路径沿用 `streamlit-webui` 已建立的 `webui/<capability>` 约定，archive 时将据此创建主 spec。
>
> 其中 `webui/result-annotation`、`webui/async-tasks`、`webui/database-management` 三项虽为新建 spec，但描述的是**既有功能的行为变更**——它们的当前实现已存在于代码中。这三份 spec 完整陈述该能力变更后的目标行为，而非仅记录增量。

### New Capabilities

- `webui/design-system`: 暗色单一主题下的视觉契约。涵盖表面层级模型（明度而非阴影）、决策色与系统信息色的语义隔离、非颜色冗余要求、对比度阈值、动效时长上限、半透明的准入条件、交互目标尺寸，以及样式在依赖升级后的稳定性约束。
- `webui/result-annotation`: 标注工作台的目标行为。交互模型为「查询图锚定 + 候选网格直接标注」（替代当前的顺序单候选比对），键盘导航为二维网格语义（替代线性推进），候选图像必须渲染而非仅显示路径。**BREAKING** 原「上/左=上一候选、下/右=下一候选」的线性键位语义不再成立。
- `webui/async-tasks`: 任务进度观察的目标行为。自动刷新不得阻塞服务端处理，且不得导致无关界面区域（尤其标注界面）重新加载。
- `webui/database-management`: 数据库管理的目标行为。删除确认必须为模态，不可为页内可滚走的折叠区；列表以高密度形式呈现。

### Modified Capabilities

无。见上方说明——空 specs 目录下无 base spec 可供 diff。

## Impact

**代码**

| 文件 | 变更性质 |
|---|---|
| `.streamlit/config.toml` | 新建，锁定 `base="dark"` |
| `src/qsearch/webui/app.py` | 约 190 行内联 CSS（`:40-229`）替换为令牌体系；tabs 结构调整以支持专注模式 |
| `src/qsearch/webui/ui/annotation_ui.py` | 重写为网格布局；接入 `st.image`；接通键盘流 |
| `src/qsearch/webui/ui/task_ui.py` | 移除 `time.sleep` + `st.rerun` 刷新机制（`:82-85`） |
| `src/qsearch/webui/ui/database_ui.py` | 删除确认改 `st.dialog`（`:136-165`）；列表改紧凑表格（`:47-83`） |
| `src/qsearch/webui/ui/search_ui.py` | 组件外观对齐令牌；文案中文化 |
| `src/qsearch/webui/utils/shortcuts.py` | 重写为可用实现；键位映射适配网格模型 |
| `requirements.txt` | Streamlit 版本由 `>=1.30.0` 钉为确定值 |

业务逻辑层（`search_engine.py`、`annotation_manager.py`、`database_manager.py`、`task_manager.py`、`db_manager.py`、`exporter.py`）不在本次范围内。UI 与逻辑分离良好，这是本次重构可控的前提。

**依赖**

- Streamlit 需 ≥1.31（`st.dialog` 引入版本），钉版本时需一并确认
- 可能需要引入或替换键盘快捷键方案；`streamlit-shortcuts>=0.1.0`（`requirements.txt:44`）的实际可用性待验证

**明确不在范围内（Non-goals）**

- **rerun 开销优化**：`st.tabs` 当前全量执行四个页面，且 `search_ui.py:21-22`、`annotation_ui.py:19-20`、`task_ui.py:19-20` 各自重建 `DatabaseManager` 并调用未缓存的 `list_databases()`，标注页的 `get_unlabeled_queries` / `get_query_results` / `get_statistics` 每次全跑。**这意味着 120ms 的动效时长不会带来 120ms 的观感**——单次点击仍是一整轮服务端往返，实际体验为「动画很快，然后界面冻住」。本次接受这一现状，但它是后续独立变更的首要候选。
- 亮色模式：仅做深色单一模式，令牌与对比度验证各一套。
- 画布类标注能力（画框、多边形、骨骼打点、时间轴）：QSearch 的标注是 hit/miss/skip 判断，不涉及几何标注。
- 四段式固定布局与画布浮动工具栏：Streamlit 的文档流不提供固定右栏、固定底栏与真画布浮层，需自定义组件或前端重写方可实现。
