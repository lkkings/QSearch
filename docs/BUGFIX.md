# 已修复的问题

## 问题 1: normalize_text() missing 1 required positional argument: 'strategies'

### 原因
`normalize_text()` 函数需要两个参数：
```python
def normalize_text(text: str, strategies: List[str]) -> str:
    ...
```

但在 `text_extractor.py` 中只传递了一个参数。

### 解决方案
创建了一个简化的 `simple_normalize_text()` 函数，不需要额外参数：

```python
def simple_normalize_text(text: str) -> str:
    """Simple text normalization without external dependencies."""
    if not text:
        return ""
    
    # Remove extra whitespace
    normalized = ' '.join(text.split())
    
    return normalized
```

### 修改的文件
- `src/qsearch/features/text_extractor.py`

---

## 问题 2: ccache warning

### 警告信息
```
UserWarning: No ccache found. Please be aware that recompiling all 
source files may be required. You can download and install ccache from: 
https://github.com/ccache/ccache/blob/master/doc/INSTALL.md
```

### 原因
PaddlePaddle 需要编译 C++ 扩展，建议使用 ccache 来加速编译。

### 解决方案
这是一个警告，不会影响功能。如果想消除警告，可以：

#### Windows
```bash
# 下载 ccache
# https://github.com/ccache/ccache/releases

# 或使用 Chocolatey
choco install ccache

# 添加到 PATH
set PATH=%PATH%;C:\path\to\ccache
```

#### Linux/Mac
```bash
# Ubuntu/Debian
sudo apt-get install ccache

# CentOS/RHEL
sudo yum install ccache

# macOS
brew install ccache
```

### 忽略此警告
如果不需要频繁重新编译 PaddlePaddle 扩展，可以忽略此警告。它不会影响 QSearch 的正常使用。

---

## 验证修复

运行以下命令验证问题已解决：

```bash
# 测试文本提取
python -c "
from src.qsearch.features.text_extractor import TextFeatureExtractor
from src.qsearch.config.loader import ConfigLoader

config = ConfigLoader('config/features.yaml').base_config
extractor = TextFeatureExtractor(config.get('text_features', {}))
print('✓ TextFeatureExtractor 初始化成功')
"
```

或运行完整测试：

```bash
python scripts/verify_install.py
```

---

## 更新日期
2025-09-10
