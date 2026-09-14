"""网格导航的测试。

方向键数学的边界条件多（四角、单行、单列、末行不满），而这些在界面上
靠点击验不全，故在此单元测试覆盖。
"""

import pytest

from qsearch.webui import grid_nav


class TestPosition:
    """线性索引与二维坐标的转换。"""

    def test_first_item_is_row_0_col_0(self):
        assert grid_nav.position(0, cols=5) == (0, 0)

    def test_single_row_increments_col_only(self):
        assert grid_nav.position(2, cols=5) == (0, 2)
        assert grid_nav.position(4, cols=5) == (0, 4)

    def test_wraps_to_next_row(self):
        assert grid_nav.position(5, cols=5) == (1, 0)
        assert grid_nav.position(7, cols=5) == (1, 2)

    def test_multiple_rows(self):
        assert grid_nav.position(12, cols=5) == (2, 2)

    def test_different_column_counts(self):
        assert grid_nav.position(9, cols=4) == (2, 1)
        assert grid_nav.position(9, cols=6) == (1, 3)

    def test_rejects_zero_cols(self):
        with pytest.raises(ValueError, match="列数必须大于 0"):
            grid_nav.position(0, cols=0)


class TestMove:
    """四个方向的焦点移动。"""

    def test_right_increments_col(self):
        assert grid_nav.move(0, "right", total=10, cols=5) == 1

    def test_left_decrements_col(self):
        assert grid_nav.move(3, "left", total=10, cols=5) == 2

    def test_down_moves_to_next_row(self):
        assert grid_nav.move(2, "down", total=10, cols=5) == 7

    def test_up_moves_to_previous_row(self):
        assert grid_nav.move(7, "up", total=10, cols=5) == 2

    def test_right_at_row_end_stops(self):
        """到行末后不折到下一行的开头 —— 折行会让空间方向失效。"""
        assert grid_nav.move(4, "right", total=10, cols=5) == 4

    def test_left_at_row_start_stops(self):
        """到行首后不折到上一行的末尾。"""
        assert grid_nav.move(5, "left", total=10, cols=5) == 5

    def test_up_at_top_row_stops(self):
        assert grid_nav.move(2, "up", total=10, cols=5) == 2

    def test_down_at_bottom_row_stops(self):
        """到底部后不环绕。"""
        assert grid_nav.move(7, "down", total=10, cols=5) == 7

    def test_down_from_second_row_to_ragged_last_row_stops(self):
        """20 个候选按 6 列排布：末行只有 2 个。从第 2 行向下会落在
        不存在的格子上 —— 停住而非跳到末行末尾。
        """
        # 第 2 行的第 4 格 = 索引 9，向下应落在 15，但总数 14，故停住
        assert grid_nav.move(9, "down", total=14, cols=6) == 9

    def test_right_into_ragged_last_row_stops(self):
        """同一行内向右超出范围也停住。"""
        # 末行只有 2 个：索引 12 和 13，从 13 向右停住
        assert grid_nav.move(13, "right", total=14, cols=6) == 13

    def test_single_column_grid_vertical_only(self):
        """单列时左/右无效，只有上/下。"""
        assert grid_nav.move(2, "up", total=5, cols=1) == 1
        assert grid_nav.move(2, "down", total=5, cols=1) == 3
        assert grid_nav.move(2, "left", total=5, cols=1) == 2
        assert grid_nav.move(2, "right", total=5, cols=1) == 2

    def test_single_row_horizontal_only(self):
        """单行时上/下无效，只有左/右。"""
        assert grid_nav.move(2, "left", total=5, cols=10) == 1
        assert grid_nav.move(2, "right", total=5, cols=10) == 3
        assert grid_nav.move(2, "up", total=5, cols=10) == 2
        assert grid_nav.move(2, "down", total=5, cols=10) == 2

    def test_zero_candidates_returns_unchanged(self):
        assert grid_nav.move(0, "right", total=0, cols=5) == 0

    def test_negative_index_is_clamped_before_move(self):
        """会话状态可能含非法值 —— 先夹回合法再移动。"""
        assert grid_nav.move(-3, "right", total=10, cols=5) == 1

    def test_out_of_bound_index_is_clamped_before_move(self):
        assert grid_nav.move(999, "down", total=10, cols=5) == 9

    def test_rejects_unknown_direction(self):
        with pytest.raises(ValueError, match="未知方向"):
            grid_nav.move(0, "forward", total=10, cols=5)

    def test_rejects_zero_cols(self):
        with pytest.raises(ValueError, match="列数必须大于 0"):
            grid_nav.move(0, "right", total=10, cols=0)


class TestClamp:
    """焦点索引的合法化。"""

    def test_negative_becomes_zero(self):
        assert grid_nav.clamp(-5, total=10) == 0

    def test_exceeds_upper_becomes_last(self):
        assert grid_nav.clamp(100, total=10) == 9

    def test_within_range_stays_unchanged(self):
        assert grid_nav.clamp(5, total=10) == 5

    def test_zero_total_returns_zero(self):
        assert grid_nav.clamp(5, total=0) == 0


class TestNavMap:
    """预计算的导航表。

    JS 侧靠这张表做查找，而不在 JS 里重写一遍网格数学 —— 两份实现会漂移，
    且其中只有一份被测到。故此表必须与 move() 逐项一致。
    """

    def test_length_matches_total(self):
        assert len(grid_nav.nav_map(14, cols=6)) == 14

    def test_every_entry_has_four_directions(self):
        for entry in grid_nav.nav_map(10, cols=5):
            assert set(entry) == {"left", "right", "up", "down"}

    def test_agrees_with_move_for_every_index_and_direction(self):
        """逐项与 move() 比对 —— 这是防漂移的实际保障。"""
        for total, cols in [(20, 5), (14, 6), (7, 4), (1, 5), (5, 1)]:
            table = grid_nav.nav_map(total, cols)
            for i in range(total):
                for d in grid_nav.DIRECTIONS:
                    assert table[i][d] == grid_nav.move(i, d, total, cols), (
                        f"total={total} cols={cols} i={i} dir={d} 不一致"
                    )

    def test_boundaries_point_at_self(self):
        """越界方向指向自身，表达「停住」。"""
        table = grid_nav.nav_map(10, cols=5)
        assert table[0]["left"] == 0
        assert table[0]["up"] == 0
        assert table[4]["right"] == 4
        assert table[9]["down"] == 9

    def test_zero_total_yields_empty_table(self):
        assert grid_nav.nav_map(0, cols=5) == []

    def test_rejects_zero_cols(self):
        with pytest.raises(ValueError, match="列数必须大于 0"):
            grid_nav.nav_map(10, cols=0)


class TestRowCount:
    """网格的行数。"""

    def test_exact_multiple(self):
        assert grid_nav.row_count(15, cols=5) == 3

    def test_ragged_last_row_rounds_up(self):
        assert grid_nav.row_count(14, cols=6) == 3

    def test_less_than_one_row(self):
        assert grid_nav.row_count(4, cols=6) == 1

    def test_zero_candidates(self):
        assert grid_nav.row_count(0, cols=5) == 0

    def test_rejects_zero_cols(self):
        with pytest.raises(ValueError, match="列数必须大于 0"):
            grid_nav.row_count(10, cols=0)
