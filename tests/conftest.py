"""pytest 공용 픽스처 — DB 가용성 기반 통합테스트 스킵 (plan §7.1).

DSN 결정 우선순위:
  ① TEST_DATABASE_URL / DATABASE_URL env (libpq 또는 +psycopg 형태 모두 허용)
  ② testcontainers 로 groonga/pgroonga 컨테이너 자동 기동 (docker daemon 가용 시)
  ③ 둘 다 불가 → pytest.skip (단위테스트는 영향 없음)
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# testcontainers 가 기동할 PGroonga 이미지 (compose 와 동일 핀).
PGROONGA_IMAGE = "groonga/pgroonga:4.0.6-debian-17"


def _split_dsn(url: str) -> dict[str, str]:
    """입력 DSN 을 libpq(postgresql://) + sqlalchemy(postgresql+psycopg://) 두 형태로."""
    if url.startswith("postgresql+psycopg://"):
        sa = url
        libpq = "postgresql://" + url.split("://", 1)[1]
    elif url.startswith("postgresql://"):
        libpq = url
        sa = "postgresql+psycopg://" + url.split("://", 1)[1]
    else:  # postgres:// 등
        tail = url.split("://", 1)[1]
        libpq = "postgresql://" + tail
        sa = "postgresql+psycopg://" + tail
    return {"libpq": libpq, "sqlalchemy": sa}


@pytest.fixture(scope="session")
def db_dsn():
    """통합테스트용 DB DSN. 없으면 skip."""
    env_url = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
    if env_url:
        yield _split_dsn(env_url)
        return

    try:
        from testcontainers.postgres import PostgresContainer
    except Exception:  # pragma: no cover
        pytest.skip("DB 미가용: TEST_DATABASE_URL 미설정 & testcontainers 미설치")

    container = PostgresContainer(
        image=PGROONGA_IMAGE,
        username="cudo",
        password="cudo",
        dbname="cudo_wiki",
        driver="psycopg",
    )
    try:
        container.start()
    except Exception as exc:  # docker daemon down 등
        pytest.skip(f"pgroonga 컨테이너 기동 불가(daemon down 등): {exc}")

    try:
        sa_url = container.get_connection_url(driver="psycopg")
        yield _split_dsn(sa_url)
    finally:
        container.stop()


@pytest.fixture(scope="session")
def migrated_db(db_dsn):
    """db_dsn 에 `alembic upgrade head` 1회 적용 후 DSN 반환."""
    env = os.environ.copy()
    env["ALEMBIC_DATABASE_URL"] = db_dsn["sqlalchemy"]
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"alembic upgrade head 실패\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    return db_dsn
