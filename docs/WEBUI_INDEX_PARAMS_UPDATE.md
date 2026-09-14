# WebUI 索引构建参数配置更新

## 更新日期
2026-09-12

## 更新概述

本次更新为 QSearch WebUI 添加了完整的索引构建参数配置功能，用户现在可以在创建数据集时通过可视化界面配置所有索引构建参数，无需手动编辑 YAML 配置文件。

## 主要变更

### 1. 数据库 Schema 更新

#### 新增字段
- `num_workers`：INTEGER，CPU 并行进程数
- `num_gpus`：INTEGER NOT NULL DEFAULT 0，GPU 数量

#### 迁移脚本
- **文件**：`scripts/migrate_queue_schema.py`
- **功能**：安全地将新字段添加到现有的 `task_queue` 表
- **特性**：
  - 检查字段是否已存在，避免重复迁移
  - 使用事务确保原子性
  - 自动备份数据库到 `data/backups/`
  - 详细的迁移报告

### 2. WebUI 前端更新

#### 文件：`src/qsearch/webui/ui/database_ui.py`

**新增功能：**

1. **配置预设选择**
   - 下拉框选择预设：default、fast、accurate、mobile
   - 带有描述文字说明每个预设的特点

2. **计算资源配置**
   - CPU 并行进程数滑块（1-16，默认 4）
   - GPU 数量滑块（0-4，默认 0）
   - 智能切换：GPU > 0 时自动禁用 CPU 并行数设置

3. **高级参数面板**（可折叠）
   - **特征提取配置**：
     - 模型路径输入
     - 图像尺寸选择（224/256/384）
     - 批处理大小滑块（8-256）
   
   - **OCR 配置**：
     - OCR 引擎选择（paddleocr/easyocr/tesseract）
     - 检测阈值滑块（0.0-1.0）
     - 识别阈值滑块（0.0-1.0）
   
   - **索引构建配置**：
     - 索引类型选择（Flat/IVFFlat/IVFPQ/HNSW）
     - 聚类中心数输入
     - PQ 子向量数输入
     - 最小词频输入
     - N-gram 范围输入
   
   - **匹配策略配置**：
     - 图像权重滑块（0.0-1.0）
     - OCR 权重滑块（0.0-1.0）
     - 检测结果权重滑块（0.0-1.0）
     - 图像相似度阈值滑块（0.0-1.0）
     - OCR 相似度阈值滑块（0.0-1.0）
     - 检测相似度阈值滑块（0.0-1.0）

4. **智能表单验证**
   - 权重之和必须等于 1.0，自动显示当前总和
   - 警告提示当权重和不为 1.0 时
   - 实时参数预览

### 3. 后端逻辑更新

#### 文件：`src/qsearch/webui/task_manager.py`

**更新：`enqueue_index_build` 方法**
```python
def enqueue_index_build(
    self,
    database_name: str,
    config_preset: str | None = None,
    config_yaml: str | None = None,
    num_workers: int | None = None,
    num_gpus: int = 0,
) -> str:
```

- 接受 `num_workers` 和 `num_gpus` 参数
- 传递给 `TaskQueue.enqueue` 方法
- 保持向后兼容性

#### 文件：`src/qsearch/tasks/queue.py`

**更新：`enqueue` 方法**
```python
def enqueue(
    self,
    kind: str,
    database_name: str,
    lane: str = "default",
    task_name: str | None = None,
    num_workers: int | None = None,
    num_gpus: int = 0,
    config_preset: str | None = None,
    config_yaml: str | None = None,
    payload: dict | None = None,
) -> str:
```

- 接受并保存 `num_workers` 和 `num_gpus` 到数据库
- 支持索引构建和批量搜索两种任务类型

#### 文件：`src/qsearch/tasks/runner_index.py`

**更新：`run_index_build` 函数**
```python
def run_index_build(task: dict, task_id: str, database_name: str) -> dict:
```

- 从 task 字典读取 `num_workers` 和 `num_gpus`
- 传递给 `IndexBuilder.build_index` 方法
- 支持 GPU 模式切换

### 4. 测试和验证

#### 文件：`scripts/test_index_build_params.py`

**测试覆盖：**
1. 任务入队参数保存
   - CPU 模式（num_workers=4, num_gpus=0）
   - GPU 模式（num_workers=None, num_gpus=2）

2. 参数读取验证
   - 从数据库正确读取 num_workers
   - 从数据库正确读取 num_gpus
   - 配置预设正确保存

3. 清理测试数据
   - 自动取消测试任务

**测试结果：**
```
✓ 所有测试通过
```

### 5. 文档更新

#### 新增文档：`docs/INDEX_BUILD_PARAMS.md`

**内容包括：**
1. 功能特性详细说明
2. 所有配置项的参数说明和推荐值
3. 不同场景的使用示例
4. 性能优化建议
5. 技术实现说明
6. 故障排查指南

#### 更新文档：`README.md`

**新增章节：**
1. WebUI 可视化界面使用说明
2. 索引构建参数配置常见问题
3. WebUI 功能特性介绍

## 技术架构

### 数据流

```
用户填写表单
    ↓
database_ui.py 收集参数
    ↓
TaskManager.enqueue_index_build()
    ↓
TaskQueue.enqueue() 保存到数据库
    ↓
Scheduler 调度任务
    ↓
runner_index.run_index_build() 读取参数
    ↓
IndexBuilder.build_index() 执行构建
```

### 关键文件

| 文件 | 职责 |
|------|------|
| `src/qsearch/webui/ui/database_ui.py` | WebUI 表单实现 |
| `src/qsearch/webui/task_manager.py` | 任务管理器 |
| `src/qsearch/tasks/queue.py` | 任务队列 |
| `src/qsearch/tasks/runner_index.py` | 索引构建执行器 |
| `src/qsearch/indexing/builder.py` | 索引构建器 |
| `scripts/migrate_queue_schema.py` | 数据库迁移脚本 |
| `scripts/test_index_build_params.py` | 功能测试脚本 |

## 使用指南

### 启动 WebUI

```bash
uv run scripts/start_webui.py
```

### 创建数据集并配置参数

1. 访问 `http://localhost:8501`
2. 点击左侧"数据集"
3. 点击"创建新数据集"
4. 填写基本信息
5. 选择配置预设或展开"高级参数"自定义
6. 配置计算资源（CPU 或 GPU）
7. 点击"创建数据集"

### 监控任务

1. 主页显示实时队列状态
2. 点击"任务监控"查看详细进度
3. 点击任务可查看日志

## 配置示例

### 小型数据集（< 1000 图像）

```yaml
配置预设: fast
并行进程数: 4
GPU 数量: 0
索引类型: Flat
```

### 中型数据集 + GPU（1000-50000 图像）

```yaml
配置预设: default
GPU 数量: 1
批处理大小: 64
索引类型: IVFFlat
聚类中心数: 200
```

### 大型数据集 + 多 GPU（> 50000 图像）

```yaml
配置预设: accurate
GPU 数量: 2
批处理大小: 128
索引类型: IVFPQ
聚类中心数: 400
PQ 子向量数: 16
```

## 向后兼容性

本次更新完全向后兼容：

1. **数据库**：旧版本数据库可通过迁移脚本升级
2. **API**：所有新参数均为可选，默认值保持原有行为
3. **命令行**：脚本参数保持不变
4. **配置文件**：YAML 配置文件格式不变

## 未来改进

1. **参数预设模板**
   - 保存用户自定义配置为模板
   - 快速应用常用配置

2. **参数验证增强**
   - 实时验证参数合理性
   - 根据数据集大小推荐参数

3. **性能预估**
   - 根据参数估算构建时间
   - 估算内存和显存占用

4. **配置对比**
   - 比较不同配置的效果
   - A/B 测试支持

## 测试清单

- [x] 数据库 schema 迁移
- [x] WebUI 表单功能
- [x] 任务入队参数传递
- [x] 参数从数据库读取
- [x] CPU 模式执行
- [x] GPU 模式执行
- [x] 配置预设加载
- [x] 自定义配置生成
- [x] 权重验证
- [x] 参数预览
- [x] 文档更新
- [x] 测试脚本

## 已知问题

无

## 贡献者

- Claude Opus 5 (1M context)

## 参考链接

- [索引构建参数配置文档](INDEX_BUILD_PARAMS.md)
- [WebUI 使用指南](../README.md#三使用说明)
- [配置文件说明](../README.md#四配置文件说明)
