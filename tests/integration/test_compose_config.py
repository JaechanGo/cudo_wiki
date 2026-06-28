"""docker compose config 유효성 (@integration — docker CLI 필요).

[M-2] env_file required:false → .env 부재에도 config 종료코드 0.
config 는 daemon 불필요(파싱만)이나, docker CLI 부재 시 skip.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]


def _run_config(*extra: str) -> subprocess.CompletedProcess:
    if shutil.which("docker") is None:
        pytest.skip("docker CLI 미설치")
    result = subprocess.run(
        ["docker", "compose", *extra, "config"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 and "Cannot connect to the Docker daemon" in (
        result.stdout + result.stderr
    ):
        pytest.skip("docker daemon down (config 는 보통 daemon 불요지만 일부 환경 의존)")
    return result


def test_docker_compose_config_valid():
    """[M-2] .env 부재에도 config 종료0. 기본 프로파일 = postgres + cudo-wiki-mcp."""
    result = _run_config()
    assert result.returncode == 0, f"docker compose config 실패:\n{result.stderr}"
    assert "cudo-wiki-mcp" in result.stdout
    assert "postgres" in result.stdout


def test_docker_compose_config_migrate_profile():
    """migrate 는 profile=migrate → --profile migrate config 에서 3서비스 모두 유효."""
    result = _run_config("--profile", "migrate")
    assert result.returncode == 0, f"docker compose --profile migrate config 실패:\n{result.stderr}"
    assert "migrate" in result.stdout
    assert "cudo-wiki-mcp" in result.stdout
    assert "postgres" in result.stdout
