from dataclasses import replace
from time import perf_counter

from starlette.concurrency import run_in_threadpool

from .deepseek import explain
from .errors import AppError
from .katago import analyze
from .models import ExplainRequest, PositionRequest
from .sgf import parse_position


def result(state, started, message):
    return {
        'state': state,
        'elapsedMs': round((perf_counter() - started) * 1000),
        'message': message
    }


async def test_settings(client, settings):
    request = PositionRequest(
        sgfText='(;GM[1]FF[4]CA[UTF-8]SZ[19]RU[chinese]KM[7.5];B[pd];W[dd])',
        moveIndex=2, rules='chinese', komi=7.5
    )
    started = perf_counter()
    try:
        position = await run_in_threadpool(parse_position, request)
        analysis = await analyze(client, replace(settings, visits=32), request, position)
        katago = result('passed', started, '围棋引擎可用')
    except Exception as error:
        message = '引擎或模型无法完成分析，请检查高级设置中的路径；较大的模型可切换轻量版后重试。'
        if isinstance(error, AppError) and error.code == 'KATAGO_TIMEOUT':
            message = '引擎测试超过 120 秒，可切换轻量版后重试。'
        elif isinstance(error, AppError) and error.code == 'KATAGO_INVALID_RESULT':
            message = '引擎返回的分析结果不符合要求，请检查引擎版本、模型和 BLACK 视角设置。'
        return {
            'katago': result('failed', started, message),
            'ai': {'state': 'skipped', 'elapsedMs': 0, 'message': '未执行，请先解决引擎问题'}
        }
    started = perf_counter()
    try:
        await explain(
            client, settings,
            ExplainRequest(**request.model_dump(), analysis=analysis), position
        )
        ai = result('passed', started, 'AI 解释可用')
    except Exception as error:
        message = 'AI 解释测试失败，请检查接口配置或稍后重试；围棋引擎仍可使用。'
        if isinstance(error, AppError):
            if error.code == 'AI_NOT_CONFIGURED':
                message = '尚未配置 AI 密钥，请填写后重新保存并测试；围棋引擎仍可使用。'
            elif error.code == 'AI_TIMEOUT':
                message = 'AI 解释超过 60 秒，请稍后重试；围棋引擎仍可使用。'
            elif error.message == 'DeepSeek 鉴权失败，请检查后端配置；分析结果已保留':
                message = 'AI 密钥验证失败，请检查密钥和接口地址；围棋引擎仍可使用。'
            elif error.message == 'DeepSeek 请求受限，请稍后单独重试解释':
                message = 'AI 请求受限，请稍后重试；围棋引擎仍可使用。'
        ai = result('failed', started, message)
    return {'katago': katago, 'ai': ai}
