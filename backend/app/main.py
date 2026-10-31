import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException

from .config import Settings
from .deepseek import explain, explain_move
from .errors import AppError, invalid
from .engine_install import EmptyRequest, EngineInstaller, InstallRequest
from .game_records import GameRecords, RecordsRequest, RecordsResponse, SgfDownloadRequest, SgfDownloadResponse, download_sgf
from .katago import analyze
from .models import AnalysisResult, ExplainMoveRequest, ExplainRequest, ExplanationResult, MoveExplanationResult, PositionRequest
from .sgf import parse_position
from .settings_test import test_settings

from .preferences import SavePreferences, apply_preferences, load_preferences, public_preferences, save_preferences

installer = EngineInstaller()
game_records = GameRecords()
settings = installer.label_settings(load_preferences(Settings()))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 创建连接池不发请求，不启动或管理 KataGo 进程。
    async with httpx.AsyncClient(trust_env=False, follow_redirects=False) as client:
        app.state.client = client
        app.state.operation_lock = asyncio.Lock()
        try:
            yield
        finally:
            await installer.close()


app = FastAPI(title='GoGo 本地分析服务', version='0.1.0', lifespan=lifespan, debug=False)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_origins),
    allow_credentials=False,
    allow_methods=['POST'],
    allow_headers=['Content-Type']
)


@app.middleware('http')
async def local_origin_only(request: Request, call_next):
    origin = request.headers.get('origin')
    if origin and origin not in settings.allowed_origins:
        return JSONResponse(status_code=400, content={'code': 'INVALID_INPUT', 'message': '页面来源未获允许，请使用固定本地地址'})
    if request.method == 'POST' and request.headers.get('content-type', '').split(';')[0].strip() != 'application/json':
        return JSONResponse(status_code=400, content={'code': 'INVALID_INPUT', 'message': '请求必须采用 JSON 格式'})
    try:
        return await call_next(request)
    except Exception:
        # 不记录异常对象；其中可能包含上游请求头或响应内容。
        return JSONResponse(status_code=500, content={'code': 'INTERNAL_ERROR', 'message': '本地服务异常，请稍后重试'})


@app.exception_handler(AppError)
async def app_error_handler(_request: Request, error: AppError):
    return JSONResponse(status_code=error.status, content={'code': error.code, 'message': error.message})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_request: Request, _error: RequestValidationError):
    return JSONResponse(status_code=400, content={'code': 'INVALID_INPUT', 'message': '请求字段、手数、贴目或分析结果不符合接口约定'})


@app.exception_handler(HTTPException)
async def http_error_handler(_request: Request, _error: HTTPException):
    if _error.status_code in (404, 405):
        return JSONResponse(status_code=_error.status_code, content={'code': 'INVALID_INPUT', 'message': '接口路径或请求方法不正确'})
    return JSONResponse(status_code=400, content={'code': 'INVALID_INPUT', 'message': '接口路径或请求方法不正确'})


@app.exception_handler(Exception)
async def unexpected_error_handler(_request: Request, _error: Exception):
    return JSONResponse(status_code=500, content={'code': 'INTERNAL_ERROR', 'message': '本地服务异常，请稍后重试'})


@app.post('/api/analyze', response_model=AnalysisResult)
async def analyze_position(payload: PositionRequest, request: Request):
    lock = request.app.state.operation_lock
    if lock.locked():
        raise AppError('KATAGO_UNAVAILABLE', '安装、分析或测试正在进行，请等待完成后重试', 503)
    async with lock:
        position = await run_in_threadpool(parse_position, payload)
        return await analyze(request.app.state.client, settings, payload, position)


@app.post('/api/explain', response_model=ExplanationResult)
async def explain_position(payload: ExplainRequest, request: Request):
    lock = request.app.state.operation_lock
    if lock.locked():
        raise AppError('AI_UNAVAILABLE', '安装、分析或测试正在进行，请等待完成后重试', 502)
    async with lock:
        position = await run_in_threadpool(parse_position, payload)
        try:
            position.validate_analysis(payload.analysis, payload.moveIndex)
        except ValueError:
            raise invalid('分析结果的手数、行棋方或候选变化与棋谱局面不一致') from None
        return await explain(request.app.state.client, settings, payload, position)


@app.post('/api/explain-move', response_model=MoveExplanationResult)
async def explain_played_move(payload: ExplainMoveRequest, request: Request):
    lock = request.app.state.operation_lock
    if lock.locked():
        raise AppError('AI_UNAVAILABLE', '安装、分析或测试正在进行，请等待完成后重试', 502)
    async with lock:
        before_request = PositionRequest(
            sgfText=payload.sgfText, moveIndex=payload.moveIndex - 1,
            rules=payload.rules, komi=payload.komi
        )
        before = await run_in_threadpool(parse_position, before_request)
        after = await run_in_threadpool(parse_position, payload)
        try:
            before.validate_analysis(payload.beforeAnalysis, payload.moveIndex - 1)
            after.validate_analysis(payload.afterAnalysis, payload.moveIndex)
            if (payload.beforeAnalysis.engineLabel != payload.afterAnalysis.engineLabel or
                    payload.beforeAnalysis.visitBudget != payload.afterAnalysis.visitBudget):
                raise ValueError('两侧分析配置不一致')
        except ValueError:
            raise invalid('落子前后分析的手数、行棋方、配置或候选变化与棋谱不一致') from None
        return await explain_move(request.app.state.client, settings, payload, before, after)


@app.post('/api/settings/read')
async def read_settings():
    return public_preferences(settings)


@app.post('/api/records/query', response_model=RecordsResponse)
async def query_game_records(payload: RecordsRequest, request: Request):
    return await game_records.query(request.app.state.client, payload)


@app.post('/api/records/sgf', response_model=SgfDownloadResponse)
async def download_game_record(payload: SgfDownloadRequest, request: Request):
    return await download_sgf(request.app.state.client, payload)


@app.post('/api/settings/save')
async def update_settings(payload: SavePreferences, request: Request):
    global settings
    lock = request.app.state.operation_lock
    if lock.locked():
        raise invalid('安装、分析或测试正在进行，请完成后再保存配置')
    async with lock:
        try:
            updated = installer.label_settings(apply_preferences(settings, payload))
        except ValueError as error:
            raise invalid(str(error)) from None
        await run_in_threadpool(save_preferences, updated)
        settings = updated
        return public_preferences(settings)


async def configure_installed_engine(binary, weights):
    global settings
    updated = installer.label_settings(replace(settings, katago_path=binary, katago_model_path=weights))
    await run_in_threadpool(save_preferences, updated)
    settings = updated


@app.post('/api/engine/status')
async def engine_status(payload: EmptyRequest):
    return installer.status(settings)


@app.post('/api/engine/install')
async def install_engine(payload: InstallRequest, request: Request):
    await installer.start(payload.tier, request.app.state.operation_lock, configure_installed_engine, settings)
    return installer.status(settings)


@app.post('/api/settings/test')
async def check_settings(payload: EmptyRequest, request: Request):
    lock = request.app.state.operation_lock
    if lock.locked():
        raise AppError('ENGINE_BUSY', '安装、分析或测试正在进行，请完成后再测试', 409)
    async with lock:
        return await test_settings(request.app.state.client, settings)
