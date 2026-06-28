# 답변 렌더 규약 — 출처 · 첨부 · 기권 (RENDER_CONVENTIONS.md)

> C 도구 출력(JSON 구조)을 LibreChat 답변에 어떻게 표면화할지 규약화합니다. 모든 필드는
> **C 스키마와 1:1** 매핑이며, 임의 추정/생성을 금지합니다. LibreChat 마크다운 렌더 한도 내.
>
> 진실원: `app/mcp/schemas.py`(SourceMeta·CitationOut·AttachmentOut·SearchToolOut),
> `app/search/abstain.py`(ABSTAIN_MESSAGE_KO), `app/mcp/tools/_guard.py`(ABSENT/DENY 메시지),
> `app/mcp/citations.py`(인용 후검증). 모든 본문 텍스트는 핸들러에서 `redact_pii` 통과(NFR-003).

---

## 1. 출처(조항 인용) 렌더 — FEAT-007

**입력**: `SearchToolOut.citations[]`(`CitationOut`) + `SearchToolOut.hits[].source`(`SourceMeta`).

### 1.1 사용 가능한 필드 (C 스키마 — 그대로만 사용)
- `SourceMeta`: `board_id` · `board_name` · `post_id?` · `title` · `reg_code?` ·
  `effective_date?` · `source_url?` · `attachments[]`.
- `CitationOut`: `kind` · `canonical_id` · `label?` · `chunk_id?` · `validated`.
- `HitOut`: `snippet`(레닥션 완료) · `score` · `source` · `citation?`.

### 1.2 ★ 조번호 = 메타 결정론 (LLM 생성 금지)
- 조항 라벨/번호는 **메타데이터에서만** 가져옵니다. 모델이 조번호를 생성·추론하지 않습니다.
- C 의 2차 가드(`citations.py: verify_citations_against_hits`)를 통과해 `validated=true` 인
  인용만 "확정 근거"로 렌더합니다. `validated=false` 는 근거로 표기하지 않습니다(또는 약한 표기).
- `CitationOut.label` 이 있으면 그 라벨을 그대로 사용. 없으면 `SourceMeta.title` 로 대체하되
  조번호를 **지어내지 않습니다**.

### 1.3 권장 포맷 (기본 = 답변 하단 목록)
답변 본문 뒤에 근거 목록을 붙입니다. 한 줄 형식:
```
[근거] {board_name} · {title} · {label}  (시행일 {effective_date})  — {source_url}
```
- `effective_date`/`source_url`/`label` 이 없으면 해당 토막을 생략합니다(빈 괄호/대시 금지).
- 다중 근거: 조항별 구분 목록 — 스니펫(`hits[].snippet`) ↔ 출처 1:1. 폐지/구버전 규정은
  명시(예: `(개정 전)` 라벨). 스니펫은 이미 PII 레닥션 완료 상태입니다.

### 1.4 인라인 각주 대안 (UX 실테스트로 확정 — 열린질문 #6)
각주식(본문에 `[1]` 표식 + 하단 정의)도 허용하나, **기본은 §1.3 하단 목록**입니다.
```
연차휴가는 1년간 15일입니다[1].

[1] 인사규정 · 제0조(휴가) (시행일 2025-01-01) — http://gw.cudo.co.kr/...
```
- 어느 포맷이든 조번호는 메타에서만. 확정은 운영 UX 실테스트(FEAT-007 precondition).

### 1.5 GLM temperature=0 정합
- 재현성을 위해 GLM 은 temperature=0 전제(FEAT-007/INT-002). 단 이는 운영 librechat.yaml
  `endpoints` 설정 영역으로 **D 범위 밖**(plan §1.4) — 본 규약은 정합 요구만 기록.

---

## 2. 첨부 링크/이미지 렌더 — FEAT-011

**입력**: `AttachmentOut`(`get_attachment` 출력) / `SourceMeta.attachments[]`(`AttachmentRef`).

### 2.1 사용 가능한 필드 (C 스키마)
- `AttachmentOut`: `mode`("text"|"image") · `file_name` · `mime_type?` · `download_url?` ·
  `text?`(text 모드) · `page_no?` · `image_base64?` · `unverified_image` · `warning_ko?` ·
  `ocr_text?` · `message_ko?`.
- `AttachmentRef`: `attachment_id` · `file_name` · `kind` · `download_url?`.

### 2.2 `mode = "text"`
- 다운로드 링크 + 레닥션 추출텍스트를 함께 노출:
```
[원문 다운로드: {file_name}]({download_url})
```
  이어서 `text`(레닥션 완료)를 인용 블록으로. `download_url` 이 `None` 이면 링크 생략하고
  텍스트만 노출(빈 링크 렌더 금지).

### 2.3 `mode = "image"`
- **v1 기본 = 링크 폴백**(볼륨 미마운트 등 게이트 미충족). `unverified_image=true` 이면
  인라인 이미지 대신 **링크 + `warning_ko`** 를 노출:
```
⚠️ {warning_ko}
[원문 이미지 다운로드: {file_name}]({download_url})
```
- `image_base64` 가 채워진 경우(큐레이션 + 볼륨 게이트 충족 + 한도 내)에만 인라인 이미지로
  렌더. base64 가 `None` 이면 절대 인라인 시도하지 않습니다(C 가 한도 초과 시 None→링크 폴백).
- `ocr_text` 가 있으면 보조 텍스트로 함께 제시 가능(레닥션 완료 전제).

### 2.4 명시 콘텐츠 블록 원칙
- 도구 응답 콘텐츠 블록에 **명시적 링크/이미지를 포함**하고, LibreChat 의 resource 자동 렌더에
  의존하지 않습니다(FEAT-011 rule). 즉 download_url/이미지를 답변 텍스트에 직접 렌더.

### 2.5 폐쇄망 / 발급 주체 (열린질문 #3)
- `download_url` 은 **사내 URL·폐쇄망 도달**이어야 합니다(외부 egress 금지).
- URL 발급 주체(MCP 정적 서빙 vs 사이드카)와 만료 정책, `download_url` 채움 책임(A 인제스트/C)은
  **미정 → 열린질문/후속**. 규약은 "사내 URL 만, 자동 렌더 의존 최소화"까지.

---

## 3. 기권(거절) UX — FEAT-016

### 3.1 근거 부재 기권
- `SearchToolOut.abstained == true` → 답변은 `message_ko`(= `abstain.py` 의
  `ABSTAIN_MESSAGE_KO`)를 **그대로 표면화**합니다:
  > 요청하신 내용에 해당하는 사내 규정을 찾지 못했습니다. 질문을 더 구체적으로 바꾸거나 담당
  > 부서에 문의해 주세요.
- **환각 보충 금지**: 모델이 일반 지식으로 답을 채우지 않습니다. `serverInstructions: true` 가
  C `_INSTRUCTIONS`("근거 없으면 기권")를 모델에 주입합니다.

### 3.2 신원부재 / 접근거부
- 신원부재 → `_guard.ABSENT_MESSAGE_KO` 표면화:
  > 로그인 세션을 확인할 수 없습니다. LibreChat 로그인 상태를 확인해 주세요.
- 보드 비허용(deny) → `_guard.DENY_MESSAGE_KO` 표면화:
  > 해당 자료에 접근 권한이 없습니다.
- 두 경우 모두 환각 보충 없이 안내 메시지만. (신원부재는 `acl_audit(identity_absent)` 기록됨.)

### 3.3 기타 도구의 not-found/deny
- `RegulationOut`/`ListBoardsOut`/`AuthorityOut`/`CompareOut`/`DiffOut` 의 `message_ko` 가
  채워진 경우도 동일 — 해당 메시지를 그대로 노출하고 결과를 지어내지 않습니다.

---

## 4. thumbs(👍/👎) → query_log — FEAT-018 (★ 실현성 판정: 후속/범위 밖)

### 4.1 현황 (정직 판정)
- **스키마 준비됨**: `query_log.feedback`(CHECK IN `'helpful'`/`'not_helpful'`) + `feedback_note`
  컬럼이 존재합니다(0002 마이그레이션).
- **C 쓰기 경로 부재**: `grep -rn feedback app/` = **0건**. `audit.write_query_log` 는 INSERT
  전용 — feedback 을 채우는 도구/엔드포인트가 없습니다.
- **LibreChat 네이티브 훅 부재**: thumbs 는 LibreChat 자체 저장소(Mongo)에 메시지 단위로
  저장되며, 외부 Postgres 로 push 하는 네이티브 webhook/MCP 콜이 없습니다.
- **상관키 부재**: `query_log` row(asked_at·session_id 기반)와 LibreChat 메시지
  (messageId·conversationId)를 잇는 키가 전파되지 않습니다(session-id 조차 §0/열린질문 #1 미확정).

### 4.2 판정
**v1 자동 배선 불가 = 범위 밖 / 후속 필요(FEAT-018). 임의 구현 금지.**

### 4.3 후보 경로 (미구현 — 후속 설계용 기록일 뿐)
- (a) 신규 MCP 도구 `record_feedback(query_log_id|session_id, helpful)` + LibreChat 측
  thumbs→도구호출 트리거(네이티브 미지원 → 커스텀/플러그인 필요).
- (b) 신규 사내 수집 엔드포인트 → `UPDATE query_log SET feedback = ...`.
- 두 경로 모두 **상관키 설계**(LibreChat messageId/conversationId ↔ query_log_id) + 신규
  스키마/코드가 선행해야 합니다. 본 D 산출물에서는 구현하지 않습니다.

---

## 5. C 정합 요약 (참조)

| 렌더 항목 | C 진실원 | 핵심 규칙 |
|---|---|---|
| 출처/인용 | `schemas.py: SourceMeta·CitationOut·HitOut` · `citations.py` | 조번호 메타 결정론, `validated=true` 우선 |
| 첨부 | `schemas.py: AttachmentOut·AttachmentRef` | text=링크+텍스트, image=v1 링크 폴백, 사내 URL |
| 기권 | `abstain.py: ABSTAIN_MESSAGE_KO` · `_guard.py: ABSENT/DENY` | message_ko 그대로, 환각 보충 금지 |
| 피드백 | `query_log.feedback`(스키마만) · grep 0건 | 후속 FEAT-018, 자동 배선 불가 |
