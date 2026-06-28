"""0004 acl_audit — C MCP 서버 보안 감사 테이블 (Task009 plan §5.2).

쟁점3 결정 (A): query_log(질의 분석)와 별개로 ACL deny/신원부재/민감보드요청 같은 **보안 이벤트**를
별도 테이블에 적재(관심사 분리, PII 처리 일관). decision CHECK enum 은 0002 enum-CHECK 스타일과 일관,
user_email_hash 는 sha256(원문 금지, PIPA). 인덱스 (occurred_at)·(decision).

13표(0002)→14표. 기존 스키마 테스트가 subset/화이트리스트 기반이라 회귀 없이 올라감.

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE acl_audit (
            acl_audit_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            occurred_at         timestamptz NOT NULL DEFAULT now(),
            tool_name           text NOT NULL,
            user_role           text,                      -- 헤더 role (원문, PII 아님)
            user_email_hash     text,                      -- sha256(email), 원문 금지(PIPA)
            identity_present    boolean NOT NULL,
            decision            text NOT NULL
                CHECK (decision IN ('allow','deny','identity_absent','filtered')),
            requested_board_ids integer[],                 -- 요청 보드(있으면)
            allowed_board_ids   integer[],                 -- 해석된 허용 보드
            denied_board_ids    integer[],                 -- drop 된 보드(민감/미존재)
            reason              text,                      -- 'sensitive_board'/'unknown_board'/'no_identity'/...
            session_id          text
        );
        """
    )
    op.execute("CREATE INDEX idx_acl_audit_occurred_at ON acl_audit (occurred_at);")
    op.execute("CREATE INDEX idx_acl_audit_decision ON acl_audit (decision);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS acl_audit CASCADE;")
