import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')


@dataclass(frozen=True)
class Settings:
    katago_url: str = os.getenv('KATAGO_URL', 'http://127.0.0.1:8001/analyze')
    engine_label: str = os.getenv('KATAGO_ENGINE_LABEL', 'KataGo 1.17.0 · kata1-b18c384nbt-s9996604416-d4316597426')
    visits: int = int(os.getenv('KATAGO_VISITS', '500'))
    # 这不是推断出的视角；本机现有服务配置已经明确设置为 BLACK。
    katago_perspective: str = os.getenv('KATAGO_PERSPECTIVE', 'BLACK')
    katago_timeout: float = 120
    ai_url: str = 'https://api.deepseek.com/chat/completions'
    ai_model: str = os.getenv('DEEPSEEK_MODEL', 'deepseek-flash')
    ai_key: str = field(default_factory=lambda: os.getenv('DEEPSEEK_API_KEY', '').strip(), repr=False)
    max_tokens: int = 1000
    katago_path: str = ''
    katago_model_path: str = ''
    candidate_count: int = 3
    stop_move: int = 20
    ai_timeout: float = 60
    allowed_origins: tuple[str, ...] = tuple(
        value.strip() for value in os.getenv('ALLOWED_ORIGINS', 'http://127.0.0.1:5178').split(',') if value.strip()
    )

    def __post_init__(self):
        upstream = urlparse(self.katago_url)
        if upstream.scheme != 'http' or upstream.hostname not in ('127.0.0.1', 'localhost', '::1') or upstream.username or upstream.password:
            raise ValueError('KATAGO_URL 必须是回环地址上的 HTTP 分析接口')
        if self.katago_perspective != 'BLACK':
            raise ValueError('请先将 KataGo 服务配置 reportAnalysisWinratesAs 设为 BLACK')
        if self.visits < 1 or not self.engine_label.strip() or not self.ai_model.strip():
            raise ValueError('引擎标识、预算或 AI 模型配置无效')
        for origin in self.allowed_origins:
            parsed = urlparse(origin)
            if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1') or parsed.path or parsed.query or parsed.fragment:
                raise ValueError('页面来源必须是显式的本机 HTTP 来源，不可使用通配符')
