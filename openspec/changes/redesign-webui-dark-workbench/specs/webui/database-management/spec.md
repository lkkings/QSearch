## Purpose

管理图像数据库的创建、查看与删除。删除会永久移除索引文件与全部标注成果，因此其确认必须是无法被忽略或误触的模态决策；列表则需在有限屏幕内呈现尽可能多的数据库状态。

## ADDED Requirements

### Requirement: 删除确认为模态

删除数据库的确认 SHALL 以模态形式呈现，SHALL NOT 表现为页面内可被滚动移出视野的区域。

#### Scenario: 确认框拦截页面交互

- **WHEN** 用户请求删除某个数据库
- **THEN** 系统 SHALL 呈现模态确认，且在该确认被处理前 SHALL NOT 允许用户与页面其余部分交互

#### Scenario: 确认框不可被滚走

- **WHEN** 删除确认处于待处理状态
- **THEN** 该确认 SHALL 保持在视野内，SHALL NOT 因页面滚动而移出

#### Scenario: 后果明确告知

- **WHEN** 呈现删除确认
- **THEN** 系统 SHALL 明确说明将被永久移除的内容，并说明该操作不可撤销

#### Scenario: 确认对象明确

- **WHEN** 呈现删除确认
- **THEN** 该确认 SHALL 指明被删除数据库的名称

#### Scenario: 取消不产生变更

- **WHEN** 用户取消删除
- **THEN** 系统 SHALL 关闭确认且 SHALL NOT 对该数据库产生任何变更

#### Scenario: 确认后执行并反馈

- **WHEN** 用户确认删除
- **THEN** 系统 SHALL 执行删除并告知结果；删除失败时 SHALL 呈现失败原因且 SHALL NOT 声称成功

### Requirement: 危险操作的动作命名明确

系统 SHALL 使危险操作的确认动作在语义上不可与取消混淆。

#### Scenario: 动作文案具体

- **WHEN** 呈现删除确认的操作选项
- **THEN** 确认动作的文案 SHALL 指明其后果，SHALL NOT 使用「是」「确定」等无法体现后果的泛化措辞

#### Scenario: 确认动作非默认焦点

- **WHEN** 删除确认出现
- **THEN** 初始焦点 SHALL NOT 落在执行删除的动作上

### Requirement: 数据库列表高密度呈现

数据库列表 SHALL 在有限的垂直空间内呈现尽可能多的条目。

#### Scenario: 单屏可见多个数据库

- **WHEN** 存在多个数据库
- **THEN** 系统 SHALL 以紧凑形式呈现，使多个条目在无需滚动的情况下同屏可见

#### Scenario: 条目间无冗余分隔

- **WHEN** 渲染相邻的数据库条目
- **THEN** 二者之间 SHALL NOT 插入占据显著垂直空间的分隔元素

#### Scenario: 关键状态可扫读

- **WHEN** 用户浏览数据库列表
- **THEN** 每个条目 SHALL 呈现其图像数量、索引构建状态与标注命中率

#### Scenario: 行悬停可辨

- **WHEN** 用户将指针悬停于某个条目
- **THEN** 该条目 SHALL 呈现可辨的悬停状态，且 SHALL NOT 发生位置偏移

### Requirement: 索引未构建状态明确

系统 SHALL 明确区分已构建索引与未构建索引的数据库。

#### Scenario: 未构建索引的提示

- **WHEN** 某数据库尚未构建索引
- **THEN** 系统 SHALL 明确标示该状态，使用户知晓其尚不可用于搜索

#### Scenario: 状态标示非仅颜色

- **WHEN** 标示索引构建状态
- **THEN** 该标示 SHALL 具备非颜色的冗余标识
