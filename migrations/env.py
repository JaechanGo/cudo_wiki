"""alembic 환경 — raw DDL 마이그레이션 (ORM 미사용, target_metadata=None).

DSN 우선순위 (plan §4.8, [M-1]):
  ① 환경변수 ALEMBIC_DATABASE_URL (있으면 그대로 — 스킴 postgresql+psycopg:// 권장)
  ② app.common.config.Settings.sqlalchemy_dsn (= postgresql+psycopg://...)
``postgresql://`` 런타임 dsn 은 넘기지 않는다 — SQLAlchemy 가 psycopg2 를 선택해 실패하므로.

online/offline 모두 지원. offline(`--sql`)은 DB 연결 없이 DDL 을 stdout 으로 출력
→ daemon 없이 13표·확장·인덱스 생성 검증 가능 (검증 게이트 2).
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from app.common.config import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# raw SQL DDL 만 사용 — autogenerate 미사용.
target_metadata = None


def _get_url() -> str:
    url = os.getenv("ALEMBIC_DATABASE_URL")
    if url:
        return url
    return get_settings().sqlalchemy_dsn


def run_migrations_offline() -> None:
    """offline: URL 만으로 DDL 을 SQL 텍스트로 방출 (DB 연결 없음)."""
    context.configure(
        url=_get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """online: sync Engine(psycopg3) 으로 실제 DB 에 적용."""
    connectable = create_engine(_get_url(), future=True)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
