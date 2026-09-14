# 数据库索引构建失败问题解决方案

## 问题描述

创建数据库索引构建失败，报错：
```
错误：配置缺失：D:\VibeCoding\QSearch\data\databases\test2\config.yaml
```

## 问题原因

项目中存在两个数据库目录：
- `./databases/` - 实际存储数据库的目录（包含 test 和 test2）
- `./data/databases/` - 空目录

**根本原因**：WebUI 默认使用 `./databases` 作为数据库根目录，但在某些情况下（可能是环境变量未设置或被覆盖），索引构建任务会在 `data/databases` 路径查找配置文件。

## 解决方案

### 方案 1：使用启动脚本（推荐）✅

我已经为你创建了两个启动脚本，它们会自动设置正确的环境变量：

#### Windows 用户
```bash
# 双击运行或在命令行中执行
start_webui.bat
```

#### Linux/Mac 用户
```bash
# 在终端中执行
./start_webui.sh
```

### 方案 2：手动设置环境变量

在启动 WebUI **之前**，设置环境变量：

#### Windows CMD
```cmd
set QSEARCH_DATABASES_ROOT=databases
streamlit run src/qsearch/webui/app.py
```

#### Windows PowerShell
```powershell
$env:QSEARCH_DATABASES_ROOT="databases"
streamlit run src/qsearch/webui/app.py
```

#### Linux/Mac Bash
```bash
export QSEARCH_DATABASES_ROOT=databases
streamlit run src/qsearch/webui/app.py
```

### 方案 3：使用 .env 文件

我已经创建了 `.env` 文件，内容如下：
```
QSEARCH_DATABASES_ROOT=databases
```

如果你的启动脚本支持自动加载 `.env` 文件，这个方案也可以工作。但要确保在 Python 代码中使用 `python-dotenv` 库加载环境变量。

## 验证修复

1. **重启 WebUI**（使用上述任何一种方案）

2. **检查数据库路径**
   ```bash
   # 在 WebUI 的日志中，你应该看到：
   # 数据库目录: databases
   ```

3. **重新构建索引**
   - 进入 WebUI 的数据库管理页面
   - 选择 `test2` 数据库
   - 点击"构建索引"按钮
   - 索引构建应该成功启动

## 目录结构说明

```
QSearch/
├── databases/              ← 实际数据库存储位置 ✓
│   ├── test/
│   │   ├── config.yaml
│   │   ├── image_list.txt
│   │   ├── metadata.json
│   │   └── index/
│   └── test2/
│       ├── config.yaml
│       ├── image_list.txt
│       ├── metadata.json
│       └── index/
├── data/
│   ├── databases/          ← 空目录（不使用）
│   └── queue/              ← 任务队列数据
├── .env                    ← 环境变量配置（新创建）
├── start_webui.bat         ← Windows 启动脚本（新创建）
└── start_webui.sh          ← Linux/Mac 启动脚本（新创建）
```

## 常见问题

### Q: 为什么会有两个数据库目录？

A: `./databases` 是 WebUI 的默认数据库目录。`data/databases` 可能是之前的配置或测试遗留，当前项目不使用这个目录。

### Q: 我应该删除 `data/databases` 目录吗？

A: 可以删除，因为它是空的。但保留它也不会造成问题，只要正确设置了环境变量。

### Q: 环境变量设置后，为什么还是报错？

A: 请确保：
1. 在启动 WebUI **之前**设置了环境变量
2. 完全重启了 WebUI（关闭所有相关进程）
3. 检查任务调度器也被重启了

### Q: 如何检查环境变量是否生效？

A: 在 WebUI 启动时，检查日志输出，或在 Python 中运行：
```python
import os
print(os.environ.get('QSEARCH_DATABASES_ROOT'))
# 应该输出: databases
```

## 技术细节

### 相关代码位置

- **WebUI 入口**: `src/qsearch/webui/app.py:296`
  ```python
  databases_root = Path(os.environ.get('QSEARCH_DATABASES_ROOT', './databases'))
  ```

- **索引构建任务**: `src/qsearch/tasks/runner_index.py:50-55`
  ```python
  db_dir = databases_root / database_name
  config_path = db_dir / "config.yaml"
  if not config_path.exists():
      raise FileNotFoundError(f"配置缺失：{config_path}")
  ```

### 为什么需要环境变量？

- WebUI 默认使用 `./databases` 作为数据库根目录
- 任务调度器需要知道相同的根目录才能找到配置文件
- 环境变量 `QSEARCH_DATABASES_ROOT` 统一了所有组件使用的路径

## 后续建议

1. **统一配置管理**：考虑将路径配置集中到配置文件中
2. **路径验证**：在 WebUI 启动时验证数据库目录是否正确
3. **错误提示优化**：当配置文件缺失时，提供更明确的错误信息和解决建议

## 更新日志

- 2024-09-13: 创建此文档，添加启动脚本和 .env 文件
