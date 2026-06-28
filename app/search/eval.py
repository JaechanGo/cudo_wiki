"""평가 하네스 — recall@10 / 인용정확도 / 기권율 (plan §8).

eval_query/eval_gold 골든셋으로 검색·라우팅 품질을 측정한다. answer_type=authority 는 집계 경로의
AggregateRow.extra["canonical_authority_id"] 를 gold 와 대조(major-2). 빈 골든셋은 graceful(지표
None, exit 0). CLI: ``python -m app.search.eval [--eval-set NAME]``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import asdict, dataclass, field

from psycopg.rows import dict_row

from app.search.aggregate import aggregate
from app.search.intent import classify_intent
from app.search.router import route
from app.search.search import search
from app.search.types import QueryIntent, SearchHit


@dataclass
class EvalReport:
    """평가 리포트. 분모 0 인 지표는 None(N/A)."""

    total: int
    recall_at_10: float | None
    citation_accuracy: float | None
    abstain_recall: float | None
    over_abstain: int
    per_type: dict = field(default_factory=dict)


def _hit_canonical(hit: SearchHit) -> str | None:
    """hit 의 결정론 인용 식별자(clause/authority/post 우선순위)."""
    if hit.canonical_clause_id:
        return hit.canonical_clause_id
    if hit.canonical_authority_id:
        return hit.canonical_authority_id
    if hit.source_post_id is not None:
        return f"post#{hit.source_post_id}"
    return None


async def _candidate_ids(conn, query_text: str, intent: QueryIntent) -> list[str]:
    """recall 측정용 top-10 후보 canonical_id 목록."""
    if intent in (QueryIntent.AUTHORITY_LOOKUP, QueryIntent.AGGREGATE):
        agg = await aggregate(conn, query_text)
        return [
            r.extra.get("canonical_authority_id")
            for r in agg.rows[:10]
            if r.extra.get("canonical_authority_id")
        ]
    sr = await search(conn, query_text, limit=10)
    return [cid for h in sr.hits if (cid := _hit_canonical(h))]


async def _cited_ids(conn, query_text: str) -> set[str]:
    """라우팅 결과의 (검증된) 인용 canonical_id 집합."""
    result = await route(conn, query_text, do_rerank=False)
    if result.aggregate is not None:
        return {
            r.extra.get("canonical_authority_id")
            for r in result.aggregate.rows
            if r.extra.get("canonical_authority_id")
        }
    if result.citations is not None:
        return {c.canonical_id for c in result.citations if c.validated}
    return set()


async def _did_abstain(conn, query_text: str) -> bool:
    """라우팅 결과가 거절했는지(검색 경로만 abstain 설정)."""
    result = await route(conn, query_text, do_rerank=False)
    return bool(result.abstain and result.abstain.abstained)


async def run_eval(conn, eval_set: str | None = None) -> EvalReport:
    """골든셋으로 recall@10·인용정확도·기권율을 계산한다(빈 셋이면 지표 None)."""
    async with conn.cursor(row_factory=dict_row) as cur:
        if eval_set is not None:
            await cur.execute(
                "SELECT eval_query_id, query_text, answer_type, should_abstain "
                "FROM eval_query WHERE eval_set = %s ORDER BY eval_query_id",
                (eval_set,),
            )
        else:
            await cur.execute(
                "SELECT eval_query_id, query_text, answer_type, should_abstain "
                "FROM eval_query ORDER BY eval_query_id"
            )
        queries = await cur.fetchall()

    if not queries:
        return EvalReport(0, None, None, None, 0, {})

    recall_hits: list[bool] = []
    cite_hits: list[bool] = []
    abstain_targets = 0
    abstain_correct = 0
    over_abstain = 0
    per_type: dict[str, dict] = {}

    for q in queries:
        qid, text = q["eval_query_id"], q["query_text"]
        answer_type, should_abstain = q["answer_type"], q["should_abstain"]
        bucket = per_type.setdefault(answer_type, {"total": 0, "recall_hits": 0})
        bucket["total"] += 1

        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT expected_canonical_id FROM eval_gold "
                "WHERE eval_query_id = %s AND relevance >= 1 "
                "AND expected_canonical_id IS NOT NULL",
                (qid,),
            )
            gold = {r["expected_canonical_id"] for r in await cur.fetchall()}

        intent = classify_intent(text)
        if gold:
            cands = set(await _candidate_ids(conn, text, intent))
            hit = bool(gold & cands)
            recall_hits.append(hit)
            if hit:
                bucket["recall_hits"] += 1

        if should_abstain:
            abstain_targets += 1
            if await _did_abstain(conn, text):
                abstain_correct += 1
        else:
            if gold:
                cite_hits.append(bool(gold & await _cited_ids(conn, text)))
            if await _did_abstain(conn, text):
                over_abstain += 1

    return EvalReport(
        total=len(queries),
        recall_at_10=(sum(recall_hits) / len(recall_hits)) if recall_hits else None,
        citation_accuracy=(sum(cite_hits) / len(cite_hits)) if cite_hits else None,
        abstain_recall=(abstain_correct / abstain_targets) if abstain_targets else None,
        over_abstain=over_abstain,
        per_type=per_type,
    )


def _dsn() -> str:
    """DSN 결정: TEST_DATABASE_URL / DATABASE_URL → Settings.dsn."""
    env = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
    if env:
        if env.startswith("postgresql+psycopg://"):
            return "postgresql://" + env.split("://", 1)[1]
        return env
    from app.common.config import get_settings

    return get_settings().dsn


async def _amain(eval_set: str | None) -> None:
    import psycopg

    async with await psycopg.AsyncConnection.connect(_dsn()) as conn:
        report = await run_eval(conn, eval_set=eval_set)
    if report.total == 0:
        print("골든셋 비어있음(0건) — 지표 N/A")
        return
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))


def main() -> None:
    """CLI 진입점."""
    parser = argparse.ArgumentParser(description="검색 코어 평가 하네스")
    parser.add_argument("--eval-set", default=None, help="eval_query.eval_set 필터")
    args = parser.parse_args()
    asyncio.run(_amain(args.eval_set))


if __name__ == "__main__":
    main()
