"""缩略图生成与缓存。

标注网格最多同屏承载 20 张候选图。任务 3.3 的实测：渲染 20 张原图使服务端
耗时 2484ms、载荷 1527KB；换成缩略图后热缓存下 50ms、208KB —— 49 倍差距。
缩略图在此不是优化，是网格模式能否成立的前提。

缓存键含 mtime：图像被替换后自动重新生成，不需要手动清缓存。用
``functools.lru_cache`` 而非自建字典，一是有上限不会无界增长，二是
``cache_info()`` 让命中行为可被测试断言，而非只能靠观察耗时推断。
"""

from __future__ import annotations

from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError

# 长边取值由任务 3.3 实测确定。
#
# 240/320/400 的生成耗时几乎相同（699–790ms），成本由源图解码支配而非缩放，
# 故按画质选而非按速度选。题目图偏高（约 760×1040），长边 400 缩出实宽约
# 292px，覆盖 4–6 列的渲染宽度（295/233/192）全程无放大。长边 320 在 5 列时
# 恰好 1:1，但标注员切到 4 列即变放大 —— 文字密集的题目图发虚会直接损害
# 「靠肉眼判断相似度」这件事本身。代价仅 94KB。
DEFAULT_LONG_EDGE = 400

# 查询图不参与网格，可给更大尺寸 —— 它是比对的锚，清晰度优先。
QUERY_LONG_EDGE = 900

_CACHE_MAXSIZE = 512

_JPEG_QUALITY = 82


class ThumbnailError(RuntimeError):
    """图像无法读取或解码时抛出。

    携带可展示给标注员的原因说明 —— 某张候选图坏掉不应让整页失败，
    但标注员需要知道那一格为什么是空的。
    """


@lru_cache(maxsize=_CACHE_MAXSIZE)
def _render(path_str: str, mtime: float, long_edge: int) -> bytes:
    """生成缩略图字节。

    参数中的 ``mtime`` 不被函数体使用，它只作为缓存键的一部分存在：
    图像内容变化时 mtime 随之变化，旧条目自然失效。

    Args:
        path_str: 图像路径
        mtime: 文件修改时间，仅用于缓存键
        long_edge: 长边像素数

    Returns:
        JPEG 字节

    Raises:
        ThumbnailError: 文件不存在、非图像或解码失败
    """
    try:
        with Image.open(path_str) as im:
            im = im.convert("RGB")
            im.thumbnail((long_edge, long_edge), Image.LANCZOS)
            buf = BytesIO()
            im.save(buf, "JPEG", quality=_JPEG_QUALITY, optimize=True)
            return buf.getvalue()
    except FileNotFoundError as exc:
        raise ThumbnailError("文件不存在") from exc
    except UnidentifiedImageError as exc:
        raise ThumbnailError("无法识别的图像格式") from exc
    except OSError as exc:
        raise ThumbnailError(f"图像损坏或读取失败：{exc}") from exc


def get_thumbnail(path: str | Path, long_edge: int = DEFAULT_LONG_EDGE) -> bytes:
    """取得某张图像的缩略图。

    Args:
        path: 图像路径
        long_edge: 长边像素数，默认 ``DEFAULT_LONG_EDGE``

    Returns:
        JPEG 字节

    Raises:
        ThumbnailError: 文件不存在或无法解码
    """
    p = Path(path)
    try:
        mtime = p.stat().st_mtime
    except FileNotFoundError as exc:
        raise ThumbnailError("文件不存在") from exc
    except OSError as exc:
        raise ThumbnailError(f"无法访问文件：{exc}") from exc

    return _render(str(p), mtime, long_edge)


def cache_info():
    """返回底层缓存的统计。

    Returns:
        ``functools.CacheInfo``，含 hits / misses / maxsize / currsize
    """
    return _render.cache_info()


def clear_cache() -> None:
    """清空缓存。供测试与「刷新数据」使用。"""
    _render.cache_clear()
