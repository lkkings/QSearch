"""共享的状态标示组件。

这些组件把「哪些颜色可以用在哪里」这条纪律固定在一处，而不是散落在四个
页面模块里各写一遍状态字典。

两组颜色的边界（见 tokens.css 的 D2 说明）：

  决策寄存器   高饱和 + 图标 + 实心    只表示「人给出的判断」
  信息寄存器   低饱和 + 无图标 + chip  只表示机器输出

置信度与命中都天然想要绿色。若同色，标注员将无法区分「这是我判的」与
「这是机器猜的」，机器的高置信会污染人的判断基线。所以置信度走信息
寄存器，命中走决策寄存器，两者在饱和度与形态两条通道上都不重叠。

另一条纪律：任何状态都不得仅靠颜色区分。绿/红对红绿色盲（男性约 8%）
不可靠，故每个状态都带图标或字形冗余。
"""

from html import escape

import streamlit as st

# 置信等级 —— 机器输出。无图标，靠 chip 形态与文字区分。
_CONFIDENCE = {
    "HIGH": ("qs-chip--conf-high", "高"),
    "MEDIUM": ("qs-chip--conf-mid", "中"),
    "LOW": ("qs-chip--conf-low", "低"),
}

# 标注结果 —— 人的判断。带图标，高饱和实心。
# 图标经 CSS ::before 注入（见 chips.css 的 .qs-icon--*），不写字面字形：
# 原始 HTML 拿不到 Streamlit 的 `:material/xxx:` 短代码。
_LABEL = {
    "hit": ("qs-badge--hit", "qs-icon--hit", "命中"),
    "miss": ("qs-badge--miss", "qs-icon--miss", "未命中"),
    "skip": ("qs-badge--skip", "qs-icon--skip", "跳过"),
}

# 任务状态 —— 机器输出。图标 + 低饱和。
_TASK = {
    "pending": ("qs-chip--task-pending", "qs-icon--task-pending", "等待中"),
    "running": ("qs-chip--task-running", "qs-icon--task-running", "运行中"),
    "completed": ("qs-chip--task-done", "qs-icon--task-done", "已完成"),
    "failed": ("qs-chip--task-failed", "qs-icon--task-failed", "失败"),
    "cancelled": ("qs-chip--task-cancelled", "qs-icon--task-cancelled", "已取消"),
}

# 匹配类型 —— 机器输出，中性呈现。
_MATCH_TYPE = {
    "exact": "精确",
    "content": "内容",
}


def confidence_chip(level: str) -> str:
    """置信等级的 chip 标记。

    Args:
        level: ``HIGH`` / ``MEDIUM`` / ``LOW``

    Returns:
        HTML 片段。低饱和、无图标 —— 与决策色在形态上区分开。
    """
    cls, text = _CONFIDENCE.get(
        (level or "").upper(), ("qs-chip--conf-unknown", "未知")
    )
    return f'<span class="qs-chip {cls}">{escape(text)}</span>'


def label_badge(label: str | None) -> str:
    """标注结果的徽章。

    Args:
        label: ``hit`` / ``miss`` / ``skip``，``None`` 表示未标注

    Returns:
        HTML 片段。高饱和实心 + 图标 —— 图标是颜色之外的冗余通道。
    """
    if not label:
        return (
            '<span class="qs-badge qs-badge--unlabeled qs-icon '
            'qs-icon--unlabeled">未标注</span>'
        )

    cls, icon_cls, text = _LABEL.get(
        label.lower(), ("qs-badge--unlabeled", "qs-icon--unlabeled", "未标注")
    )
    return (
        f'<span class="qs-badge {cls} qs-icon {icon_cls}">{escape(text)}</span>'
    )


def task_status_chip(status: str) -> str:
    """任务状态的 chip 标记。

    Args:
        status: ``pending`` / ``running`` / ``completed`` / ``failed`` / ``cancelled``

    Returns:
        HTML 片段。低饱和 + 图标 —— 任务状态是机器输出，不占用决策色。
    """
    cls, icon_cls, text = _TASK.get(
        (status or "").lower(),
        ("qs-chip--task-pending", "qs-icon--task-unknown", "未知"),
    )
    return f'<span class="qs-chip {cls} qs-icon {icon_cls}">{escape(text)}</span>'


def index_status(built: bool) -> str:
    """索引构建状态。

    Args:
        built: 索引是否已构建

    Returns:
        HTML 片段。图标 + 文字双重标示，使其在灰度下仍可辨 —— 未构建索引
        的库不能用于搜索，这个状态被误读的代价是用户白等一次失败的搜索。
    """
    if built:
        return (
            '<span class="qs-chip qs-chip--index-built qs-icon '
            'qs-icon--index-built">索引已建</span>'
        )
    return (
        '<span class="qs-chip qs-chip--index-missing qs-icon '
        'qs-icon--index-missing">索引未建</span>'
    )


def match_type_text(match_type: str) -> str:
    """匹配类型的中文文案。

    Args:
        match_type: ``exact`` / ``content``

    Returns:
        中文文案
    """
    return _MATCH_TYPE.get((match_type or "").lower(), match_type or "未知")


def render(html: str) -> None:
    """渲染一段组件 HTML。

    集中此处，避免各页面反复写 ``unsafe_allow_html=True``。

    Args:
        html: 由本模块其他函数产出的 HTML 片段
    """
    st.markdown(html, unsafe_allow_html=True)


def worker_slider(key: str, label: str = "并行进程数") -> int:
    """并行数选择器。上限硬绑 CPU 核数。

    滑块的 ``max_value`` 就是 CPU 核数，因此越界值在 UI 层就无法产生；
    ``clamp_workers`` 仍在入队时再收一遍，用于挡住绕过 UI 的调用路径。

    Args:
        key: Streamlit 组件 key，须在整个应用内唯一
        label: 显示标签

    Returns:
        用户选择的并行数
    """
    from qsearch.tasks import settings

    default = settings.default_max_workers()

    workers = st.slider(
        label,
        min_value=1,
        max_value=settings.CPU_COUNT,
        value=default,
        key=key,
        help=(
            f"本机 {settings.CPU_COUNT} 核，上限即为核数。"
            f"每个进程约占 {settings.WORKER_MEMORY_GB}GB 内存"
            f"（各自持有一套 OCR 与编码器模型），"
            f"当前推荐 {default}。"
        ),
    )

    # 内存推算与 CPU 上限是两条独立约束。核数够但内存不够时给出提示，
    # 而不是静默降级 —— 用户明确选了这个数字。
    memory_cap = settings.memory_aware_worker_cap()
    if workers > memory_cap:
        st.caption(
            f":material/warning: 按可用内存估算约能容纳 {memory_cap} 个进程，"
            f"选 {workers} 可能触发换页或 OOM。"
        )

    return workers


def scheduler_badge(status: dict) -> str:
    """调度进程状态标记。

    Args:
        status: :func:`qsearch.tasks.service.scheduler_status` 的返回值

    Returns:
        HTML 片段
    """
    if status.get("running"):
        pid = status.get("pid")
        return (
            '<span class="qs-chip qs-chip--index-built qs-icon '
            'qs-icon--index-built">调度器运行中'
            f'{f" · PID {pid}" if pid else ""}</span>'
        )

    return (
        '<span class="qs-chip qs-chip--index-missing qs-icon '
        'qs-icon--index-missing">调度器未运行</span>'
    )
