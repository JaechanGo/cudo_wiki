"""인제스트 파이프라인 단계간 전달 dataclass (plan §1·§12).

크롤→추출→정제→정규화→적재 각 단계의 입출력 계약을 frozen dataclass 로 고정한다.
DB 스키마(0002)의 컬럼과 1:1 매핑되도록 필드명을 맞췄다(loader 가 그대로 적재).

frozen=True: 단계 산출물은 불변. 후속 단계가 값을 덧붙일 땐 ``dataclasses.replace`` 사용
(예: normalize 가 RawPost.body_text 채움 → replace(raw, body_text=...)).

계층/링크는 DB id 가 아직 없으므로 **canonical id 참조**로 표현한다
(예: ParsedClause.parent_canonical_id → loader 가 clause_id 로 해소).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

# ── 크롤 단계 ────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class PostRef:
    """목록 한 행(viewBoard.do 의 ``var exData=[...]`` 1요소, crawler.list_post_refs 산출).

    art_no=art_seq_no(본문 진입키), view_count=read_cnt, has_attachment=add_file_yn=='Y'.
    메타(title/author/posted_at)는 목록 JSON 에 이미 완비 → crawl_post 가 재파싱 없이 사용.
    """

    art_no: int
    title: str
    author: str | None = None
    posted_at: datetime | None = None
    view_count: int = 0
    has_attachment: bool = False


@dataclass(frozen=True, slots=True)
class RawAttachment:
    """첨부 ref(+선택적 바이트). attachment 테이블 적재 전 단계.

    bizbox_file_seq 는 BizBox 파일 순번(post 내 dedup 자연키 보조, plan §4).
    content 는 다운로드 후 채워지는 바이트(추출기 입력); ref 단계에선 None 가능.
    """

    file_name: str
    kind: str  # 'hwp'|'pdf'|'image'|'excel'|'word'|'etc' (attachment.kind CHECK)
    bizbox_file_seq: int | None = None
    download_url: str | None = None
    mime_type: str | None = None
    file_ext: str | None = None
    byte_size: int | None = None
    sha256: str | None = None
    content: bytes | None = None


@dataclass(frozen=True, slots=True)
class RawPost:
    """글 1건(메타 + 2-hop 본문 + 첨부 ref). crawler.crawl_post 산출."""

    board_no: int
    art_no: int
    title: str
    body_html: str | None = None
    body_text: str | None = None  # normalize.clean_html 후 채움(replace)
    doc_type: str = "etc"  # post.doc_type CHECK enum
    author_name: str | None = None
    author_dept: str | None = None
    posted_at: datetime | None = None
    view_count: int = 0
    source_url: str | None = None
    content_hash: str | None = None
    attachments: tuple[RawAttachment, ...] = ()


# ── 추출 단계 ────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ExtractedPage:
    """첨부 페이지 단위 산출(OCR 등). attachment_page 테이블 매핑."""

    page_no: int
    ocr_text: str | None = None
    ocr_confidence: float | None = None
    image_path: str | None = None
    width_px: int | None = None
    height_px: int | None = None


@dataclass(frozen=True, slots=True)
class ExtractResult:
    """첨부 1건 추출 결과(extract.extract_attachment 산출). attachment 갱신용."""

    extracted_text: str | None = None
    page_count: int | None = None
    method: str | None = None  # 'pyhwp'|'libreoffice'|'ocr-shim'|'native' (CHECK)
    ocr_status: str = "pending"  # 'pending'|'extracting'|'ocr'|'done'|'failed'
    is_table: bool = False
    error_msg: str | None = None
    pages: tuple[ExtractedPage, ...] = ()


# ── 정규화 단계 (결정론 파서 산출) ──────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ParsedRegulation:
    """규정 논리단위(clause_parser 전처리/메타 추출). regulation 테이블 매핑.

    source_post_id/board_id 는 적재 시점 값이라 upsert_regulation 인자로 별도 전달.
    reg_code 는 백필 컬럼(1차 멱등은 source_post_id 기반, plan §4) → 보통 None.
    """

    title: str
    reg_type: str  # '규정'|'지침'|'세칙'|'전결규정' (regulation.reg_type CHECK)
    category: str | None = None
    reg_code: str | None = None
    effective_date: date | None = None
    revision_no: int | None = None
    enacted_date: date | None = None


@dataclass(frozen=True, slots=True)
class ParsedClause:
    """조/항/호/목/부칙/별표 1개(clause_parser.parse_clauses 산출). clause 테이블 매핑.

    canonical_clause_id 포맷(plan §7): ``R{rid}#a{art}[의{branch}][-p{para}][-i{item}]``,
    부칙=``R{rid}#supp{n}``, clause 적재 별표=``R{rid}#appx{n}``.
    parent_canonical_id: 계층 부모의 canonical id(loader 가 parent_clause_id 로 해소).
    """

    canonical_clause_id: str
    clause_label: str
    text: str
    depth: str  # 'article'|'paragraph'|'item'|'subitem' (clause.depth CHECK)
    order_seq: int
    article_no: int | None = None
    article_branch: int | None = None
    paragraph_no: int | None = None
    item_no: int | None = None
    sub_item_label: str | None = None
    clause_title: str | None = None
    effective_date: date | None = None
    parent_canonical_id: str | None = None


@dataclass(frozen=True, slots=True)
class ParsedAuthority:
    """전결표 셀 1개(authority_parser.parse_authority_matrix 산출). authority_matrix 매핑.

    amount_band 는 DB 생성열(int8range '[]') → 파서는 amount_min/amount_max 만 채운다.
    "초과"(exclusive)는 amount_min=경계+1 보정. min>max 역전은 파서가 차단(plan §3·§10).
    consulter_roles 는 text[] → tuple 로 보존.
    """

    canonical_authority_id: str
    business_item: str
    action_type: str  # '전결'|'합의'|'보고'|'협조' (authority_matrix.action_type CHECK)
    business_category: str | None = None
    approver_role: str | None = None
    consulter_roles: tuple[str, ...] = ()
    amount_min: int | None = None
    amount_max: int | None = None
    currency: str = "KRW"
    condition_note: str | None = None
    matrix_row_label: str | None = None
    matrix_col_label: str | None = None
    effective_date: date | None = None
    order_seq: int | None = None


# ── 시드 / 헬스 ──────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class BoardSeed:
    """보드 마스터 시드 1건(loader.upsert_board_seed 입력). board 테이블 매핑."""

    bizbox_board_no: int
    name: str
    slug: str
    board_class: str  # board.board_class CHECK enum
    default_chunk_strategy: str  # board.default_chunk_strategy CHECK enum
    included: bool = True
    use_mecab_parallel: bool = False
    required_role: str | None = None
    # 크롤 소스 디스크리미네이터 — run.main 이 source 별로 (client, list_fn, crawl_fn) 분기.
    # 'bizbox'(기본)=BizBox 그룹웨어, 'gainge'=지식뱅크(cudo.gainge.com) GraphQL 영상.
    source: str = "bizbox"


@dataclass(frozen=True, slots=True)
class BoardHealth:
    """보드 수집 상태 스냅샷(health.detect_stalled 산출). ingest_state 조회 매핑."""

    board_id: int
    status: str  # 'idle'|'running'|'paused'|'error'
    health: str  # 'healthy'|'stalled'|'degraded'|'error'
    bizbox_board_no: int | None = None
    name: str | None = None
    heartbeat_at: datetime | None = None
    last_run_at: datetime | None = None
    last_success_at: datetime | None = None
    consecutive_failures: int = 0
    total_posts: int = 0
    total_attachments: int = 0
    error_msg: str | None = None


@dataclass(frozen=True, slots=True)
class IngestCounts:
    """1회 보드 실행 집계(advance_ingest_state 입력 보조)."""

    posts: int = 0
    attachments: int = 0
    clauses: int = 0
    authorities: int = 0
    failures: int = 0
    errors: tuple[str, ...] = field(default_factory=tuple)
