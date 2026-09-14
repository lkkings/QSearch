"""交互并行度裁决与两车道内存预算。

覆盖 4.6（clamp_interactive_workers）与 4.7（内存预算估算与降级）。

内存场景全部构造出来，不依赖跑测试那台机器的实际空闲内存 —— 否则同一份断言
在 8GB 与 64GB 机器上结论相反。
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from qsearch.tasks import settings


def _fake_memory(available_gb: float):
    """构造一个 psutil.virtual_memory() 的替身。

    Args:
        available_gb: 期望被报告的可用内存 GB 数

    Returns:
        可直接赋给 ``psutil.virtual_memory`` 的无参函数
    """
    return lambda: SimpleNamespace(available=int(available_gb * (1024 ** 3)))


# ---------- 4.6：交互并行度收敛 ----------


@pytest.mark.parametrize(
    "requested,expected",
    [
        (0, 1),          # 下界收敛
        (-5, 1),         # 负数同样收敛到 1
        (99, 4),         # 超上限收敛到天花板
        (3, 3),          # 区间内原样通过
        (None, 2),        # 未指定取默认值
        ("abc", 2),      # 非整数回退默认值
        (2.9, 2),        # 浮点截断而非四舍五入
    ],
)
def test_clamp_interactive_workers(requested, expected) -> None:
    """请求值被收敛到 [1, 上限]，非法输入回退默认值。"""
    assert settings.clamp_interactive_workers(requested) == expected


def test_interactive_ceiling_is_lower_than_cpu_count() -> None:
    """交互上限与 CPU 核数解耦。

    交互 worker 永久驻留，数量该由同时使用的人数决定，不该随核数膨胀。
    """
    assert settings.INTERACTIVE_WORKERS_CEILING == 4
    assert settings.INTERACTIVE_WORKERS_DEFAULT == 2


# ---------- 4.7：内存预算与降级 ----------


def test_ample_memory_keeps_both_lanes(monkeypatch: pytest.MonkeyPatch) -> None:
    """内存充足时两车道都保持请求值，不降级。"""
    import psutil

    monkeypatch.setattr(psutil, "virtual_memory", _fake_memory(64.0))

    plan = settings.plan_worker_budget(background=4, interactive=2)

    assert plan["background"] == 4
    assert plan["interactive"] == 2
    assert plan["degraded"] is False
    assert plan["reason"] is None


def test_low_memory_degrades_interactive_not_background(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """内存不足时降交互并行度，后台并行度保持请求值。

    降后台是可感知的吞吐退化，降交互只在多人并发时表现为排队 —— 因此代价
    落在交互侧。
    """
    import psutil

    # 4 后台 + 2 交互 = 6 × 1.5GB = 9GB；只给 7.5GB，恰好容得下 5 个 worker。
    monkeypatch.setattr(psutil, "virtual_memory", _fake_memory(7.5))

    plan = settings.plan_worker_budget(background=4, interactive=2)

    assert plan["background"] == 4, "后台并行度不该被降"
    assert plan["interactive"] == 1
    assert plan["requested_interactive"] == 2
    assert plan["degraded"] is True


def test_degradation_reason_is_not_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    """降级必须给出原因与降级前后的值，供启动脚本打印。"""
    import psutil

    monkeypatch.setattr(psutil, "virtual_memory", _fake_memory(7.5))

    plan = settings.plan_worker_budget(background=4, interactive=2)
    reason = plan["reason"]

    assert reason, "降级不得静默"
    # 原因里要能看出降到了几，否则用户无法判断生效值。
    assert "1" in reason
    assert plan["available_gb"] == pytest.approx(7.5, abs=0.01)


def test_interactive_never_drops_below_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """即使后台并行度已经吃掉全部内存，交互车道仍保留 1 个 worker。

    交互并行度降到 0 等于关掉单图查询这个功能，那不是降级而是移除。
    """
    import psutil

    monkeypatch.setattr(psutil, "virtual_memory", _fake_memory(1.0))

    plan = settings.plan_worker_budget(background=8, interactive=4)

    assert plan["interactive"] == 1
    assert plan["background"] == 8


def test_missing_psutil_skips_estimation(monkeypatch: pytest.MonkeyPatch) -> None:
    """psutil 缺失时不猜内存，也不降级。"""
    monkeypatch.setitem(sys.modules, "psutil", None)

    plan = settings.plan_worker_budget(background=4, interactive=2)

    assert plan["degraded"] is False
    assert plan["interactive"] == 2
    assert plan["available_gb"] is None
    assert "psutil" in plan["reason"]
