"""GLM 전송 직전 최소 PII 마스킹 — 순수 함수 (plan §5.3, D-05).

★ B 자체 게이트. 전체 PIPA 레닥션은 C 책임. rerank 는 반드시 이 redact 를 통과한 본문만
GLM client 에 전달한다(비레닥션 본문 GLM 전송 금지 — NOGO 제약). 동일 시그니처로 추후
app/common 승격 시 마이그레이션 무비용. 마스킹 순서: 긴 패턴(주민/카드) → 짧은 패턴(전화).
"""

from __future__ import annotations

import re

# (정규식, 치환토큰) — 적용 순서 중요(카드 16자리를 전화보다 먼저 제거).
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[이메일]"),
    (re.compile(r"\b\d{6}-\d{7}\b"), "[주민번호]"),
    (re.compile(r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b"), "[카드]"),
    (re.compile(r"\b0\d{1,2}-?\d{3,4}-?\d{4}\b"), "[전화]"),
]


def redact(text: str) -> str:
    """이메일/주민번호/카드/전화 패턴을 마스킹 토큰으로 치환한다(원본 PII 부분문자열 제거)."""
    out = text
    for pattern, token in _PATTERNS:
        out = pattern.sub(token, out)
    return out
