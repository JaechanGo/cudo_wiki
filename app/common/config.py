"""설정 로더 — `.env` / 환경변수 → `Settings` (pydantic-settings).

DSN 프로퍼티 2종 (plan §6.1, [M-1] 회귀 가드):
  - `dsn`            → ``postgresql://...``          : 런타임 AsyncConnectionPool(psycopg3) 전용.
  - `sqlalchemy_dsn` → ``postgresql+psycopg://...``  : alembic(SQLAlchemy create_engine) 전용.
    SQLAlchemy 는 무지정 ``postgresql://`` 에서 기본 드라이버로 psycopg2 를 선택하는데
    의존성에는 psycopg3 만 있으므로, ``+psycopg`` 스킴으로 psycopg3 를 명시 선택하게 강제한다.
    (미명시 시 ``alembic upgrade head`` 가 ``ModuleNotFoundError: psycopg2`` 로 실패.)
"""

from __future__ import annotations

from functools import lru_cache
from urllib.parse import quote

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """환경변수(.env) 기반 설정. 필드명 대문자 = env 키 (예 db_host → DB_HOST)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── Database ──────────────────────────────────────────────
    db_host: str = "postgres"
    db_port: int = 5432
    db_name: str = "cudo_wiki"
    db_user: str = "cudo"
    db_password: str = ""  # 로컬은 빈값 허용. 운영은 .env 로 주입(커밋 금지).

    # ── LLM gateway (GLM-5.2 via 사내 LiteLLM) ────────────────
    litellm_base: str = "http://litellm:4000/v1"
    litellm_key_glm: str = ""

    # ── OCR shim ──────────────────────────────────────────────
    ocr_base: str = "http://ocr-shim:8900"

    # ── BizBox 그룹웨어 크롤(서비스계정) ──────────────────────
    bizbox_base: str = "http://gw.cudo.co.kr"
    bizbox_user: str = ""
    bizbox_password: str = ""
    # 브라우저 세션 쿠키 재사용(anti-bot 차단 우회용 임시 수단). 설정 시 login() 의 자동 로그인
    # 3단계를 건너뛰고 이 JSESSIONID 를 세션 쿠키로 주입. 세션 만료 시 무효 → 평상시 비움.
    bizbox_jsessionid: str = ""

    # ── MCP server ────────────────────────────────────────────
    mcp_port: int = 8080
    log_level: str = "INFO"

    # ── 검색 랭킹 ─────────────────────────────────────────────
    # 최신순 가중(recency_w): score = raw_score * (1 + recency_w * recency_factor),
    # recency_factor = 1/(1 + age_days/half_life)(반감기 365일). 0.0=비활성(순수 어휘).
    # 사내 정보는 현행(is_current) 안에서도 최신 글을 우선 노출해야 하므로 기본 활성(0.3).
    # 평가 골든셋 영향 시 .env(SEARCH_RECENCY_W)로 조정.
    search_recency_w: float = 0.3

    def _userinfo(self) -> str:
        """``user:password`` (특수문자 URL 인코딩). 빈 비번도 안전(``user:``)."""
        return f"{quote(self.db_user, safe='')}:{quote(self.db_password, safe='')}"

    @property
    def dsn(self) -> str:
        """런타임 psycopg3 풀용 libpq DSN (``postgresql://``)."""
        return f"postgresql://{self._userinfo()}@{self.db_host}:{self.db_port}/{self.db_name}"

    @property
    def sqlalchemy_dsn(self) -> str:
        """alembic(SQLAlchemy) 전용 DSN (``postgresql+psycopg://`` → psycopg3 강제)."""
        return (
            f"postgresql+psycopg://{self._userinfo()}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


@lru_cache
def get_settings() -> Settings:
    """프로세스 단일 Settings 인스턴스(싱글톤)."""
    return Settings()
