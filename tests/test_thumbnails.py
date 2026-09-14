"""缩略图生成与缓存的测试。

缓存行为必须可断言而非靠观察耗时推断：mtime 参与缓存键这件事，只有
「改了 mtime 会重新生成」被测到才算成立。
"""

import pytest
from PIL import Image

from qsearch.webui import thumbnails


@pytest.fixture(autouse=True)
def _clear_cache():
    """每个测试前后清空缓存，避免测试间互相污染。"""
    thumbnails.clear_cache()
    yield
    thumbnails.clear_cache()


def _make_image(path, size=(760, 1040), color=(200, 190, 180)):
    """写一张真实可解码的 JPEG。"""
    Image.new("RGB", size, color).save(path, "JPEG", quality=90)
    return path


class TestThumbnailGeneration:
    """生成行为。"""

    def test_returns_jpeg_bytes(self, tmp_path):
        src = _make_image(tmp_path / "q.jpg")

        data = thumbnails.get_thumbnail(src)

        assert isinstance(data, bytes)
        assert data[:2] == b"\xff\xd8", "应为 JPEG（SOI 标记）"

    def test_long_edge_is_respected(self, tmp_path):
        """长边缩到指定值，短边按比例。"""
        src = _make_image(tmp_path / "q.jpg", size=(760, 1040))

        data = thumbnails.get_thumbnail(src, long_edge=400)

        from io import BytesIO
        with Image.open(BytesIO(data)) as im:
            assert max(im.size) == 400
            # 760x1040 缩到长边 400 -> 宽约 292
            assert im.size[0] == pytest.approx(292, abs=2)

    def test_thumbnail_is_much_smaller_than_source(self, tmp_path):
        """缩略图载荷显著小于原图 —— 这是网格模式成立的前提。"""
        src = _make_image(tmp_path / "q.jpg")
        source_size = src.stat().st_size

        data = thumbnails.get_thumbnail(src)

        assert len(data) < source_size

    def test_default_long_edge_matches_measured_value(self):
        """默认长边为 3.3 实测确定的 400 —— 覆盖 4–6 列全程无放大。"""
        assert thumbnails.DEFAULT_LONG_EDGE == 400

    def test_query_long_edge_exceeds_candidate(self):
        """查询图是比对的锚，其尺寸应大于网格中的候选图。"""
        assert thumbnails.QUERY_LONG_EDGE > thumbnails.DEFAULT_LONG_EDGE


class TestCaching:
    """缓存命中与失效。"""

    def test_same_path_and_mtime_hits_cache(self, tmp_path):
        src = _make_image(tmp_path / "q.jpg")

        first = thumbnails.get_thumbnail(src)
        info_after_first = thumbnails.cache_info()
        second = thumbnails.get_thumbnail(src)
        info_after_second = thumbnails.cache_info()

        assert first == second
        assert info_after_first.misses == 1
        assert info_after_first.hits == 0
        assert info_after_second.hits == 1, "第二次应命中缓存"
        assert info_after_second.misses == 1, "第二次不应再次生成"

    def test_changed_mtime_regenerates(self, tmp_path):
        """mtime 变化后重新生成 —— 图像被替换时不需手动清缓存。"""
        src = tmp_path / "q.jpg"
        _make_image(src, color=(200, 190, 180))

        thumbnails.get_thumbnail(src)
        assert thumbnails.cache_info().misses == 1

        # 用不同内容覆盖，并推进 mtime
        import os
        import time
        _make_image(src, color=(20, 40, 60))
        future = time.time() + 10
        os.utime(src, (future, future))

        thumbnails.get_thumbnail(src)

        info = thumbnails.cache_info()
        assert info.misses == 2, "mtime 变化应触发重新生成"
        assert info.hits == 0

    def test_different_long_edge_is_a_separate_entry(self, tmp_path):
        """长边是缓存键的一部分 —— 切换网格密度不会取到错误尺寸。"""
        src = _make_image(tmp_path / "q.jpg")

        thumbnails.get_thumbnail(src, long_edge=400)
        thumbnails.get_thumbnail(src, long_edge=240)

        assert thumbnails.cache_info().misses == 2

    def test_distinct_paths_are_separate_entries(self, tmp_path):
        a = _make_image(tmp_path / "a.jpg")
        b = _make_image(tmp_path / "b.jpg")

        thumbnails.get_thumbnail(a)
        thumbnails.get_thumbnail(b)

        assert thumbnails.cache_info().misses == 2

    def test_clear_cache_resets_counters(self, tmp_path):
        src = _make_image(tmp_path / "q.jpg")
        thumbnails.get_thumbnail(src)

        thumbnails.clear_cache()

        info = thumbnails.cache_info()
        assert info.hits == 0
        assert info.misses == 0
        assert info.currsize == 0

    def test_cache_is_bounded(self):
        """缓存有上限 —— 长时间标注不应无界增长。"""
        assert thumbnails.cache_info().maxsize is not None
        assert thumbnails.cache_info().maxsize > 0


class TestDegradation:
    """不可读图像的降级。

    某张候选图坏掉不应让整页失败，但标注员需要知道那一格为什么是空的。
    """

    def test_missing_file_raises_thumbnail_error(self, tmp_path):
        with pytest.raises(thumbnails.ThumbnailError) as exc:
            thumbnails.get_thumbnail(tmp_path / "does-not-exist.jpg")

        assert "不存在" in str(exc.value)

    def test_non_image_file_raises_thumbnail_error(self, tmp_path):
        bad = tmp_path / "not-an-image.jpg"
        bad.write_text("this is not image data", encoding="utf-8")

        with pytest.raises(thumbnails.ThumbnailError):
            thumbnails.get_thumbnail(bad)

    def test_truncated_image_raises_thumbnail_error(self, tmp_path):
        """截断的 JPEG —— 比「完全不是图像」更接近真实的损坏形态。"""
        src = _make_image(tmp_path / "q.jpg")
        data = src.read_bytes()
        src.write_bytes(data[: len(data) // 3])

        with pytest.raises(thumbnails.ThumbnailError):
            thumbnails.get_thumbnail(src)

    def test_error_carries_displayable_reason(self, tmp_path):
        """错误信息可直接展示给标注员，不是裸的堆栈。"""
        with pytest.raises(thumbnails.ThumbnailError) as exc:
            thumbnails.get_thumbnail(tmp_path / "nope.jpg")

        msg = str(exc.value)
        assert msg and "Traceback" not in msg

    def test_one_bad_image_does_not_poison_others(self, tmp_path):
        """一张坏图不影响其余图像的生成。"""
        good = _make_image(tmp_path / "good.jpg")
        bad = tmp_path / "bad.jpg"
        bad.write_text("garbage", encoding="utf-8")

        with pytest.raises(thumbnails.ThumbnailError):
            thumbnails.get_thumbnail(bad)

        assert thumbnails.get_thumbnail(good)[:2] == b"\xff\xd8"
