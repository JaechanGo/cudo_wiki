"""통합테스트 공용 시드 헬퍼 (plan §9.2).

실데이터 부재(A 병렬) → FK 순서(board → post/regulation → clause/authority → chunk → glossary →
eval)로 최소행 insert. B 자체검증용이며 chunk 등은 평소 read-only(시드만 예외, D-08).
"""

from __future__ import annotations

from dataclasses import dataclass

CLAUSE_CANONICAL = "REG-인사-제15조"
AUTHORITY_CANONICAL = "AUTH-구매-001"


@dataclass
class SeedIds:
    """시드가 만든 핵심 행 id."""

    reg_board: int
    notice_board: int
    auth_board: int
    notice_post: int
    regulation: int
    clause: int
    auth_regulation: int
    authority: int
    clause_chunk: int
    notice_chunk: int
    auth_chunk: int


async def _scalar(conn, sql: str, params: tuple = ()) -> int:
    """RETURNING 단일 컬럼 정수 반환."""
    cur = await conn.execute(sql, params)
    row = await cur.fetchone()
    return row[0]


async def seed_minimal(conn) -> SeedIds:
    """규정 조항·전결표·공지·동의어 최소 코퍼스를 시드한다(같은 트랜잭션 내 가시)."""
    reg_board = await _scalar(
        conn,
        "INSERT INTO board (bizbox_board_no,name,slug,board_class,"
        "default_chunk_strategy,use_mecab_parallel) "
        "VALUES (8001,'규정','seed-reg','regulation','article',true) RETURNING board_id",
    )
    notice_board = await _scalar(
        conn,
        "INSERT INTO board (bizbox_board_no,name,slug,board_class,default_chunk_strategy) "
        "VALUES (8002,'공지','seed-notice','notice','whole') RETURNING board_id",
    )
    auth_board = await _scalar(
        conn,
        "INSERT INTO board (bizbox_board_no,name,slug,board_class,default_chunk_strategy) "
        "VALUES (8003,'전결','seed-auth','authority','authority_cell') RETURNING board_id",
    )

    notice_post = await _scalar(
        conn,
        "INSERT INTO post (board_id,bizbox_art_no,title,doc_type) "
        "VALUES (%s,1,'연차 사용 안내','notice') RETURNING post_id",
        (notice_board,),
    )

    regulation = await _scalar(
        conn,
        "INSERT INTO regulation (board_id,title,reg_type) "
        "VALUES (%s,'인사규정','규정') RETURNING regulation_id",
        (reg_board,),
    )
    clause = await _scalar(
        conn,
        "INSERT INTO clause (regulation_id,canonical_clause_id,clause_label,text,"
        "depth,order_seq) VALUES (%s,%s,'제15조',"
        "'직원은 매년 연차휴가를 사용할 수 있다','article',1) RETURNING clause_id",
        (regulation, CLAUSE_CANONICAL),
    )

    auth_regulation = await _scalar(
        conn,
        "INSERT INTO regulation (board_id,title,reg_type) "
        "VALUES (%s,'전결규정','전결규정') RETURNING regulation_id",
        (auth_board,),
    )
    authority = await _scalar(
        conn,
        "INSERT INTO authority_matrix (regulation_id,canonical_authority_id,business_item,"
        "action_type,approver_role,amount_min,amount_max,order_seq) "
        "VALUES (%s,%s,'구매','전결','팀장',1000000,5000000,1) RETURNING authority_id",
        (auth_regulation, AUTHORITY_CANONICAL),
    )

    clause_chunk = await _scalar(
        conn,
        "INSERT INTO chunk (chunk_class,board_id,clause_id,seq_in_source,body,"
        "canonical_clause_id,clause_label) VALUES ('clause',%s,%s,0,"
        "'직원은 매년 연차휴가를 사용할 수 있다',%s,'제15조') RETURNING chunk_id",
        (reg_board, clause, CLAUSE_CANONICAL),
    )
    notice_chunk = await _scalar(
        conn,
        "INSERT INTO chunk (chunk_class,board_id,source_post_id,seq_in_source,body) "
        "VALUES ('notice_section',%s,%s,0,'연차휴가는 연 15일 부여된다') RETURNING chunk_id",
        (notice_board, notice_post),
    )
    auth_chunk = await _scalar(
        conn,
        "INSERT INTO chunk (chunk_class,board_id,authority_id,seq_in_source,body) "
        "VALUES ('authority_cell',%s,%s,0,'구매 300만원 전결 팀장') RETURNING chunk_id",
        (auth_board, authority),
    )

    await conn.execute(
        "INSERT INTO glossary_synonym (headword,synonyms,register) "
        "VALUES ('연차', ARRAY['연차','연차휴가','annual leave'], 'official')"
    )

    return SeedIds(
        reg_board=reg_board, notice_board=notice_board, auth_board=auth_board,
        notice_post=notice_post, regulation=regulation, clause=clause,
        auth_regulation=auth_regulation, authority=authority,
        clause_chunk=clause_chunk, notice_chunk=notice_chunk, auth_chunk=auth_chunk,
    )


async def seed_golden_set(conn, ids: SeedIds) -> None:
    """평가 하네스용 골든셋(clause/authority/abstain 3건)을 시드한다."""
    # 질의 "연차" → query_expand(OR 확장)로 clause 본문("…연차휴가…") 매칭. &@~ 의 공백은 AND
    # 이므로 본문에 없는 단어를 더하면 과거절 → 동의어 확장이 작동하는 단일 headword 사용.
    eq_clause = await _scalar(
        conn,
        "INSERT INTO eval_query (query_text,answer_type,should_abstain,eval_set) "
        "VALUES ('연차','clause',false,'seed') RETURNING eval_query_id",
    )
    await conn.execute(
        "INSERT INTO eval_gold (eval_query_id,target_kind,clause_id,"
        "expected_canonical_id,relevance) VALUES (%s,'clause',%s,%s,3)",
        (eq_clause, ids.clause, CLAUSE_CANONICAL),
    )

    eq_auth = await _scalar(
        conn,
        "INSERT INTO eval_query (query_text,answer_type,should_abstain,eval_set) "
        "VALUES ('300만원 결재라인','authority',false,'seed') RETURNING eval_query_id",
    )
    await conn.execute(
        "INSERT INTO eval_gold (eval_query_id,target_kind,authority_id,"
        "expected_canonical_id,relevance) VALUES (%s,'authority',%s,%s,3)",
        (eq_auth, ids.authority, AUTHORITY_CANONICAL),
    )

    await conn.execute(
        "INSERT INTO eval_query (query_text,answer_type,should_abstain,eval_set) "
        "VALUES ('존재하지않는규정XYZ','abstain',true,'seed')"
    )
