"""系统资源监控模块。"""

import psutil
from typing import Dict, Optional


def get_system_resources() -> Dict[str, any]:
    """获取系统资源使用情况。

    Returns:
        包含 CPU、内存、GPU 使用情况的字典
    """
    resources = {
        'cpu_percent': psutil.cpu_percent(interval=0.1),
        'cpu_count': psutil.cpu_count(),
        'memory_percent': psutil.virtual_memory().percent,
        'memory_used_gb': psutil.virtual_memory().used / (1024**3),
        'memory_total_gb': psutil.virtual_memory().total / (1024**3),
    }

    # 尝试获取 GPU 信息
    gpu_info = get_gpu_info()
    if gpu_info:
        resources['gpu'] = gpu_info

    return resources


def get_gpu_info() -> Optional[Dict[str, any]]:
    """获取 GPU 使用信息（如果可用）。

    Returns:
        GPU 信息字典，如果不可用则返回 None
    """
    try:
        import GPUtil
        gpus = GPUtil.getGPUs()

        if not gpus:
            return None

        # 返回第一个 GPU 的信息（主要 GPU）
        gpu = gpus[0]
        return {
            'name': gpu.name,
            'load_percent': gpu.load * 100,
            'memory_used_mb': gpu.memoryUsed,
            'memory_total_mb': gpu.memoryTotal,
            'memory_percent': (gpu.memoryUsed / gpu.memoryTotal) * 100 if gpu.memoryTotal > 0 else 0,
            'temperature': gpu.temperature,
        }
    except ImportError:
        # GPUtil 未安装
        return None
    except Exception:
        # GPU 不可用或其他错误
        return None


def format_memory_size(size_gb: float) -> str:
    """格式化内存大小显示。

    Args:
        size_gb: 内存大小（GB）

    Returns:
        格式化的字符串
    """
    return f"{size_gb:.1f} GB"


def get_cpu_status_color(percent: float) -> str:
    """根据 CPU 使用率返回状态颜色。

    Args:
        percent: CPU 使用率百分比

    Returns:
        状态颜色（normal/warning/error）
    """
    if percent < 70:
        return "normal"
    elif percent < 90:
        return "warning"
    else:
        return "error"


def get_memory_status_color(percent: float) -> str:
    """根据内存使用率返回状态颜色。

    Args:
        percent: 内存使用率百分比

    Returns:
        状态颜色（normal/warning/error）
    """
    if percent < 80:
        return "normal"
    elif percent < 95:
        return "warning"
    else:
        return "error"
