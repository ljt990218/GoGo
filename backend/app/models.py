import math
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

Rules = Literal['chinese', 'japanese']
Player = Literal['black', 'white']
FiniteNumber = Annotated[float, Field(strict=True, allow_inf_nan=False)]


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=False)


class Point(Contract):
    x: Annotated[StrictInt, Field(ge=0, le=18)]
    y: Annotated[StrictInt, Field(ge=0, le=18)]


class Candidate(Contract):
    point: Point | None
    blackWinRate: Annotated[FiniteNumber, Field(ge=0, le=1)]
    blackScoreLead: FiniteNumber
    scoreStdev: Annotated[FiniteNumber, Field(ge=0)] | None = None
    principalVariation: list[Point | None]


class AnalysisResult(Contract):
    moveIndex: Annotated[StrictInt, Field(ge=0)]
    toPlay: Player
    candidates: Annotated[list[Candidate], Field(min_length=1, max_length=3)]
    engineLabel: Annotated[str, Field(min_length=1, max_length=256)]
    visitBudget: Annotated[StrictInt, Field(gt=0)]
    analyzedAt: str

    @field_validator('analyzedAt')
    @classmethod
    def validate_timestamp(cls, value: str):
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if stamp.utcoffset() is None or stamp.utcoffset().total_seconds() != 0:
            raise ValueError('时间必须为 UTC ISO 8601')
        return value


class PositionRequest(Contract):
    sgfText: Annotated[str, Field(min_length=1, max_length=2 * 1024 * 1024)]
    moveIndex: Annotated[StrictInt, Field(ge=0)]
    rules: Rules
    komi: Annotated[FiniteNumber, Field(ge=-50, le=50)]

    @field_validator('komi')
    @classmethod
    def validate_komi(cls, value: float):
        if not math.isfinite(value) or not (value * 2).is_integer():
            raise ValueError('贴目必须为 0.5 的倍数')
        return value


class ExplainRequest(PositionRequest):
    analysis: AnalysisResult
    candidateIndex: Annotated[StrictInt, Field(ge=0, le=2)] = 0


class ExplanationResult(Contract):
    candidateIndex: Annotated[StrictInt, Field(ge=0, le=2)]
    explanation: str
    aiModel: str
    explainedAt: str
