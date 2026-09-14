"""任务系统的运行时设置。

并行度的唯一裁决点。所有并行数最终都经过 :func:`clamp_workers`，因此
"并行数不能超过 CPU 核数" 这条约束只在一处实现，不散落在 UI 与调度器里。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# 硬上限。os.cpu_count() 在容器里可能返回宿主机核数，但它是标准库能给出的
# 最好答案；再往下要读 cgroup，超出本项目范围。
CPU_COUNT = os.cpu_count() or 1

# 每个 worker 自带 OCR 引擎与中英文编码器，实测常驻约 1GB，留出图像缓冲余量。
# 与 features/feature_extractor.py 中的同名常量保持一致。
WORKER_MEMORY_GB = 1.5

# psutil 缺失时无法测量可用内存，保守封顶。
MAX_WORKERS_WITHOUT_MEMINFO = 4

ENV_MAX_WORKERS = "QSEARCH_MAX_WORKERS"
ENV_MAX_CONCURRENT_TASKS = "QSEARCH_MAX_CONCURRENT_TASKS"
ENV_QUEUE_ROOT = "QSEARCH_QUEUE_ROOT"

# 同时运行的任务数。默认 1：每个并发任务都会持有一整套模型副本，
# 放开并发等于成倍占用内存，而任务内部已经用进程池并行了。
DEFAULT_MAX_CONCURRENT_TASKS = 1
MAX_CONCURRENT_TASKS_CEILING = 4

# 交互车道的并行度与后台车道不对称，两者的优化目标不同：
#
#              后台车道            交互车道
#   工作单元    数万张图            1 张图
#   优化目标    吞吐                延迟
#   加 worker   近线性提速          只增并发人数，单次不变快
#   内存驻留    任务执行期间        永久（复用模型即不能回收）
#
# 交互 worker 永久驻留，其数量该由「同时使用的人数」决定，而非 CPU 核数 ——
# 给交互车道 8 个进程是用 12GB 常驻内存换一个不存在的并发需求。上限定在 4：
# 再高说明该走真正的服务化，不该靠堆常驻进程解决。
INTERACTIVE_WORKERS_DEFAULT = 2
INTERACTIVE_WORKERS_CEILING = 4

ENV_INTERACTIVE_WORKERS = "QSEARCH_INTERACTIVE_WORKERS"


def clamp_workers(requested: int | None) -> int:
    """把请求的并行数收敛到 [1, CPU_COUNT]。

    Args:
        requested: 请求的并行数，``None`` 表示取默认值

    Returns:
        合法的并行数
    """
    if requested is None:
        return default_max_workers()

    try:
        value = int(requested)
    except (TypeError, ValueError):
        logger.warning("并行数 %r 不是整数，回退到默认值", requested)
        return default_max_workers()

    if value > CPU_COUNT:
        logger.warning(
            "请求并行数 %d 超过 CPU 核数 %d，已收敛到 %d",
            value, CPU_COUNT, CPU_COUNT,
        )

    return max(1, min(value, CPU_COUNT))


def clamp_interactive_workers(requested: int | None) -> int:
    """把交互车道并行度收敛到 [1, INTERACTIVE_WORKERS_CEILING]。

    与 :func:`clamp_workers` 共享「非法输入回退默认值」的语义，但默认值与
    天花板各不相同 —— 见 :data:`INTERACTIVE_WORKERS_DEFAULT` 处的取舍说明。

    Args:
        requested: 请求的交互并行数，``None`` 表示取默认值

    Returns:
        位于 ``[1, INTERACTIVE_WORKERS_CEILING]`` 的并行数
    """
    if requested is None:
        return INTERACTIVE_WORKERS_DEFAULT

    try:
        value = int(requested)
    except (TypeError, ValueError):
        logger.warning(
            "交互并行数 %r 不是整数，回退到默认值 %d",
            requested, INTERACTIVE_WORKERS_DEFAULT,
        )
        return INTERACTIVE_WORKERS_DEFAULT

    if value > INTERACTIVE_WORKERS_CEILING:
        logger.warning(
            "请求交互并行数 %d 超过上限 %d，已收敛到 %d",
            value, INTERACTIVE_WORKERS_CEILING, INTERACTIVE_WORKERS_CEILING,
        )

    return max(1, min(value, INTERACTIVE_WORKERS_CEILING))


def plan_worker_budget(
    background: int | None = None, interactive: int | None = None
) -> dict:
    """估算两车道的内存预算，超出可用内存时降交互并行度。

    降 M 不降 N：降后台并行度是可感知的吞吐退化（后台是本系统的主要负载），
    降交互并行度只在多人同时查询时表现为排队。降级不静默 —— 返回值带上原因
    与降级前后的值，供启动脚本打印。

    Args:
        background: 请求的后台并行数，``None`` 取默认推算值
        interactive: 请求的交互并行数，``None`` 取默认值

    Returns:
        含 ``background``、``interactive``、``requested_interactive``、
        ``degraded``、``reason``、``required_gb``、``available_gb`` 的字典
    """
    resolved_bg = clamp_workers(background)
    resolved_ia = clamp_interactive_workers(interactive)

    plan = {
        "background": resolved_bg,
        "interactive": resolved_ia,
        "requested_interactive": resolved_ia,
        "degraded": False,
        "reason": None,
        "required_gb": (resolved_bg + resolved_ia) * WORKER_MEMORY_GB,
        "available_gb": None,
    }

    try:
        import psutil
    except ImportError:
        # 测不到可用内存时不猜。保守封顶已由 memory_aware_worker_cap 处理。
        plan["reason"] = "psutil 缺失，跳过内存预算估算"
        return plan

    available_gb = psutil.virtual_memory().available / (1024 ** 3)
    plan["available_gb"] = available_gb

    if plan["required_gb"] <= available_gb:
        return plan

    # 后台并行度保持请求值，交互并行度让到内存能容下为止，但不低于 1。
    affordable = int(available_gb // WORKER_MEMORY_GB) - resolved_bg
    degraded_ia = max(1, min(resolved_ia, affordable))

    if degraded_ia == resolved_ia:
        return plan

    plan["interactive"] = degraded_ia
    plan["degraded"] = True
    plan["required_gb"] = (resolved_bg + degraded_ia) * WORKER_MEMORY_GB
    plan["reason"] = (
        f"两车道共需约 {(resolved_bg + resolved_ia) * WORKER_MEMORY_GB:.1f}GB，"
        f"可用内存约 {available_gb:.1f}GB；"
        f"交互并行度由 {resolved_ia} 降为 {degraded_ia}（后台保持 {resolved_bg}）"
    )

    logger.warning("内存不足，%s", plan["reason"])
    return plan


def memory_aware_worker_cap() -> int:
    """按可用内存推算能容纳多少个 worker。

    Returns:
        内存视角下的 worker 上限，至少为 1
    """
    try:
        import psutil
    except ImportError:
        logger.debug("psutil 不可用，保守封顶 %d", MAX_WORKERS_WITHOUT_MEMINFO)
        return min(CPU_COUNT, MAX_WORKERS_WITHOUT_MEMINFO)

    available_gb = psutil.virtual_memory().available / (1024 ** 3)
    return max(1, int(available_gb // WORKER_MEMORY_GB))


def default_max_workers() -> int:
    """默认并行数：环境变量优先，否则取 CPU 与内存的较小值。

    Returns:
        默认并行数
    """
    env_value = os.environ.get(ENV_MAX_WORKERS)
    if env_value:
        try:
            return max(1, min(int(env_value), CPU_COUNT))
        except ValueError:
            logger.warning("%s=%r 不是整数，忽略", ENV_MAX_WORKERS, env_value)

    cpu_budget = max(1, CPU_COUNT - 1)
    workers = min(cpu_budget, memory_aware_worker_cap())

    if workers < cpu_budget:
        logger.info("受内存限制，默认并行数降为 %d（CPU 预算 %d）", workers, cpu_budget)

    return workers


def max_concurrent_tasks() -> int:
    """同时运行的任务数上限。

    Returns:
        并发任务数，范围 [1, MAX_CONCURRENT_TASKS_CEILING]
    """
    env_value = os.environ.get(ENV_MAX_CONCURRENT_TASKS)
    if not env_value:
        return DEFAULT_MAX_CONCURRENT_TASKS

    try:
        value = int(env_value)
    except ValueError:
        logger.warning("%s=%r 不是整数，忽略", ENV_MAX_CONCURRENT_TASKS, env_value)
        return DEFAULT_MAX_CONCURRENT_TASKS

    return max(1, min(value, MAX_CONCURRENT_TASKS_CEILING))


def queue_root(project_root: Path | None = None) -> Path:
    """队列数据目录。

    Args:
        project_root: 项目根目录，仅在环境变量未设置时使用

    Returns:
        队列根目录，调用方负责创建
    """
    env_value = os.environ.get(ENV_QUEUE_ROOT)
    if env_value:
        return Path(env_value)

    root = project_root or Path(__file__).resolve().parents[3]
    return root / "data" / "queue"
