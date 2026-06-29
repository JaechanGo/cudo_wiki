"""0005 — gainge 영상 통합: board.board_class / post.doc_type CHECK enum 에 'video' 추가.

지식뱅크(cudo.gainge.com) 영상을 board(board_class='video') + post(doc_type='video')로 적재해
규정·공지와 구분한다(recommend_videos 도구 전용, 규정/일반 검색에서는 board_id 로 제외).
process_post 가 doc_type=board_class 로 박으므로 두 CHECK 를 동시에 확장해야 INSERT 가 통과한다.
chunk_class 는 notice_section 폴백을 재사용하므로 추가 불필요.

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 0002 인라인 무명 CHECK 의 PostgreSQL 자동 제약명(= {table}_{column}_check).
_BOARD_CK = "board_board_class_check"
_POST_CK = "post_doc_type_check"
_OLD = "('notice','regulation','authority','manual','form','meeting','etc')"
_NEW = "('notice','regulation','authority','manual','form','meeting','etc','video')"


def _swap_check(table: str, constraint: str, column: str, allowed: str) -> None:
    op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {constraint}")
    op.execute(
        f"ALTER TABLE {table} ADD CONSTRAINT {constraint} "
        f"CHECK ({column} IN {allowed})"
    )


def upgrade() -> None:
    _swap_check("board", _BOARD_CK, "board_class", _NEW)
    _swap_check("post", _POST_CK, "doc_type", _NEW)


def downgrade() -> None:
    _swap_check("board", _BOARD_CK, "board_class", _OLD)
    _swap_check("post", _POST_CK, "doc_type", _OLD)
