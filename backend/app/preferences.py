import json
import os
import tempfile
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field, StrictInt, field_validator
from typing import Annotated

from .config import ROOT, Settings
from .models import Contract

PREFERENCES_PATH = ROOT / 'settings.json'


class Preferences(Contract):
    aiUrl: str
    maxTokens: Annotated[StrictInt, Field(ge=1)]
    katagoPath: str
    katagoModelPath: str
    visits: Annotated[StrictInt, Field(ge=1)]
    candidateCount: Annotated[StrictInt, Field(ge=1, le=3)]

    stopMove: Annotated[StrictInt, Field(ge=1)]

    @field_validator('aiUrl')
    @classmethod
    def valid_url(cls, value):
        parsed = urlparse(value)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError('请填写完整的 AI 接口 URL')
        return value


class SavePreferences(Preferences):
    apiKey: str = Field(repr=False)


def public_preferences(settings):
    return {
        'aiUrl': settings.ai_url,
        'maxTokens': settings.max_tokens,
        'katagoPath': settings.katago_path,
        'katagoModelPath': settings.katago_model_path,
        'visits': settings.visits,
        'candidateCount': settings.candidate_count,
        'stopMove': settings.stop_move,
        'apiKeyConfigured': bool(settings.ai_key)
    }


def apply_preferences(settings, payload):
    if bool(payload.katagoPath.strip()) != bool(payload.katagoModelPath.strip()):
        raise ValueError('KataGo 程序和权重路径必须同时填写或同时留空')
    for value in (payload.katagoPath, payload.katagoModelPath):
        if value and not Path(value).is_absolute():
            raise ValueError('KataGo 程序和权重必须使用绝对路径')
    return replace(
        settings, ai_url=payload.aiUrl, ai_key=payload.apiKey.strip() or settings.ai_key,
        max_tokens=payload.maxTokens, katago_path=payload.katagoPath.strip(),
        katago_model_path=payload.katagoModelPath.strip(), visits=payload.visits,
        candidate_count=payload.candidateCount, stop_move=payload.stopMove
    )


def load_preferences(settings):
    if not PREFERENCES_PATH.exists():
        return settings
    return apply_preferences(settings, SavePreferences.model_validate_json(PREFERENCES_PATH.read_text()))


def save_preferences(settings):
    data = public_preferences(settings)
    del data['apiKeyConfigured']
    data['apiKey'] = settings.ai_key
    descriptor, temporary = tempfile.mkstemp(dir=ROOT, prefix='.settings-')
    try:
        with os.fdopen(descriptor, 'w') as output:
            json.dump(data, output, ensure_ascii=False)
        os.replace(temporary, PREFERENCES_PATH)
    finally:
        Path(temporary).unlink(missing_ok=True)
