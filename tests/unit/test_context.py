"""context.resolve_identity / identity_from_headers 단위테스트 (Task009 §4.2·§8.1).

헤더→Identity 해석은 ACL 의 신원 원천. 대소문자 무관·공백/빈값 정리·신원부재 fail-closed 신호
(raw_present=False)를 검증한다. customUserVars 경로는 C 코드에 구조적으로 부재(헤더만 읽음).
"""

from __future__ import annotations

from app.mcp.context import (
    HEADER_EMAIL,
    HEADER_ROLE,
    HEADER_SESSION,
    HEADER_USER_ID,
    Identity,
    identity_from_headers,
    resolve_identity,
)


def test_extracts_role_and_email():
    ident = identity_from_headers({HEADER_ROLE: "staff", HEADER_EMAIL: "a@cudo.co.kr"})
    assert ident.role == "staff"
    assert ident.email == "a@cudo.co.kr"
    assert ident.raw_present is True


def test_header_keys_case_insensitive():
    """starlette 멀티딕트가 아니라 일반 dict 라도 대소문자 무관 정규화."""
    ident = identity_from_headers(
        {"X-LibreChat-User-Role": "admin", "X-LIBRECHAT-USER-EMAIL": "b@cudo.co.kr"}
    )
    assert ident.role == "admin"
    assert ident.email == "b@cudo.co.kr"
    assert ident.raw_present is True


def test_absent_headers_fail_closed():
    """헤더 전무 → raw_present=False (신원부재 → fail-closed 신호)."""
    ident = identity_from_headers({})
    assert ident.role is None
    assert ident.email is None
    assert ident.raw_present is False


def test_none_headers_fail_closed():
    """헤더 컨테이너 자체가 None(stdio 등) → 안전 부재."""
    ident = identity_from_headers(None)
    assert ident.raw_present is False


def test_empty_string_values_treated_absent():
    """LibreChat 미인증 시 빈 문자열 보간 → 공백/빈값은 부재로 취급(fail-closed)."""
    ident = identity_from_headers({HEADER_ROLE: "  ", HEADER_EMAIL: ""})
    assert ident.role is None
    assert ident.email is None
    assert ident.raw_present is False


def test_email_only_is_present():
    """role 미제공(LibreChat v1)이라도 email 있으면 인증 직원으로 판정(§9-2)."""
    ident = identity_from_headers({HEADER_EMAIL: "c@cudo.co.kr"})
    assert ident.role is None
    assert ident.email == "c@cudo.co.kr"
    assert ident.raw_present is True


def test_optional_user_id_and_session():
    ident = identity_from_headers(
        {
            HEADER_EMAIL: "d@cudo.co.kr",
            HEADER_USER_ID: "u-123",
            HEADER_SESSION: "sess-9",
        }
    )
    assert ident.user_id == "u-123"
    assert ident.session_id == "sess-9"


def test_values_stripped():
    ident = identity_from_headers({HEADER_ROLE: "  staff ", HEADER_EMAIL: " e@cudo.co.kr "})
    assert ident.role == "staff"
    assert ident.email == "e@cudo.co.kr"


def test_identity_is_frozen():
    ident = Identity(role="r", email="e", user_id=None, session_id=None, raw_present=True)
    try:
        ident.role = "x"  # type: ignore[misc]
    except AttributeError:
        return
    raise AssertionError("Identity 는 frozen 이어야 한다")


# ── resolve_identity(ctx) — Context 의존 경로(얇은 래퍼) ────────────────────


class _FakeHeaders(dict):
    """starlette Headers 대용(대소문자 무관은 identity_from_headers 가 처리)."""


class _FakeRequest:
    def __init__(self, headers):
        self.headers = headers


class _FakeReqCtx:
    def __init__(self, request):
        self.request = request


class _FakeCtx:
    def __init__(self, request):
        self.request_context = _FakeReqCtx(request)


def test_resolve_identity_from_http_ctx():
    ctx = _FakeCtx(_FakeRequest(_FakeHeaders({HEADER_EMAIL: "f@cudo.co.kr"})))
    ident = resolve_identity(ctx)
    assert ident.email == "f@cudo.co.kr"
    assert ident.raw_present is True


def test_resolve_identity_stdio_request_none():
    """stdio 전송 → request_context.request 가 None → 부재."""
    ctx = _FakeCtx(None)
    ident = resolve_identity(ctx)
    assert ident.raw_present is False


def test_resolve_identity_no_request_context():
    """request_context 속성 부재(방어적) → 부재."""

    class _Bare:
        pass

    ident = resolve_identity(_Bare())
    assert ident.raw_present is False
