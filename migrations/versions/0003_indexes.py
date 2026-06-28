"""0003 indexes — PGroonga(N-gram/TokenDelimit/동의어) · btree · GiST · GIN · 부분 unique.

erd description 인덱스 전략 전수 반영 (plan §4.5/§4.7). 테이블·확장(0001/0002) 선행 가정.
- N-gram 본문(전 보드 재현율): tokenizer=TokenNgram, normalizer=NormalizerNFKC150,
  ops=pgroonga_text_full_text_search_ops_v2 (&@~ 질의).
- mecab 병렬(방식 A): chunk.tokenized TokenDelimit. 방식 B(clause.text TokenMecab)는 R0 미채택
  (이미지 mecab 의존) → clause.text 는 ngram 인덱스만 [R2].
- 동의어 질의확장: glossary_synonym headword/synonyms term/array ops (pgroonga_query_expand 지원).
- 조항ID 정확필드: btree(=). 범위/배열/jsonb: GiST/GIN.
- 부분 unique(현행 1행): clause/authority_matrix/regulation WHERE is_current.

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NGRAM = "WITH (tokenizer='TokenNgram', normalizer='NormalizerNFKC150')"

# 멱등 보장 + downgrade 전수 제거를 위해 인덱스명을 명시. (이름, DDL) 리스트.
_INDEXES: list[tuple[str, str]] = [
    # ── [N-gram 본문 FTS — 전 보드 재현율] ────────────────────────────────
    (
        "idx_chunk_body_pgroonga",
        f"CREATE INDEX idx_chunk_body_pgroonga ON chunk "
        f"USING pgroonga (body pgroonga_text_full_text_search_ops_v2) {_NGRAM};",
    ),
    (
        # 기본 현행만 검색 — WHERE is_current 부분 인덱스 병용.
        "idx_chunk_body_current_pgroonga",
        f"CREATE INDEX idx_chunk_body_current_pgroonga ON chunk "
        f"USING pgroonga (body pgroonga_text_full_text_search_ops_v2) {_NGRAM} "
        f"WHERE is_current;",
    ),
    (
        "idx_post_title_pgroonga",
        f"CREATE INDEX idx_post_title_pgroonga ON post "
        f"USING pgroonga (title pgroonga_text_full_text_search_ops_v2) {_NGRAM};",
    ),
    (
        "idx_post_body_text_pgroonga",
        f"CREATE INDEX idx_post_body_text_pgroonga ON post "
        f"USING pgroonga (body_text pgroonga_text_full_text_search_ops_v2) {_NGRAM};",
    ),
    (
        "idx_attachment_extracted_text_pgroonga",
        f"CREATE INDEX idx_attachment_extracted_text_pgroonga ON attachment "
        f"USING pgroonga (extracted_text pgroonga_text_full_text_search_ops_v2) {_NGRAM};",
    ),
    (
        "idx_attachment_page_ocr_text_pgroonga",
        f"CREATE INDEX idx_attachment_page_ocr_text_pgroonga ON attachment_page "
        f"USING pgroonga (ocr_text pgroonga_text_full_text_search_ops_v2) {_NGRAM};",
    ),
    (
        "idx_regulation_title_pgroonga",
        f"CREATE INDEX idx_regulation_title_pgroonga ON regulation "
        f"USING pgroonga (title pgroonga_text_full_text_search_ops_v2) {_NGRAM};",
    ),
    (
        "idx_authority_business_item_pgroonga",
        f"CREATE INDEX idx_authority_business_item_pgroonga ON authority_matrix "
        f"USING pgroonga (business_item pgroonga_text_full_text_search_ops_v2) {_NGRAM};",
    ),
    (
        # clause.text — R0 는 ngram 만(방식 B TokenMecab 미채택) [R2].
        "idx_clause_text_pgroonga",
        f"CREATE INDEX idx_clause_text_pgroonga ON clause "
        f"USING pgroonga (text pgroonga_text_full_text_search_ops_v2) {_NGRAM};",
    ),
    # ── [mecab 병렬 — 방식 A: chunk.tokenized TokenDelimit] ────────────────
    (
        "idx_chunk_tokenized_pgroonga",
        "CREATE INDEX idx_chunk_tokenized_pgroonga ON chunk "
        "USING pgroonga (tokenized pgroonga_text_full_text_search_ops_v2) "
        "WITH (tokenizer='TokenDelimit');",
    ),
    # ── [동의어 질의확장 — pgroonga_query_expand 지원] ─────────────────────
    (
        "idx_glossary_headword_pgroonga",
        "CREATE INDEX idx_glossary_headword_pgroonga ON glossary_synonym "
        "USING pgroonga (headword pgroonga_text_term_search_ops_v2);",
    ),
    (
        "idx_glossary_synonyms_pgroonga",
        "CREATE INDEX idx_glossary_synonyms_pgroonga ON glossary_synonym "
        "USING pgroonga (synonyms pgroonga_text_array_term_search_ops_v2);",
    ),
    # ── [조항ID 정확필드 — 결정론 인용, btree =] ──────────────────────────
    (
        "idx_clause_canonical_clause_id",
        "CREATE INDEX idx_clause_canonical_clause_id ON clause (canonical_clause_id);",
    ),
    (
        "idx_clause_clause_label",
        "CREATE INDEX idx_clause_clause_label ON clause (clause_label);",
    ),
    (
        "idx_chunk_canonical_clause_id",
        "CREATE INDEX idx_chunk_canonical_clause_id ON chunk (canonical_clause_id);",
    ),
    (
        "idx_authority_canonical_authority_id",
        "CREATE INDEX idx_authority_canonical_authority_id "
        "ON authority_matrix (canonical_authority_id);",
    ),
    # ── [범위/배열/jsonb] ─────────────────────────────────────────────────
    (
        # 금액밴드 포함질의(amount_band @> :v::int8) — GiST.
        "idx_authority_amount_band_gist",
        "CREATE INDEX idx_authority_amount_band_gist ON authority_matrix "
        "USING gist (amount_band);",
    ),
    (
        "idx_authority_amount_min",
        "CREATE INDEX idx_authority_amount_min ON authority_matrix (amount_min);",
    ),
    (
        "idx_authority_amount_max",
        "CREATE INDEX idx_authority_amount_max ON authority_matrix (amount_max);",
    ),
    (
        "idx_authority_approver_role",
        "CREATE INDEX idx_authority_approver_role ON authority_matrix (approver_role);",
    ),
    (
        "idx_authority_consulter_roles_gin",
        "CREATE INDEX idx_authority_consulter_roles_gin ON authority_matrix "
        "USING gin (consulter_roles);",
    ),
    (
        "idx_query_log_returned_ids_gin",
        "CREATE INDEX idx_query_log_returned_ids_gin ON query_log "
        "USING gin (returned_canonical_ids);",
    ),
    (
        "idx_query_log_answer_citation_ids_gin",
        "CREATE INDEX idx_query_log_answer_citation_ids_gin ON query_log "
        "USING gin (answer_citation_ids);",
    ),
    (
        "idx_chunk_meta_gin",
        "CREATE INDEX idx_chunk_meta_gin ON chunk USING gin (meta jsonb_path_ops);",
    ),
    # ── [보조 btree / FK / 신선도] ────────────────────────────────────────
    ("idx_post_board_id", "CREATE INDEX idx_post_board_id ON post (board_id);"),
    ("idx_post_posted_at", "CREATE INDEX idx_post_posted_at ON post (posted_at);"),
    ("idx_chunk_board_id", "CREATE INDEX idx_chunk_board_id ON chunk (board_id);"),
    (
        "idx_chunk_is_current",
        "CREATE INDEX idx_chunk_is_current ON chunk (board_id) WHERE is_current;",
    ),
    ("idx_regulation_board_id", "CREATE INDEX idx_regulation_board_id ON regulation (board_id);"),
    ("idx_regulation_reg_code", "CREATE INDEX idx_regulation_reg_code ON regulation (reg_code);"),
    ("idx_clause_regulation_id", "CREATE INDEX idx_clause_regulation_id ON clause (regulation_id);"),
    ("idx_attachment_post_id", "CREATE INDEX idx_attachment_post_id ON attachment (post_id);"),
    (
        "idx_authority_regulation_id",
        "CREATE INDEX idx_authority_regulation_id ON authority_matrix (regulation_id);",
    ),
    ("idx_eval_gold_query_id", "CREATE INDEX idx_eval_gold_query_id ON eval_gold (eval_query_id);"),
    # ── [부분 unique — 현행 1행 보장] ─────────────────────────────────────
    (
        "uq_clause_canonical_current",
        "CREATE UNIQUE INDEX uq_clause_canonical_current ON clause (canonical_clause_id) "
        "WHERE is_current;",
    ),
    (
        "uq_authority_canonical_current",
        "CREATE UNIQUE INDEX uq_authority_canonical_current ON authority_matrix "
        "(canonical_authority_id) WHERE is_current;",
    ),
    (
        "uq_regulation_reg_code_current",
        "CREATE UNIQUE INDEX uq_regulation_reg_code_current ON regulation (reg_code) "
        "WHERE is_current;",
    ),
]


def upgrade() -> None:
    for _name, ddl in _INDEXES:
        op.execute(ddl)


def downgrade() -> None:
    # 역순 1단: 본 파일 인덱스 전수 제거(부분 unique 포함) — 0002 테이블 drop·0001 ext drop 선행 [m-6].
    for name, _ddl in reversed(_INDEXES):
        op.execute(f"DROP INDEX IF EXISTS {name};")
