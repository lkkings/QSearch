# WebUI 更新说明

## 更新内容

本次更新对 QSearch WebUI 进行了以下改进：

### 1. 简化导航 - 只保留主页

**修改文件**: `src/qsearch/webui/app.py`

- 移除了"搜索"、"标注"、"详情"页面的导航
- 侧边栏现在只显示"主页"
- 所有功能都集中在主页中，简化了用户界面

**变更代码**:
```python
# 定义页面 - 只保留主页
home_page = st.Page(
    "pages/home.py", title="主页", icon=":material/home:", default=True
)

# 创建导航 - 只显示主页
pg = st.navigation([home_page])
```

### 2. 增强队列信息显示

**修改文件**: `src/qsearch/webui/app.py`

队列概览现在显示四个指标：
- ✅ **排队中**: 等待执行的任务数
- ✅ **运行中**: 正在执行的任务数  
- ✅ **成功**: 已完成的任务数（新增）
- ✅ **失败**: 失败的任务数（新增）

**显示效果**:
```
队列概览
┌─────────┬─────────┐
│ 排队中  │ 运行中  │
│   5     │   2     │
├─────────┼─────────┤
│ 成功    │ 失败    │
│   120   │   3     │
└─────────┴─────────┘
```

### 3. 新增系统资源监控

**新增文件**: `src/qsearch/webui/system_monitor.py`

**功能特性**:
- 📊 **CPU 监控**: 显示 CPU 使用率和核心数
- 💾 **内存监控**: 显示内存使用率和已用/总量
- 🎮 **GPU 监控**: 显示 GPU 负载、显存使用、温度（如果可用）
- 🎨 **颜色编码**: 根据资源使用情况显示不同颜色
  - 绿色：正常（CPU < 70%, 内存 < 80%）
  - 黄色：警告（CPU 70-90%, 内存 80-95%）
  - 红色：危险（CPU > 90%, 内存 > 95%）

**显示效果**:
```
资源监控
━━━━━━━━━━━━━━━━━━━━
CPU (8 核)
45.2%

内存
62.3%
△ 10.2/16.0 GB

GPU 负载        GPU 显存
25.6%          48.3%
               △ 3860/8000 MB

🎮 NVIDIA GeForce RTX 3070
🌡️ 温度: 65°C
```

### 4. 依赖更新

**修改文件**: `requirements.txt`

新增依赖：
- `gputil>=1.4.0` - GPU 监控（可选，如果系统没有 GPU 会优雅降级）

已有依赖（无需额外安装）：
- `psutil>=5.9.0` - CPU 和内存监控

## 安装和使用

### 1. 安装新依赖

```bash
# 如果有 GPU，推荐安装 gputil
pip install gputil>=1.4.0

# 或使用 uv
uv pip install gputil>=1.4.0

# 或重新安装所有依赖
pip install -r requirements.txt
```

### 2. 启动 WebUI

```bash
# 使用启动脚本
python scripts/start_webui.py

# 或直接启动
streamlit run src/qsearch/webui/app.py
```

### 3. 验证功能

启动后，您应该能看到：
1. ✅ 侧边栏只显示"主页"
2. ✅ 队列概览显示 4 个指标（排队、运行、成功、失败）
3. ✅ 资源监控显示 CPU、内存使用情况
4. ✅ 如果有 GPU，还会显示 GPU 信息

## 测试系统监控

运行测试脚本验证监控功能：

```bash
python scripts/test_system_monitor.py
```

预期输出示例：
```
============================================================
系统资源监控测试
============================================================

📊 CPU 信息:
  核心数: 8
  使用率: 45.2%

💾 内存信息:
  使用率: 62.3%
  已使用: 10.2 GB
  总容量: 16.0 GB

🎮 GPU 信息:
  名称: NVIDIA GeForce RTX 3070
  负载: 25.6%
  显存使用: 48.3%
  显存已用: 3860 MB
  显存总量: 8000 MB
  温度: 65°C

✅ 系统监控测试通过！
```

## 技术细节

### 系统监控 API

`src/qsearch/webui/system_monitor.py` 提供以下函数：

```python
# 获取所有系统资源信息
resources = get_system_resources()
# 返回: {
#     'cpu_percent': float,
#     'cpu_count': int,
#     'memory_percent': float,
#     'memory_used_gb': float,
#     'memory_total_gb': float,
#     'gpu': {  # 可选，如果有 GPU
#         'name': str,
#         'load_percent': float,
#         'memory_used_mb': float,
#         'memory_total_mb': float,
#         'memory_percent': float,
#         'temperature': float
#     }
# }

# 格式化内存大小
formatted = format_memory_size(10.5)  # "10.5 GB"

# 获取状态颜色
color = get_cpu_status_color(85.0)  # "warning"
color = get_memory_status_color(92.0)  # "warning"
```

### 性能考虑

- CPU 使用率采样间隔: 0.1 秒（快速但准确）
- GPU 信息获取失败时优雅降级，不影响其他功能
- 资源监控每次侧边栏刷新时更新（Streamlit 自动管理）

### 错误处理

所有监控功能都有完善的错误处理：
- GPU 不可用时显示"GPU 信息不可用"
- GPUtil 未安装时不会崩溃
- 任何监控错误都会显示警告而非中断应用

## 未来改进建议

1. **自动刷新**: 添加定时自动刷新资源监控（每 5-10 秒）
2. **历史趋势**: 显示 CPU/内存使用的小型趋势图
3. **多 GPU 支持**: 支持显示多个 GPU 的信息
4. **磁盘监控**: 添加磁盘使用情况显示
5. **网络监控**: 添加网络 I/O 监控

## 问题排查

### GPU 信息显示"不可用"

**原因**: 可能是以下之一
1. 系统没有 NVIDIA GPU
2. GPUtil 未安装
3. NVIDIA 驱动未正确安装

**解决方案**:
```bash
# 1. 检查是否有 NVIDIA GPU
nvidia-smi

# 2. 安装 GPUtil
pip install gputil

# 3. 更新 NVIDIA 驱动
# 访问 https://www.nvidia.com/drivers
```

### CPU/内存显示错误

**原因**: psutil 未安装或版本过旧

**解决方案**:
```bash
pip install --upgrade psutil>=5.9.0
```

### 资源监控完全不显示

**原因**: 可能是导入错误

**解决方案**:
```bash
# 检查模块是否可以导入
python -c "from qsearch.webui.system_monitor import get_system_resources; print('OK')"
```

## 更新日期

- 创建日期: 2024-01-XX
- 最后更新: 2024-01-XX
- 作者: Claude Code
