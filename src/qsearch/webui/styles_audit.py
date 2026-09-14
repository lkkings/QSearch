"""设计令牌的对比度核算。

把「令牌是否满足对比度规格」从一次性的肉眼检查变成可复算的断言。
`--text-3` 原值 #6B7580 压在 surface-2 上仅 4.31:1 —— 低于 4.5 下限，
而它用在显示文件路径的 caption 上。这类偏差算得出来，看不出来。

供 tests/ 与 scripts/audit_contrast.py 共用。
"""

from __future__ import annotations

import re
from pathlib import Path

TOKENS_PATH = Path(__file__).parent / "styles" / "tokens.css"

# WCAG 2.1 阈值
MIN_BODY = 4.5      # 正文、标签、数值等承载信息的文本
MIN_LARGE = 3.0     # 大号或粗体标题
MIN_NON_TEXT = 3.0  # 描边、焦点环等非文本 UI 组件（WCAG 1.4.11）

_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def parse_tokens(path: Path | None = None) -> dict[str, str]:
    """从 tokens.css 的 :root 块中提取令牌。

    Args:
        path: tokens.css 路径，默认为模块同级的 styles/tokens.css

    Returns:
        令牌名（不含 ``--`` 前缀）到原始值字符串的映射
    """
    css = (path or TOKENS_PATH).read_text(encoding="utf-8")
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    return {
        m.group(1): m.group(2).strip()
        for m in re.finditer(r"--([\w-]+)\s*:\s*([^;]+);", css)
    }


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    """将 hex 色值转为 RGB 三元组。

    Args:
        value: ``#rgb`` 或 ``#rrggbb``

    Returns:
        (r, g, b)，各通道 0-255

    Raises:
        ValueError: 不是合法的 hex 色值
    """
    v = value.strip()
    if not _HEX_RE.match(v):
        raise ValueError(f"不是 hex 色值：{value!r}")
    h = v.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    """WCAG 相对亮度。

    Args:
        rgb: (r, g, b)，各通道 0-255

    Returns:
        相对亮度，0.0-1.0
    """
    def channel(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg: str, bg: str) -> float:
    """两个 hex 色值之间的对比度。

    Args:
        fg: 前景 hex
        bg: 背景 hex

    Returns:
        对比度，1.0-21.0
    """
    l1 = relative_luminance(hex_to_rgb(fg))
    l2 = relative_luminance(hex_to_rgb(bg))
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


# 需要核算的组合。
#
# 文字令牌 × 它们实际会压在其上的表面 —— 而非全部叉乘：dialog 表面上
# 不会出现 text-3 这类附属信息，凑出来的组合会制造假失败。
TEXT_ON_SURFACE = [
    ("text-1", ["surface-0", "surface-1", "surface-2", "surface-3", "surface-4"]),
    ("text-2", ["surface-0", "surface-1", "surface-2", "surface-3"]),
    ("text-3", ["surface-0", "surface-1", "surface-2"]),
]

# chip 的文字 × 自身填充。取值依据 chips.css 中各 chip 的实际 color 属性，
# 而非按令牌名推测 —— 例如 task-done 确实用作文字色，task-cancelled 不是。
CHIP_TEXT_PAIRS = [
    ("info-high-text", "info-high-bg"),   # conf-high
    ("info-mid-text", "info-mid-bg"),     # conf-mid / index-missing / task-running
    ("info-low-text", "info-low-bg"),     # conf-low / task-failed
    ("task-done", "info-high-bg"),        # index-built / task-done
    ("text-2", "surface-2"),              # task-pending / task-cancelled 的文字
    ("text-3", "surface-2"),              # conf-unknown
]

# chip 的描边 × 自身填充。
#
# 描边不是文本，故阈值取 3:1（WCAG 1.4.11 非文本对比）而非 4.5。
# 本项目规格的 4.5 明确限定于「正文、标签或数值等承载信息的文本」。
#
# 这些描边仍需达标：chip 与 badge 的形态差异（描边 vs 实心）是 D2 的
# 第二条通道，描边看不见时该通道就失效了。
CHIP_BORDER_PAIRS = [
    ("info-high", "info-high-bg"),
    ("info-mid", "info-mid-bg"),
    ("info-low", "info-low-bg"),
    ("task-done", "info-high-bg"),
    ("task-running", "info-mid-bg"),
    ("task-failed", "info-low-bg"),
    ("task-pending", "surface-2"),
    ("task-cancelled", "surface-2"),
]

# badge：决策色作填充，深色前景压其上
BADGE_PAIRS = [
    ("on-hit", "hit"),
    ("on-miss", "miss"),
    ("on-skip", "skip"),
]

# 焦点环 × 它出现的表面。焦点指示是非文本 UI 组件，阈值 3:1。
FOCUS_PAIRS = [
    ("focus", "surface-0"),
    ("focus", "surface-1"),
    ("focus", "surface-2"),
]


def audit(tokens: dict[str, str] | None = None) -> list[dict]:
    """核算全部需要检查的组合。

    Args:
        tokens: 令牌映射，默认从 tokens.css 读取

    Returns:
        每项含 fg / bg / ratio / threshold / passes / group 的记录列表
    """
    t = tokens if tokens is not None else parse_tokens()
    rows: list[dict] = []

    def add(fg: str, bg: str, group: str, threshold: float = MIN_BODY) -> None:
        if fg not in t or bg not in t:
            return
        try:
            ratio = contrast_ratio(t[fg], t[bg])
        except ValueError:
            return  # 非 hex（如 rgba 状态层）不参与核算
        rows.append({
            "group": group,
            "fg": fg, "fg_value": t[fg],
            "bg": bg, "bg_value": t[bg],
            "ratio": round(ratio, 2),
            "threshold": threshold,
            "passes": ratio >= threshold,
        })

    for fg, backgrounds in TEXT_ON_SURFACE:
        for bg in backgrounds:
            add(fg, bg, "文字/表面")

    for fg, bg in CHIP_TEXT_PAIRS:
        add(fg, bg, "chip 文字")

    for fg, bg in CHIP_BORDER_PAIRS:
        add(fg, bg, "chip 描边", MIN_NON_TEXT)

    for fg, bg in BADGE_PAIRS:
        add(fg, bg, "badge 文字")

    for fg, bg in FOCUS_PAIRS:
        add(fg, bg, "焦点环", MIN_NON_TEXT)

    return rows


def failures(tokens: dict[str, str] | None = None) -> list[dict]:
    """仅返回未达标的组合。

    Args:
        tokens: 令牌映射，默认从 tokens.css 读取

    Returns:
        未达标记录列表
    """
    return [r for r in audit(tokens) if not r["passes"]]


def format_table(rows: list[dict]) -> str:
    """将核算结果格式化为 Markdown 表格。

    Args:
        rows: audit() 的返回值

    Returns:
        Markdown 表格文本
    """
    lines = [
        "| 分组 | 前景 | 背景 | 对比度 | 下限 | |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        mark = "✓" if r["passes"] else "✗"
        lines.append(
            f"| {r['group']} | `--{r['fg']}` {r['fg_value']} "
            f"| `--{r['bg']}` {r['bg_value']} "
            f"| {r['ratio']} | {r['threshold']} | {mark} |"
        )
    return "\n".join(lines)
