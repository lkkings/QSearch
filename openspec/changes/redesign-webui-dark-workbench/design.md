## Context

动机见 `proposal.md` 的 Why。此处仅记录塑造技术方案的约束。

**平台约束（Streamlit）**

- 交互模型为「一次交互 = 一轮服务端往返 + 脚本重跑」，不存在客户端局部更新（除 fragment 与自定义组件）
- 布局为文档流 + 单一可折叠侧栏；无固定右栏、无固定底栏、无真画布浮层
- 服务端无法感知视口宽度，响应式断点不可用
- 主题分两层：原生主题（`config.toml`）与注入的自定义 CSS。二者若不一致会互相打架
- `st.tabs` 的所有分支**全量执行**，不是懒加载

**代码现状**

- 约 190 行内联 CSS 集中于 `app.py:40-229`，全为硬编码亮色值
- `app.py:129` 依赖 Streamlit 生成的哈希类名 `.css-1r6slb0`
- 业务逻辑（`search_engine` / `annotation_manager` / `database_manager` / `task_manager`）与 UI 分离良好，本次不触碰
- `requirements.txt:43` 为 `streamlit>=1.30.0`，未钉版本
- `shortcuts.py` 的 fallback 试图用 `postMessage` 写 `st.session_state`——`components.v1.html` 是隔离 iframe，此路不通

**候选规模**

`search_ui.py:100-106` 允许 top_n 为 1–20。网格最多需承载 20 张图像，这是缩略图性能与查询图锚定方案的主要压力来源。

## Goals / Non-Goals

**Goals:**

- 令牌集中于单一来源，组件不再各自硬编码颜色
- 三种风格（Flat 2.0 / Material / Glassmorphism）在阴影这一冲突点上取得统一裁决
- 「人的判断」与「机器的推断」在视觉上不可混淆
- 网格模式下方向键移动焦点**不产生服务端往返**
- 样式不因 Streamlit 补丁升级而破损

**Non-Goals:**

- 不引入前端构建流水线（npm / bundler）。若某项需求只能靠双向自定义组件实现，则记为后续变更而非本次强行落地
- 不做亮色模式，令牌与对比度各验证一套
- 不优化 rerun 开销（tabs 懒加载、`list_databases` 缓存等），见 `proposal.md` 的 Non-goals
- 不追求像素级还原某个具体设计系统，Material 在此是原则来源而非视觉模板

## Decisions

### D1. 阴影的裁决：高度以表面明度表达

三种风格在阴影上直接冲突：Flat 2.0 要少阴影，Material 要高度层级，Glassmorphism 要浮起。

裁决：**明度承担层级，阴影只留给真浮层。**

```
surface-0 --> surface-1 --> surface-2 --> surface-3 --> surface-4
 #0F1214     #16191C      #1D2125      #252A30      #2D333A
 应用底       面板/侧栏     卡片/表格行   下拉/popover  dialog
   |            |             |             |            |
   +-- 无阴影 --+-- 无阴影 ---+---- 阴影 ----+--- 阴影 ---+
                                    ^
                          脱离文档平面者才投影
```

三方各自得到了想要的：Flat 2.0 得到主体界面零阴影零渐变；Material 得到清晰层级（MD3 在深色模式本就用 surface tint 而非阴影表达 elevation）；Glassmorphism 只在真浮层出现，而那里三方都同意应当浮起。

底色取 `#0F1214` 而非纯黑：纯黑背景上的高饱和色（尤其 `#00E676`）会产生光晕（halation），长时间盯屏加剧疲劳。

*备选方案*：全局统一弱阴影——被否，既不够 flat 也建立不起层级，两边都不讨好。

### D2. 决策色与系统信息色分离为两组

置信度（机器输出）与命中（人的判断）都天然想要绿色。若同色，标注员将无法区分「这是我判的」与「这是机器猜的」——这不是审美问题，是标注质量问题：机器的高置信会污染人的判断基线。

```
决策色（高饱和，仅人的判断）      系统信息色（低饱和，仅机器输出）
  --hit    #00E676  命中           --info-high  #4A9EBE  置信高
  --miss   #FF5252  未命中         --info-mid   #B89550  置信中
  --skip   #78909C  跳过           --info-low   #8A6A6A  置信低
  --focus  #00B0FF  焦点/选中
```

分离依据两条：**饱和度**（高饱和专属于人）与**形态**（决策色带图标 + 实心，信息色为无图标 chip）。双通道冗余，任一通道失效仍可区分。

`--focus` 与 `--info-high` 同处蓝调，但前者只作为焦点环/边框出现，后者只作为 chip 填充出现，承载位置不重叠。

### D3. 令牌注入方式：CSS 自定义属性 + 原生主题双层

`config.toml` 锁定 `base="dark"` 并设置 `primaryColor` / `backgroundColor` / `secondaryBackgroundColor` / `textColor`，使 Streamlit 未被自定义 CSS 覆盖的内建组件也落在同一色系内。自定义 CSS 在 `:root` 声明全部令牌，组件规则只引用 `var(--*)`，不再出现字面色值。

这样做的关键收益：原生主题提供兜底基线。任何遗漏的组件会落在正确色系而非亮色——这正是当前深色模式破损的根因（无 `config.toml`，主题跟浏览器走）。

*备选方案*：纯 CSS 注入不动 `config.toml`——被否，Streamlit 内建组件（date picker、multiselect 下拉、`st.json` 等）的内部样式无法全部覆盖，必然残留亮色。

### D4. 选择器策略：仅用 `data-testid`，并钉版本

`app.py:129` 的 `.css-1r6slb0` 是 Streamlit 构建产物的哈希类名，升版即碎。全面改用 `data-testid`（如 `[data-testid="stMetricValue"]`，该属性 Streamlit 视为半公开契约，跨小版本稳定得多）。

同时将 `streamlit>=1.30.0` 钉为确定版本。理由不止于选择器：`st.dialog` 需 ≥1.31，`st.fragment` 需 ≥1.37，二者都是本设计的硬依赖，开区间约束无法保证它们存在。

即便如此，`data-testid` 仍非正式公开 API。缓解见 R1。

### D5. 网格布局：`st.columns` 固定列数 + 缩略图

网格用 `st.columns(n)` 逐行铺开。因服务端无法感知视口宽度，列数**不做响应式**，而是给标注员一个显式的密度选择（如 4 / 5 / 6 列），存于 `st.session_state`。这把不可获知的信息交给唯一知道答案的人。

top_n 上限为 20，全尺寸渲染 20 张原图会拖慢每次 rerun。候选卡片渲染**缩略图**（长边约 320px），生成结果按图像路径 + mtime 缓存。

卡片结构：

```
+------------------+
| [焦点环]         |  <- 2px --focus，仅当前焦点
|                  |
|   候选缩略图     |
|                  |
+------------------+
| #3   .923   [高] |  <- rank / 综合分 / 置信 chip（低饱和）
+------------------+
| [v] [x] [-]      |  <- 决策按钮（高饱和 + 图标）
+------------------+
 左边缘 3px 实心条 = 已标注状态（--hit / --miss / --skip）
```

详细评分（文本分/视觉分/哈希距离）走卡片上的 `st.popover`——满足「可查但不占图像空间」，且 popover 是 Streamlit 原生浮层，可承载毛玻璃。

*备选方案*：`st.data_editor` 表格化——被否，图像比对是本任务的核心，表格无法给图像足够尺寸。

### D6. 查询图锚定：`st.columns` 上下分区 + 粘性定位

查询图置于网格上方独立区块。规格要求「焦点移动时查询图位置与呈现不变」，而网格滚动时它会滚出视野。

方案：对查询图容器施加 `position: sticky; top: 0`。这是纯 CSS，不需要 rerun，也不与 Streamlit 的文档流冲突。

风险：sticky 依赖祖先链上无 `overflow: hidden`。Streamlit 的容器结构可能违反此前提，需实测。退路见 R2。

### D7. 键盘导航：单个 `components.v1.html` 桥接 + 事件驱动 rerun

现有 fallback（`shortcuts.py:34-90`）走不通——`components.v1.html` 是隔离 iframe，`postMessage` 到 `streamlit:setComponentValue` 不会写入 `st.session_state`；那是双向自定义组件的协议，纯 HTML 组件没有。

方案：注入的 JS 在 `window.parent.document` 上监听 `keydown`，将按键映射为对**已存在但视觉隐藏**的 Streamlit 按钮的 `.click()` 调用。Streamlit 的既有事件通路随即接管。

```
按键 --> iframe 内 JS --> parent DOM 查找隐藏按钮 --> .click()
                                                       |
                                          Streamlit 原生事件 --> rerun
```

这样做的价值：不引入前端构建（符合 Non-Goals），且状态变更完全走 Streamlit 既有路径，无需自行同步 session state。

**但焦点移动必须避免 rerun。** 方向键若走上述通路，每次移动都是一整轮往返——网格导航会慢到不可用。所以焦点分两层：

| 层 | 载体 | 是否 rerun |
|---|---|---|
| 视觉焦点（方向键移动） | JS 在 parent DOM 上改 CSS 类 | 否 |
| 逻辑焦点（标注时读取） | JS 点击对应卡片的隐藏按钮 | 是 |

方向键只改 CSS 类，零往返，响应即时。按下 `1`/`0`/`S` 时，JS 读取当前带焦点类的卡片索引，点击该卡片对应的隐藏标注按钮。**服务端不需要知道焦点在哪**，只需要知道哪张卡被标注了。

这条也顺带满足了规格中「输入文本时不触发标注」——JS 侧检查 `event.target` 是否为输入元素即可提前返回。

键位映射（网格语义，替代原线性语义）：

| 键 | 动作 | 层 |
|---|---|---|
| 方向键 | 网格内移动焦点，边界处停住 | 视觉 |
| `1` / `0` / `S` | 标注当前焦点为 命中 / 未命中 / 跳过 | 逻辑 |
| `Enter` | 保存并进入下一题 | 逻辑 |
| `?` | 唤出快捷键速查浮层 | 视觉 |

*备选方案*：写真正的双向自定义组件——技术上更干净，但需要 npm 构建流水线，与 Non-Goals 冲突。若 D7 实测失败，这是首选退路（记为独立变更）。

### D8. 任务刷新：`st.fragment(run_every=...)` 替代 `sleep` + `rerun`

现状 `task_ui.py:82-85` 的 `time.sleep(interval)` + `st.rerun()` 有两个独立缺陷：`sleep` 阻塞服务端线程；`rerun` 重跑整个脚本，而 `st.tabs` 全量执行意味着标注页一并被重跑。

`st.fragment(run_every=interval)` 同时解决二者——它只重跑被装饰的函数，且不阻塞。这直接满足 `webui/async-tasks` 中「不阻塞服务」与「影响范围受限」两条要求。

进度 toast 用 `st.toast`（原生浮层，可施加毛玻璃）。仅在存在运行中任务时启用 `run_every`，终态任务不再产生刷新——满足「无运行中任务时不刷新」。

### D9. 删除确认：`st.dialog`

`database_ui.py:143` 的 `st.expander` 无法满足模态语义（可滚走、不拦截交互）。改用 `st.dialog`——原生模态，且是毛玻璃背板的正当落点。

确认按钮文案取「删除 <库名>」而非「是」，初始焦点不落在删除上（规格 D 要求）。

### D10. 专注模式：CSS 覆盖而非独立页面

标注需要「侧栏收起 + 放开 1400px 上限」，其余页面不需要。

方案：`st.session_state['focus_mode']` 为真时，注入一段覆盖 `.block-container` 的 `max-width` 与 padding 的 CSS，并将侧栏 `initial_sidebar_state` 设为 collapsed。不拆分为独立页面——那会破坏现有 tab 导航结构，改动面远超收益。

### D11. 令牌与组件规则的物理组织

CSS 从 `app.py` 抽出，落为独立静态资源，由一个薄模块读取并注入：

```
src/qsearch/webui/
  styles/
    tokens.css        令牌声明（:root）
    base.css          排版、间距、滚动条
    components.css    Streamlit 组件覆盖（data-testid 选择器）
    workbench.css     标注工作台专属（网格、卡片、焦点环、sticky）
    glass.css         三处浮层的毛玻璃
  ui/
    styles.py         读取 + 注入，供 app.py 调用
```

依据用户全局规则的「多个小文件优于少数大文件，200-400 行典型」。当前 190 行 CSS 内联在 `app.py` 中，与页面装配逻辑混杂；抽出后 `app.py` 回归其编排职责。

## Risks / Trade-offs

**R1. `data-testid` 并非正式公开 API，仍可能随版本变化**
→ 钉确定版本（D4），使升级成为显式决策。CSS 集中于 `styles/`（D11），审查面收窄至单一目录。升级流程中加入一次视觉核查。相比现状（哈希类名，补丁版即碎）已是量级改善，但无法做到零风险。

**R2. `position: sticky` 可能因 Streamlit 容器结构失效**
→ 需在实现早期验证（祖先链是否存在 `overflow: hidden`）。退路：查询图缩为固定高度条带常驻顶部，牺牲其显示尺寸换取「锚定」这一硬要求。规格要求的是位置不变，不是尺寸最大。

**R3. D7 的键盘桥接依赖 parent DOM 结构与跨 iframe 访问**
→ 隐藏按钮以稳定的 `key` 生成可预测的 DOM 标识，JS 按该标识定位而非依赖 DOM 路径。同源 iframe 下 `window.parent.document` 可访问；若 Streamlit 未来收紧沙箱，退路是 D7 备选方案（双向自定义组件，需 npm，记为独立变更）。
→ 附带风险：`.click()` 触发的 rerun 时序若与用户连续按键重叠，可能丢事件。缓解：标注类操作在 rerun 期间禁用键盘响应（JS 侧加锁）。

**R4. 20 张缩略图仍可能拖慢 rerun**
→ 缩略图按路径 + mtime 缓存（D5），首次生成后命中缓存。若实测仍慢，密度选择器（D5）已给出标注员自行降到 4 列的通路，且可对超出首屏的卡片延后加载。

**R5. 交互延迟仍受 rerun 支配，动效 100ms 不等于观感 100ms**
→ 本次明确不优化 rerun 开销（Non-Goals）。D7 的双层焦点使**最高频的操作（方向键移动）完全绕开 rerun**，这是本次能取得的最大观感收益。标注类操作仍是一轮往返。诚实记录：动效时长达标不代表交互延迟达标。

**R6. 单一暗色主题排除了明亮环境下的使用场景**
→ 用户已明确选择仅深色。令牌体系（D3）为后续增加亮色留了结构位——届时只需增加一组 `:root` 覆盖，组件规则无需改动。

**R7. 四份 spec 登记为 New 而非 Modified，archive 时将创建主 spec 而非合并**
→ 这是空 `openspec/specs/` 的必然结果（见 `proposal.md` Capabilities 说明）。三份描述既有功能的 spec 已完整陈述目标行为而非仅记录增量，故 archive 产出的主 spec 是完整且自洽的。代价：`streamlit-webui` 当初声明的部分需求（如「自动展开未标注候选项」）不会以 REMOVED 形式留下痕迹，因为它从未进入过主 spec。

## Migration Plan

无数据迁移——本次不触碰持久层与业务逻辑。

部署顺序有一处依赖：`config.toml`（D3）须先于自定义 CSS 生效，否则原生主题仍为亮色基线，中间态会出现亮暗混杂。

回滚：CSS 与 UI 层改动可整体回退至当前提交。`requirements.txt` 的版本钉定需同步回退，否则 `st.dialog` / `st.fragment` 的调用点在旧版本上会报错。

## Open Questions

- ~~网格密度的默认列数（4 / 5 / 6）取值。~~ **已由 3.3 实测解决：缩略图长边 400，默认 5 列。**

  长边取值不受耗时约束——240/320/400 的生成耗时几乎相同（699–790ms），成本由源图解码支配而非缩放。故按画质选：题目图偏高（760×1040），长边 400 缩出实宽约 292px，覆盖 4–6 列的渲染宽度（295/233/192）全程无放大。长边 320 在 5 列时是 1:1，但切到 4 列即变放大，文字密集的题目图发虚会直接损害"靠肉眼判断相似度"这件事。代价仅 94KB。

  同时确认 D5 的缓存是必需而非优化：热缓存服务端 50ms vs 原图 2484ms（49 倍），载荷 1527KB → 208KB。

- 毛玻璃的模糊半径与背景不透明度具体取值。需在深色底上实测对比度后定，不影响架构。

## 实测记录

**rerun 地板（R5 的实测确认）**：3.3 测量中，即便热缓存下服务端仅耗 50ms，端到端仍约 2900–3000ms。这是 Streamlit 的页面导航 + websocket 握手 + 脚本重跑的固定开销，与动效时长无关。

这坐实了 D7 双层焦点的必要性：若方向键走服务端往返，每次移动约 3 秒，网格导航不可用。也坐实了 R5 的诚实记录——动效压到 100ms 不会让交互变成 100ms。10.6 以此为基线。

