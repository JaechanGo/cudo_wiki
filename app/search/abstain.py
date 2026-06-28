"""거절 게이트 — 관련도 임계 미달 시 한국어 거절 결정, 순수 함수 (plan §6.3, D-06).

pgroonga_score 는 코퍼스 의존 절대 스케일이라 R0 는 보수적 절대 임계(ABS_THRESHOLD) 우선 +
평가 하네스로 보정(R-4). 상대 마진은 기본 off. 무근거 질의를 거절해 인용정확도/기권 NFR 을 지킨다.
"""

from __future__ import annotations

from app.search.types import AbstainDecision, SearchHit

# pgroonga_score 절대 임계(보수적 작은 양수). 실데이터 확보 후 평가 하네스로 재튜닝(R-4).
ABS_THRESHOLD: float = 1e-6

# 사용자 노출 한국어 거절 메시지.
ABSTAIN_MESSAGE_KO: str = (
    "요청하신 내용에 해당하는 사내 규정을 찾지 못했습니다. "
    "질문을 더 구체적으로 바꾸거나 담당 부서에 문의해 주세요."
)


def decide_abstain(
    hits: list[SearchHit],
    *,
    abs_threshold: float = ABS_THRESHOLD,
    rel_margin: float | None = None,
) -> AbstainDecision:
    """검색/리랭크 후 hits 의 상위 score 로 거절 여부를 판정한다.

    규칙: hits 비면 거절(empty_hits), top_score < abs_threshold 면 거절(below_abs_threshold).
    그 외 비거절. rel_margin 은 R0 미사용(인터페이스 보존).
    """
    if not hits:
        return AbstainDecision(True, "empty_hits", ABSTAIN_MESSAGE_KO)

    top_score = max(h.score for h in hits)
    if top_score < abs_threshold:
        return AbstainDecision(True, "below_abs_threshold", ABSTAIN_MESSAGE_KO)

    return AbstainDecision(False, "", "")
