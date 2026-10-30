import re
from dataclasses import dataclass

from sgfmill import boards, sgf, sgf_grammar

from .coordinates import from_row_col, from_sgf, setup_points, to_gtp, to_row_col
from .errors import AppError, invalid, unsupported
from .models import AnalysisResult, Player, Point, PositionRequest

ROOT_ONLY = {'AB', 'AW', 'AE', 'PL', 'SZ', 'RU', 'KM', 'HA', 'GM', 'FF', 'CA'}
RULE_MAP = {'chinese': 'chinese', 'japanese': 'japanese'}


def board_key(board: boards.Board) -> tuple:
    return tuple(board.get(row, col) for row in range(board.side) for col in range(board.side))


def play(board: boards.Board, point: Point | None, player: Player, previous: tuple | None) -> tuple:
    before = board_key(board)
    if point is None:
        return before
    if point.x >= board.side or point.y >= board.side:
        raise ValueError('坐标超出棋盘')
    row, col = to_row_col(point, board.side)
    color = 'b' if player == 'black' else 'w'
    if board.get(row, col) is not None:
        raise ValueError('交叉点已有棋子')
    board.play(row, col, color)
    if board.get(row, col) != color:
        raise ValueError('不允许自杀落子')
    if board_key(board) == previous:
        raise ValueError('不允许立即回提劫')
    return before


@dataclass
class Position:
    size: int
    initial_player: Player
    to_play: Player
    initial_stones: list[list[str]]
    moves: list[list[str]]
    board: boards.Board
    previous: tuple | None

    def validate_analysis(self, analysis: AnalysisResult, move_index: int):
        if analysis.moveIndex != move_index or analysis.toPlay != self.to_play:
            raise ValueError('分析手数或行棋方不一致')
        seen = set()
        for candidate in analysis.candidates:
            point_key = to_gtp(candidate.point, self.size)
            if point_key in seen:
                raise ValueError('候选点重复')
            seen.add(point_key)
            play(self.board.copy(), candidate.point, self.to_play, self.previous)
            variation = candidate.principalVariation
            if variation and variation[0] != candidate.point:
                raise ValueError('主要变化首手与候选点不一致')
            board = self.board.copy()
            previous = self.previous
            player = self.to_play
            for point in variation:
                previous = play(board, point, player, previous)
                player = 'white' if player == 'black' else 'black'

    def stones_for_explanation(self) -> dict[str, list[str]]:
        return {
            color: [
                to_gtp(from_row_col(row, col, self.size), self.size)
                for row in range(self.size - 1, -1, -1)
                for col in range(self.size)
                if self.board.get(row, col) == sign
            ]
            for color, sign in [('black', 'b'), ('white', 'w')]
        }


def single(node, name: str) -> str | None:
    if not node.has_property(name):
        return None
    values = node.get_raw_list(name)
    if len(values) != 1:
        raise ValueError(f'属性 {name} 必须只有一个值')
    # 仅处理 SGF 规定的转义，不推断其他字段或规则别名。
    return sgf_grammar.text_value(values[0]).decode('utf-8')


def parse_position(request: PositionRequest) -> Position:
    try:
        return _parse_position(request)
    except AppError:
        raise
    except (ValueError, KeyError, IndexError, UnicodeError, RecursionError) as error:
        # 不把解析库异常的原始输入传播到日志或响应。
        if isinstance(error, RecursionError):
            raise unsupported('棋谱分支嵌套过深，无法解析') from None
        raise invalid('棋谱语法、属性或着手不合法，请检查原始 SGF') from None


def _parse_position(request: PositionRequest) -> Position:
    text = request.sgfText.removeprefix('\ufeff')
    raw = text.encode('utf-8')
    if len(raw) > 2 * 1024 * 1024:
        raise invalid('棋谱超过 2 MB')
    if not re.match(rb'\s*\(\s*;', raw):
        raise invalid('SGF 必须以游戏树开始，不能包含前导杂项')
    tokens, end = sgf_grammar.tokenise(raw)
    if raw[end:].strip():
        if raw[end:].lstrip().startswith(b'('):
            raise unsupported('一个文件包含多盘棋，请拆分文件')
        raise invalid('SGF 含损坏语法或多余尾部内容')
    properties = set()
    for kind, value in tokens:
        if kind == 'D':
            properties = set()
        elif kind == 'I':
            if value in properties:
                raise invalid('SGF 同一节点包含重复属性')
            properties.add(value)
    coarse = sgf_grammar.parse_sgf_game(raw)
    raw_root = coarse.sequence[0]
    if raw_root.get('SZ') not in ([b'9'], [b'13'], [b'19']):
        raise unsupported('棋谱必须明确指定 SZ[9]、SZ[13] 或 SZ[19]')
    if 'CA' in raw_root and (len(raw_root['CA']) != 1 or raw_root['CA'][0].lower() not in (b'utf8', b'utf-8')):
        raise unsupported('仅支持 UTF-8 编码棋谱，请另存为 UTF-8')
    game = sgf.Sgf_game.from_coarse_game_tree(coarse, override_encoding='utf-8')
    root = game.get_root()
    size = game.get_size()
    if single(root, 'GM') not in (None, '1'):
        raise unsupported('仅支持围棋 SGF（GM[1]）')
    if single(root, 'FF') not in (None, '1', '2', '3', '4'):
        raise unsupported('不支持此 SGF 格式版本')
    rule_text = single(root, 'RU')
    mapped_rule = RULE_MAP.get(rule_text.strip().lower()) if rule_text is not None else None
    if mapped_rule is not None and mapped_rule != request.rules:
        raise invalid('请求规则与棋谱已明确的规则不一致')
    komi_text = single(root, 'KM')
    if komi_text is not None:
        if not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)', komi_text):
            raise invalid('KM 必须为有效贴目')
        komi = float(komi_text)
        if not -50 <= komi <= 50 or not (komi * 2).is_integer() or komi != request.komi:
            raise invalid('请求贴目与棋谱不一致，或不在支持范围内')
    handicap_text = single(root, 'HA')
    if handicap_text is not None and not re.fullmatch(r'\d+', handicap_text):
        raise invalid('让子数 HA 必须是非负整数')
    handicap = int(handicap_text) if handicap_text is not None else 0
    if handicap == 1 or handicap > size * size:
        raise invalid('HA 让子数不合法')
    player_text = single(root, 'PL')
    if player_text not in (None, 'B', 'W'):
        raise invalid('根节点 PL 必须为 B 或 W')
    initial_player: Player = 'white' if player_text == 'W' or (player_text is None and handicap >= 2) else 'black'
    setup = {'AB': set(), 'AW': set(), 'AE': set()}
    occupied = set()
    for name in setup:
        if not root.has_property(name):
            continue
        for value in root.get_raw_list(name):
            for point in setup_points(sgf_grammar.text_value(value).decode('ascii'), size):
                pair = to_row_col(point, size)
                if pair in occupied:
                    raise invalid('初始摆子存在重复或重叠')
                occupied.add(pair)
                setup[name].add(pair)
    if handicap >= 2 and len(setup['AB']) != handicap:
        raise invalid('HA 与 AB 数量不一致，不能推测让子位置')
    board = boards.Board(size)
    if not board.apply_setup(setup['AB'], setup['AW'], setup['AE']):
        raise invalid('初始摆子存在无气棋块')
    initial_stones = [
        [color, to_gtp(from_row_col(row, col, size), size)]
        for name, color in [('AB', 'B'), ('AW', 'W')]
        for row, col in sorted(setup[name])
    ]
    moves = []
    previous = None
    to_play = initial_player
    selected = Position(size, initial_player, to_play, initial_stones, [], board.copy(), None) if request.moveIndex == 0 else None
    for node in game.get_main_sequence():
        if node is not root:
            forbidden = ROOT_ONLY.intersection(node.properties())
            if forbidden:
                raise unsupported(f'第 {len(moves)} 手后出现中途属性 {sorted(forbidden)[0]}，MVP 不支持')
        if node.has_property('KO'):
            raise unsupported('不支持 KO 强制非法着手属性')
        if node.has_property('B') and node.has_property('W'):
            raise invalid('同一节点不能包含黑白两手')
        color = 'B' if node.has_property('B') else 'W' if node.has_property('W') else None
        if color is None:
            continue
        if node.has_setup_stones():
            raise invalid('同一节点不能混合初始摆子与着手')
        actual = 'black' if color == 'B' else 'white'
        if actual != to_play:
            raise invalid(f'第 {len(moves) + 1} 手行棋方与当前局面不一致')
        try:
            point = from_sgf(single(node, color), size, allow_pass=True)
            previous = play(board, point, actual, previous)
        except ValueError as error:
            raise invalid(f'第 {len(moves) + 1} 手不合法：{error}') from None
        moves.append([color, to_gtp(point, size)])
        to_play = 'white' if actual == 'black' else 'black'
        if len(moves) == request.moveIndex:
            selected = Position(size, initial_player, to_play, initial_stones, list(moves), board.copy(), previous)
    if selected is None:
        raise invalid('分析手数超出棋谱主线范围')
    return selected
