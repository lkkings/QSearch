## 1. 版本与主题基线

> 顺序有硬依赖：`config.toml` 必须先于自定义 CSS 生效，否则中间态出现亮暗混杂（design.md Migration Plan）。

- [x] 1.1 将 `requirements.txt:43` 的 `streamlit>=1.30.0` 钉为确定版本（须 ≥1.37：`st.dialog` 需 1.31、`st.fragment` 需 1.37），并同步 `pyproject.toml` 的 `dependencies`；验证 `uv run python -c "import streamlit as s; print(s.__version__); assert hasattr(s,'dialog') and hasattr(s,'fragment')"` 通过
- [x] 1.2 新建 `.streamlit/config.toml`，设 `base="dark"` 与 primaryColor / backgroundColor / secondaryBackgroundColor / textColor（D3）；验证将操作系统主题切为亮色后启动 `scripts/start_webui.py`，四个页面均呈暗色（spec: design-system「操作系统偏好为亮色」）
- [x] 1.3 在 config.toml 生效、自定义 CSS 尚未改动的状态下，逐页截图留存基线；验证产出四张对照截图，供后续组件改造比对

## 2. 样式骨架

- [x] 2.1 建立 `src/qsearch/webui/styles/` 并写入 `tokens.css`，在 `:root` 声明全部令牌：五级 surface、border、text、决策色、系统信息色、间距、圆角、动效时长、控件高度（D1/D2）；验证文件内无组件规则，仅令牌声明
- [x] 2.2 新建 `src/qsearch/webui/ui/styles.py`，读取 `styles/` 下各 CSS 并注入；验证单元测试覆盖「文件缺失时报错而非静默注入空样式」
- [x] 2.3 将 `app.py:40-229` 的内联 CSS 迁出至 `base.css` 与 `components.css`，`app.py` 改为调用 `styles.py`；验证 `app.py` 内不再出现 `<style>` 字面量，且页面渲染与 1.3 基线无回归
- [x] 2.4 全量替换组件规则中的字面色值为 `var(--*)`；验证 `grep -nE "#[0-9a-fA-F]{3,6}|rgba?\(" src/qsearch/webui/styles/components.css src/qsearch/webui/styles/workbench.css` 无输出（字面色值应仅存于 `tokens.css`）

## 3. 早期风险验证

> 这三项的结论会改变后续实现路径，必须先做（design.md R2/R3/R4）。

- [x] 3.1 验证 `position: sticky` 在 Streamlit 容器结构下是否生效：检查查询图容器祖先链是否存在 `overflow: hidden`；验证产出结论——生效则按 D6 实施，失效则改用固定高度条带（R2 退路）并记录该决定
- [x] 3.2 验证键盘桥接可行性：在 `components.v1.html` 内注入 JS，尝试 `window.parent.document` 查找一个隐藏 Streamlit 按钮并 `.click()`；验证按钮的 on-click 回调确实被触发（若失败则触发 R3 退路，记为独立变更并停止 6 组任务）
- [x] 3.3 测量 20 张原图与 20 张缩略图在单次 rerun 中的渲染耗时差；验证产出耗时数据，据此确认缩略图长边取值与默认列数（design.md Open Questions 之一）

## 4. 组件外观

- [x] 4.1 移除全部装饰性渐变：h1 渐变裁字（`app.py:186-192`）、主按钮（`:63-67`）、进度条（`:161-164`）、标签条选中态（`:109-126`）、侧边栏（`:144-146`）；验证 `grep -n "linear-gradient" src/qsearch/webui/styles/*.css` 无输出
- [x] 4.2 将 `app.py:129` 的哈希类名 `.css-1r6slb0` 及其余生成类名全部改为 `data-testid` 选择器（D4）；验证 `grep -nE "\.css-[a-z0-9]+" src/qsearch/webui/styles/*.css` 无输出
- [x] 4.3 移除卡片与表格行的悬停位移（`app.py:138-141` 的 `translateY`），改为背景状态层；验证悬停时元素位置不变（spec: design-system「无位移类装饰动效」）
- [x] 4.4 非浮层元素（面板、卡片、表格行）去除投影，层级改由 surface 明度表达；验证 `components.css` 中 `box-shadow` 仅出现于下拉、popover、dialog、toast 规则内（spec: design-system「非浮层元素无阴影」）
- [x] 4.5 置信度由 emoji 圆点（`annotation_ui.py:107`）改为低饱和 chip，无图标、实心填充；验证其与决策色在饱和度与形态两个通道上均可区分（spec: design-system「同屏并存时可区分」）
- [x] 4.6 badge（`app.py:200-227`）与文件上传区（`:172-183`）改为深色系令牌；验证二者在暗色底上文本对比度 ≥4.5:1
- [x] 4.7 指标数值（`app.py:70-80`）由全紫改为 `--text-1` + 字重，仅语义值上色；验证普通计数类指标不再着色
- [x] 4.8 输入框、下拉框、次要按钮统一为紧凑高度（32px），决策类按钮 48px；验证实测各控件可点击区域高度达标（spec: design-system「交互目标尺寸」）
- [x] 4.9 数据库列表（`database_ui.py:47-83`）由「列 + 每行 divider」改为紧凑表格，移除行间 divider；验证多个数据库条目可同屏无滚动可见，且行悬停无位移（spec: database-management「数据库列表高密度呈现」）
- [x] 4.10 索引未构建状态增加非颜色冗余标识；验证该状态在灰度截图下仍可辨（spec: database-management「状态标示非仅颜色」）

## 5. 标注工作台

- [x] 5.1 实现缩略图生成，按图像路径 + mtime 缓存（D5）；验证单元测试覆盖「同路径同 mtime 命中缓存」与「mtime 变化后重新生成」
- [x] 5.2 接入 `st.image` 渲染查询图与候选图（全项目当前零处使用）；验证标注页可见图像内容而非路径文字（spec: result-annotation「图像可见」）
- [x] 5.3 实现图像不可读时的降级：占位标识 + 失败原因，不中断其余候选项；验证故意指向一个损坏文件后，其余候选正常显示（spec: result-annotation「图像不可读时的降级」）
- [x] 5.4 实现候选网格：`st.columns(n)` 逐行铺开，列数由 session_state 中的密度选择控制（D5）；验证 top_n=20 时全部 20 项同屏呈现（spec: result-annotation「全部候选同屏可见」）
- [x] 5.5 实现候选卡片结构：缩略图、rank、综合分、置信 chip、决策按钮、左边缘标注状态条；验证每张卡片无需展开即可读到评分与标注状态（spec: result-annotation「卡片自带评分」「卡片自带标注状态」）
- [x] 5.6 将详细评分（文本分/视觉分/哈希距离）移入卡片上的 `st.popover`，替换 `annotation_ui.py:99-117` 占 8 行的三列 markdown；验证详细评分可查且不占用图像显示空间（spec: result-annotation「详细评分可查」）
- [x] 5.7 实现查询图锚定（按 3.1 结论采用 sticky 或固定条带）；验证切换焦点与完成标注后，查询图位置与呈现均不变（spec: result-annotation「查询图锚定」）
- [x] 5.8 实现网格内直接标注三态（命中/未命中/跳过），标注后停留网格不跳转；验证标注即时反映于卡片，且视图不切换（spec: result-annotation「网格内直接标注」）
- [x] 5.9 实现改标：对已标注项施加新标注时替换旧记录并更新时间；验证改标后读取到新标注与新时间戳（spec: result-annotation「改标已标注项」）
- [x] 5.10 实现当前查询与整体批次进度指标，标注后即时更新；验证一次标注后两个进度均变化且无需手动刷新（spec: result-annotation「标注进度可见」）
- [x] 5.11 实现查询完成状态判定（全部标注=已完成，部分标注=部分完成）；验证单元测试覆盖三种状态转换
- [x] 5.12 实现跳转至下一道未标注查询，无剩余时明确告知；验证无未标注查询时给出提示而非静默（spec: result-annotation「跳转至未标注项」）
- [x] 5.13 实现可选备注：填写则与标注一并保存，未填写则标注单独成立；验证两种路径均正确落库（spec: result-annotation「可选备注」）

## 6. 键盘流

> 前置：3.2 必须通过。若失败则本组停止并转 R3 退路。

- [x] 6.1 重写 `shortcuts.py`，移除走不通的 `postMessage` fallback（`:34-90`）；验证旧的 `_register_shortcuts_fallback` 已删除，不留死代码
- [x] 6.2 ~~为每张候选卡片生成视觉隐藏的标注按钮~~ **实现时偏离**：卡片本身已有可见的决策按钮（`qsdec_<label>_<idx>`），JS 直接点它们即可，无需额外的 60 个隐藏按钮。key 仍具可预测的 DOM 标识（`.st-key-qsdec_hit_0`），且 `.st-key-<key>` 是精确类选择器，不存在 `_1` 误配 `_11` 的问题；验证 DOM 中实测 60 个决策按钮可按该标识定位
- [x] 6.3 实现双层焦点的视觉层：方向键在 parent DOM 上改 CSS 类移动焦点，零 rerun，边界处停住（D7）；验证连续按方向键无网络请求产生，且焦点不越界跳题（spec: result-annotation「方向键移动网格焦点」「焦点位于网格边界」）
- [x] 6.4 实现焦点视觉标识（2px `--focus` 焦点环）；验证任一时刻可明确看出按键将作用于哪张卡片（spec: result-annotation「焦点可见」）
- [x] 6.5 实现逻辑层：`1`/`0`/`S` 读取当前焦点卡片索引并点击其隐藏按钮，`Enter` 保存并进入下一题；验证按键标注结果落在焦点所在项上（spec: result-annotation「按键标注当前焦点」）
- [x] 6.6 实现输入区域守卫：JS 侧检查 `event.target` 是否为输入元素并提前返回；验证在备注框内输入 `1` 或 `0` 不触发标注（spec: result-annotation「输入文本时不触发标注」）
- [x] 6.7 实现 rerun 期间的键盘加锁，避免连续按键在往返期间丢事件（R3）；验证快速连按标注键不产生错标或丢标
- [x] 6.8 将键位提示移至按钮本体，并实现 `?` 唤出的速查浮层，替换侧栏文字（`annotation_ui.py:220-227`）；验证键位就近可见（spec: result-annotation「键位提示就近可见」）
- [x] 6.9 为键位映射逻辑补单元测试；验证网格二维移动的边界条件（四角、单行、单列）均有覆盖

## 7. 行为缺陷修复

- [x] 7.1 将 `task_ui.py:82-85` 的 `time.sleep` + `st.rerun()` 替换为 `st.fragment(run_every=...)`（D8）；验证任务页自动刷新期间标注页不重新加载，标注焦点、未提交备注、滚动位置均保持（spec: async-tasks「标注不被刷新打断」）
- [x] 7.2 使 `run_every` 仅在存在运行中任务时启用，终态任务不再刷新；验证全部任务进入终态后不再产生周期性请求（spec: async-tasks「无运行中任务时不刷新」「终态不再刷新」）
- [x] 7.3 实现进度 toast（`st.toast` + 毛玻璃），呈现已处理数/总数/完成比例，不拦截下方操作；验证 toast 显示期间可正常点击其下方元素（spec: async-tasks「进度提示不阻挡操作」）
- [x] 7.4 将 `database_ui.py:136-165` 的删除确认由 `st.expander` 改为 `st.dialog`（D9）；验证确认待处理时无法与页面其余部分交互，且不因滚动移出视野（spec: database-management「删除确认为模态」）
- [x] 7.5 删除确认的动作文案改为「删除 <库名>」，初始焦点不落在删除动作上；验证文案体现后果且初始焦点在取消或对话框本体（spec: database-management「危险操作的动作命名明确」）

## 8. 专注模式与浮层

- [x] 8.1 实现 `focus_mode` 的 CSS 覆盖：收起侧栏、压缩边距、放开 1400px 上限（D10）；验证宽屏下标注界面利用可用视口宽度（spec: result-annotation「宽度不受内容页上限约束」）
- [x] 8.2 实现退出专注模式的通路；验证可返回其他功能页（spec: result-annotation「可退出专注模式」）
- [x] 8.3 编写 `glass.css`，仅覆盖 toast、popover、dialog 三处浮层；验证 `grep` 确认半透明与 `backdrop-filter` 未出现于卡片、表格、侧栏规则（spec: design-system「主体界面不使用半透明」）
- [x] 8.4 实测并定下毛玻璃的模糊半径与背景不透明度（design.md Open Questions 之二）；验证浮层承载的文本对比度仍 ≥4.5:1（spec: design-system「半透明不牺牲可读性」）

## 9. 文案统一

- [x] 9.1 将四个 UI 模块（`database_ui.py`、`search_ui.py`、`annotation_ui.py`、`task_ui.py`）的英文界面文案统一为中文，与 `app.py` 一致；验证跨页面切换时文案不在语言间跳变（spec: result-annotation「界面文案语言一致」）

## 9.5. Bug 修复

- [x] 9.5.1 修复 `ConfigLoader` 缺少 `load_preset` 方法导致创建数据库失败的问题；添加 `load_preset` 方法调用 `presets.get_preset()`
- [x] 9.5.2 修复 `database_manager.py` 中 `from scripts.index_database import build_index` 的架构问题；将索引构建逻辑移至 `qsearch.indexing.builder` 模块，避免已安装包引用项目脚本目录

## 10. 整体验证

- [x] 10.1 计算全部文本/背景令牌组合的对比度；验证正文 ≥4.5:1、大号标题 ≥3:1，产出一份对照表（spec: design-system「文本对比度」）
- [x] 10.2 以灰度渲染四个页面截图；验证标注状态、置信等级、索引状态、任务状态在无色彩信息时仍可区分（spec: design-system「状态不得仅依赖颜色」「红绿色盲可用性」）
- [x] 10.3 核查全部过渡动效时长；验证状态反馈 ≤100ms、浮层进出 ≤150ms（spec: design-system「动效时长上限」）
- [x] 10.4 走通一遍完整标注流程（选库 → 搜索 → 网格标注 → 跳转未标注 → 查看统计），全程仅用键盘；验证无需鼠标即可完成标注闭环
- [x] 10.5 在钉定版本的相邻补丁版本上启动一次；验证自定义样式未丢失或错位（spec: design-system「框架补丁升级」，缓解 R1）
- [x] 10.6 记录标注类操作的实际交互延迟；验证产出实测数据，用于诚实反映 R5（动效达标不等于交互延迟达标），并作为后续 rerun 优化变更的基线
