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


# ── Task009 C 도구 통합테스트용 확장 시드 (plan §8) ───────────────────────

# PII 를 포함한 본문/추출/condition_note (레닥션 검증용).
PII_CLAUSE_TEXT = "징계 시 환급 계좌 110-123-456789 로 입금하며 이메일 hr@cudo.co.kr 로 통지한다"
PII_ATTACH_TEXT = "급여계좌 301-1234-5678-91, 담당 hong@cudo.co.kr 시행일 2024-01-01"
PII_CONDITION = "단, 계좌 123456-78-901234 확인 후 집행"


@dataclass
class ToolSeedIds:
    """C 도구 테스트 시드 id."""

    reg_board: int
    curated_post: int
    curated_reg: int
    pii_clause: int
    text_attachment: int
    curated_image_attachment: int
    plain_post: int
    noncurated_image_attachment: int
    authority_reg: int
    authority_with_condition: int


async def seed_tools_corpus(conn) -> ToolSeedIds:
    """C 도구(검색/규정/첨부/전결/보드)용 코퍼스 — PII·큐레이션·첨부 포함."""
    reg_board = await _scalar(
        conn,
        "INSERT INTO board (bizbox_board_no,name,slug,board_class,"
        "default_chunk_strategy,use_mecab_parallel) "
        "VALUES (8101,'인사규정','tool-reg','regulation','article',true) RETURNING board_id",
    )

    # 큐레이션된 규정 + 원천 post (image 게이트 조건 1).
    curated_post = await _scalar(
        conn,
        "INSERT INTO post (board_id,bizbox_art_no,title,doc_type,source_url) "
        "VALUES (%s,101,'인사규정 개정 공고','regulation','http://gw/post/101') "
        "RETURNING post_id",
        (reg_board,),
    )
    curated_reg = await _scalar(
        conn,
        "INSERT INTO regulation (board_id,source_post_id,reg_code,title,reg_type,"
        "effective_date,revision_no,curated,curated_by,curated_at) "
        "VALUES (%s,%s,'REG-인사-001','인사규정','규정','2024-03-01',3,true,'admin',now()) "
        "RETURNING regulation_id",
        (reg_board, curated_post),
    )
    pii_clause = await _scalar(
        conn,
        "INSERT INTO clause (regulation_id,canonical_clause_id,clause_label,clause_title,"
        "text,depth,order_seq,is_current) "
        "VALUES (%s,'REG-인사-제15조','제15조','징계 환급',%s,'article',1,true) "
        "RETURNING clause_id",
        (curated_reg, PII_CLAUSE_TEXT),
    )
    await conn.execute(
        "INSERT INTO clause (regulation_id,canonical_clause_id,clause_label,clause_title,"
        "text,depth,order_seq,is_current) "
        "VALUES (%s,'REG-인사-제16조','제16조','부칙','이 규정은 공포일부터 시행한다',"
        "'article',2,true)",
        (curated_reg,),
    )

    # 검색용 chunk. 소규모 코퍼스에서 PGroonga 인덱스 스캔이 안정적으로 선택되도록 seed_minimal 처럼
    # 여러 chunk 를 시드(단일 행이면 planner 가 seqscan→score 0 으로 빠질 수 있음).
    await conn.execute(
        "INSERT INTO chunk (chunk_class,board_id,clause_id,seq_in_source,body,"
        "canonical_clause_id,clause_label) VALUES ('clause',%s,%s,0,%s,"
        "'REG-인사-제15조','제15조')",
        (reg_board, pii_clause, PII_CLAUSE_TEXT),
    )
    await conn.execute(
        "INSERT INTO chunk (chunk_class,board_id,clause_id,seq_in_source,body,"
        "canonical_clause_id,clause_label) "
        "SELECT 'clause',%s,clause_id,1,'이 규정은 공포일부터 시행한다',"
        "'REG-인사-제16조','제16조' FROM clause "
        "WHERE regulation_id=%s AND canonical_clause_id='REG-인사-제16조'",
        (reg_board, curated_reg),
    )
    await conn.execute(
        "INSERT INTO chunk (chunk_class,board_id,source_post_id,seq_in_source,body) "
        "VALUES ('notice_section',%s,%s,0,'스캔 공지 본문입니다')",
        (reg_board, curated_post),
    )
    await conn.execute(
        "INSERT INTO glossary_synonym (headword,synonyms,register) "
        "VALUES ('징계', ARRAY['징계','환급'], 'official')"
    )

    # text 첨부(hwp) — extracted_text 레닥션 검증.
    text_attachment = await _scalar(
        conn,
        "INSERT INTO attachment (post_id,file_name,mime_type,kind,storage_path,"
        "download_url,extracted_text,ocr_status,byte_size) "
        "VALUES (%s,'인사규정.hwp','application/x-hwp','hwp','/data/a/101.hwp',"
        "'http://gw/file/101',%s,'done',20480) RETURNING attachment_id",
        (curated_post, PII_ATTACH_TEXT),
    )
    # image 첨부(큐레이션 post 소속이나 v1 볼륨 미마운트 → 링크 폴백).
    curated_image_attachment = await _scalar(
        conn,
        "INSERT INTO attachment (post_id,file_name,mime_type,kind,storage_path,"
        "download_url,is_table,ocr_status,byte_size) "
        "VALUES (%s,'전결표.png','image/png','image','/data/a/101_p1.png',"
        "'http://gw/file/102',true,'done',102400) RETURNING attachment_id",
        (curated_post,),
    )
    await conn.execute(
        "INSERT INTO attachment_page (attachment_id,page_no,image_path,ocr_text) "
        "VALUES (%s,1,'/data/a/101_p1.png','스캔 표 OCR 텍스트 계좌 110-123-456789')",
        (curated_image_attachment,),
    )

    # 비큐레이션 post + image 첨부(링크 폴백 + 경고).
    plain_post = await _scalar(
        conn,
        "INSERT INTO post (board_id,bizbox_art_no,title,doc_type,source_url) "
        "VALUES (%s,102,'스캔 공지','notice','http://gw/post/102') RETURNING post_id",
        (reg_board,),
    )
    noncurated_image_attachment = await _scalar(
        conn,
        "INSERT INTO attachment (post_id,file_name,mime_type,kind,storage_path,"
        "download_url,ocr_status,byte_size) "
        "VALUES (%s,'스캔.png','image/png','image','/data/a/102_p1.png',"
        "'http://gw/file/201','done',51200) RETURNING attachment_id",
        (plain_post,),
    )

    # 전결규정 + condition_note(PII 포함) — M-2 보강 검증.
    authority_reg = await _scalar(
        conn,
        "INSERT INTO regulation (board_id,title,reg_type) "
        "VALUES (%s,'전결규정','전결규정') RETURNING regulation_id",
        (reg_board,),
    )
    authority_with_condition = await _scalar(
        conn,
        "INSERT INTO authority_matrix (regulation_id,canonical_authority_id,business_item,"
        "action_type,approver_role,consulter_roles,amount_min,amount_max,condition_note,"
        "order_seq) VALUES (%s,'AUTH-구매-010','비품 구매','전결','팀장',"
        "ARRAY['총무팀'],1000000,5000000,%s,1) RETURNING authority_id",
        (authority_reg, PII_CONDITION),
    )
    await conn.execute(
        "INSERT INTO chunk (chunk_class,board_id,authority_id,seq_in_source,body) "
        "VALUES ('authority_cell',%s,%s,0,'비품 구매 전결 팀장')",
        (reg_board, authority_with_condition),
    )

    # ★ 검색 결정성: board 필터가 붙으면 planner 가 btree(idx_chunk_is_current)를 택하고
    # pgroonga &@~ 를 Filter 로만 적용 → pgroonga_score=0 → 과거절. 운영 대형코퍼스처럼 pgroonga
    # 인덱스가 선택되도록 무관 filler chunk 다수 + ANALYZE 로 통계를 채워 plan 을 유도(테스트 한정).
    await conn.execute(
        "INSERT INTO chunk (chunk_class,board_id,source_post_id,seq_in_source,body) "
        "SELECT 'notice_section',%s,%s,g,'무관 공지 본문 '||g "
        "FROM generate_series(1,40) AS g",
        (reg_board, plain_post),
    )
    await conn.execute("ANALYZE chunk")

    return ToolSeedIds(
        reg_board=reg_board,
        curated_post=curated_post,
        curated_reg=curated_reg,
        pii_clause=pii_clause,
        text_attachment=text_attachment,
        curated_image_attachment=curated_image_attachment,
        plain_post=plain_post,
        noncurated_image_attachment=noncurated_image_attachment,
        authority_reg=authority_reg,
        authority_with_condition=authority_with_condition,
    )
