"""样式表的读取与注入。

CSS 以静态文件形式存放于 ``qsearch/webui/styles/``，而非内联在页面模块中。
放在磁盘上编辑器才能做语法高亮与检查，``app.py`` 也得以回归其页面编排职责。

加载顺序有意义：``tokens.css`` 声明了后续各表通过 ``var(--*)`` 引用的自定义
属性，必须最先；``glass.css`` 最后，使其浮层规则覆盖组件层的默认外观。
"""

from pathlib import Path

import streamlit as st

STYLES_DIR = Path(__file__).parent.parent / "styles"

# 顺序有意义，见模块 docstring。
STYLESHEETS = (
    "tokens.css",
    "base.css",
    "components.css",
    "chips.css",
    "table.css",
    "workbench.css",
    "glass.css",
)


class StylesheetError(RuntimeError):
    """声明的样式表无法读取时抛出。"""


def _read(name: str) -> str:
    """读取单个样式表。

    Args:
        name: ``STYLES_DIR`` 下的文件名

    Returns:
        文件内容

    Raises:
        StylesheetError: 文件缺失或不可读
    """
    path = STYLES_DIR / name
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise StylesheetError(
            f"样式表不存在：{path}。"
            "STYLESHEETS 中声明的每个文件都必须存在——缺失一个会让界面"
            "部分失去样式，那看起来像是页面坏了，而不像是一次明确的失败。"
        ) from exc
    except OSError as exc:
        raise StylesheetError(f"样式表读取失败 {path}：{exc}") from exc


def load_css() -> str:
    """按声明顺序拼接全部样式表。

    Returns:
        拼接后的 CSS，各段以来源文件名注释分隔

    Raises:
        StylesheetError: 任一声明的样式表缺失或不可读
    """
    parts = [f"/* ===== {name} ===== */\n{_read(name)}" for name in STYLESHEETS]
    return "\n".join(parts)


def inject_css() -> None:
    """将样式表注入当前页面。

    每次页面运行调用一次，位置在 ``st.set_page_config`` 之后、渲染内容之前。

    Raises:
        StylesheetError: 任一声明的样式表缺失或不可读
    """
    st.markdown(f"<style>\n{load_css()}\n</style>", unsafe_allow_html=True)
