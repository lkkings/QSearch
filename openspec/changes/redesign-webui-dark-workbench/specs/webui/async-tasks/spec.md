## Purpose

让长时间运行的任务（索引构建、批量搜索）的进度持续可见，同时保证观察任务进度这一行为不干扰界面上正在进行的其他工作——尤其不打断标注节奏。

## ADDED Requirements

### Requirement: 自动刷新不阻塞服务

任务进度的自动刷新 SHALL NOT 通过阻塞服务端处理来实现。

#### Scenario: 刷新等待期间服务可响应

- **WHEN** 任务进度处于两次自动刷新之间的等待期
- **THEN** 系统 SHALL 继续响应用户的其他交互，且该等待 SHALL NOT 占用服务端处理能力

#### Scenario: 多用户互不阻塞

- **WHEN** 一个用户正在观察任务进度，另一用户提交操作
- **THEN** 后者的操作 SHALL NOT 因前者的刷新等待而延迟

### Requirement: 自动刷新的影响范围受限

任务进度的自动刷新 SHALL NOT 导致与该进度无关的界面区域重新加载。

#### Scenario: 标注不被刷新打断

- **WHEN** 存在正在运行的任务且其进度处于自动刷新状态，同时标注员正在标注
- **THEN** 标注界面 SHALL NOT 因该刷新而重新加载，标注员的焦点位置、未提交的备注与滚动位置 SHALL 保持不变

#### Scenario: 仅进度区域更新

- **WHEN** 任务进度发生变化
- **THEN** 系统 SHALL 仅更新承载该进度的区域

#### Scenario: 无运行中任务时不刷新

- **WHEN** 不存在正在运行的任务
- **THEN** 系统 SHALL NOT 因进度刷新而产生周期性重新加载

### Requirement: 进度可见且不遮挡

系统 SHALL 让运行中任务的进度在用户操作其他功能时仍然可见，且不妨碍其操作。

#### Scenario: 跨页面可见

- **WHEN** 存在正在运行的任务而用户正在其他页面工作
- **THEN** 系统 SHALL 使该任务的进度保持可感知

#### Scenario: 进度提示不阻挡操作

- **WHEN** 进度提示浮于内容之上
- **THEN** 其下方内容 SHALL 保持可见，且该提示 SHALL NOT 拦截对下方元素的操作

#### Scenario: 进度信息完整

- **WHEN** 显示某个运行中任务的进度
- **THEN** 系统 SHALL 呈现其已处理数量、总数量与完成比例

### Requirement: 刷新频率可控

系统 SHALL 允许用户控制进度刷新的频率，包括完全关闭。

#### Scenario: 关闭自动刷新

- **WHEN** 用户将自动刷新设为关闭
- **THEN** 系统 SHALL NOT 再自动更新进度，且 SHALL 提供手动刷新通路

#### Scenario: 手动刷新

- **WHEN** 用户请求立即刷新
- **THEN** 系统 SHALL 获取并呈现最新的任务状态

### Requirement: 任务终态呈现

系统 SHALL 明确区分任务的各种终止状态并提供相应的后续通路。

#### Scenario: 任务完成

- **WHEN** 任务成功结束
- **THEN** 系统 SHALL 呈现其完成状态与处理结果统计

#### Scenario: 任务失败

- **WHEN** 任务因错误终止
- **THEN** 系统 SHALL 呈现失败状态与可供排查的错误信息

#### Scenario: 任务被取消

- **WHEN** 用户取消某个运行中的任务
- **THEN** 系统 SHALL 呈现取消状态，且 SHALL NOT 将其表示为失败

#### Scenario: 终态不再刷新

- **WHEN** 任务已进入终态
- **THEN** 系统 SHALL NOT 继续为该任务产生自动刷新
