"""전결권/금액밴드/카운트 구조화 SQL 집계 — 거절 아님 (plan §7.2).

★ 금액 산술/범위 판정은 전부 SQL(amount_band @> :v::int8) — LLM 절대 금지. 각 전결 행은
canonical_authority_id/regulation_id 를 AggregateRow.extra 에 담아 D(렌더)가 결정론 인용하게 한다
(major-2). 진입 분기: 금액 파싱되면 금액밴드 우선 → AGGREGATE intent 면 카운트 → 나머지 전결권자.
"""

from __future__ import annotations

from psycopg.rows import dict_row

from app.search.amount import parse_amount
from app.search.intent import classify_intent
from app.search.normalize import normalize
from app.search.types import AggregateResult, AggregateRow, QueryIntent

# 전결권자/금액밴드 공통 SELECT 컬럼(결정론 인용 식별자 선두 — major-2).
_AUTH_COLS = (
    "am.canonical_authority_id, am.regulation_id, am.business_item, am.action_type, "
    "am.approver_role, am.consulter_roles, am.amount_min, am.amount_max"
)


def _auth_row(row: dict) -> AggregateRow:
    """authority_matrix 행 → AggregateRow(extra 에 인용 식별자·금액 메타)."""
    return AggregateRow(
        label=row["business_item"],
        value=row["approver_role"],
        extra={
            "canonical_authority_id": row["canonical_authority_id"],
            "regulation_id": row["regulation_id"],
            "action_type": row["action_type"],
            "consulter_roles": row["consulter_roles"],
            "amount_min": row["amount_min"],
            "amount_max": row["amount_max"],
        },
    )


async def _approval_line(conn, amount: int, board_ids: list[int] | None) -> AggregateResult:
    """금액밴드 결재라인 — amount_band @> amount(GiST). 범위 판정은 SQL."""
    sql = (
        f"SELECT {_AUTH_COLS} FROM authority_matrix am "
        "WHERE am.amount_band @> %(amt)s::int8 AND am.is_current "
    )
    params: dict = {"amt": amount, "boards": board_ids}
    if board_ids is not None:
        sql += (
            "AND am.regulation_id IN ("
            "SELECT regulation_id FROM regulation WHERE board_id = ANY(%(boards)s)) "
        )
    sql += "ORDER BY am.order_seq NULLS LAST"
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, params)
        rows = await cur.fetchall()
    out = [_auth_row(r) for r in rows]
    return AggregateResult(kind="approval_line", rows=out, count=len(out))


async def _approver(conn, normalized_query: str, board_ids: list[int] | None) -> AggregateResult:
    """업무항목 전결권자 — business_item &@~ 질의."""
    sql = (
        f"SELECT {_AUTH_COLS} FROM authority_matrix am "
        "WHERE am.business_item &@~ %(item)s AND am.is_current "
    )
    params: dict = {"item": normalized_query, "boards": board_ids}
    if board_ids is not None:
        sql += (
            "AND am.regulation_id IN ("
            "SELECT regulation_id FROM regulation WHERE board_id = ANY(%(boards)s)) "
        )
    sql += "ORDER BY am.order_seq NULLS LAST"
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, params)
        rows = await cur.fetchall()
    out = [_auth_row(r) for r in rows]
    return AggregateResult(kind="approver", rows=out, count=len(out))


async def _board_count(conn, board_ids: list[int] | None) -> AggregateResult:
    """보드별 현행 규정 카운트(authority 인용 식별자 비해당)."""
    sql = "SELECT board_id, count(*) AS cnt FROM regulation WHERE is_current "
    params: dict = {"boards": board_ids}
    if board_ids is not None:
        sql += "AND board_id = ANY(%(boards)s) "
    sql += "GROUP BY board_id ORDER BY board_id"
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, params)
        rows = await cur.fetchall()
    out = [AggregateRow(label=str(r["board_id"]), value=r["cnt"]) for r in rows]
    return AggregateResult(kind="board_count", rows=out, count=len(out))


async def aggregate(
    conn, query: str, *, board_ids: list[int] | None = None
) -> AggregateResult:
    """질의를 구조화 SQL 집계로 처리한다(거절 게이트 비적용, 0행이면 count=0 정상).

    분기: 금액 토큰이 파싱되면 금액밴드 우선 → AGGREGATE intent 면 카운트 → 나머지 전결권자(§7.2).
    """
    normalized = normalize(query)
    amount = parse_amount(normalized)
    if amount is not None:
        return await _approval_line(conn, amount, board_ids)
    if classify_intent(normalized) == QueryIntent.AGGREGATE:
        return await _board_count(conn, board_ids)
    return await _approver(conn, normalized, board_ids)
