"""GLM 리랭크 통합테스트 — 실 엔드포인트가 유효 인덱스 배열을 반환하는지(ADR-005, plan §3.3).

추론모델(GLM-5.2)이 `content=''`(추론 잘림)로 빈 답을 주면 `parse_order()` 가 ValueError →
빈 배열이 되므로, 실 호출 결과가 비지 않은 유효 인덱스 배열임을 검증해 회귀를 즉시 검출한다.

env 가드: `LITELLM_KEY_GLM`/`LITELLM_BASE` 미설정 시 skip(키 부재 CI/로컬 비차단).
키 보안: 키 값·응답 raw 를 로그/print/assert 메시지 어디에도 노출하지 않는다(인덱스/길이만).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def _glm_env():
    from app.common.config import get_settings

    s = get_settings()
    if not s.litellm_key_glm or not s.litellm_base:
        pytest.skip("GLM 통합테스트: LITELLM_KEY_GLM/LITELLM_BASE 미설정 → skip")
    return s


async def test_glm_rank_returns_valid_index_array(_glm_env):
    """실 GLM 리랭크 호출 → 비지 않은 유효 인덱스 배열(추론 잘림 회귀 검출)."""
    from app.search.glm_client import GlmClient

    candidates = ["연차휴가 규정", "출장비 정산", "주차장 안내"]
    n = len(candidates)

    order = await GlmClient().rank("연차 며칠?", candidates)

    # 키 값/응답 raw 는 노출하지 않고 인덱스/길이만으로 판정.
    assert isinstance(order, list)
    assert order, "GLM 리랭크가 빈 인덱스 배열 반환 — 추론 잘림(content='') 회귀 의심"
    assert all(isinstance(i, int) for i in order)
    assert all(0 <= i < n for i in order), f"범위 밖 인덱스 포함(후보 {n}개)"
    assert set(order) <= set(range(n))
