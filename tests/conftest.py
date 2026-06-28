"""pytest 공용 픽스처 — DB 가용성 기반 통합테스트 스킵 (plan §7.1).

DSN 결정 우선순위:
  ① TEST_DATABASE_URL / DATABASE_URL env (libpq 또는 +psycopg 형태 모두 허용)
  ② testcontainers 로 groonga/pgroonga 컨테이너 자동 기동 (docker daemon 가용 시)
  ③ 둘 다 불가 → pytest.skip (단위테스트는 영향 없음)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# testcontainers 가 기동할 PGroonga 이미지 (compose 와 동일 핀).
PGROONGA_IMAGE = "groonga/pgroonga:4.0.6-debian-17"


def _ensure_docker_host() -> None:
    """testcontainers 가 docker 데몬에 붙도록 환경을 정합 (macOS Docker Desktop 등).

    docker CLI 는 되는데 Python docker SDK(testcontainers 백엔드)는 안 붙는 불일치 3종을 보정:
    1. **소켓 경로**: CLI 는 비표준 context 소켓을 쓰지만 SDK 는 기본 ``/var/run/docker.sock``
       만 봄 → ``docker context`` 의 Host 를 ``DOCKER_HOST`` 로 주입.
    2. **자격증명 헬퍼**: ``credsStore`` 헬퍼(예 docker-credential-desktop)가 PATH 에 없으면
       이미지/ryuk 풀이 StoreError 로 실패 → Docker.app 의 bin 을 PATH 에 보강.
    3. **ryuk reaper**: 세션 픽스처가 ``container.stop()`` 으로 직접 정리하므로 ryuk 불필요 →
       비활성(setdefault 라 사용자 override 가능).
    실패(미설치 등)는 조용히 무시 → 상위 skip-guard 가 처리.
    """
    os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")
    for d in (
        "/Applications/Docker.app/Contents/Resources/bin",
        str(Path.home() / ".docker" / "bin"),
    ):
        if os.path.isdir(d) and d not in os.environ.get("PATH", "").split(os.pathsep):
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
    if os.getenv("DOCKER_HOST"):
        return
    try:
        out = subprocess.run(
            ["docker", "context", "inspect"],
            capture_output=True, text=True, timeout=10,
        )
        host = json.loads(out.stdout)[0]["Endpoints"]["docker"]["Host"]
        if host:
            os.environ["DOCKER_HOST"] = host
    except Exception:  # docker 미설치/오류 → DOCKER_HOST 미설정 유지, skip-guard 처리.
        pass


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

    _ensure_docker_host()
    try:
        from testcontainers.postgres import PostgresContainer
    except Exception:  # pragma: no cover
        pytest.skip("DB 미가용: TEST_DATABASE_URL 미설정 & testcontainers 미설치")

    # 컨테이너 생성·기동을 한 try 로 감싼다 — testcontainers 4.x 는 docker 클라이언트를
    # 생성 시점에 만들 수 있어, daemon/소켓 부재 예외가 생성자에서 날 수 있다(→ skip-guard).
    try:
        container = PostgresContainer(
            image=PGROONGA_IMAGE,
            username="cudo",
            password="cudo",
            dbname="cudo_wiki",
            driver="psycopg",
        )
        container.start()
    except Exception as exc:  # docker daemon down / 소켓 부재 등
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
