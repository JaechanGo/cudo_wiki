"""0001 extensions — CREATE EXTENSION pgroonga.

반드시 최선행: 이후 모든 pgroonga 인덱스가 이 확장에 의존.
[m-2/R10] pgroonga 는 trusted extension 이 아니므로 CREATE EXTENSION 은 superuser 권한 필요.
          compose 의 POSTGRES_USER=${DB_USER} 가 컨테이너 superuser 라 동작.
phase-2: CREATE EXTENSION vector; 는 여기 두지 않고 별도 후속 마이그레이션 (§4.6 ADR-002).

Revision ID: 0001
Revises:
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgroonga;")


def downgrade() -> None:
    # 역순 최종단: 0003(인덱스)·0002(테이블)이 모두 drop 된 뒤 실행됨 [m-6].
    op.execute("DROP EXTENSION IF EXISTS pgroonga;")
