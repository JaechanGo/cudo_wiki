"""도구 공통 ACL 게이트 — 신원부재/보드필터 + acl_audit 결선 (Task009 §3 공통·§4.4).

모든 도구 진입의 ACL 적용 지점을 한 곳에 모은다: 신원부재면 identity_absent 감사 + None 반환(도구는
fail-closed 출력), 보드 필터에서 drop 이 있으면 filtered 감사 1건.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.mcp import audit
from app.mcp.acl import allowed_board_ids, filter_board_ids
from app.mcp.context import Identity

# 신원부재 사용자 노출 한국어(§4.4).
ABSENT_MESSAGE_KO = "로그인 세션을 확인할 수 없습니다. LibreChat 로그인 상태를 확인해 주세요."
# 보드 비허용 deny 안내.
DENY_MESSAGE_KO = "해당 자료에 접근 권한이 없습니다."


@dataclass(frozen=True)
class AccessGrant:
    """게이트 통과 결과 — 유효/허용/거부 보드."""

    effective_boards: list[int]
    allowed_boards: list[int]
    denied_boards: list[int]


async def gate_boards(
    conn, identity: Identity, *, tool_name: str, requested: list[int] | None
) -> AccessGrant | None:
    """신원·보드 ACL 게이트. 신원부재면 acl_audit(identity_absent) 후 None.

    drop 된 보드가 있으면 acl_audit(filtered) 1건. requested=None 이면 허용 전체가 유효 보드.
    """
    if not identity.raw_present:
        await audit.write_acl_audit(
            conn, tool_name=tool_name, identity=identity,
            decision="identity_absent", reason="no_identity",
        )
        return None
    allowed = await allowed_board_ids(conn, identity)
    effective, denied = filter_board_ids(requested, allowed)
    if denied:
        await audit.write_acl_audit(
            conn, tool_name=tool_name, identity=identity, decision="filtered",
            requested=requested, allowed=allowed, denied=denied,
            reason="unknown_or_sensitive_board",
        )
    return AccessGrant(
        effective_boards=effective, allowed_boards=allowed, denied_boards=denied
    )
