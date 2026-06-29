"""멱등 upsert 적재 (plan §1 loader + §4 멱등 사슬).

배치 동기 커넥션(``db.batch_connection``)이 넘긴 ``conn`` 으로 적재한다. 트랜잭션 경계는
호출부(파트3 run.py 또는 테스트)가 "1글=1커밋"으로 잡는다 — 본 모듈은 SQL 만 실행.

멱등 사슬(★ plan §4): ``post → regulation → clause/authority`` 순서로
위에서부터 닫혀야 재실행 시 중복 INSERT 가 없다.
- post: ``(board_id, bizbox_art_no)`` 일반 unique → ON CONFLICT 멱등. content_hash 동일 시 no-op.
- regulation: reg_code 가 NULL 이면 partial-unique 미발화 → **source_post_id 기준
  SELECT-then-upsert** 로 regulation_id 를 재실행 간 보존(plan §4 major #1·#2).
- clause/authority: canonical id partial-unique upsert(``WHERE is_current``).
  regulation_id 보존 전제 위에서만 멱등.

개정 버전교체는 일반 upsert 가 아니라 ``supersede_*`` 전용 함수(구행 down → 신행 순수 INSERT)로
처리한다(plan §3·§4 major #3).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from psycopg import Connection

    from app.ingest.models import (
        BoardSeed,
        IngestCounts,
        ParsedAuthority,
        ParsedClause,
        ParsedRegulation,
        RawAttachment,
        RawPost,
    )


# ── board seed ───────────────────────────────────────────────────────────────


def upsert_board_seed(conn: Connection, boards: Sequence[BoardSeed]) -> dict[int, int]:
    """19보드 마스터 시드 + 보드별 ingest_state 동반 생성(멱등).

    ``bizbox_board_no`` UNIQUE 자연키로 ON CONFLICT upsert → board_id(IDENTITY)는 재시드
    간 보존된다. 각 보드의 ingest_state 1:1 행도 함께 시드(ON CONFLICT DO NOTHING).

    Returns:
        ``{bizbox_board_no: board_id}`` 매핑.
    """
    mapping: dict[int, int] = {}
    for b in boards:
        board_id = conn.execute(
            """
            INSERT INTO board
              (bizbox_board_no, name, slug, board_class, included,
               use_mecab_parallel, default_chunk_strategy, required_role)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (bizbox_board_no) DO UPDATE SET
              name = EXCLUDED.name,
              slug = EXCLUDED.slug,
              board_class = EXCLUDED.board_class,
              included = EXCLUDED.included,
              use_mecab_parallel = EXCLUDED.use_mecab_parallel,
              default_chunk_strategy = EXCLUDED.default_chunk_strategy,
              required_role = EXCLUDED.required_role,
              updated_at = now()
            RETURNING board_id
            """,
            (
                b.bizbox_board_no, b.name, b.slug, b.board_class, b.included,
                b.use_mecab_parallel, b.default_chunk_strategy, b.required_role,
            ),
        ).fetchone()[0]
        mapping[b.bizbox_board_no] = board_id
        conn.execute(
            "INSERT INTO ingest_state (board_id) VALUES (%s) "
            "ON CONFLICT (board_id) DO NOTHING",
            (board_id,),
        )
    return mapping


# ── post / attachment ────────────────────────────────────────────────────────


def upsert_post(conn: Connection, raw: RawPost, board_id: int) -> int:
    """글 1건 upsert. ``(board_id, bizbox_art_no)`` 일반 unique 로 멱등.

    content_hash 가 동일하면 DO UPDATE 의 ``WHERE`` 술어가 거짓 → **갱신 없음(no-op)**,
    이 때 RETURNING 이 비므로 SELECT 로 기존 post_id 를 돌려준다(불필요 rewrite 회피).
    """
    row = conn.execute(
        """
        INSERT INTO post
          (board_id, bizbox_art_no, title, body_html, body_text, doc_type,
           author_name, author_dept, posted_at, view_count, source_url, content_hash)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (board_id, bizbox_art_no) DO UPDATE SET
          title = EXCLUDED.title,
          body_html = EXCLUDED.body_html,
          body_text = EXCLUDED.body_text,
          doc_type = EXCLUDED.doc_type,
          author_name = EXCLUDED.author_name,
          author_dept = EXCLUDED.author_dept,
          posted_at = EXCLUDED.posted_at,
          view_count = EXCLUDED.view_count,
          source_url = EXCLUDED.source_url,
          content_hash = EXCLUDED.content_hash,
          crawled_at = now()
        WHERE post.content_hash IS DISTINCT FROM EXCLUDED.content_hash
        RETURNING post_id
        """,
        (
            board_id, raw.art_no, raw.title, raw.body_html, raw.body_text, raw.doc_type,
            raw.author_name, raw.author_dept, raw.posted_at, raw.view_count,
            raw.source_url, raw.content_hash,
        ),
    ).fetchone()
    if row is not None:
        return row[0]
    return conn.execute(
        "SELECT post_id FROM post WHERE board_id = %s AND bizbox_art_no = %s",
        (board_id, raw.art_no),
    ).fetchone()[0]


def upsert_attachments(
    conn: Connection, post_id: int, atts: Sequence[RawAttachment]
) -> list[int]:
    """첨부 적재(자연키 부재 → 애플리케이션 dedup). plan §3·§4.

    dedup: ``(post_id, bizbox_file_seq)`` 존재검사 → 없으면 sha256 보조 검사 → 둘 다 없을 때만
    INSERT. storage_path 는 NOT NULL 이라 결정론 경로를 합성(실제 파일 저장은 추출 단계 책임).

    Returns:
        입력 순서에 대응하는 attachment_id 리스트(기존/신규 모두 포함).
    """
    ids: list[int] = []
    for att in atts:
        existing: int | None = None
        if att.bizbox_file_seq is not None:
            r = conn.execute(
                "SELECT attachment_id FROM attachment "
                "WHERE post_id = %s AND bizbox_file_seq = %s",
                (post_id, att.bizbox_file_seq),
            ).fetchone()
            existing = r[0] if r else None
        if existing is None and att.sha256:
            r = conn.execute(
                "SELECT attachment_id FROM attachment WHERE post_id = %s AND sha256 = %s",
                (post_id, att.sha256),
            ).fetchone()
            existing = r[0] if r else None
        if existing is not None:
            ids.append(existing)
            continue
        storage_path = f"bizbox/{post_id}/{att.bizbox_file_seq or 0}/{att.file_name}"
        aid = conn.execute(
            """
            INSERT INTO attachment
              (post_id, file_name, mime_type, kind, storage_path, download_url,
               bizbox_file_seq, byte_size, sha256)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING attachment_id
            """,
            (
                post_id, att.file_name, att.mime_type, att.kind, storage_path,
                att.download_url, att.bizbox_file_seq, att.byte_size, att.sha256,
            ),
        ).fetchone()[0]
        ids.append(aid)
    return ids


# ── regulation (★ 멱등 사슬 ②) ───────────────────────────────────────────────


def upsert_regulation(
    conn: Connection, reg: ParsedRegulation, board_id: int, source_post_id: int | None
) -> int:
    """규정 upsert — ``source_post_id`` 기준 SELECT-then-upsert 로 regulation_id 보존.

    reg_code 가 NULL 이면 partial-unique 가 미발화하므로 ON CONFLICT 에 의존할 수 없다.
    post 가 이미 멱등하므로 source_post_id 가 재실행 간 안정적 → 현행(is_current) 규정이 있으면
    그 regulation_id 를 재사용·UPDATE, 없으면 INSERT 한다(plan §4 major #1·#2).

    적재 규정은 ``curated=false``(ADR-003 미검증). 재적재 UPDATE 는 curated 를 건드리지 않아
    사람이 매긴 검수 플래그를 보존한다.
    """
    existing = None
    if source_post_id is not None:
        existing = conn.execute(
            "SELECT regulation_id FROM regulation "
            "WHERE source_post_id = %s AND is_current ORDER BY regulation_id LIMIT 1",
            (source_post_id,),
        ).fetchone()
    if existing is not None:
        rid = existing[0]
        conn.execute(
            """
            UPDATE regulation SET
              board_id = %s, reg_code = %s, title = %s, category = %s, reg_type = %s,
              effective_date = %s, revision_no = %s, enacted_date = %s
            WHERE regulation_id = %s
            """,
            (
                board_id, reg.reg_code, reg.title, reg.category, reg.reg_type,
                reg.effective_date, reg.revision_no, reg.enacted_date, rid,
            ),
        )
        return rid
    return conn.execute(
        """
        INSERT INTO regulation
          (source_post_id, board_id, reg_code, title, category, reg_type,
           effective_date, revision_no, enacted_date, curated)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, false)
        RETURNING regulation_id
        """,
        (
            source_post_id, board_id, reg.reg_code, reg.title, reg.category, reg.reg_type,
            reg.effective_date, reg.revision_no, reg.enacted_date,
        ),
    ).fetchone()[0]


# ── clause / authority (canonical partial-unique upsert) ─────────────────────


def upsert_clauses(
    conn: Connection, regulation_id: int, clauses: Sequence[ParsedClause]
) -> None:
    """조/항/호/목 upsert. canonical_clause_id partial-unique(``WHERE is_current``) 기준.

    parent_canonical_id → parent_clause_id 해소: 부모는 order_seq 상 자식보다 먼저 오므로
    적재하며 canonical→clause_id 맵을 쌓아 해소한다(이전 실행분은 미리 로드).
    """
    canon_to_id: dict[str, int] = {
        row[0]: row[1]
        for row in conn.execute(
            "SELECT canonical_clause_id, clause_id FROM clause "
            "WHERE regulation_id = %s AND is_current",
            (regulation_id,),
        ).fetchall()
    }
    for cl in clauses:
        parent_id = (
            canon_to_id.get(cl.parent_canonical_id)
            if cl.parent_canonical_id is not None
            else None
        )
        clause_id = conn.execute(
            """
            INSERT INTO clause
              (regulation_id, canonical_clause_id, article_no, article_branch, paragraph_no,
               item_no, sub_item_label, clause_label, clause_title, text, parent_clause_id,
               depth, effective_date, order_seq)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (canonical_clause_id) WHERE is_current DO UPDATE SET
              regulation_id = EXCLUDED.regulation_id,
              article_no = EXCLUDED.article_no,
              article_branch = EXCLUDED.article_branch,
              paragraph_no = EXCLUDED.paragraph_no,
              item_no = EXCLUDED.item_no,
              sub_item_label = EXCLUDED.sub_item_label,
              clause_label = EXCLUDED.clause_label,
              clause_title = EXCLUDED.clause_title,
              text = EXCLUDED.text,
              parent_clause_id = EXCLUDED.parent_clause_id,
              depth = EXCLUDED.depth,
              effective_date = EXCLUDED.effective_date,
              order_seq = EXCLUDED.order_seq
            RETURNING clause_id
            """,
            (
                regulation_id, cl.canonical_clause_id, cl.article_no, cl.article_branch,
                cl.paragraph_no, cl.item_no, cl.sub_item_label, cl.clause_label,
                cl.clause_title, cl.text, parent_id, cl.depth, cl.effective_date, cl.order_seq,
            ),
        ).fetchone()[0]
        canon_to_id[cl.canonical_clause_id] = clause_id


def upsert_authority(
    conn: Connection, regulation_id: int, cells: Sequence[ParsedAuthority]
) -> None:
    """전결표 셀 upsert. canonical_authority_id partial-unique 기준.

    amount_min/amount_max 만 적재 — amount_band 는 DB 생성열(int8range '[]')이 채운다.
    consulter_roles(tuple)은 text[] 로 적재(빈 값은 NULL).
    """
    for c in cells:
        consulter = list(c.consulter_roles) if c.consulter_roles else None
        conn.execute(
            """
            INSERT INTO authority_matrix
              (regulation_id, canonical_authority_id, business_category, business_item,
               action_type, approver_role, consulter_roles, amount_min, amount_max,
               currency, condition_note, matrix_row_label, matrix_col_label,
               effective_date, order_seq)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (canonical_authority_id) WHERE is_current DO UPDATE SET
              regulation_id = EXCLUDED.regulation_id,
              business_category = EXCLUDED.business_category,
              business_item = EXCLUDED.business_item,
              action_type = EXCLUDED.action_type,
              approver_role = EXCLUDED.approver_role,
              consulter_roles = EXCLUDED.consulter_roles,
              amount_min = EXCLUDED.amount_min,
              amount_max = EXCLUDED.amount_max,
              currency = EXCLUDED.currency,
              condition_note = EXCLUDED.condition_note,
              matrix_row_label = EXCLUDED.matrix_row_label,
              matrix_col_label = EXCLUDED.matrix_col_label,
              effective_date = EXCLUDED.effective_date,
              order_seq = EXCLUDED.order_seq
            """,
            (
                regulation_id, c.canonical_authority_id, c.business_category, c.business_item,
                c.action_type, c.approver_role, consulter, c.amount_min, c.amount_max,
                c.currency, c.condition_note, c.matrix_row_label, c.matrix_col_label,
                c.effective_date, c.order_seq,
            ),
        )


# ── ingest_state 워터마크 ─────────────────────────────────────────────────────


def advance_ingest_state(
    conn: Connection,
    board_id: int,
    last_art_no: int | None,
    last_posted_at: datetime | None,
    counts: IngestCounts,
) -> None:
    """보드 워터마크 전진 + 집계 갱신 (plan §4).

    ``GREATEST`` 가드로 last_art_no/last_posted_at 후퇴를 방지한다(GREATEST 는 NULL 을 건너뛰어
    최초 시드 행의 NULL 워터마크도 안전). total_posts/attachments 는 실행분 누적. 실패 0 건이면
    last_success_at 도 전진. ingest_state 행이 없으면(미시드) INSERT 로 생성.
    """
    conn.execute(
        """
        INSERT INTO ingest_state
          (board_id, last_art_no, last_posted_at, total_posts, total_attachments,
           status, health, last_run_at, last_success_at)
        VALUES (%s, %s, %s, %s, %s, 'idle', 'healthy', now(),
                CASE WHEN %s = 0 THEN now() ELSE NULL END)
        ON CONFLICT (board_id) DO UPDATE SET
          last_art_no = GREATEST(ingest_state.last_art_no, EXCLUDED.last_art_no),
          last_posted_at = GREATEST(ingest_state.last_posted_at, EXCLUDED.last_posted_at),
          total_posts = ingest_state.total_posts + EXCLUDED.total_posts,
          total_attachments = ingest_state.total_attachments + EXCLUDED.total_attachments,
          last_run_at = now(),
          last_success_at = CASE WHEN %s = 0 THEN now()
                                 ELSE ingest_state.last_success_at END
        """,
        (
            board_id, last_art_no, last_posted_at, counts.posts, counts.attachments,
            counts.failures, counts.failures,
        ),
    )


# ── 개정 버전교체 전용 (일반 upsert 와 분리, plan §3·§4 major #3) ─────────────
#
# 공통 패턴: ① 구행 ``is_current=false`` UPDATE(down) → ② 신행 **순수 INSERT(ON CONFLICT
# 없음)** → ③ supersedes_*_id 연결. 단일 트랜잭션(savepoint). 구행을 먼저 내려 partial-unique
# (``WHERE is_current``) 충돌이 없으므로 ON CONFLICT 가 불필요하다 — 일반 헬퍼가 무조건 붙이는
# ON CONFLICT 덮어쓰기와 의도가 달라 경로를 분리한다.


def supersede_regulation(
    conn: Connection,
    *,
    old_regulation_id: int,
    new_reg: ParsedRegulation,
    board_id: int,
    source_post_id: int | None,
) -> int:
    """규정 버전교체: 구 규정 down(+abolished_date) → 신 규정 순수 INSERT + supersedes 연결."""
    with conn.transaction():
        conn.execute(
            "UPDATE regulation SET is_current = false, abolished_date = CURRENT_DATE "
            "WHERE regulation_id = %s",
            (old_regulation_id,),
        )
        return conn.execute(
            """
            INSERT INTO regulation
              (source_post_id, board_id, reg_code, title, category, reg_type,
               effective_date, revision_no, enacted_date, is_current,
               supersedes_regulation_id, curated)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, true, %s, false)
            RETURNING regulation_id
            """,
            (
                source_post_id, board_id, new_reg.reg_code, new_reg.title, new_reg.category,
                new_reg.reg_type, new_reg.effective_date, new_reg.revision_no,
                new_reg.enacted_date, old_regulation_id,
            ),
        ).fetchone()[0]


def supersede_clause(
    conn: Connection,
    *,
    old_clause_id: int,
    new_clause: ParsedClause,
    regulation_id: int,
) -> int:
    """조항 버전교체: 구 조항 down(+amended_at) → 신 조항 순수 INSERT + supersedes 연결.

    같은 canonical_clause_id 를 유지하므로 구행을 먼저 내려야 partial-unique 충돌이 없다.
    parent_canonical_id 는 동 규정의 현행 조항에서 parent_clause_id 로 해소.
    """
    with conn.transaction():
        conn.execute(
            "UPDATE clause SET is_current = false, amended_at = now() WHERE clause_id = %s",
            (old_clause_id,),
        )
        parent_id: int | None = None
        if new_clause.parent_canonical_id is not None:
            r = conn.execute(
                "SELECT clause_id FROM clause "
                "WHERE regulation_id = %s AND canonical_clause_id = %s AND is_current",
                (regulation_id, new_clause.parent_canonical_id),
            ).fetchone()
            parent_id = r[0] if r else None
        return conn.execute(
            """
            INSERT INTO clause
              (regulation_id, canonical_clause_id, article_no, article_branch, paragraph_no,
               item_no, sub_item_label, clause_label, clause_title, text, parent_clause_id,
               depth, effective_date, is_current, supersedes_clause_id, order_seq)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, true, %s, %s)
            RETURNING clause_id
            """,
            (
                regulation_id, new_clause.canonical_clause_id, new_clause.article_no,
                new_clause.article_branch, new_clause.paragraph_no, new_clause.item_no,
                new_clause.sub_item_label, new_clause.clause_label, new_clause.clause_title,
                new_clause.text, parent_id, new_clause.depth, new_clause.effective_date,
                old_clause_id, new_clause.order_seq,
            ),
        ).fetchone()[0]


def supersede_authority(
    conn: Connection,
    *,
    old_authority_id: int,
    new_cell: ParsedAuthority,
    regulation_id: int,
) -> int:
    """전결 셀 버전교체: 구 셀 down → 신 셀 순수 INSERT.

    authority_matrix 는 supersedes 링크 컬럼이 스키마에 없어 is_current 토글로만 버전을
    표현한다(이력은 비현행 행으로 보존). amount_band 는 생성열이라 amount_min/max 만 적재.
    """
    with conn.transaction():
        conn.execute(
            "UPDATE authority_matrix SET is_current = false WHERE authority_id = %s",
            (old_authority_id,),
        )
        consulter = list(new_cell.consulter_roles) if new_cell.consulter_roles else None
        return conn.execute(
            """
            INSERT INTO authority_matrix
              (regulation_id, canonical_authority_id, business_category, business_item,
               action_type, approver_role, consulter_roles, amount_min, amount_max,
               currency, condition_note, matrix_row_label, matrix_col_label,
               effective_date, is_current, order_seq)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, true, %s)
            RETURNING authority_id
            """,
            (
                regulation_id, new_cell.canonical_authority_id, new_cell.business_category,
                new_cell.business_item, new_cell.action_type, new_cell.approver_role, consulter,
                new_cell.amount_min, new_cell.amount_max, new_cell.currency,
                new_cell.condition_note, new_cell.matrix_row_label, new_cell.matrix_col_label,
                new_cell.effective_date, new_cell.order_seq,
            ),
        ).fetchone()[0]


# ── chunk 빌드 (검색 인덱스 단위) ────────────────────────────────────────────


def rebuild_post_chunks(conn: Connection, post_id: int) -> int:
    """글 1건의 검색 chunk 재생성(멱등) — ★ 인제스트(A)↔검색(B) 연결고리.

    검색(``query_builder``)은 ``FROM chunk`` 로만 조회하므로, 적재된 clause/본문이
    chunk 로 들어가야 검색에 노출된다. 글 단위로:
      ① 이 글에서 파생된 기존 chunk 전부 삭제(재크롤 멱등)
      ② 규정 조항(clause) → ``chunk_class='clause'`` (canonical_clause_id 보존 → 정밀 인용)
      ③ 글 제목+본문(post.title + body_text) → ``chunk_class='notice_section'`` (조항 없는
         공지/일반보드 폴백). 제목을 prepend 하는 이유: 마감공지·사업자등록증처럼 핵심어가
         제목에만 있고 본문엔 없는 글이 많아, 본문만 인덱싱하면 '6월 마감공지' 같은 질의에서
         누락된다(제목 토큰도 검색 대상이 되도록 합본).
    tokenized(mecab)는 1차 NULL — body PGroonga(N-gram) 인덱스만으로 한국어 FTS 동작.

    Returns: 생성된 chunk 수.
    """
    conn.execute(
        """
        DELETE FROM chunk WHERE source_post_id = %(pid)s
          OR clause_id IN (
            SELECT c.clause_id FROM clause c
            JOIN regulation r ON r.regulation_id = c.regulation_id
            WHERE r.source_post_id = %(pid)s)
        """,
        {"pid": post_id},
    )
    conn.execute(
        """
        INSERT INTO chunk (chunk_class, board_id, clause_id, body, canonical_clause_id,
                           clause_label, seq_in_source, posted_at, is_current, char_len)
        SELECT 'clause', r.board_id, c.clause_id, c.text, c.canonical_clause_id,
               c.clause_label, c.order_seq, p.posted_at, c.is_current, length(c.text)
        FROM clause c
        JOIN regulation r ON r.regulation_id = c.regulation_id
        JOIN post p ON p.post_id = r.source_post_id
        WHERE r.source_post_id = %(pid)s AND c.is_current
        """,
        {"pid": post_id},
    )
    conn.execute(
        """
        INSERT INTO chunk (chunk_class, board_id, source_post_id, body,
                           seq_in_source, posted_at, is_current, char_len)
        SELECT 'notice_section', board_id, post_id,
               COALESCE(title || E'\n', '') || body_text, 0, posted_at, is_current,
               length(COALESCE(title || E'\n', '') || body_text)
        FROM post
        WHERE post_id = %(pid)s AND body_text IS NOT NULL AND length(btrim(body_text)) > 0
        """,
        {"pid": post_id},
    )
    row = conn.execute(
        """
        SELECT count(*) FROM chunk WHERE source_post_id = %(pid)s
          OR clause_id IN (SELECT c.clause_id FROM clause c
              JOIN regulation r ON r.regulation_id = c.regulation_id
              WHERE r.source_post_id = %(pid)s)
        """,
        {"pid": post_id},
    ).fetchone()
    return int(row[0]) if row else 0
