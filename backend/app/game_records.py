from collections import OrderedDict
from dataclasses import dataclass
from time import monotonic
from typing import Annotated, Literal

import httpx
from pydantic import BaseModel, Field, StrictInt, StrictStr, ValidationError, field_validator

from .errors import AppError, invalid
from .models import Contract

Platform = Literal['fox']
RecordResult = Literal['win', 'loss', 'unknown']
ChessId = Annotated[str, Field(strict=True, pattern=r'^[0-9]{1,32}$')]
BASE_URL = 'https://h5.foxwq.com/yehuDiamond/chessbook_local'
ACCOUNT_URL = 'https://newframe.foxwq.com/cgi/QueryUserInfoPanel'
PAGE_SIZE = 10
CACHE_SECONDS = 300
CACHE_LIMIT = 20


class RecordsRequest(Contract):
    platform: Platform
    account: Annotated[str, Field(strict=True, min_length=1, max_length=64)]
    page: Annotated[StrictInt, Field(ge=1)]

    @field_validator('account')
    @classmethod
    def clean_account(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('请输入账号昵称或 ID')
        return value


class SgfDownloadRequest(Contract):
    platform: Platform
    chessId: ChessId


class GameRecord(Contract):
    chessId: ChessId
    playedAt: str
    blackName: str
    whiteName: str
    boardSize: int
    moveCount: int
    result: RecordResult


class RecordsResponse(Contract):
    platform: Platform
    accountId: str
    accountName: str | None
    page: int
    pageSize: Literal[10] = PAGE_SIZE
    total: int
    items: list[GameRecord]


class SgfDownloadResponse(Contract):
    chessId: ChessId
    sgfText: str


class FoxAccount(BaseModel):
    uid: Annotated[str, Field(strict=True, pattern=r'^[0-9]+$')]
    username: Annotated[str, Field(strict=True, min_length=1)]


class FoxRecord(BaseModel):
    chessid: ChessId
    blackuid: Annotated[StrictInt, Field(gt=0)]
    whiteuid: Annotated[StrictInt, Field(gt=0)]
    blacknick: StrictStr
    whitenick: StrictStr
    starttime: StrictStr
    gamestarttime: Annotated[str, Field(strict=True, pattern=r'^[0-9]+$')]
    boardsize: Annotated[StrictInt, Field(gt=0)]
    movenum: Annotated[StrictInt, Field(ge=0)]
    winner: StrictInt


class FoxList(BaseModel):
    chesslist: list[FoxRecord]


@dataclass
class CachedRecords:
    expires_at: float
    account_id: str
    account_name: str | None
    items: list[GameRecord]


def upstream_error():
    return AppError('RECORDS_UNAVAILABLE', '棋谱平台暂时无法查询，请稍后重试', 502)


async def fetch_json(client, url, params):
    try:
        response = await client.get(url, params=params, timeout=20)
        response.raise_for_status()
        data = response.json()
    except httpx.TimeoutException:
        raise AppError('RECORDS_TIMEOUT', '棋谱平台响应超时，请稍后重试', 504) from None
    except (httpx.HTTPError, ValueError):
        raise upstream_error() from None
    if not isinstance(data, dict) or type(data.get('result')) is not int:
        raise upstream_error()
    if data['result'] != 0:
        raise AppError('RECORDS_UNAVAILABLE', '平台未能返回记录，请检查账号是否正确、记录是否公开后重试', 502)
    return data


class GameRecords:
    def __init__(self):
        self.cache: OrderedDict[tuple[str, str], CachedRecords] = OrderedDict()

    async def query(self, client: httpx.AsyncClient, payload: RecordsRequest):
        key = (payload.platform, payload.account)
        for expired in [key for key, value in self.cache.items() if value.expires_at <= monotonic()]:
            del self.cache[expired]
        cached = self.cache.get(key)
        if payload.page == 1 or cached is None:
            cached = await self.load_fox(client, payload.account)
            self.cache[key] = cached
            while len(self.cache) > CACHE_LIMIT:
                self.cache.popitem(last=False)
        self.cache.move_to_end(key)
        total = len(cached.items)
        if payload.page > max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE):
            raise invalid('该页已超出可查询范围，请重新查询第一页')
        start = (payload.page - 1) * PAGE_SIZE
        return RecordsResponse(
            platform=payload.platform,
            accountId=cached.account_id,
            accountName=cached.account_name,
            page=payload.page,
            total=total,
            items=cached.items[start:start + PAGE_SIZE],
        )

    async def load_fox(self, client, account):
        account_name = None
        account_id = account
        try:
            if not account.isascii() or not account.isdecimal():
                data = await fetch_json(client, ACCOUNT_URL, {'srcuid': 0, 'username': account})
                user = FoxAccount.model_validate(data)
                account_id = user.uid
                account_name = user.username
            uid = int(account_id)
            if uid <= 0:
                raise invalid('账号 ID 必须为正整数')
            data = await fetch_json(client, f'{BASE_URL}/YHWQFetchChessList', {
                'srcuid': 0,
                'dstuid': account_id,
                'type': 1,
                'lastcode': 0,
                'searchkey': '',
                'uin': account_id,
            })
            listing = FoxList.model_validate(data)
        except ValidationError:
            raise upstream_error() from None
        items = []
        seen = set()
        for item in sorted(listing.chesslist, key=lambda item: int(item.gamestarttime), reverse=True):
            if uid not in (item.blackuid, item.whiteuid) or item.chessid in seen:
                continue
            seen.add(item.chessid)
            if account_name is None:
                account_name = item.blacknick if item.blackuid == uid else item.whitenick
            result = 'unknown'
            if item.winner in (1, 2):
                won = item.blackuid == uid if item.winner == 1 else item.whiteuid == uid
                result = 'win' if won else 'loss'
            items.append(GameRecord(
                chessId=item.chessid,
                playedAt=item.starttime,
                blackName=item.blacknick,
                whiteName=item.whitenick,
                boardSize=item.boardsize,
                moveCount=item.movenum,
                result=result,
            ))
        return CachedRecords(monotonic() + CACHE_SECONDS, account_id, account_name, items)


async def download_sgf(client: httpx.AsyncClient, payload: SgfDownloadRequest):
    data = await fetch_json(client, f'{BASE_URL}/YHWQFetchChess', {'chessid': payload.chessId})
    if data.get('chessid') != payload.chessId:
        raise upstream_error()
    text = data.get('chess')
    if not isinstance(text, str) or not text.lstrip().startswith('('):
        raise upstream_error()
    if len(text.encode('utf-8')) > 2 * 1024 * 1024:
        raise AppError('RECORDS_UNAVAILABLE', '棋谱超过 2 MB，暂不支持下载', 502)
    return SgfDownloadResponse(chessId=payload.chessId, sgfText=text)
