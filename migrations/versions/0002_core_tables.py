"""0002 core tables — erd.json 13표 (컬럼/FK/CHECK/생성열/일반unique).

[m-3] board_id 계열(board.board_id PK · post/regulation/chunk/ingest_state 의 board_id)=integer,
      그 외 모든 id/FK=bigint. FK 타입은 참조 PK 타입과 정확히 일치.
[m-1/§4.6] chunk.embedding(vector) 은 R0 제외 → 13표 전부 생성하되 chunk 컬럼 23개(=erd 24−1),
           전체 195컬럼(=erd 196−1). 의도된 deviation(ADR-002), 결함 아님.
생성 순서 = FK 의존 순서(§4.3). 부분 unique / pgroonga 인덱스는 0003.

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ── 생성 순서(FK 의존). downgrade 는 이 역순 DROP ... CASCADE. ──────────────
_TABLES_IN_ORDER = [
    "board", "post", "regulation", "clause", "attachment", "attachment_page",
    "authority_matrix", "chunk", "glossary_synonym", "ingest_state",
    "eval_query", "eval_gold", "query_log",
]


def upgrade() -> None:
    # 1) board — 19보드 마스터. board_id=integer IDENTITY.
    op.execute(
        """
        CREATE TABLE board (
            board_id              integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            bizbox_board_no       integer NOT NULL UNIQUE,
            name                  text    NOT NULL,
            slug                  text    NOT NULL UNIQUE,
            board_class           text    NOT NULL
                CHECK (board_class IN ('notice','regulation','authority','manual','form','meeting','etc')),
            included              boolean NOT NULL DEFAULT true,
            use_mecab_parallel    boolean NOT NULL DEFAULT false,
            default_chunk_strategy text   NOT NULL
                CHECK (default_chunk_strategy IN ('article','authority_cell','heading_window','table','whole')),
            required_role         text,
            created_at            timestamptz NOT NULL DEFAULT now(),
            updated_at            timestamptz NOT NULL DEFAULT now()
        );
        """
    )

    # 2) post — 글 원본. board_id=integer FK(RESTRICT), self-FK superseded_by.
    op.execute(
        """
        CREATE TABLE post (
            post_id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            board_id              integer NOT NULL REFERENCES board(board_id) ON DELETE RESTRICT,
            bizbox_art_no         bigint  NOT NULL,
            title                 text    NOT NULL,
            body_html             text,
            body_text             text,
            doc_type              text    NOT NULL
                CHECK (doc_type IN ('notice','regulation','authority','manual','form','meeting','etc')),
            author_name           text,
            author_dept           text,
            posted_at             timestamptz,
            view_count            integer NOT NULL DEFAULT 0,
            source_url            text,
            content_hash          text,
            is_current            boolean NOT NULL DEFAULT true,
            superseded_by_post_id bigint  REFERENCES post(post_id),
            language              text    NOT NULL DEFAULT 'ko',
            crawled_at            timestamptz NOT NULL DEFAULT now(),
            source_updated_at     timestamptz,
            UNIQUE (board_id, bizbox_art_no)
        );
        """
    )

    # 3) regulation — 규정 논리단위. self-FK supersedes.
    op.execute(
        """
        CREATE TABLE regulation (
            regulation_id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            source_post_id           bigint  REFERENCES post(post_id),
            board_id                 integer NOT NULL REFERENCES board(board_id),
            reg_code                 text,
            title                    text    NOT NULL,
            category                 text,
            reg_type                 text    NOT NULL
                CHECK (reg_type IN ('규정','지침','세칙','전결규정')),
            effective_date           date,
            revision_no              smallint,
            is_current               boolean NOT NULL DEFAULT true,
            supersedes_regulation_id bigint  REFERENCES regulation(regulation_id),
            enacted_date             date,
            abolished_date           date,
            curated                  boolean NOT NULL DEFAULT false,
            curated_by               text,
            curated_at               timestamptz
        );
        """
    )

    # 4) clause — 조/항/호/목. regulation CASCADE, self-FK parent/supersedes.
    op.execute(
        """
        CREATE TABLE clause (
            clause_id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            regulation_id        bigint  NOT NULL REFERENCES regulation(regulation_id) ON DELETE CASCADE,
            canonical_clause_id  text    NOT NULL,
            article_no           integer,
            article_branch       smallint,
            paragraph_no         smallint,
            item_no              smallint,
            sub_item_label       text,
            clause_label         text    NOT NULL,
            clause_title         text,
            text                 text    NOT NULL,
            parent_clause_id     bigint  REFERENCES clause(clause_id),
            depth                text    NOT NULL
                CHECK (depth IN ('article','paragraph','item','subitem')),
            effective_date       date,
            is_current           boolean NOT NULL DEFAULT true,
            supersedes_clause_id bigint  REFERENCES clause(clause_id),
            order_seq            integer NOT NULL,
            amended_at           timestamptz
        );
        """
    )

    # 5) attachment — 첨부 원본. post CASCADE. extract_method nullable CHECK.
    op.execute(
        """
        CREATE TABLE attachment (
            attachment_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            post_id         bigint  NOT NULL REFERENCES post(post_id) ON DELETE CASCADE,
            file_name       text    NOT NULL,
            mime_type       text,
            kind            text    NOT NULL
                CHECK (kind IN ('hwp','pdf','image','excel','word','etc')),
            storage_path    text    NOT NULL,
            download_url    text,
            bizbox_file_seq integer,
            byte_size       bigint,
            sha256          text,
            page_count      integer,
            is_table        boolean NOT NULL DEFAULT false,
            extract_method  text
                CHECK (extract_method IN ('pyhwp','libreoffice','ocr-shim','native')),
            ocr_status      text    NOT NULL DEFAULT 'pending'
                CHECK (ocr_status IN ('pending','extracting','ocr','done','failed')),
            extracted_text  text,
            error_msg       text,
            extracted_at    timestamptz,
            created_at      timestamptz NOT NULL DEFAULT now()
        );
        """
    )

    # 6) attachment_page — 페이지 OCR. attachment CASCADE, UNIQUE(attachment_id,page_no).
    op.execute(
        """
        CREATE TABLE attachment_page (
            page_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            attachment_id  bigint NOT NULL REFERENCES attachment(attachment_id) ON DELETE CASCADE,
            page_no        integer NOT NULL,
            image_path     text,
            ocr_text       text,
            ocr_confidence real,
            width_px       integer,
            height_px      integer,
            UNIQUE (attachment_id, page_no)
        );
        """
    )

    # 7) authority_matrix — 전결표 셀. 생성열 amount_band int8range.
    op.execute(
        """
        CREATE TABLE authority_matrix (
            authority_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            regulation_id         bigint  NOT NULL REFERENCES regulation(regulation_id),
            source_post_id        bigint  REFERENCES post(post_id),
            clause_id             bigint  REFERENCES clause(clause_id),
            source_attachment_id  bigint  REFERENCES attachment(attachment_id),
            canonical_authority_id text   NOT NULL,
            business_category     text,
            business_item         text    NOT NULL,
            action_type           text    NOT NULL
                CHECK (action_type IN ('전결','합의','보고','협조')),
            approver_role         text,
            consulter_roles       text[],
            amount_min            bigint,
            amount_max            bigint,
            amount_band           int8range GENERATED ALWAYS AS
                                      (int8range(amount_min, amount_max, '[]')) STORED,
            currency              text    NOT NULL DEFAULT 'KRW',
            condition_note        text,
            footnote_refs         text[],
            matrix_row_label      text,
            matrix_col_label      text,
            effective_date        date,
            is_current            boolean NOT NULL DEFAULT true,
            order_seq             integer
        );
        """
    )

    # 8) chunk — 검색 1차면(통합). board_id=integer 비정규화 필터.
    #    원천 FK 택1 CHECK(chunk_class↔원천컬럼). embedding 제외(§4.6, ADR-002).
    op.execute(
        """
        CREATE TABLE chunk (
            chunk_id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            chunk_class          text    NOT NULL
                CHECK (chunk_class IN ('clause','notice_section','authority_cell','table','attachment_text','form')),
            board_id             integer NOT NULL REFERENCES board(board_id),
            source_post_id       bigint  REFERENCES post(post_id),
            clause_id            bigint  REFERENCES clause(clause_id),
            source_attachment_id bigint  REFERENCES attachment(attachment_id),
            authority_id         bigint  REFERENCES authority_matrix(authority_id),
            heading_path         text,
            seq_in_source        integer NOT NULL,
            body                 text    NOT NULL,
            tokenized            text,
            canonical_clause_id  text,
            clause_label         text,
            page_no              integer,
            bbox                 jsonb,
            posted_at            timestamptz,
            is_current           boolean NOT NULL DEFAULT true,
            char_len             integer,
            token_count          integer,
            content_hash         text,
            dedup_group_id       bigint,
            meta                 jsonb,
            created_at           timestamptz NOT NULL DEFAULT now(),
            -- 원천 FK 정확히 1개 set (chunk_class 별 정합), 나머지 NULL 강제.
            CONSTRAINT chunk_source_exactly_one CHECK (
                (chunk_class = 'clause'
                    AND clause_id IS NOT NULL
                    AND source_post_id IS NULL AND source_attachment_id IS NULL AND authority_id IS NULL)
             OR (chunk_class IN ('attachment_text','table')
                    AND source_attachment_id IS NOT NULL
                    AND clause_id IS NULL AND source_post_id IS NULL AND authority_id IS NULL)
             OR (chunk_class = 'authority_cell'
                    AND authority_id IS NOT NULL
                    AND clause_id IS NULL AND source_post_id IS NULL AND source_attachment_id IS NULL)
             OR (chunk_class IN ('notice_section','form')
                    AND source_post_id IS NOT NULL
                    AND clause_id IS NULL AND source_attachment_id IS NULL AND authority_id IS NULL)
            )
        );
        """
    )

    # 9) glossary_synonym — 동의어 사전. UNIQUE(headword,domain_category).
    op.execute(
        """
        CREATE TABLE glossary_synonym (
            synonym_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            headword        text    NOT NULL,
            synonyms        text[]  NOT NULL,
            official_form   text,
            colloquial_form text,
            register        text    NOT NULL
                CHECK (register IN ('official','colloquial','abbrev','english')),
            boost           real    NOT NULL DEFAULT 1.0,
            domain_category text,
            is_active       boolean NOT NULL DEFAULT true,
            notes           text,
            updated_at      timestamptz NOT NULL DEFAULT now(),
            UNIQUE (headword, domain_category)
        );
        """
    )

    # 10) ingest_state — 보드별 크롤 상태 1:1 (board_id PK=FK, integer).
    op.execute(
        """
        CREATE TABLE ingest_state (
            board_id             integer PRIMARY KEY REFERENCES board(board_id),
            last_art_no          bigint,
            last_posted_at       timestamptz,
            cursor               jsonb,
            total_posts          integer NOT NULL DEFAULT 0,
            total_attachments    integer NOT NULL DEFAULT 0,
            status               text    NOT NULL DEFAULT 'idle'
                CHECK (status IN ('idle','running','paused','error')),
            health               text    NOT NULL DEFAULT 'healthy'
                CHECK (health IN ('healthy','stalled','degraded','error')),
            heartbeat_at         timestamptz,
            last_run_at          timestamptz,
            last_success_at      timestamptz,
            consecutive_failures integer NOT NULL DEFAULT 0,
            error_msg            text
        );
        """
    )

    # 11) eval_query — 골든셋 질의 헤더.
    op.execute(
        """
        CREATE TABLE eval_query (
            eval_query_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            query_text     text    NOT NULL,
            query_role     text,
            answer_type    text    NOT NULL
                CHECK (answer_type IN ('clause','authority','notice','abstain')),
            should_abstain boolean NOT NULL DEFAULT false,
            eval_set       text,
            notes          text,
            created_by     text,
            created_at     timestamptz NOT NULL DEFAULT now()
        );
        """
    )

    # 12) eval_gold — 질의별 정답(graded). target_kind FK 택1 CHECK, relevance 0..3.
    op.execute(
        """
        CREATE TABLE eval_gold (
            eval_gold_id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            eval_query_id        bigint  NOT NULL REFERENCES eval_query(eval_query_id) ON DELETE CASCADE,
            target_kind          text    NOT NULL
                CHECK (target_kind IN ('clause','authority','post')),
            clause_id            bigint  REFERENCES clause(clause_id),
            authority_id         bigint  REFERENCES authority_matrix(authority_id),
            post_id              bigint  REFERENCES post(post_id),
            expected_canonical_id text,
            relevance            smallint NOT NULL CHECK (relevance BETWEEN 0 AND 3),
            notes                text,
            CONSTRAINT eval_gold_target_exactly_one CHECK (
                (target_kind = 'clause'
                    AND clause_id IS NOT NULL AND authority_id IS NULL AND post_id IS NULL)
             OR (target_kind = 'authority'
                    AND authority_id IS NOT NULL AND clause_id IS NULL AND post_id IS NULL)
             OR (target_kind = 'post'
                    AND post_id IS NOT NULL AND clause_id IS NULL AND authority_id IS NULL)
            )
        );
        """
    )

    # 13) query_log — 운영 질의 로그. email 해시(PIPA), text[] 배열.
    op.execute(
        """
        CREATE TABLE query_log (
            query_log_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            query_text            text    NOT NULL,
            normalized_query      text,
            user_role             text,
            user_email_hash       text,
            asked_at              timestamptz NOT NULL DEFAULT now(),
            result_count          integer NOT NULL DEFAULT 0,
            zero_result           boolean NOT NULL DEFAULT false,
            abstained             boolean NOT NULL DEFAULT false,
            validator_passed      boolean,
            retrieval_strategy    text,
            reranked              boolean NOT NULL DEFAULT false,
            returned_canonical_ids text[],
            answer_citation_ids   text[],
            top_score             real,
            latency_ms            integer,
            feedback              text CHECK (feedback IN ('helpful','not_helpful')),
            feedback_note         text,
            session_id            text
        );
        """
    )


def downgrade() -> None:
    # FK 역의존 순서로 DROP ... CASCADE (self-FK·교차참조 일괄 정리) [m-6].
    for table in reversed(_TABLES_IN_ORDER):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE;")
