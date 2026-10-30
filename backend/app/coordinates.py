import re

from .models import Point

COLUMNS = 'ABCDEFGHJKLMNOPQRST'


def to_gtp(point: Point | None, size: int) -> str:
    if point is None:
        return 'pass'
    return f'{COLUMNS[point.x]}{size - point.y}'


def from_gtp(value: str, size: int) -> Point | None:
    if value == 'pass':
        return None
    if not isinstance(value, str) or not re.fullmatch(r'[A-HJ-T][1-9][0-9]?', value):
        raise ValueError('非法 GTP 坐标')
    x = COLUMNS.index(value[0])
    y = size - int(value[1:])
    if not 0 <= x < size or not 0 <= y < size:
        raise ValueError('GTP 坐标超出棋盘')
    return Point(x=x, y=y)


def from_sgf(value: str, size: int, allow_pass: bool = False) -> Point | None:
    if allow_pass and value in ('', 'tt'):
        return None
    if not re.fullmatch(r'[a-s]{2}', value):
        raise ValueError('非法 SGF 坐标')
    point = Point(x=ord(value[0]) - 97, y=ord(value[1]) - 97)
    if point.x >= size or point.y >= size:
        raise ValueError('SGF 坐标超出棋盘')
    return point


def to_row_col(point: Point, size: int) -> tuple[int, int]:
    return size - 1 - point.y, point.x


def from_row_col(row: int, col: int, size: int) -> Point:
    return Point(x=col, y=size - 1 - row)


def setup_points(value: str, size: int) -> list[Point]:
    parts = value.split(':')
    if len(parts) > 2:
        raise ValueError('非法摆子范围')
    start = from_sgf(parts[0], size)
    if len(parts) == 1:
        return [start]
    end = from_sgf(parts[1], size)
    if start.x > end.x or start.y > end.y:
        raise ValueError('摆子范围顺序错误')
    return [Point(x=x, y=y) for y in range(start.y, end.y + 1) for x in range(start.x, end.x + 1)]
