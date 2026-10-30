import asyncio
import math
import json
import tempfile
from pathlib import Path
from datetime import datetime, timezone

import httpx
from pydantic import ValidationError

from .config import Settings
from .coordinates import from_gtp
from .errors import AppError, invalid_result
from .models import AnalysisResult, Candidate, PositionRequest
from .sgf import Position


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def number(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('缺少有效数值')
    return float(value)


def normalize_result(payload, position: Position, request: PositionRequest, settings: Settings) -> AnalysisResult:
    try:
        if not isinstance(payload, list) or len(payload) != 1:
            raise ValueError('预期恰好一个局面结果')
        result = payload[0]
        if not isinstance(result, dict) or result['isDuringSearch'] is not False:
            raise ValueError('不是最终结果')
        if type(result['turnNumber']) is not int or result['turnNumber'] != request.moveIndex:
            raise ValueError('手数不一致')
        expected_player = 'B' if position.to_play == 'black' else 'W'
        if result['rootInfo']['currentPlayer'] != expected_player:
            raise ValueError('行棋方不一致')
        infos = result['moveInfos']
        if not isinstance(infos, list) or not infos:
            raise ValueError('没有候选点')
        orders = []
        for info in infos:
            order = info['order']
            if type(order) is not int or order < 0:
                raise ValueError('非法推荐序号')
            orders.append(order)
        if len(set(orders)) != len(orders) or min(orders) != 0:
            raise ValueError('推荐序号重复或缺少首选')
        candidates = []
        # 使用引擎声明的 order，不按胜率、目数或访问数重新选点。
        for info in sorted(infos, key=lambda item: item['order'])[:settings.candidate_count]:
            variation = info['pv']
            if not isinstance(variation, list):
                raise ValueError('缺少主要变化数组')
            candidates.append(Candidate(
                point=from_gtp(info['move'], position.size),
                blackWinRate=number(info['winrate']),
                blackScoreLead=number(info['scoreLead']),
                scoreStdev=number(info['scoreStdev']),
                principalVariation=[from_gtp(value, position.size) for value in variation]
            ))
        analysis = AnalysisResult(
            moveIndex=request.moveIndex,
            toPlay=position.to_play,
            candidates=candidates,
            engineLabel=settings.engine_label,
            visitBudget=settings.visits,
            analyzedAt=utc_now()
        )
        position.validate_analysis(analysis, request.moveIndex)
        return analysis
    except (ValueError, TypeError, KeyError, IndexError, ValidationError):
        raise invalid_result() from None


async def analyze(client: httpx.AsyncClient, settings: Settings, request: PositionRequest, position: Position) -> AnalysisResult:
    payload = {
        'initialStones': position.initial_stones,
        'initialPlayer': 'B' if position.initial_player == 'black' else 'W',
        'moves': position.moves,
        'rules': request.rules,
        'komi': request.komi,
        'boardXSize': position.size,
        'boardYSize': position.size,
        'analyzeTurns': [request.moveIndex],
        'maxVisits': settings.visits
    }
    if settings.katago_path:
        return await analyze_local(settings, payload, position, request)
    try:
        async with asyncio.timeout(settings.katago_timeout):
            response = await client.post(settings.katago_url, json=payload, timeout=settings.katago_timeout)
            if response.status_code == 504:
                raise AppError('KATAGO_TIMEOUT', 'KataGo 分析超时，请稍后重试', 504)
            if response.status_code == 422:
                raise invalid_result()
            if response.status_code != 200:
                raise AppError('KATAGO_UNAVAILABLE', 'KataGo 服务暂不可用，请检查本地引擎服务', 503)
            try:
                payload = response.json()
            except ValueError:
                raise invalid_result() from None
            return normalize_result(payload, position, request, settings)
    except (TimeoutError, httpx.TimeoutException):
        raise AppError('KATAGO_TIMEOUT', 'KataGo 分析超过 120 秒，请稍后重试', 504) from None
    except httpx.RequestError:
        raise AppError('KATAGO_UNAVAILABLE', '无法连接 KataGo，请检查本地 8001 端口的引擎服务', 503) from None


async def analyze_local(settings, payload, position, request):
    process = None
    stderr = tempfile.TemporaryFile()
    payload['id'] = 'gogo'
    try:
        async with asyncio.timeout(settings.katago_timeout):
            process = await asyncio.create_subprocess_exec(
                settings.katago_path, 'analysis',
                '-config', str(Path(__file__).with_name('katago-analysis.cfg')),
                '-model', settings.katago_model_path,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=stderr, limit=16 * 1024 * 1024
            )
            process.stdin.write((json.dumps(payload) + '\n').encode())
            await process.stdin.drain()
            while line := await process.stdout.readline():
                result = json.loads(line)
                if result.get('id') != 'gogo':
                    continue
                if 'error' in result:
                    raise invalid_result()
                if result.get('isDuringSearch') is False:
                    return normalize_result([result], position, request, settings)
            code = await process.wait()
            stderr.seek(0, 2)
            stderr.seek(max(0, stderr.tell() - 4000))
            detail = stderr.read().decode('utf-8', errors='replace').strip()
            message = f'KataGo 已退出（退出码 {code}）'
            if detail:
                message += f'：{detail}'
            else:
                message += '，未提供错误日志，请检查程序、权重和引擎配置'
            raise AppError('KATAGO_UNAVAILABLE', message, 503)
    except (TimeoutError, asyncio.TimeoutError):
        raise AppError('KATAGO_TIMEOUT', 'KataGo 分析超过 120 秒，请稍后重试', 504) from None
    except (OSError, ValueError):
        raise AppError('KATAGO_UNAVAILABLE', '无法使用 KataGo，请检查程序及权重路径', 503) from None
    finally:
        if process is not None and process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()
        stderr.close()
