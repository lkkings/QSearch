# QSearch

基于 OCR 与向量相似度的**题目图片检索引擎**。

给定一批题目图片作为底库，再给定一批待查询的题目图片，QSearch 通过「感知哈希精确匹配」与「文本语义召回 + 结构化校验」双通道，找出查询图在底库中对应的同一道题。适用于题库去重、跨版本题目对齐、拍照搜题等场景。

- **语言 / 版本**：Python ≥ 3.12
- **核心依赖**：Transformers（GOT-OCR 文字识别）、Sentence-Transformers（语义编码）、Faiss（向量检索）、ImageHash（感知哈希）

---

## 目录

- [一、系统架构](#一系统架构)
  - [1.1 整体数据流](#11-整体数据流)
  - [1.2 模块职责](#12-模块职责)
  - [1.3 双通道匹配机制](#13-双通道匹配机制)
  - [1.4 索引产物](#14-索引产物)
- [二、安装说明](#二安装说明)
  - [2.1 环境准备](#21-环境准备)
  - [2.2 安装依赖](#22-安装依赖)
  - [2.3 下载模型](#23-下载模型)
- [三、快速开始](#三快速开始)
- [四、配置说明](#四配置说明)
- [五、更新日志](#五更新日志)
  - [2.3 OCR 运行设备（CPU / GPU）](#23-ocr-运行设备cpu--gpu)
  - [2.4 下载预训练模型](#24-下载预训练模型)
  - [2.5 验证安装](#25-验证安装)
- [三、脚本使用说明](#三脚本使用说明)
  - [3.1 download_images.py — 图片下载与打包](#31-download_imagespy--图片下载与打包)
  - [3.2 download_models.py — 预训练模型下载](#32-download_modelspy--预训练模型下载)
  - [3.3 verify_install.py — 安装自检](#33-verify_installpy--安装自检)
  - [3.4 index_database.py — 构建底库索引](#34-index_databasepy--构建底库索引)
  - [3.5 search_queries.py — 批量查询匹配](#35-search_queriespy--批量查询匹配)
- [四、配置文件说明](#四配置文件说明)
  - [4.1 配置加载机制与优先级](#41-配置加载机制与优先级)
  - [4.2 config/features.yaml — 特征提取配置](#42-configfeaturesyaml--特征提取配置)
  - [4.3 config/matching.yaml — 匹配策略配置](#43-configmatchingyaml--匹配策略配置)
  - [4.4 内置预设](#44-内置预设)
  - [4.5 配置校验规则](#45-配置校验规则)
  - [4.6 推荐做法：合并为单一配置文件](#46-推荐做法合并为单一配置文件)
  - [4.7 配置项接线状态（务必阅读）](#47-配置项接线状态务必阅读)
- [五、端到端示例](#五端到端示例)
- [六、输出结果格式](#六输出结果格式)
- [七、常见问题](#七常见问题)

---

## 一、系统架构

### 1.1 整体数据流

```
                        ┌──────────────────────────────────────┐
                        │  配置层  src/qsearch/config/         │
                        │  loader → schema → validator         │
                        │  presets(conservative/balanced/...)  │
                        └──────────────┬───────────────────────┘
                                       │ config dict
                     ┌─────────────────┴──────────────────┐
                     ▼                                    ▼
      ┌──────────────────────────┐          ┌──────────────────────────┐
      │  底库图片 base images    │          │  查询图片 query images   │
      └────────────┬─────────────┘          └────────────┬─────────────┘
                   │                                      │
                   ▼        特征提取层 features/          ▼
      ┌───────────────────────────────────────────────────────────────┐
      │  FeatureExtractor（编排器，支持多进程 / 多 GPU 分片）         │
      │                                                               │
      │  ┌── TextFeatureExtractor ───────────────────────────────┐    │
      │  │  preprocessing   图像预处理（去噪/增强/二值化/纠偏）  │    │
      │  │         ↓                                             │    │
      │  │  OCREngine       Transformers 中英文识别 + 置信度过滤 │    │
      │  │         ↓                                             │    │
      │  │  QuestionParser  切分题干 / 选项，判定题型            │    │
      │  │         ↓                                             │    │
      │  │  FormulaExtractor  pix2tex 公式转 LaTeX（可选）       │    │
      │  │         ↓                                             │    │
      │  │  RoBERTa / MPNet   语义编码 → 768 维向量              │    │
      │  └───────────────────────────────────────────────────────┘    │
      │                                                               │
      │  ┌── ImageFeatureExtractor ──────────────────────────────┐    │
      │  │  感知哈希 dHash / pHash / aHash                       │    │
      │  │  CNN 深度特征 efficientnet_b4 / resnet50（可选）      │    │
      │  └───────────────────────────────────────────────────────┘    │
      └────────────────────────────┬──────────────────────────────────┘
                                   │
              ┌────────────────────┴───────────────────┐
              ▼            索引层 indexing/            ▼
   ┌────────────────────────┐              ┌────────────────────────┐
   │ HashIndex              │              │ FaissIndexBuilder      │
   │ 哈希 → 图片 ID 字典    │              │ IndexFlatIP            │
   │ O(1) 查找 + 汉明距离   │              │ L2 归一化后取内积      │
   │                        │              │ = 精确余弦相似度       │
   └───────────┬────────────┘              └───────────┬────────────┘
               │                                       │
               ▼            匹配层 matching/           ▼
   ┌────────────────────────┐              ┌────────────────────────┐
   │ ExactMatcher           │              │ ContentMatcher         │
   │ 通道 A：感知哈希       │              │ 通道 B：两阶段匹配     │
   └───────────┬────────────┘              └───────────┬────────────┘
               └──────────────┬────────────────────────┘
                              ▼
                   ┌───────────────────────┐
                   │ QuestionMatcher       │
                   │ 双通道汇总 / 去重标记 │
                   │ top-K / 置信度分级    │
                   └──────────┬────────────┘
                              ▼
                   results.json + query_stats.json
```

### 1.2 模块职责

| 模块 | 文件 | 职责 |
|------|------|------|
| **配置加载** | `config/loader.py` | `ConfigLoader`：读取 YAML、深度递归合并、运行时覆盖。基础配置不可变（对外一律返回深拷贝）；`export_yaml` 用临时文件 + 原子重命名写出，避免写坏原文件 |
| **配置预设** | `config/presets.py` | 内置 `conservative` / `balanced` / `aggressive` 三套匹配参数，接口 `get_preset(name)`、`list_presets()` |
| **配置模式** | `config/schema.py` | `FEATURES_SCHEMA`、`MATCHING_SCHEMA` 与 `ConfigValidator`，校验字段类型、枚举取值与区间 |
| **依赖校验** | `config/validator.py` | `DependencyValidator`：跨小节一致性校验，详见 [4.5](#45-配置校验规则) |
| **图像预处理** | `features/preprocessing.py` | `ImagePreprocessor`：去噪、对比度增强、缩放、二值化（otsu 等）、去边框、倾斜纠正 |
| **OCR 引擎** | `features/ocr_engine.py` | `OCREngine`：通过 Transformers 加载 GOT-OCR 2.0 中英模型；支持 CPU、指定单卡和 Accelerate 多卡自动切分。默认模型目录 `models/got-ocr-2.0-hf` |
| **题目解析** | `features/question_parser.py` | `QuestionParser`：正则切分题干与 A/B/C/D 选项、判定题型、提取公式片段、选项标签归一化 |
| **公式识别** | `features/formula_extractor.py` | `FormulaExtractor`：pix2tex（LaTeX-OCR）图片转 LaTeX，含合法性校验、归一化、公式相似度比较 |
| **文本特征** | `features/text_extractor.py` | `TextFeatureExtractor`：串联预处理 → OCR → 解析 → 编码；按语言自动路由中文 RoBERTa 或英文 MPNet，输出 768 维向量及各分量权重 |
| **图像特征** | `features/image_extractor.py` | `ImageFeatureExtractor`：感知哈希 + CNN 深度特征（深度特征默认关闭） |
| **特征编排** | `features/feature_extractor.py` | `FeatureExtractor`：单图 / 批量 / 多 GPU 分片提取，特征持久化（pickle / json）。文本与图像任一路成功即记 `extraction_success=True`，单图失败不中断整批 |
| **向量索引** | `indexing/faiss_index.py` | `FaissIndexBuilder`：`IndexFlatIP` + L2 归一化实现精确余弦相似度；增查、保存 / 加载、统计 |
| **哈希索引** | `indexing/hash_index.py` | `HashIndex`：字典实现 O(1) 精确查找，`lookup_similar` 按汉明距离阈值检索 |
| **匹配引擎** | `matching/matchers.py` | `ExactMatcher` / `ContentMatcher` / `QuestionMatcher`，见 [1.3](#13-双通道匹配机制) |
| **文本归一化** | `utils/text_normalization.py` | 去空白、标点归一（全角↔半角）、Unicode 归一、大小写、排序、选项集合归一、公式归一 |

### 1.3 双通道匹配机制

**通道 A：精确匹配（`ExactMatcher`）**

用查询图的感知哈希在 `HashIndex` 中按汉明距离检索，距离 ≤ `max_distance` 视为命中，并按距离换算置信度。用于识别同一张图，或仅存在压缩、缩放等轻微差异的图片。

**通道 B：内容匹配（`ContentMatcher`，两阶段）**

*阶段 1 — 向量召回*：用题干语义向量在 Faiss 中检索 `top_k` 个候选，滤掉余弦相似度低于 `text_similarity_threshold` 的候选。

*阶段 2 — 文本相似度验证*：对每个候选计算题干的 Levenshtein 编辑距离，生成文本相似度分数。

可选条件（`optional_conditions`），仅作加分，不参与淘汰：

| 条件 | 当前实现 |
|------|----------|
| `formula_match` | **简化实现**：query 与候选双方都提取到公式时记 1.0，否则记 0.5。并未真正比较 LaTeX 内容 |
| `visual_similarity` | **占位实现**：恒定返回 0.7，未使用 CNN 深度特征 |

这两项的完整实现能力已存在于 `FormulaExtractor.compare_formulas()` 与 `ImageFeatureExtractor` 中，但尚未接入匹配器，详见 [4.7](#47-配置项接线状态务必阅读)。

*最终打分*：`final_score = 0.7 × vector_similarity + 0.3 × text_similarity`，其中 `text_similarity` 基于题干的 Levenshtein 编辑距离计算。总分低于 `threshold` 的候选被淘汰。

**汇总（`QuestionMatcher`）**

依次执行两个通道 → 同时出现在两侧的结果在内容匹配项上标记 `also_exact_match: true` → 各通道分别截取前 `top_k` → 按置信度分级（`≥0.9` HIGH、`≥0.8` MEDIUM、其余 LOW）→ 记录本次查询耗时 `processing_time_ms`。

### 1.4 索引产物

`index_database.py` 在 `--output-dir` 下生成：

| 文件 | 内容 |
|------|------|
| `features.pkl` | 全量特征记录（pickle），查询阶段作为特征数据库回读 |
| `text_index.faiss` | Faiss 向量索引本体 |
| `text_index_ids.pkl` | 向量下标 → 图片路径的映射表 |
| `hash_index.pkl` | 感知哈希索引 |
| `index_stats.json` | 图片总数、成功提取数、向量数、哈希索引统计 |

---

## 快速开始

**新用户？** 请查看 [快速开始指南](QUICKSTART.md)

**重要更新（v2.0）：** 查看 [变更日志](CHANGELOG.md) 了解最新架构变更

### 三步快速启动

```bash
# 1. 下载所有模型
python scripts/download_models.py

# 2. 验证安装
python scripts/verify_install.py

# 3. 建立索引并查询
python scripts/index_database.py --image-dir ./data/base --output-dir ./data/index
python scripts/search_queries.py --query-dir ./data/queries --index-dir ./data/index --output-dir ./data/results
```

详细说明请查看 [QUICKSTART.md](QUICKSTART.md)

---

## 二、安装说明

### 2.1 环境准备

需要 Python 3.12 及以上（仓库已通过 `.python-version` 固定为 `3.12`）。推荐用 [uv](https://github.com/astral-sh/uv) 管理环境，本文命令统一以 `uv` 为例。

```bash
# 安装 uv（如未安装）
# Windows PowerShell:
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
# Linux / macOS:
curl -LsSf https://astral.sh/uv/install.sh | sh

# 创建虚拟环境
uv venv --python 3.12
```

### 2.2 安装依赖

仓库提供四份依赖清单，按平台选择其一：

| 文件 | 适用场景 | 说明 |
|------|----------|------|
| `requirements.txt` | 通用 | 用环境标记自动区分平台：Windows 装 `faiss-cpu`，Linux 装 `faiss-gpu` |
| `requirements-windows.txt` | Windows | 固定 `faiss-cpu`，并显式列出 Windows 上常缺的间接依赖 |
| `requirements-linux-gpu.txt` | Linux + CUDA | 固定 `faiss-gpu`，OCR 使用 PyTorch / Transformers 的 CUDA 支持 |
| `requirements-complete.txt` | Windows 完整兜底 | 把全部间接依赖显式钉住，用于依赖解析反复失败时 |

```bash
# 方式一：按 pyproject.toml 安装（推荐，含项目自身包）
uv pip install -e .

# 方式二：按平台清单安装
uv pip install -r requirements.txt              # 通用
uv pip install -r requirements-windows.txt      # Windows
uv pip install -r requirements-linux-gpu.txt    # Linux GPU
uv pip install -r requirements-complete.txt     # 完整兜底
```

> **建议执行 `uv pip install -e .`**（可编辑安装）。`scripts/search_queries.py` 直接以 `from qsearch...` 导入包，不含 `sys.path` 兜底逻辑，未安装包时会 `ImportError`。

### 2.3 OCR 运行设备（CPU / GPU）

OCR 与文本编码统一使用 PyTorch / Transformers。`OCREngine(use_gpu=True)` 会在 CUDA 可用时启用 GPU：单卡使用 `gpu_id` 指定设备，多卡默认由 Accelerate 的 `device_map="auto"` 按显存自动切分；CUDA 不可用时自动回退到 CPU。

### 2.4 下载预训练模型

```bash
uv run scripts/download_models.py
```

会把两个语义编码模型和 OCR 模型下载到项目 `models/` 目录：中文 `hfl/chinese-roberta-wwm-ext`、英文 `sentence-transformers/all-mpnet-base-v2`，以及 `stepfun-ai/GOT-OCR-2.0-hf`。OCR 模型也会在首次使用时自动下载并保存到 `models/got-ocr-2.0-hf/`。

国内网络可通过镜像加速 HuggingFace 下载：

```bash
# Windows PowerShell
$env:HF_ENDPOINT = "https://hf-mirror.com"
# Linux / macOS
export HF_ENDPOINT=https://hf-mirror.com
```

### 2.5 验证安装

```bash
uv run scripts/verify_install.py
```

逐项检查依赖与 GPU 可用性，全部必需项通过时返回退出码 0，否则返回 1。

---

## 三、使用说明

### 3.1 WebUI 可视化界面（推荐）

QSearch 提供了基于 Streamlit 的 Web 界面，支持数据集管理、索引构建、批量检索等全流程操作。

#### 启动 WebUI

```bash
uv run scripts/start_webui.py
```

或直接运行 Streamlit：

```bash
uv run streamlit run src/qsearch/webui/app.py
```

默认会在 `http://localhost:8501` 打开浏览器。

#### 核心功能

**主页**
- 实时队列监控：显示任务状态（排队、运行中、已完成、失败）
- 系统资源监控：CPU、GPU、内存使用情况
- 快速操作入口

**数据集管理**
- 创建数据集：支持从本地目录或图片列表文件创建
- **完整参数配置**：创建数据集时可配置所有索引构建参数
  - 配置预设选择（default、fast、accurate、mobile）
  - CPU/GPU 计算资源配置
  - 特征提取参数（模型路径、图像尺寸、批处理大小）
  - OCR 参数（引擎选择、检测/识别阈值）
  - 索引类型（Flat、IVFFlat、IVFPQ、HNSW）
  - 匹配策略（权重、相似度阈值）
- 查看数据集详情与索引统计
- 删除数据集

**任务监控**
- 查看所有任务历史
- 实时查看任务进度与日志
- 取消运行中的任务
- 导出任务结果

详细的参数配置说明请参考：[索引构建参数配置文档](docs/INDEX_BUILD_PARAMS.md)

---

### 3.2 命令行脚本

以下脚本均位于 `scripts/`。所有脚本都可加 `--help` 查看参数。

#### 3.2.1 download_images.py — 图片下载与打包

从 JSONL 清单批量下载题目图片，边下边压缩，最终产出单个 `.zip`。针对大规模长时间下载做了三点设计：**支持中断续传**、**内存占用恒定**、**压缩包抗损坏**。

**输入格式**：JSONL（每行一个独立 JSON 对象），每行须含 `page_id` 与 `page_url` 两个字段：

```json
{"page_id": "10001", "page_url": "https://example.com/img/10001.jpg"}
{"page_id": "10002", "page_url": "https://example.com/img/10002.png"}
```

包内文件名为 `{page_id}{扩展名}`，扩展名取自 URL 后缀，URL 无后缀时回退为 `.jpg`。

**参数**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--input` | str | `data/test.json` | 输入 JSONL 文件路径 |
| `--output-zip` | str | `data/images.zip` | 最终输出的 zip 路径；分片目录为该路径加 `.d` 后缀 |
| `--workers` | int | `8` | 并发下载线程数 |
| `--timeout` | int | `15` | 单次请求超时（秒） |
| `--retries` | int | `3` | 单张图片的重试次数 |
| `--pool-connections` | int | `10` | 连接池缓存的池数量（对应 `HTTPAdapter.pool_connections`） |
| `--pool-maxsize` | int | `20` | 单个连接池的最大连接数（对应 `HTTPAdapter.pool_maxsize`） |
| `--shard-size` | int | `2000` | 每个分片容纳的图片数；崩溃最多只影响当前打开的分片 |
| `--queue-size` | int | `64` | 写入队列缓冲的图片数上限，**决定内存占用上限** |
| `--restart` | flag | 关 | 丢弃已有分片目录，从头开始下载 |
| `--merge` | flag | 关 | 只把已有分片合并成最终 zip 并退出，不下载 |
| `--no-merge` | flag | 关 | 下载完成后保留分片、不合并 |

**抗损坏与续传原理**

zip 的中央目录只存在于文件末尾，若采用「每张图追加一次」的方案，就要反复重写中央目录，此时被强杀会毁掉整个压缩包。本脚本改为写入一批**有界分片**（`part-00000.zip`、`part-00001.zip`……）：分片写满即正常关闭，已完成的分片永久安全，崩溃最多只损坏当前正在写的那一个——下次运行时通过扫描其 local file header 抢救可用条目。

续传进度直接从分片内容推导，不依赖旁挂的进度日志，因此不存在「进度文件与压缩包内容不一致」的问题。（旧版本遗留的 `.progress` 文件会在运行时自动清理。）

**示例**

```bash
# 基本用法
uv run scripts/download_images.py --input data/page_url_and_id.json --output-zip data/images.zip

# 提高并发与连接池，加大分片
uv run scripts/download_images.py \
  --input data/page_url_and_id.json \
  --output-zip data/images.zip \
  --workers 32 --pool-connections 32 --pool-maxsize 64 --shard-size 5000

# 中断后续传：重复原命令即可，已下载的会被自动跳过
uv run scripts/download_images.py --input data/page_url_and_id.json --output-zip data/images.zip

# 内存受限时压低缓冲
uv run scripts/download_images.py --input data/list.json --queue-size 16 --workers 4

# 只合并已有分片
uv run scripts/download_images.py --output-zip data/images.zip --merge

# 从头重下
uv run scripts/download_images.py --input data/list.json --output-zip data/images.zip --restart
```

### 3.2.2 download_models.py — 预训练模型下载

下载并校验语义编码模型，**无命令行参数**。

```bash
uv run scripts/download_models.py
```

| 模型 | 用途 | 落盘位置 |
|------|------|----------|
| `hfl/chinese-roberta-wwm-ext` | 中文题干语义编码 | `models/chinese-roberta-wwm-ext/` |
| `sentence-transformers/all-mpnet-base-v2` | 英文题干语义编码 | `models/all-mpnet-base-v2/` |

下载过程同时会在 `models/` 下留一份 HuggingFace 缓存目录（`models--*` 形式）。脚本会打印模型隐藏层维度与嵌入维度用于确认，成功返回退出码 0，任一模型失败返回 1。

### 3.2.3 verify_install.py — 安装自检

检查依赖与运行环境，**无命令行参数**。

```bash
uv run scripts/verify_install.py
```

检查项：核心依赖（PyTorch、TorchVision、NumPy）、向量检索（Faiss 及版本）、OCR / NLP 库（Transformers、Accelerate、Sentence-Transformers）、图像处理（OpenCV、Pillow、ImageHash）、工具库（PyYAML、tqdm、python-Levenshtein、scikit-image）、CUDA 可用性与 GPU 型号列表、QSearch 自身模块与可用预设列表。

### 3.2.4 index_database.py — 构建底库索引

对底库图片提取特征并构建 Faiss 向量索引与哈希索引。

不带参数运行会进入终端向导，交互项与 WebUI 的“创建数据库”表单一致：

```bash
uv run scripts/index_database.py
```

向导及 `--database-name` 模式会像 WebUI 一样创建托管数据库、将索引任务加入
后台队列并确保调度器运行。完整传入 `--image-dir` 与 `--output-dir` 时保留旧版
同步构建模式。

**参数**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `--image-dir` | str | 条件必填 | — | 底库图片目录，**递归**扫描 `.jpg` / `.jpeg` / `.png` / `.bmp` |
| `--output-dir` | str | 条件必填 | — | 兼容模式的索引输出目录；与 `--database-name` 二选一 |
| `--database-name` | str | 条件必填 | — | 创建托管数据库并通过调度器构建索引 |
| `--databases-root` | str | | `databases` | 托管数据库根目录 |
| `--config` | str | | — | YAML 配置文件路径；指定后**忽略** `--preset` |
| `--preset` | str | | `balanced` | 内置预设名：`conservative` / `balanced` / `aggressive` |
| `--num-workers` | int | | 自动 | CPU 特征提取进程数 |
| `--num-gpus` | int | | `1`（兼容模式） | 参与特征提取的 GPU 数量；`0` 表示 CPU |
| `--batch-size` | int | | `128` | 文本编码与图片深度特征提取的批大小 |
| `--interactive` | flag | | | 强制进入终端向导 |
| `--non-interactive` | flag | | | 禁止提示，缺少必要参数时直接报错 |
| `--yes` | flag | | | 跳过执行前确认 |

**示例**

```bash
# 用默认 balanced 预设建库
uv run scripts/index_database.py --image-dir data/base_images --output-dir data/index

# 高精度预设 + 单卡
uv run scripts/index_database.py \
  --image-dir data/base_images --output-dir data/index \
  --preset conservative --num-gpus 1

# 使用自定义配置文件
uv run scripts/index_database.py \
  --image-dir data/base_images --output-dir data/index \
  --config config/my_config.yaml

# 创建托管数据库并加入 WebUI 共用的任务队列
uv run scripts/index_database.py \
  --image-dir data/base_images --database-name math_questions \
  --databases-root databases --non-interactive
```

**注意**：Faiss 向量维度、索引类型与查询参数均从数据库配置读取；建库和检索应使用一致的编码模型与维度。

### 3.2.5 search_queries.py — 批量查询匹配

加载已建好的索引，对查询图片批量执行双通道匹配。

不带参数运行会进入终端向导，自动列出 `databases/` 下已构建索引的数据库，
并按该库配置展示查询期可调参数。提交后与 WebUI 一样进入后台任务队列，
调度器将结果写入数据库的 `annotations/annotations.db`：

```bash
uv run scripts/search_queries.py
```

使用 `--database-name` 可非交互入队；完整传入 `--index-dir` 与
`--output-file` 时保留旧版同步检索模式。

**参数**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `--query-dir` | str | 条件必填 | — | 查询图片目录，**递归**扫描 `.jpg` / `.jpeg` / `.png` / `.bmp` |
| `--query-list` | str | 条件必填 | — | 每行一个图片路径的 UTF-8 文本文件；与 `--query-dir` 二选一 |
| `--index-dir` | str | 条件必填 | — | 旧版同步模式的索引目录或托管数据库目录 |
| `--database-name` | str | 条件必填 | — | 调度模式使用的托管数据库名；与 `--index-dir` 二选一 |
| `--databases-root` | str | | `databases` | 托管数据库根目录 |
| `--task-name` | str | | 自动 | 调度任务的可读名称 |
| `--output-file` | str | 同步模式必填 | — | 指定后采用旧版同步执行并输出 JSON |
| `--config` | str | | — | 调度模式的查询配置覆盖；同步模式的完整配置 |
| `--preset` | str | | `balanced` | 内置预设名：`conservative` / `balanced` / `aggressive` |
| `--num-gpus` | int | | `0`（调度模式） | 查询特征提取使用的 GPU 数量；`0` 使用 CPU worker 池 |
| `--batch-size` | int | | `32` | 查询文本编码与图片深度特征提取的批大小 |
| `--top-n` | int | | 库配置 | 每个 Query 返回 1–20 个结果 |
| `--interactive` | flag | | | 强制进入终端向导 |
| `--non-interactive` | flag | | | 禁止提示，缺少必要参数时直接报错 |
| `--yes` | flag | | | 跳过执行前确认 |

同步模式除 `--output-file` 外，还会在其同级目录写出 `query_stats.json`。
调度模式的任务进度和结果可直接在 WebUI 的任务监控与标注页面查看。

> 建库与查询应使用**同一套配置**（尤其是编码模型与感知哈希参数），否则特征不可比，匹配结果无意义。

**示例**

```bash
# 推荐：通过 WebUI 共用调度器执行
uv run scripts/search_queries.py \
  --query-dir data/query_images \
  --database-name math_questions \
  --databases-root databases --num-gpus 1 --non-interactive

# 旧版同步查询并导出 JSON
uv run scripts/search_queries.py \
  --query-dir data/query_images \
  --index-dir data/index \
  --output-file data/results/matches.json

# 高召回预设，便于人工复核边界样本
uv run scripts/search_queries.py \
  --query-dir data/query_images --index-dir data/index \
  --output-file data/results/matches.json --preset aggressive

# CPU 环境
uv run scripts/search_queries.py \
  --query-dir data/query_images --index-dir data/index \
  --output-file data/results/matches.json --num-gpus 0
```

---

## 四、配置文件说明

### 4.1 配置加载机制与优先级

两个脚本的配置来源二选一，逻辑一致：

```
指定 --config  →  读取该 YAML 文件，作为完整配置（--preset 被忽略）
未指定        →  取 --preset 对应的内置预设（默认 balanced）
```

`ConfigLoader` 支持深度递归合并（`merge_configs` / `load_multiple`）与运行时覆盖（`get_config(overrides=...)`），但**脚本的 `--config` 只接收单个文件路径**，内部取的是 `ConfigLoader(path).base_config`。因此不能同时把 `config/features.yaml` 与 `config/matching.yaml` 传进去，需要两者同时生效时请参照 [4.6](#46-推荐做法合并为单一配置文件) 合并成一个文件。

配置的顶层结构如下（`features.yaml` 提供前四段，`matching.yaml` 提供后两段）：

```yaml
text:      { ... }   # 文本特征分量与编码模型
image:     { ... }   # 图像特征分量
ocr:       { ... }   # OCR 引擎参数
metadata:  { ... }   # 元信息开关
exact_match:   { ... }   # 精确匹配（合并时须置于 matching 下）
content_match: { ... }   # 内容匹配（合并时须置于 matching 下）
output:        { ... }   # 输出控制（合并时须置于 matching 下）
```

> **重要**：`ContentMatcher` 等匹配器从 `config['matching']['content_match']` 读取参数，而 `config/matching.yaml` 现在把 `exact_match` / `content_match` / `output` 放在**顶层**。直接把该文件当 `--config` 传入，匹配参数不会生效，会静默退回代码内的默认值。合并配置时务必把这三段套进 `matching:` 下一层，见 [4.6](#46-推荐做法合并为单一配置文件)。

### 4.2 config/features.yaml — 特征提取配置

控制从图片提取哪些特征、怎么提取。

#### `text.components` — 文本分量

| 参数 | 类型 | 默认值 | 说明 | 状态 |
|------|------|--------|------|------|
| `stem.enabled` | bool | `true` | 是否提取题干 | 生效 |
| `stem.weight` | float | `0.6` | 题干在文本特征中的权重 | 仅记录，不参与打分 |
| `options.enabled` | bool | `true` | 是否提取选项 | 生效 |
| `options.weight` | float | `0.3` | 选项权重 | 仅记录，不参与打分 |
| `options.normalization` | list | `[remove_whitespace, normalize_punctuation, sort]` | 选项归一化策略，按序执行；可选值：`remove_whitespace`、`normalize_punctuation`、`sort`、`lowercase` | 生效 |
| `formulas.enabled` | bool | `false` | 是否提取公式 | 未接线，见下 |
| `formulas.weight` | float | `0.1` | 公式权重 | 仅记录，不参与打分 |

关于 `weight`：三者之和不应超过 `1.0`，否则依赖校验器报错（见 [4.5](#45-配置校验规则)）。但需要说明的是，这些权重只会写入特征记录的 `weights` 字段留档，**匹配打分过程并不读取**。

关于 `formulas.enabled`：`FormulaExtractor` 在代码库中从未被实例化，置 `true` 只会在特征记录中追加一条警告，既不会真正提取公式，也不会增加耗时。详见 [4.7](#47-配置项接线状态务必阅读)。

#### `text.encoding` — 语义编码

| 参数 | 类型 | 默认值 | 说明 | 状态 |
|------|------|--------|------|------|
| `chinese_model` | str | `hfl/chinese-roberta-wwm-ext` | 中文编码模型，可填 HuggingFace 名或本地路径 | 生效 |
| `english_model` | str | `sentence-transformers/all-mpnet-base-v2` | 英文编码模型 | 生效 |
| `embedding_dim` | int | `768` | 向量维度 | **未接线**，见下 |

模型加载时优先查找 `models/` 下的本地目录，未命中再回落到 HuggingFace。语言由 `TextFeatureExtractor` 自动判定并路由到对应模型。

`embedding_dim` 没有任何读取处：实际维度取决于所选模型的输出，而 Faiss 索引维度由两个脚本里硬编码的 `dimension=768` 决定。换用非 768 维模型时必须直接改脚本，改这里无效。

#### `image.components` — 图像分量

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `perceptual_hash.enabled` | bool | `true` | 是否计算感知哈希。**精确匹配通道依赖此项** |
| `perceptual_hash.algorithm` | enum | `dHash` | 哈希算法，可选 `dHash` / `pHash` / `aHash` |
| `perceptual_hash.hash_size` | int | `16` | 哈希边长；`16` 对应 256 位，直接决定汉明距离的取值范围 |
| `deep_features.enabled` | bool | `true` | 是否提取 CNN 深度特征。`visual_similarity` 依赖此项 |
| `deep_features.model` | str | `efficientnet_b4` | 骨干网络，可选 `efficientnet_b4` / `resnet50` |
| `deep_features.output_dim` | int | `512` | 深度特征维度 |
| `batch_size` | int | `128` | 图像特征批大小；显存不足时下调 |

> `hash_size` 变更后旧索引失效，必须重建。

#### `ocr` — OCR 参数

| 参数 | 类型 | 默认值 | 说明 | 状态 |
|------|------|--------|------|------|
| `engine` | enum | `transformers` | OCR 引擎，当前仅支持 Transformers | 已接线 |
| `languages` | list | `[ch, en]` | 识别语种，元素取值 `ch` / `en` | 已接线 |
| `confidence_threshold` | float | `0.5` | 置信度下限（0–1），低于此值的识别结果被丢弃 | 已接线 |

#### `metadata`

| 参数 | 类型 | 默认值 | 说明 | 状态 |
|------|------|--------|------|------|
| `question_type_detection` | bool | `true` | 是否检测题型 | 未接线，题型检测始终开启 |

### 4.3 config/matching.yaml — 匹配策略配置

控制怎么判定两道题是同一题。

#### `exact_match` — 精确匹配通道

| 参数 | 类型 | 默认值 | 说明 | 状态 |
|------|------|--------|------|------|
| `enabled` | bool | `true` | 是否启用精确匹配通道 | **未接线**，通道始终执行 |
| `criteria.perceptual_hash.max_distance` | int | `5` | 汉明距离阈值。范围随 `hash_size` 而定（`hash_size: 16` 时为 0–256）。`0` 表示逐位相同；调大可容忍压缩、水印等轻微差异，但过大会引入误配 | 生效 |

#### `content_match.stage1` — 阶段 1 向量召回

| 参数 | 类型 | 默认值 | 说明 | 状态 |
|------|------|--------|------|------|
| `content_match.enabled` | bool | `true` | 是否启用内容匹配通道 | **未接线**，通道始终执行 |
| `text_similarity_threshold` | float | `0.75` | 余弦相似度下限（0–1），低于此值不进入阶段 2 | 生效 |
| `top_k` | int | `100` | 每条查询召回的候选数。调大提升召回、线性增加阶段 2 开销 | 生效 |

#### `content_match.optional_conditions` — 可选条件

这两项**只加分、不淘汰**。开关与权重已生效，但打分逻辑目前是简化 / 占位实现。

| 参数 | 类型 | 默认值 | 说明 | 状态 |
|------|------|--------|------|------|
| `formula_match.enabled` | bool | `false` | 是否计入公式相似度。依赖校验器要求同时开启 `text.components.formulas.enabled` | 开关生效，**打分是简化实现**：双方都有公式记 1.0，否则 0.5。因公式提取未接线，实际恒为 0.5 |
| `formula_match.weight` | float | `0.15` | 公式项权重 | 生效 |
| `visual_similarity.enabled` | bool | `false` | 是否计入视觉相似度。依赖校验器要求同时开启 `image.components.deep_features.enabled` | 开关生效，**打分是占位实现**：恒返回 0.7，未使用 CNN 特征 |
| `visual_similarity.weight` | float | `0.05` | 视觉项权重 | 生效 |

`optional_score` 为各启用项得分的加权平均；无启用项时为 `0.0`。由于两项当前都返回常量，开启它们只会给全部候选叠加一个近似固定的偏移，不具备区分能力。

#### `content_match.scoring` — 最终打分

| 参数 | 类型 | 默认值 | 说明 | 状态 |
|------|------|--------|------|------|
| `method` | enum | `weighted_sum` | 打分方式，当前仅支持 `weighted_sum` | 生效（唯一取值） |
| `threshold` | float | `0.85` | 最终得分下限（0–1）。**控制精确率与召回率平衡的最关键参数** | 生效 |

实际计算式为 `final_score = 0.7 × vector_similarity + 0.3 × text_similarity`，其中 `text_similarity` 基于题干的 Levenshtein 编辑距离计算。

#### `output` — 输出控制

| 参数 | 类型 | 默认值 | 说明 | 状态 |
|------|------|--------|------|------|
| `top_k` | int | `10` | 每种匹配类型最多返回的结果数 | 生效 |
| `grouping.by_match_type` | bool | `true` | 结果按匹配类型分组（`exact_matches` / `content_matches`） | **未接线**，输出恒按此结构分组 |
| `include_details.feature_scores` | bool | `true` | 是否输出各特征分项得分 | **未接线**，`scores` 字段恒输出 |
| `include_details.debug_info` | bool | `false` | 是否输出调试信息 | **未接线**，无额外调试信息输出 |

### 4.4 内置预设

预设定义在 `src/qsearch/config/presets.py`，通过 `--preset` 选择。

| 预设 | 定位 |
|------|------|
| `conservative` | 高精确率，严格阈值，目标精确率 > 99%。适合自动化去重等误配代价高的场景 |
| `balanced` | 精确率与召回率均衡，**默认值**。适合大多数场景 |
| `aggressive` | 高召回率，宽松阈值，尽量捞出边界样本。适合配合人工复核 |

**关键阈值对照**

| 参数 | conservative | balanced | aggressive |
|------|-------------|----------|------------|
| `exact_match` 汉明距离 `max_distance` | `3` | `5` | `8` |
| `stage1.text_similarity_threshold` | `0.85` | `0.75` | `0.65` |
| `stage1.top_k` | `50` | `100` | `200` |
| `formula_match.weight` | `0.15` | `0.15` | `0.10` |
| `visual_similarity.weight` | `0.05` | `0.05` | `0.10` |
| `scoring.threshold` | `0.90` | `0.85` | `0.75` |
| `output.top_k` | `5` | `10` | `20` |

三个预设都把 `formula_match` 与 `visual_similarity` 置为 `enabled: true`；`aggressive` 另外开启了 `include_details.debug_info`。

> **两点需要注意**：
>
> 1. 预设**只包含 `matching` 一段**，不含 `text` / `image` / `ocr` / `metadata`。仅用 `--preset` 时，特征提取侧全部走代码内默认值——其中 `text.components.formulas` 与 `image.components.deep_features` 均默认关闭。
>
>    这意味着三个预设默认开启的 `formula_match` 与 `visual_similarity` 拿不到对应特征。更关键的是，这两项当前是简化 / 占位实现（见 [4.7](#47-配置项接线状态务必阅读)），即便改用自定义配置文件打开特征开关也**不会**得到真正的公式或视觉比对：它们分别恒定贡献 0.5 与 0.7。
>
> 2. 预设中的取值与 `config/*.yaml` 里的示例值并不完全一致。以实际生效的那一路为准。

### 4.5 配置校验规则

`config/validator.py` 的 `DependencyValidator`（便捷入口 `validate_dependencies(config)`）返回错误信息列表，空列表表示通过。校验内容：

| 类别 | 规则 |
|------|------|
| **公式依赖** | 启用 `formula_match` 时，必须同时启用 `text.components.formulas` |
| **视觉依赖** | 启用 `visual_similarity` 时，必须同时启用 `image.components.deep_features` |
| **权重合法性** | 已启用的文本分量权重之和不得大于 `1.0` |
| **阈值区间** | `content_match.scoring.threshold`、`stage1.text_similarity_threshold`、`ocr.confidence_threshold` 均须落在 `[0.0, 1.0]` |
| **模型引用** | `chinese_model`、`english_model`、`deep_features.model` 必须是字符串 |

`config/schema.py` 的 `ConfigValidator` 另提供 `validate_features()` 与 `validate_matching()`，按 `FEATURES_SCHEMA` / `MATCHING_SCHEMA` 校验类型与枚举取值（如 `algorithm` 限 `dHash` / `pHash` / `aHash`，`languages` 元素限 `ch` / `en`）。

> **两个校验器都不会被脚本自动调用**。改完配置建议先手动跑一遍：

```bash
uv run python -c "from qsearch.config.loader import ConfigLoader; from qsearch.config.validator import validate_dependencies; c = ConfigLoader('config/my_config.yaml').base_config; e = validate_dependencies(c); print('\n'.join(e) if e else 'OK')"
```

### 4.6 推荐做法：合并为单一配置文件

由于 `--config` 只收单个文件，且匹配参数必须位于 `matching:` 之下，建议维护一份完整配置。以下模板可直接使用：

```yaml
# config/my_config.yaml

# ---------- 特征提取 ----------
text:
  components:
    stem:
      enabled: true
      weight: 0.6
    options:
      enabled: true
      weight: 0.3
      normalization:
        - remove_whitespace
        - normalize_punctuation
        - sort
    formulas:
      enabled: false        # 若下方开启 formula_match，这里必须改成 true
      weight: 0.1
  encoding:
    chinese_model: models/chinese-roberta-wwm-ext
    english_model: models/all-mpnet-base-v2
    embedding_dim: 768

image:
  components:
    perceptual_hash:
      enabled: true
      algorithm: dHash
      hash_size: 16
    deep_features:
      enabled: true         # visual_similarity 依赖此项
      model: efficientnet_b4
      output_dim: 512
  batch_size: 128

ocr:
  engine: transformers
  languages: [ch, en]
  confidence_threshold: 0.5

metadata:
  question_type_detection: true

# ---------- 匹配策略（注意必须嵌在 matching 之下）----------
matching:
  exact_match:
    enabled: true
    criteria:
      perceptual_hash:
        max_distance: 5

  content_match:
    enabled: true
    stage1:
      text_similarity_threshold: 0.75
      top_k: 100
    optional_conditions:
      # 两项当前均为简化/占位实现（恒定返回常量），故一并关闭；见 4.7
      formula_match:
        enabled: false
        weight: 0.15
      visual_similarity:
        enabled: false
        weight: 0.05
    scoring:
      method: weighted_sum
      threshold: 0.85

  output:
    top_k: 10
    grouping:
      by_match_type: true
    include_details:
      feature_scores: true
      debug_info: false
```

**调参建议**

| 目标 | 调整方向 |
|------|----------|
| 误配太多（精确率低） | 提高 `scoring.threshold`、`text_similarity_threshold`；下调 `max_distance` |
| 漏配太多（召回率低） | 反向调整上述参数；提高 `stage1.top_k` |
| 速度太慢 | 关闭 `image.components.deep_features`；下调 `stage1.top_k` |
| 显存不足 | 下调 `image.batch_size` 与 `--num-gpus` |

### 4.7 配置项接线状态（务必阅读）

配置文件里的字段并非全部已接入代码。以下逐项列出实测结果——**标记为「未接线」的字段改了不会有任何效果**（它们仍会通过 schema 校验，因此不会报错，属于静默失效）。

**已生效**

| 配置项 | 生效位置 |
|--------|----------|
| `text.components.stem.enabled` / `options.enabled` | `text_extractor.py` 控制是否提取 |
| `text.components.options.normalization` | 选项归一化策略实际执行 |
| `text.encoding.chinese_model` / `english_model` | 编码器加载路径（优先本地 `models/`，否则回落 HuggingFace） |
| `image.components.perceptual_hash.*` | `enabled` / `algorithm` / `hash_size` 全部生效 |
| `image.components.deep_features.enabled` / `model` / `output_dim` | 控制 CNN 特征**提取**（但提取结果未用于匹配打分，见下） |
| `image.batch_size` | 批大小，且遇 OOM 会自动折半重试 |
| `matching.exact_match.criteria.perceptual_hash.max_distance` | 汉明距离阈值 |
| `matching.content_match.stage1.*` | 相似度阈值与召回数 |
| `matching.content_match.stage2.required_conditions.*` | 三项必要条件全部生效 |
| `matching.content_match.scoring.*` | 权重与最终阈值 |
| `matching.output.top_k` | 每通道返回条数 |

**未接线**

| 配置项 | 实测情况 | 实际行为 |
|--------|----------|----------|
| `metadata.question_type_detection` | 仅存在于 schema，无任何读取处 | 题型检测始终开启（`QuestionParser` 无条件运行） |
| `text.encoding.embedding_dim` | 无任何读取处 | 维度由脚本内硬编码的 `dimension=768` 决定 |
| `text.components.*.weight` | 写入了特征记录的 `weights` 字段，但匹配打分完全不读取 | 仅作元信息留存，不影响任何结果 |
| `text.components.formulas.enabled` | `FormulaExtractor` 在整个代码库中**从未被实例化**，`self.formula_extractor` 恒为 `None` | 置 `true` 只会在特征记录里追加一条 `Formula extraction enabled but extractor not initialized` 警告，不会提取公式，也不会增加耗时 |
| `matching.exact_match.enabled` | 无读取处 | 只要查询图算出了感知哈希，精确通道就会执行 |
| `matching.content_match.enabled` | 无读取处 | 内容通道始终执行 |
| `matching.output.grouping.by_match_type` | 无读取处 | 输出恒按 `exact_matches` / `content_matches` 分组 |
| `matching.output.include_details.feature_scores` / `debug_info` | 无读取处 | `scores` 字段恒输出；无额外调试信息 |

**已接线但为简化 / 占位实现**

| 配置项 | 说明 |
|--------|------|
| `optional_conditions.formula_match` | 开关与权重生效，但打分逻辑是「双方都有公式记 1.0，否则 0.5」。由于上表中公式提取未接线，双方的 `formulas` 恒为空，因此该项**恒定贡献 0.5** |
| `optional_conditions.visual_similarity` | 开关与权重生效，但相似度恒返回占位值 `0.7`，未使用已提取的 CNN 特征 |

> **对使用者的直接影响**：可选条件当前只会给所有候选叠加一个近似常量的偏移，不具备区分能力。若追求可复现的结果，建议把 `formula_match` 与 `visual_similarity` 都置为 `false`。
>
> `FormulaExtractor.compare_formulas()` 与 `ImageFeatureExtractor` 已具备完整能力，缺的只是接入匹配器这一步；需要这两项能力时从此处着手。

---

## 五、端到端示例

```bash
# 0) 环境
uv venv --python 3.12
uv pip install -e .
uv run scripts/download_models.py
uv run scripts/verify_install.py

# 1) 下载底库图片（已有本地图片可跳过）
uv run scripts/download_images.py \
  --input data/base_urls.json \
  --output-zip data/base_images.zip \
  --workers 32

# 2) 解压待用
#    Windows PowerShell: Expand-Archive data/base_images.zip data/base_images
#    Linux / macOS:      unzip data/base_images.zip -d data/base_images

# 3) 建库
uv run scripts/index_database.py \
  --image-dir data/base_images \
  --output-dir data/index \
  --preset balanced \
  --num-gpus 1

# 4) 查询
uv run scripts/search_queries.py \
  --query-dir data/query_images \
  --index-dir data/index \
  --output-file data/results/matches.json \
  --preset balanced \
  --num-gpus 1

# 5) 查看统计
cat data/results/query_stats.json
```

---

## 六、输出结果格式

`--output-file` 是一个 JSON 数组，每个元素对应一张查询图：

```json
[
  {
    "query_image": "data/query_images/q_0001.jpg",
    "exact_matches": [
      {
        "image_id": "data/base_images/10001.jpg",
        "match_type": "EXACT_MATCH",
        "distance": 2,
        "confidence": 0.9922,
        "scores": {
          "hash_distance": 2
        },
        "confidence_level": "HIGH"
      }
    ],
    "content_matches": [
      {
        "image_id": "data/base_images/10001.jpg",
        "match_type": "CONTENT_MATCH",
        "final_score": 0.9134,
        "confidence": 0.9134,
        "verification_passed": ["stage1_vector", "stage2_required"],
        "scores": {
          "vector_similarity": 0.9421,
          "required_score": 0.9668,
          "optional_score": 0.6875
        },
        "also_exact_match": true,
        "confidence_level": "HIGH"
      }
    ],
    "processing_time_ms": 182.4
  }
]
```

公共字段：

| 字段 | 说明 |
|------|------|
| `query_image` | 查询图片路径 |
| `exact_matches` | 感知哈希通道命中，按置信度降序，最多 `output.top_k` 条 |
| `content_matches` | 内容匹配通道命中，按 `final_score` 降序，最多 `output.top_k` 条 |
| `image_id` | 命中的底库图片路径 |
| `match_type` | `EXACT_MATCH` 或 `CONTENT_MATCH` |
| `confidence` | 置信度（0–1）。内容匹配中该值等于 `final_score` |
| `confidence_level` | 分级：`HIGH`（≥0.9）/ `MEDIUM`（≥0.8）/ `LOW` |
| `processing_time_ms` | 该条查询耗时（毫秒） |

精确匹配专有字段：

| 字段 | 说明 |
|------|------|
| `distance` | 汉明距离，越小越像 |
| `scores.hash_distance` | 同上，冗余保留 |

内容匹配专有字段：

| 字段 | 说明 |
|------|------|
| `final_score` | `0.7 × vector_similarity + 0.3 × text_similarity` |
| `verification_passed` | 已通过的校验阶段列表 |
| `scores.vector_similarity` | 阶段 1 的余弦相似度 |
| `scores.required_score` | 必要条件各项得分的算术平均 |
| `scores.optional_score` | 可选条件的加权平均；无启用项时为 `0.0` |
| `also_exact_match` | 该结果同时被精确匹配命中，可信度更高 |

> `confidence` 由 `1.0 - distance / 256` 换算，分母固定为 256（对应 `hash_size: 16`）。若把 `hash_size` 改成其他值，该置信度的标度会失真，`distance` 字段仍然准确。

同级目录的 `query_stats.json`：

```json
{
  "total_queries": 200000,
  "total_exact_matches": 145230,
  "total_content_matches": 178432,
  "avg_processing_time_ms": 182.4,
  "queries_with_matches": 189210
}
```

---

## 七、常见问题

**Q：`ImportError: No module named 'qsearch'`**

未安装项目包。执行 `uv pip install -e .`。`search_queries.py` 不含 `sys.path` 兜底，必须安装后使用。

**Q：如何使用 WebUI 配置索引构建参数？**

启动 WebUI 后，在"数据集"页面创建新数据集时，展开"高级参数"面板即可看到完整的配置选项。详细说明请参考 [索引构建参数配置文档](docs/INDEX_BUILD_PARAMS.md)。

主要配置项包括：
- **配置预设**：快速选择 default/fast/accurate/mobile 预设
- **计算资源**：CPU 并行数或 GPU 数量
- **特征提取**：模型路径、图像尺寸、批处理大小
- **OCR 引擎**：引擎选择、检测/识别阈值
- **索引类型**：Flat/IVFFlat/IVFPQ/HNSW
- **匹配策略**：权重分配、相似度阈值

**Q：WebUI 的任务队列在哪里查看？**

主页显示实时队列状态，包括排队、运行中、已完成、失败的任务数量。点击"任务监控"页面可以查看详细的任务历史、进度和日志。

**Q：如何监控系统资源使用情况？**

主页右侧显示实时的系统资源监控，包括 CPU 使用率、GPU 使用率（如果有）、内存使用情况和可用内存。这些数据每 2 秒自动刷新。

**Q：OCR 未使用 GPU，或多卡加载失败**

确认安装的是带 CUDA 的 PyTorch，并可通过 `torch.cuda.is_available()` 检测到显卡。多卡自动切分依赖 `accelerate`；项目依赖已包含该包。无可用 CUDA 时 `OCREngine` 会自动回退到 CPU。

**Q：Windows 上 `faiss-gpu` 装不上**

Faiss 官方不提供 Windows GPU 轮子，Windows 上只能用 `faiss-cpu`。用 `requirements-windows.txt` 或 `requirements.txt`（后者含平台标记，会自动选对）。

**Q：模型下载很慢或超时**

设置镜像后重跑 `download_models.py`：`$env:HF_ENDPOINT = "https://hf-mirror.com"`（PowerShell）或 `export HF_ENDPOINT=https://hf-mirror.com`。

**Q：`download_images.py` 中断后压缩包读不出来**

正常现象且已被处理：下载期间数据在分片目录（`<output-zip>.d`）里，最终 zip 只在合并后才存在。直接重跑原命令即可续传；只想合并已有分片就加 `--merge`。

**Q：下载时内存持续上涨**

下调 `--queue-size`（默认 64）与 `--workers`。队列长度决定了内存中缓冲的图片数量上限，是内存占用的主要来源。

**Q：改了配置为什么没生效**

三种常见原因：① 同时传了 `--config` 和 `--preset`，后者被忽略；② 把 `config/matching.yaml` 直接当 `--config` 传入，但匹配参数需要嵌在 `matching:` 之下，见 [4.1](#41-配置加载机制与优先级)；③ 修改了特征侧参数（如 `hash_size`、编码模型）但没重建索引。

**Q：显存不足（OOM）**

下调 `image.batch_size`（默认 128）与 `--num-gpus`，并关闭 `image.components.deep_features`（CNN 骨干是显存主要占用方）。图像特征提取遇到 OOM 时会自动把批大小折半重试，但持续 OOM 仍需手动下调。

**Q：查询结果全是空的，一条都没匹配上**

检查 `scoring.threshold` 是否设置过高。默认阈值为 `0.85`，可以尝试降低到 `0.75` 或 `0.65` 来增加召回率。同时确认索引文件存在且特征提取成功。

其次确认建库与查询用的是同一套配置：编码模型或 `hash_size` 不一致会让特征不可比。最后可临时改用 `--preset aggressive` 放宽阈值，确认链路本身是通的。

**Q：`--checkpoint-every` 不起作用**

当前版本只声明了该参数，未实现检查点写出，因此没有文件可供 `--resume-from` 读取。参见 [3.2.4](#324-index_databasepy--构建底库索引) 的说明。

**Q：想启用公式匹配 / 视觉相似度**

当前版本**做不到**，需要改代码。两项的匹配打分是简化 / 占位实现（分别恒返回 0.5 与 0.7），且 `FormulaExtractor` 从未被实例化，因此把配置开关打开也拿不到真实的比对结果。

底层能力已经具备——`FormulaExtractor.compare_formulas()` 可比较 LaTeX，`ImageFeatureExtractor` 已能产出 CNN 深度特征——缺的只是接入 `matchers.py` 的 `_check_optional_conditions()`，以及在 `TextFeatureExtractor` 中实际构造 `FormulaExtractor`。详见 [4.7](#47-配置项接线状态务必阅读)。

**Q：为什么 4.7 列出的那些字段不直接删掉**

它们都在 `schema.py` 的校验模式里，删字段会连带改校验逻辑与预设。当前先在文档里标明真实状态，避免使用者在无效旋钮上浪费时间；后续接线时这些字段可直接复用。
