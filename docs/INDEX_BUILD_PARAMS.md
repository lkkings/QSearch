# 索引构建参数配置功能

## 概述

WebUI 现在支持在创建数据集时完整配置索引构建的所有参数，用户可以根据硬件资源和性能需求灵活调整。

## 功能特性

### 1. 配置预设

选择预置的配置方案，快速应用最佳实践：

- **default**（默认）：平衡的通用配置
- **fast**（快速）：更快的处理速度，精度略低
- **accurate**（精确）：更高的检索精度，处理稍慢
- **mobile**（移动设备）：适用于移动设备拍摄的图像

### 2. 计算资源配置

#### CPU 模式
- **并行进程数**：控制 CPU 多进程并行度
  - 范围：1-16
  - 默认：4
  - 建议：设置为 CPU 核心数的 50-75%

#### GPU 模式
- **GPU 数量**：使用的 GPU 卡数
  - 0：仅使用 CPU
  - \> 0：使用指定数量的 GPU
  - 注意：GPU 模式下会忽略并行进程数设置

### 3. 特征提取配置

#### 图像特征
- **模型路径**：ResNet50 模型位置（默认自动检测）
- **图像尺寸**：输入图像大小
  - 默认：224
  - 可选：256, 384（更大尺寸提高精度但降低速度）
- **批处理大小**：每批处理的图像数
  - 默认：32
  - GPU 模式建议：64-128
  - CPU 模式建议：8-32

#### OCR 文本
- **OCR 引擎**：文本识别引擎选择
  - `paddleocr`：PaddleOCR（推荐，中英文支持好）
  - `easyocr`：EasyOCR（多语言支持）
  - `tesseract`：Tesseract（传统 OCR）
- **检测阈值**：文本检测置信度阈值
  - 范围：0.0-1.0
  - 默认：0.3
  - 建议：低质量图像降低至 0.2，高质量图像提升至 0.5
- **识别阈值**：文本识别置信度阈值
  - 范围：0.0-1.0
  - 默认：0.5
  - 建议：根据实际识别效果调整

### 4. 索引构建配置

#### Faiss 索引
- **索引类型**：向量索引算法
  - `Flat`：精确搜索（小数据集 < 10k）
  - `IVFFlat`：倒排文件 + 精确（中等数据集 10k-100k）
  - `IVFPQ`：倒排文件 + 乘积量化（大数据集 > 100k）
  - `HNSW`：分层可导航小世界图（高性能，内存占用大）

- **聚类中心数**：IVF 索引的聚类数量（仅 IVF* 类型）
  - 建议：sqrt(N) 到 4*sqrt(N)，N 为图像总数
  - 示例：10k 图像建议 100-400

- **PQ 子向量数**：乘积量化的分段数（仅 IVFPQ）
  - 必须能整除特征维度
  - 默认：8
  - 建议：维度 2048 时使用 8 或 16

#### 文本索引
- **最小词频**：词汇表中词的最低出现次数
  - 默认：1
  - 建议：大数据集设置为 2-3 以过滤噪声

- **N-gram 范围**：文本特征的 n-gram 范围
  - 格式：`[min, max]`
  - 默认：`[1, 2]`（unigram + bigram）
  - 建议：中文保持 `[1, 2]`，英文可用 `[1, 3]`

### 5. 匹配策略

#### 权重配置
- **图像权重**：图像相似度的权重（0.0-1.0）
- **OCR 权重**：OCR 文本相似度的权重（0.0-1.0）
- **检测结果权重**：对象检测结果的权重（0.0-1.0）

注意：三个权重之和应等于 1.0

#### 相似度阈值
- **图像相似度**：图像特征匹配的最低阈值
  - 范围：0.0-1.0
  - 默认：0.7
- **OCR 相似度**：文本匹配的最低阈值
  - 范围：0.0-1.0
  - 默认：0.5
- **检测相似度**：对象检测匹配的最低阈值
  - 范围：0.0-1.0
  - 默认：0.6

## 使用示例

### 场景 1：小型数据集（< 1000 图像）

```yaml
配置预设: fast
并行进程数: 4
GPU 数量: 0
索引类型: Flat
```

### 场景 2：中型数据集 + GPU（1000-50000 图像）

```yaml
配置预设: default
并行进程数: 8
GPU 数量: 1
批处理大小: 64
索引类型: IVFFlat
聚类中心数: 200
```

### 场景 3：大型数据集 + 多 GPU（> 50000 图像）

```yaml
配置预设: accurate
并行进程数: 16
GPU 数量: 2
批处理大小: 128
索引类型: IVFPQ
聚类中心数: 400
PQ 子向量数: 16
```

### 场景 4：高精度 OCR 需求

```yaml
配置预设: accurate
OCR 引擎: paddleocr
检测阈值: 0.2
识别阈值: 0.6
OCR 权重: 0.4
图像权重: 0.5
检测结果权重: 0.1
```

## 性能优化建议

### CPU 优化
1. 并行进程数设置为物理核心数的 50-75%
2. 批处理大小设置较小（8-32）
3. 使用 Fast 或 Default 预设

### GPU 优化
1. GPU 数量设置为可用 GPU 卡数
2. 批处理大小设置较大（64-128）
3. 图像尺寸可适当增大（384）以提升精度

### 内存优化
1. 大数据集使用 IVFPQ 索引而非 Flat
2. 降低批处理大小
3. 减少并行进程数

### 精度优化
1. 使用 Accurate 预设
2. 图像尺寸设置为 384
3. 索引类型使用 Flat 或 HNSW
4. OCR 阈值适当降低以提高召回

## 技术实现

### 数据流

```
WebUI 表单
    ↓
TaskManager.enqueue_index_build()
    ↓
TaskQueue.enqueue()
    ↓
数据库（queue.db）
    ↓
Scheduler 调度
    ↓
runner_index.run_index_build()
    ↓
IndexBuilder.build_index()
```

### 关键文件

- `src/qsearch/webui/ui/database_ui.py`：WebUI 表单实现
- `src/qsearch/webui/task_manager.py`：任务管理器
- `src/qsearch/tasks/queue.py`：任务队列
- `src/qsearch/tasks/runner_index.py`：索引构建执行器
- `src/qsearch/indexing/builder.py`：索引构建器

### 数据库 Schema

```sql
CREATE TABLE task_queue (
    task_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    task_name TEXT,
    database_name TEXT,
    lane TEXT NOT NULL,
    total_items INTEGER,
    processed INTEGER,
    failed INTEGER,
    stage TEXT,
    num_workers INTEGER,
    num_gpus INTEGER NOT NULL DEFAULT 0,
    config_preset TEXT,
    config_yaml TEXT,
    payload TEXT,
    created_at REAL NOT NULL,
    started_at REAL,
    finished_at REAL
);
```

## 迁移说明

如果你有旧版本的 QSearch 安装，运行以下命令升级数据库：

```bash
python scripts/migrate_queue_schema.py
```

该脚本会安全地添加 `num_workers` 和 `num_gpus` 列到现有的任务队列表。

## 测试

运行测试脚本验证功能：

```bash
python scripts/test_index_build_params.py
```

测试包括：
1. 任务入队参数保存
2. 参数从数据库读取
3. CPU 和 GPU 模式切换

## 故障排查

### 问题：GPU 模式不工作

**原因**：系统未正确安装 GPU 版本的依赖

**解决**：
```bash
pip install -r requirements-linux-gpu.txt
```

### 问题：并行进程数过高导致内存不足

**原因**：每个进程都会加载完整的模型

**解决**：
1. 降低并行进程数
2. 减小批处理大小
3. 考虑使用 GPU 模式

### 问题：索引构建失败

**原因**：参数配置不合理

**解决**：
1. 检查聚类中心数是否过大
2. 确认 PQ 子向量数能整除特征维度
3. 验证图像路径是否正确

## 更新日志

### 2026-09-12
- ✅ 添加完整的索引构建参数配置
- ✅ 支持 CPU/GPU 模式切换
- ✅ 更新数据库 schema
- ✅ 创建迁移脚本
- ✅ 添加测试验证
