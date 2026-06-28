"""헤더 → Identity 해석 — MCP Context 의존 격리 (Task009 plan §4.1·§4.2, M-1).

★ 헤더 접근 API 버전 확정 기록 (M-1, 추정 금지):
    설치 mcp 버전 = **1.28.1** (pyproject 핀 ``mcp>=1.8,<2``).
    가용 헤더 경로 = **(i) ``ctx.request_context.request``** (streamable-http → starlette Request,
                       stdio → None). 구현 1단계 실검증 결과:
      - ``from mcp.server.fastmcp import FastMCP, Context`` 유효.
      - ``mcp.shared.context.RequestContext`` 에 ``request: RequestT | None`` 필드 존재.
      - streamable-http 경로(``mcp/server/streamable_http.py:269``)에서
        ``ServerMessageMetadata(request_context=request)`` 로 starlette ``Request`` 가 주입됨 →
        lowlevel server(``server.py:771``)가 ``RequestContext(..., request=request_data)`` 로 전달.
      - 경로 (ii) ``get_http_headers`` 는 이 버전에 **부재**(import 실패 확인).
      - 경로 (iii) ``transport.headers`` 는 상위 계열 전용 — 미사용.
    R0 ``app/mcp/server.py`` 의 ``FastMCP``·``streamable_http_app()`` 도 이 버전에서 import 유효
    (스모크 확인).

스푸핑 방지(§4.2): 신원은 **LibreChat 인증세션이 주입하는 보간 헤더만** 신뢰한다. C 는 헤더만
읽으므로 customUserVars(``{{사용자입력}}``) 경로는 C 코드에서 구조적으로 부재 — 단 헤더 값의 출처
(인증세션 vs customUserVars 매핑)는 D 의 librechat.yaml 이 보장(§7.4, m-2).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

# ── 헤더 키 계약(C 가 확정 — D 의 librechat.yaml headers: 보간값과 이 키로 일치) ──────────
HEADER_ROLE = "x-librechat-user-role"
HEADER_EMAIL = "x-librechat-user-email"
HEADER_USER_ID = "x-librechat-user-id"
HEADER_SESSION = "x-librechat-session-id"


@dataclass(frozen=True)
class Identity:
    """헤더에서 해석한 신원. raw_present=False 면 신원부재 → fail-closed(§4.4)."""

    role: str | None
    email: str | None
    user_id: str | None
    session_id: str | None
    raw_present: bool


def _clean(value: object) -> str | None:
    """헤더 값 정리 — 공백 제거, 빈 문자열/None 은 부재로 취급(미인증 빈 보간 방어)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def identity_from_headers(headers: Mapping[str, object] | None) -> Identity:
    """헤더 매핑 → Identity. 키는 소문자 정규화로 비교(대소문자 무관, 순수 함수)."""
    norm: dict[str, object] = {}
    if headers:
        for key, value in headers.items():
            norm[key.lower()] = value
    role = _clean(norm.get(HEADER_ROLE))
    email = _clean(norm.get(HEADER_EMAIL))
    user_id = _clean(norm.get(HEADER_USER_ID))
    session_id = _clean(norm.get(HEADER_SESSION))
    return Identity(
        role=role,
        email=email,
        user_id=user_id,
        session_id=session_id,
        raw_present=bool(role or email),
    )


def _ctx_headers(ctx: object) -> Mapping[str, object] | None:
    """MCP Context 에서 HTTP 요청 헤더를 안전 추출(None-guard 격리, §4.1)."""
    request_context = getattr(ctx, "request_context", None)
    request = getattr(request_context, "request", None)
    if request is None:  # stdio 전송 또는 비-HTTP → 헤더 없음.
        return None
    return getattr(request, "headers", None)


def resolve_identity(ctx: object) -> Identity:
    """MCP Context → Identity. 모든 도구 진입의 ACL 신원 원천(§3 공통)."""
    return identity_from_headers(_ctx_headers(ctx))
