# PaddleOCR 模型位置更新说明

## 变更内容

PaddleOCR 模型现在会下载到项目目录，而不是用户主目录。

### 之前
```
~/.paddleocr/          # 用户主目录
├── whl/
│   ├── det/
│   ├── rec/
│   └── cls/
```

### 现在
```
项目目录/models/paddleocr/     # 项目目录
├── whl/
│   ├── det/
│   ├── rec/
│   └── cls/
```

---

## 好处

1. **项目自包含**：所有模型都在项目目录下，便于管理
2. **便于部署**：可以直接打包整个 models 目录
3. **多项目隔离**：不同项目可以使用不同版本的模型
4. **便于版本控制**：可以将模型加入 .gitignore 或选择性提交

---

## 实现方式

### 1. download_models.py

设置环境变量 `PADDLE_OCR_HOME`，让 PaddleOCR 使用项目目录：

```python
# 设置 PaddleOCR 模型下载目录到项目的 models/paddleocr
paddle_models_dir = MODELS_DIR / "paddleocr"
os.environ['PADDLE_OCR_HOME'] = str(paddle_models_dir)
```

### 2. ocr_engine.py

在初始化时设置模型目录：

```python
# 默认使用项目目录下的 models/paddleocr
project_root = Path(__file__).resolve().parents[3]
self.model_dir = str(project_root / "models" / "paddleocr")

# 设置环境变量
os.environ['PADDLE_OCR_HOME'] = self.model_dir
```

### 3. verify_install.py

优先检查项目目录，其次检查用户主目录：

```python
# 优先检查项目目录下的 PaddleOCR 模型
project_paddle_dir = MODELS_DIR / "paddleocr"
home_paddle_dir = Path.home() / ".paddleocr"

if project_paddle_dir.exists():
    # 使用项目目录的模型
elif home_paddle_dir.exists():
    # 使用用户目录的模型（提示迁移）
```

---

## 使用方法

### 下载模型到项目目录

```bash
python scripts/download_models.py
```

这会自动将 PaddleOCR 模型下载到 `models/paddleocr/`

### 验证模型位置

```bash
python scripts/verify_install.py
```

输出示例：
```
检查 PaddleOCR 模型:
✓ PaddleOCR 模型（项目目录）
  位置: D:\VibeCoding\QSearch\models\paddleocr
  大小: 156.3 MB
```

---

## 迁移指南

如果你之前已经在用户主目录下载了模型，有两种方式：

### 方式 1：重新下载（推荐）

```bash
# 重新下载到项目目录
python scripts/download_models.py
```

优点：自动设置，无需手动操作

### 方式 2：手动迁移

```bash
# Windows
xcopy /E /I %USERPROFILE%\.paddleocr models\paddleocr

# Linux/Mac
cp -r ~/.paddleocr models/paddleocr
```

---

## 目录结构

```
项目目录/
├── models/
│   ├── chinese-roberta-wwm-ext/     # 中文编码器
│   ├── all-mpnet-base-v2/           # 英文编码器
│   └── paddleocr/                   # PaddleOCR 模型（新增）
│       └── whl/
│           ├── det/                 # 文本检测模型
│           │   └── ch/
│           │       └── ch_PP-OCRv4_det_infer/
│           ├── rec/                 # 文本识别模型
│           │   └── ch/
│           │       └── ch_PP-OCRv4_rec_infer/
│           └── cls/                 # 方向分类器
│               └── ch_ppocr_mobile_v2.0_cls_infer/
```

---

## 环境变量

PaddleOCR 通过 `PADDLE_OCR_HOME` 环境变量确定模型位置：

```python
import os
os.environ['PADDLE_OCR_HOME'] = '/path/to/your/models/paddleocr'
```

我们的代码已经自动设置了这个变量，无需手动配置。

---

## 常见问题

### Q1: 已经下载到用户目录的模型会被重复下载吗？

A1: 是的。`download_models.py` 会重新下载到项目目录。如果想节省时间，可以手动复制已有的模型。

### Q2: 可以同时保留两个位置的模型吗？

A2: 可以，但只会使用项目目录的模型。用户目录的模型可以删除以节省空间。

### Q3: 如何指定自定义的模型目录？

A3: 在初始化 OCREngine 时传入 `model_dir` 参数：

```python
from qsearch.features.ocr_engine import OCREngine

ocr = OCREngine(model_dir="/your/custom/path")
```

### Q4: 模型大小是多少？

A4: PaddleOCR 中文模型约 150-200 MB

### Q5: 可以将模型加入版本控制吗？

A5: 不建议。模型文件较大，建议在 `.gitignore` 中排除：

```gitignore
# .gitignore
models/paddleocr/
models/chinese-roberta-wwm-ext/
models/all-mpnet-base-v2/
```

只提交下载脚本，在新环境中运行 `python scripts/download_models.py` 重新下载。

---

## 部署建议

### 开发环境

```bash
# 下载所有模型
python scripts/download_models.py
```

### 生产环境

**方式 1：预打包模型**
```bash
# 打包模型
tar -czf models.tar.gz models/

# 在生产环境解压
tar -xzf models.tar.gz
```

**方式 2：首次运行下载**
```bash
# 在生产环境运行
python scripts/download_models.py
```

---

## 更新日期

2025-09-10

## 影响的文件

- `scripts/download_models.py` - 设置下载目录
- `src/qsearch/features/ocr_engine.py` - 使用项目目录
- `scripts/verify_install.py` - 检查项目目录优先
