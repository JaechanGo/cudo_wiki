"""설정 로더 단위테스트 (DB 불필요 — 항상 실행).

[M-1] 회귀 가드: `dsn` 은 ``postgresql://``, `sqlalchemy_dsn` 은 ``postgresql+psycopg://``.
alembic 이 psycopg3 를 쓰게 강제하는 스킴 분리를 깨지 않도록 단언한다.
"""

from __future__ import annotations

import pytest

from app.common.config import Settings, get_settings

# 환경변수 키 모음 (필드명 대문자).
_ENV_KEYS = [
    "DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD",
    "LITELLM_BASE", "LITELLM_KEY_GLM", "OCR_BASE",
    "BIZBOX_BASE", "BIZBOX_USER", "BIZBOX_PASSWORD",
    "MCP_PORT", "LOG_LEVEL",
]


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """관련 env 를 모두 제거 → 기본값 검증을 위한 격리."""
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _settings_no_envfile(**_kwargs) -> Settings:
    """`.env` 파일 무시(_env_file=None) → 순수 env/기본값만 검증."""
    return Settings(_env_file=None)


def test_defaults(clean_env: None) -> None:
    """env 부재 시 기본값 (db_port=5432, mcp_port=8080, log_level=INFO)."""
    s = _settings_no_envfile()
    assert s.db_port == 5432
    assert s.mcp_port == 8080
    assert s.log_level == "INFO"
    # 빈 비번 허용(로컬).
    assert s.db_password == ""


def test_env_parsing(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """env 주입이 필드로 파싱되고 타입 변환(int)된다."""
    monkeypatch.setenv("DB_HOST", "db.internal")
    monkeypatch.setenv("DB_PORT", "6543")
    monkeypatch.setenv("DB_NAME", "wiki")
    monkeypatch.setenv("DB_USER", "alice")
    monkeypatch.setenv("DB_PASSWORD", "s3cr3t")
    monkeypatch.setenv("MCP_PORT", "9090")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    s = _settings_no_envfile()
    assert s.db_host == "db.internal"
    assert s.db_port == 6543  # str → int
    assert s.db_name == "wiki"
    assert s.db_user == "alice"
    assert s.db_password == "s3cr3t"
    assert s.mcp_port == 9090
    assert s.log_level == "DEBUG"


def test_dsn_scheme_runtime(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """[M-1] 런타임 dsn 은 postgresql:// (psycopg2/psycopg3 스킴 비명시 → psycopg_pool libpq)."""
    monkeypatch.setenv("DB_HOST", "h")
    monkeypatch.setenv("DB_PORT", "5432")
    monkeypatch.setenv("DB_NAME", "n")
    monkeypatch.setenv("DB_USER", "u")
    monkeypatch.setenv("DB_PASSWORD", "p")
    s = _settings_no_envfile()
    assert s.dsn.startswith("postgresql://")
    assert not s.dsn.startswith("postgresql+")
    assert s.dsn == "postgresql://u:p@h:5432/n"


def test_sqlalchemy_dsn_scheme_alembic(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[M-1] alembic 측 dsn 은 postgresql+psycopg:// (psycopg3 명시 선택)."""
    monkeypatch.setenv("DB_HOST", "h")
    monkeypatch.setenv("DB_PORT", "5432")
    monkeypatch.setenv("DB_NAME", "n")
    monkeypatch.setenv("DB_USER", "u")
    monkeypatch.setenv("DB_PASSWORD", "p")
    s = _settings_no_envfile()
    assert s.sqlalchemy_dsn.startswith("postgresql+psycopg://")
    assert s.sqlalchemy_dsn == "postgresql+psycopg://u:p@h:5432/n"


def test_two_dsn_share_credentials(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[M-1] 두 DSN 은 스킴만 다르고 host/port/name(자격증명)은 동일."""
    monkeypatch.setenv("DB_HOST", "pghost")
    monkeypatch.setenv("DB_PORT", "5444")
    monkeypatch.setenv("DB_NAME", "cudo_wiki")
    monkeypatch.setenv("DB_USER", "cudo")
    monkeypatch.setenv("DB_PASSWORD", "")
    s = _settings_no_envfile()
    tail = "@pghost:5444/cudo_wiki"
    assert s.dsn.endswith(tail)
    assert s.sqlalchemy_dsn.endswith(tail)
    # 스킴 제거 후 나머지(자격증명+호스트)가 동일.
    assert s.dsn.split("://", 1)[1] == s.sqlalchemy_dsn.split("://", 1)[1]


def test_password_url_encoded(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """특수문자 비번은 URL 인코딩되어 DSN 파싱을 깨지 않는다."""
    monkeypatch.setenv("DB_PASSWORD", "p@ss:w/rd")
    s = _settings_no_envfile()
    assert "p%40ss%3Aw%2Frd" in s.dsn


def test_get_settings_singleton() -> None:
    """get_settings() 는 lru_cache 싱글톤."""
    get_settings.cache_clear()
    assert get_settings() is get_settings()
    get_settings.cache_clear()
