"""배치 오케스트레이션 CLI (plan §1·§2).

``python -m app.ingest.run --board <no> | --all [--full] [--health-check]``

흐름(보드별): list_post_refs → crawl_post → normalize → extract(첨부) → 규정보드면
parse_clauses/parse_authority(reg_id 먼저 확정 후) → loader.upsert_* → advance_ingest_state →
health.update_heartbeat.

트랜잭션 **"1글=1커밋"은 run 이 잡는다**(loader 인계 1항): 글마다 ``with conn.transaction()``.
글 단위 try/except 로 **실패 격리** — 1글 실패가 보드 전체를 중단시키지 않는다(plan §8).
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from dataclasses import replace
from typing import TYPE_CHECKING

from app.ingest.authority_parser import parse_authority_matrix
from app.ingest.board_seed import BOARDS
from app.ingest.clause_parser import parse_clauses
from app.ingest.crawler import crawl_post, list_post_refs
from app.ingest.extract import extract_attachment
from app.ingest.extract.excel import extract_excel_cells
from app.ingest.health import detect_stalled, update_heartbeat
from app.ingest.loader import (
    advance_ingest_state,
    upsert_attachments,
    upsert_authority,
    upsert_board_seed,
    upsert_clauses,
    upsert_post,
    upsert_regulation,
)
from app.ingest.models import IngestCounts, ParsedRegulation
from app.ingest.normalize import clean_html

if TYPE_CHECKING:
    from psycopg import Connection

    from app.ingest.bizbox_client import BizboxClient
    from app.ingest.extract.ocr import OcrClient
    from app.ingest.models import ExtractResult, RawAttachment, RawPost

# board_no → BoardSeed(보드 메타). board_class 로 규정/일반 분기.
_SEED_BY_NO = {b.bizbox_board_no: b for b in BOARDS}


# ── content_hash / 추출 영속화 ───────────────────────────────────────────────


def _content_hash(body_text: str, atts: tuple[RawAttachment, ...]) -> str:
    """body_text + 첨부 sha256(정렬) → 변경감지 해시(plan §4)."""
    digest = hashlib.sha256()
    digest.update((body_text or "").encode("utf-8"))
    for sha in sorted(a.sha256 or "" for a in atts):
        digest.update(b"|")
        digest.update(sha.encode("utf-8"))
    return digest.hexdigest()


def _reg_type(title: str) -> str:
    """제목에서 reg_type 추정(regulation.reg_type CHECK enum)."""
    if "세칙" in title:
        return "세칙"
    if "지침" in title:
        return "지침"
    if "전결" in title:
        return "전결규정"
    return "규정"


def _persist_extract(conn: Connection, attachment_id: int, result: ExtractResult) -> None:
    """추출 결과를 attachment(+attachment_page)에 영속화(loader 외 직접 UPDATE)."""
    conn.execute(
        """
        UPDATE attachment SET
          extracted_text = %s, page_count = %s, extract_method = %s,
          ocr_status = %s, is_table = %s, error_msg = %s, extracted_at = now()
        WHERE attachment_id = %s
        """,
        (
            result.extracted_text, result.page_count, result.method,
            result.ocr_status, result.is_table, result.error_msg, attachment_id,
        ),
    )
    for page in result.pages:
        conn.execute(
            """
            INSERT INTO attachment_page
              (attachment_id, page_no, ocr_text, ocr_confidence, image_path, width_px, height_px)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (attachment_id, page_no) DO UPDATE SET
              ocr_text = EXCLUDED.ocr_text, ocr_confidence = EXCLUDED.ocr_confidence,
              image_path = EXCLUDED.image_path, width_px = EXCLUDED.width_px,
              height_px = EXCLUDED.height_px
            """,
            (
                attachment_id, page.page_no, page.ocr_text, page.ocr_confidence,
                page.image_path, page.width_px, page.height_px,
            ),
        )


# ── 글 1건 처리 ───────────────────────────────────────────────────────────────


def _download_and_extract(
    client: BizboxClient,
    raw: RawPost,
    ocr_client: OcrClient | None,
) -> tuple[tuple[RawAttachment, ...], list[ExtractResult | None]]:
    """첨부 바이트 다운로드 + 추출. (sha256/content 채운 atts, 추출결과) 반환."""
    atts: list[RawAttachment] = []
    results: list[ExtractResult | None] = []
    for att in raw.attachments:
        content: bytes | None = None
        try:
            content = client.download_attachment(att.download_url or "", {})
        except Exception:  # 다운로드 실패는 격리(추출만 skip, 첨부 ref 는 적재).
            content = None
        sha = hashlib.sha256(content).hexdigest() if content else att.sha256
        att2 = replace(
            att, content=content, sha256=sha, byte_size=len(content) if content else att.byte_size
        )
        atts.append(att2)
        results.append(extract_attachment(att2, ocr_client=ocr_client) if content else None)
    return tuple(atts), results


def process_post(
    conn: Connection,
    client: BizboxClient,
    *,
    board_id: int,
    board_no: int,
    board_class: str,
    art_no: int,
    ocr_client: OcrClient | None = None,
) -> IngestCounts:
    """글 1건: 크롤→정제→추출→적재(규정이면 clause/authority). 호출부가 트랜잭션을 잡는다."""
    raw = crawl_post(client, board_no, art_no)
    body_text = clean_html(raw.body_html, None)

    atts, results = _download_and_extract(client, raw, ocr_client)
    content_hash = _content_hash(body_text, atts)
    raw2 = replace(
        raw, body_text=body_text, doc_type=board_class,
        content_hash=content_hash, attachments=atts,
    )

    post_id = upsert_post(conn, raw2, board_id)
    att_ids = upsert_attachments(conn, post_id, atts)
    for aid, result in zip(att_ids, results, strict=False):
        if result is not None:
            _persist_extract(conn, aid, result)

    n_clauses = 0
    n_auth = 0
    if board_class == "regulation":
        reg = ParsedRegulation(title=raw.title, reg_type=_reg_type(raw.title))
        reg_id = upsert_regulation(conn, reg, board_id, source_post_id=post_id)
        clauses = parse_clauses(body_text, reg_id)
        upsert_clauses(conn, reg_id, clauses)
        n_clauses = len(clauses)
        for att in atts:
            if att.kind == "excel" and att.content:
                cells = extract_excel_cells(att.content)
                authorities = parse_authority_matrix(cells, reg_id)
                upsert_authority(conn, reg_id, authorities)
                n_auth += len(authorities)

    return IngestCounts(posts=1, attachments=len(att_ids), clauses=n_clauses, authorities=n_auth)


# ── 보드 1개 크롤 ─────────────────────────────────────────────────────────────


def crawl_board(
    conn: Connection,
    client: BizboxClient,
    *,
    board_no: int,
    board_id: int,
    board_class: str,
    full: bool = False,
    ocr_client: OcrClient | None = None,
) -> IngestCounts:
    """보드 1개 증분 크롤. 글마다 1트랜잭션(실패 격리) → 워터마크 전진 + heartbeat."""
    with conn.transaction():
        update_heartbeat(conn, board_id, status="running", health="healthy")
        wm = conn.execute(
            "SELECT last_art_no, last_posted_at FROM ingest_state WHERE board_id = %s",
            (board_id,),
        ).fetchone()
    since_art = None if full else (wm[0] if wm else None)
    since_dt = None if full else (wm[1] if wm else None)

    refs = list_post_refs(client, board_no, since_art, since_dt)

    posts = atts = clauses = auths = failures = 0
    errors: list[str] = []
    max_art = since_art
    max_dt = since_dt
    for ref in refs:
        try:
            with conn.transaction():
                c = process_post(
                    conn, client, board_id=board_id, board_no=board_no,
                    board_class=board_class, art_no=ref.art_no, ocr_client=ocr_client,
                )
            posts += c.posts
            atts += c.attachments
            clauses += c.clauses
            auths += c.authorities
            if max_art is None or ref.art_no > max_art:
                max_art = ref.art_no
            if ref.posted_at is not None and (max_dt is None or ref.posted_at > max_dt):
                max_dt = ref.posted_at
        except Exception as exc:  # 글 단위 실패 격리(plan §8) — 보드 중단 금지.
            failures += 1
            errors.append(f"art {ref.art_no}: {exc}")

    counts = IngestCounts(
        posts=posts, attachments=atts, clauses=clauses, authorities=auths,
        failures=failures, errors=tuple(errors),
    )
    with conn.transaction():
        advance_ingest_state(conn, board_id, max_art, max_dt, counts)
        update_heartbeat(
            conn, board_id, status="idle",
            health="healthy" if failures == 0 else "degraded",
        )
    return counts


# ── CLI ──────────────────────────────────────────────────────────────────────


def _build_clients() -> tuple[BizboxClient, OcrClient]:
    """실세션 클라이언트(BizBox httpx + OCR). CLI 실행 경로 전용(import 시 생성 안 함)."""
    from app.common.config import get_settings
    from app.ingest.bizbox_client import HttpBizboxClient
    from app.ingest.extract.ocr import OcrClient

    settings = get_settings()
    client = HttpBizboxClient(settings)
    client.login()
    return client, OcrClient(base_url=settings.ocr_base)


def _run_health_check() -> int:
    from app.ingest.db import batch_connection

    with batch_connection(autocommit=True) as conn:
        stalled = detect_stalled(conn)
    if not stalled:
        print("[health] 모든 보드 정상(무신호 임계 내).")
        return 0
    print(f"[health] stalled 보드 {len(stalled)}건:")
    for b in stalled:
        print(f"  - board {b.bizbox_board_no} ({b.name}): last_success={b.last_success_at}")
    return 1


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="app.ingest.run", description="BizBox 인제스트 배치 오케스트레이션"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--board", type=int, help="단일 보드(bizbox_board_no) 크롤")
    group.add_argument("--all", action="store_true", help="19보드 전체 크롤")
    parser.add_argument("--full", action="store_true", help="워터마크 무시 전체 재수집")
    parser.add_argument("--health-check", action="store_true", help="stalled 보드 점검 후 종료")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI 엔트리포인트."""
    args = _parse_args(argv)

    if args.health_check:
        return _run_health_check()

    if not args.all and args.board is None:
        print("사용법: --board <no> | --all [--full] [--health-check]", file=sys.stderr)
        return 2

    targets = list(BOARDS) if args.all else [_SEED_BY_NO[args.board]]

    from app.ingest.db import batch_connection

    client, ocr_client = _build_clients()
    with batch_connection() as conn:
        board_map = upsert_board_seed(conn, BOARDS)
        conn.commit()
        for seed in targets:
            counts = crawl_board(
                conn, client,
                board_no=seed.bizbox_board_no,
                board_id=board_map[seed.bizbox_board_no],
                board_class=seed.board_class,
                full=args.full,
                ocr_client=ocr_client,
            )
            print(
                f"[{seed.bizbox_board_no} {seed.name}] posts={counts.posts} "
                f"att={counts.attachments} clauses={counts.clauses} "
                f"auth={counts.authorities} fail={counts.failures}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
