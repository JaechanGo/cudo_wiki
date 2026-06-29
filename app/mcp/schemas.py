"""도구 입력/출력 pydantic 모델 — 결정론 직렬화 (Task009 plan §2·§3·§6).

모든 사용자 노출 텍스트는 한국어이나 코드 식별자/필드명은 영문. 필드 선언 순서 = 직렬화 순서
(pydantic 보존) → 결정론. 본문 텍스트 필드는 도구 핸들러에서 redact_pii 통과 후 채운다.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel

# ── 출처메타(§6) — 모든 도구가 동일 구조 ─────────────────────────────────


class AttachmentRef(BaseModel):
    """출처 첨부 링크 1건(다운로드 URL — 바이트 미전송)."""

    attachment_id: int
    file_name: str
    kind: str
    download_url: str | None = None


class SourceMeta(BaseModel):
    """결정론 출처메타 — board·title·시행일·원문URL·첨부링크(§6)."""

    board_id: int
    board_name: str
    post_id: int | None = None
    title: str
    reg_code: str | None = None
    effective_date: date | None = None
    source_url: str | None = None
    attachments: list[AttachmentRef] = []


# ── 인용(§3 공통) ────────────────────────────────────────────────────────


class CitationOut(BaseModel):
    """결정론 인용 1건 — Citation dataclass 의 직렬화 형태."""

    kind: str
    canonical_id: str
    label: str | None = None
    chunk_id: int | None = None
    validated: bool = False


# ── search_regulations(§3.1) ─────────────────────────────────────────────


class HitOut(BaseModel):
    """검색 결과 1건 — 레닥션 스니펫 + 출처 + 인용."""

    snippet: str
    score: float
    source: SourceMeta
    citation: CitationOut | None = None


class SearchToolOut(BaseModel):
    """search_regulations 출력 — 거절 게이트·전략·리랭크·인용."""

    abstained: bool
    message_ko: str | None = None
    strategy: str = ""
    reranked: bool = False
    hits: list[HitOut] = []
    citations: list[CitationOut] = []


# ── get_regulation(§3.2) ─────────────────────────────────────────────────


class ClauseOut(BaseModel):
    """조항 1건(text 는 레닥션 통과)."""

    canonical_clause_id: str
    clause_label: str
    clause_title: str | None = None
    text: str


class RegulationOut(BaseModel):
    """규정 본문 + 조항 목록. message_ko 채워지면 not-found/deny 안내."""

    regulation_id: int | None = None
    title: str | None = None
    reg_type: str | None = None
    effective_date: date | None = None
    revision_no: int | None = None
    source: SourceMeta | None = None
    clauses: list[ClauseOut] = []
    message_ko: str | None = None


# ── get_attachment(§3.3, B-1) ────────────────────────────────────────────


class AttachmentOut(BaseModel):
    """첨부 서빙 — text(다운로드링크+추출텍스트) / image(큐레이션+볼륨 게이트 → base64 or 링크폴백).

    image 분기 v1: 게이트 미충족 시 image_base64=None·unverified_image=true·경고 라벨(B-1).
    """

    mode: str = "text"  # "text" | "image"
    file_name: str = ""
    mime_type: str | None = None
    download_url: str | None = None
    # text 모드
    text: str | None = None
    # image 모드
    page_no: int | None = None
    image_base64: str | None = None
    unverified_image: bool = False
    warning_ko: str | None = None
    ocr_text: str | None = None
    message_ko: str | None = None


# ── list_boards(§3.4) ────────────────────────────────────────────────────


class BoardOut(BaseModel):
    """허용 보드 1건."""

    board_id: int
    name: str
    slug: str
    board_class: str


class ListBoardsOut(BaseModel):
    """list_boards 출력 — ACL 허용 보드만."""

    boards: list[BoardOut] = []
    message_ko: str | None = None


class RecentPostItem(BaseModel):
    """최근 글 1건 (시간순 목록용)."""

    post_id: int
    title: str
    board_name: str
    posted_at: date | None = None
    source_url: str | None = None


class RecentPostsOut(BaseModel):
    """list_recent_posts 출력 — 게시판 최신 글 게시일 내림차순."""

    posts: list[RecentPostItem] = []
    message_ko: str | None = None


# ── get_approval_authority(§3.5, M-2) ────────────────────────────────────


class AuthorityRowOut(BaseModel):
    """전결 행 — condition_note 는 C 직접 SQL 보강 후 레닥션(M-2)."""

    business_item: str | None = None
    approver_role: str | None = None
    action_type: str | None = None
    consulter_roles: list[str] | None = None
    amount_min: int | None = None
    amount_max: int | None = None
    condition_note: str | None = None
    citation: str | None = None  # AUTH canonical_id


class AuthorityOut(BaseModel):
    """전결권/금액밴드 집계."""

    kind: str
    count: int
    rows: list[AuthorityRowOut] = []
    message_ko: str | None = None


# ── aggregate_compare(§3.6, m-4) ─────────────────────────────────────────


class CompareRowOut(BaseModel):
    """보드별 카운트 비교 행(v1=카운트 한정)."""

    board_id: int
    label: str  # 보드명
    value: int | None = None


class CompareOut(BaseModel):
    """aggregate_compare 출력 — v1=보드별 현행 규정 카운트 비교."""

    kind: str
    count: int
    rows: list[CompareRowOut] = []
    message_ko: str | None = None


# ── get_regulation_diff(§3.7) ────────────────────────────────────────────


class ClauseRefOut(BaseModel):
    """diff added/removed 참조."""

    canonical_clause_id: str
    clause_label: str | None = None


class ClauseChangeOut(BaseModel):
    """diff changed 항목(before/after 는 레닥션 통과)."""

    canonical_clause_id: str
    clause_label: str | None = None
    before: str
    after: str


class DiffOut(BaseModel):
    """규정 개정 diff. is_initial=true 면 직전판 부재(전체 added)."""

    from_regulation_id: int | None = None
    to_regulation_id: int | None = None
    is_initial: bool = False
    added: list[ClauseRefOut] = []
    removed: list[ClauseRefOut] = []
    changed: list[ClauseChangeOut] = []
    message_ko: str | None = None
