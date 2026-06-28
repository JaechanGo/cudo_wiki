"""docker-compose.yml 구조 검증 (DB/도커 불필요 — YAML 파싱만).

plan §7.2: 3서비스 / mcp 포트 비노출 / 외부망 external:true / postgres 이미지 핀(≠latest).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_COMPOSE_PATH = Path(__file__).resolve().parents[2] / "docker-compose.yml"


@pytest.fixture(scope="module")
def compose() -> dict:
    with _COMPOSE_PATH.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_three_services(compose: dict) -> None:
    services = compose["services"]
    assert set(services) == {"postgres", "cudo-wiki-mcp", "migrate"}


def test_mcp_no_host_ports(compose: dict) -> None:
    """cudo-wiki-mcp 는 호스트 포트 비노출 → `ports` 키 부재."""
    assert "ports" not in compose["services"]["cudo-wiki-mcp"]


def test_postgres_no_host_ports(compose: dict) -> None:
    """postgres 도 internal 전용 → 호스트 포트 비노출."""
    assert "ports" not in compose["services"]["postgres"]


def test_external_networks(compose: dict) -> None:
    """librechat_default / litellm-gateway_default 는 external:true."""
    nets = compose["networks"]
    assert nets["librechat_default"]["external"] is True
    assert nets["litellm-gateway_default"]["external"] is True


def test_postgres_image_pinned_pgroonga(compose: dict) -> None:
    """postgres 이미지 = groonga/pgroonga, 태그 핀(≠latest, ≠무태그)."""
    image = compose["services"]["postgres"]["image"]
    assert image.startswith("groonga/pgroonga")
    assert ":" in image, "이미지 태그가 핀되어야 함"
    tag = image.rsplit(":", 1)[1]
    assert tag != "latest", ":latest 금지 (재현성)"


def test_mcp_and_migrate_share_build(compose: dict) -> None:
    """mcp·migrate 는 동일 이미지(docker/Dockerfile.mcp) 재사용."""
    svc = compose["services"]
    assert svc["cudo-wiki-mcp"]["build"]["dockerfile"] == "docker/Dockerfile.mcp"
    assert svc["migrate"]["build"]["dockerfile"] == "docker/Dockerfile.mcp"


def test_migrate_profile(compose: dict) -> None:
    """migrate 는 profile=migrate (평상시 미기동)."""
    assert "migrate" in compose["services"]["migrate"]["profiles"]


def test_env_file_optional(compose: dict) -> None:
    """[M-2] mcp·migrate 의 env_file 은 required:false → .env 부재에도 config 통과."""
    for name in ("cudo-wiki-mcp", "migrate"):
        env_file = compose["services"][name]["env_file"]
        # long syntax: [{path: .env, required: false}]
        assert any(
            isinstance(e, dict) and e.get("path") == ".env" and e.get("required") is False
            for e in env_file
        ), f"{name}: env_file 에 .env required:false 항목 필요"


def test_postgres_only_internal(compose: dict) -> None:
    """postgres 는 internal 망만 (외부망 미합류 — DB 격리)."""
    assert compose["services"]["postgres"]["networks"] == ["internal"]


def test_mcp_joins_external_networks(compose: dict) -> None:
    """cudo-wiki-mcp 는 internal + 두 외부망 합류."""
    nets = compose["services"]["cudo-wiki-mcp"]["networks"]
    assert set(nets) == {"internal", "librechat_default", "litellm-gateway_default"}
