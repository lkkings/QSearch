"""网格焦点的二维导航。

标注工作台由「顺序单候选」改为「候选网格」后，方向键的语义随之变更：
不再是沿线性序列前进/后退，而是在二维网格内移动。这是一处 BREAKING 变更 ——
原「上/左=上一候选、下/右=下一候选」不再成立。

这里只做纯粹的索引运算，不涉及 Streamlit 也不涉及 DOM。抽成独立模块的理由
是它的边界条件多（四角、单行、单列、末行不满），而这些条件靠界面点击去验
成本高、覆盖不全。

末行不满是最容易出错的一处：20 个候选按 6 列排布时，末行只有 2 个，
从第 2 行第 2 列向下移动会落在不存在的格子上。
"""

from __future__ import annotations

# 方向键到 (行偏移, 列偏移) 的映射。
DIRECTIONS = {
    "left": (0, -1),
    "right": (0, 1),
    "up": (-1, 0),
    "down": (1, 0),
}


def position(index: int, cols: int) -> tuple[int, int]:
    """索引转 (行, 列)。

    Args:
        index: 从 0 开始的线性索引
        cols: 每行列数

    Returns:
        (行, 列)，均从 0 开始

    Raises:
        ValueError: ``cols`` 小于 1
    """
    if cols < 1:
        raise ValueError(f"列数必须大于 0，收到 {cols}")
    return divmod(index, cols)


def move(index: int, direction: str, total: int, cols: int) -> int:
    """在网格内移动焦点。

    边界处停住 —— 不折行、不环绕、不跳到其他查询。折行会让方向键的空间
    含义失效（按「右」跳到下一行的最左端不符合视觉预期），环绕则会让标注员
    失去「已经到边了」这个反馈。

    Args:
        index: 当前焦点索引
        direction: ``left`` / ``right`` / ``up`` / ``down``
        total: 候选总数
        cols: 每行列数

    Returns:
        新的焦点索引。移动会越界时返回原索引。

    Raises:
        ValueError: ``direction`` 不是四个方向之一，或 ``cols`` 小于 1
    """
    if direction not in DIRECTIONS:
        raise ValueError(
            f"未知方向 {direction!r}，应为 {sorted(DIRECTIONS)} 之一"
        )
    if cols < 1:
        raise ValueError(f"列数必须大于 0，收到 {cols}")
    if total <= 0:
        return index

    index = clamp(index, total)
    row, col = position(index, cols)
    d_row, d_col = DIRECTIONS[direction]

    new_row = row + d_row
    new_col = col + d_col

    # 越出左右边界：停住，不折行
    if new_col < 0 or new_col >= cols:
        return index

    # 越出上边界：停住
    if new_row < 0:
        return index

    new_index = new_row * cols + new_col

    # 越出末尾。两种情形都落在这里：向下超出最后一行，以及向右超出末行的
    # 最后一个元素（末行不满时）。
    if new_index >= total:
        return index

    return new_index


def clamp(index: int, total: int) -> int:
    """把索引夹到合法范围内。

    候选数会随查询切换而变化（不同查询的 top_n 可能不同），焦点索引需要
    在换题后被夹回合法范围，否则会指向不存在的卡片。

    Args:
        index: 待夹取的索引
        total: 候选总数

    Returns:
        ``0`` 到 ``total - 1`` 之间的索引；``total`` 为 0 时返回 0
    """
    if total <= 0:
        return 0
    return max(0, min(index, total - 1))


def nav_map(total: int, cols: int) -> list[dict[str, int]]:
    """预计算每个索引在四个方向上的目标索引。

    键盘桥接的 JS 侧需要这套数学，但在 JS 里重写一遍意味着两份实现会漂移，
    而其中只有一份被测到。改为在此预计算成查表，JS 只做查找。

    Args:
        total: 候选总数
        cols: 每行列数

    Returns:
        长度为 ``total`` 的列表，每项形如
        ``{"left": i, "right": i, "up": i, "down": i}``。
        越界方向的目标为原索引本身（即「停住」）。

    Raises:
        ValueError: ``cols`` 小于 1
    """
    if cols < 1:
        raise ValueError(f"列数必须大于 0，收到 {cols}")
    return [
        {d: move(i, d, total, cols) for d in DIRECTIONS}
        for i in range(max(0, total))
    ]


def row_count(total: int, cols: int) -> int:
    """网格的行数。

    Args:
        total: 候选总数
        cols: 每行列数

    Returns:
        行数；``total`` 为 0 时返回 0

    Raises:
        ValueError: ``cols`` 小于 1
    """
    if cols < 1:
        raise ValueError(f"列数必须大于 0，收到 {cols}")
    if total <= 0:
        return 0
    return -(-total // cols)  # 向上取整
