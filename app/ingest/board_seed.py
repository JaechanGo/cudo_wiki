"""19개 사내게시판 마스터 시드 (DESIGN §7 표, plan §1).

`loader.upsert_board_seed` 입력 상수. ``bizbox_board_no`` 가 UNIQUE 자연키.
**제외 4보드(인사발령·경조사·모범사원·동호회)는 개인정보 보드라 포함하지 않는다**(DESIGN §7).

board_class / default_chunk_strategy 는 0002 스키마 CHECK enum 에 매핑한 운영 기본값:
- board_class    ∈ {notice,regulation,authority,manual,form,meeting,etc}
- chunk_strategy ∈ {article,authority_cell,heading_window,table,whole}

규정 핵심 보드(사내규정)만 조 단위 청킹(article) + mecab 병렬(DESIGN §0 "규정/전결 보드
mecab 병렬"). reg_code 채번/직무 ACL 은 phase-2 운영 합의(DESIGN §8) → required_role 은 1차 None.

★ bizbox_board_no = **실 boardNo**(viewBoard.do 가 받는 값) — 좌측 jstree 노드 id 가 아님.
   라이브 실측(2026-06-29) 변환규칙: jstree ``1401000XXX`` → ``900000XXX`` (900000000+id%1e6),
   jstree ``501000XXX`` → ``XXX`` (id%1e6). 23보드 전수 검증(exData 건수 ↔ 트리 카운트 일치).
   주석의 ``jstree=`` 는 화면 트리 노드 id(추적용), 코드 값은 크롤이 쓰는 실 boardNo.
"""

from __future__ import annotations

from app.ingest.models import BoardSeed

# (bizbox_board_no=실boardNo, 게시판명, slug, board_class, chunk_strategy, mecab_parallel)
BOARDS: tuple[BoardSeed, ...] = (
    BoardSeed(73, "CEO칼럼", "ceo-column", "notice", "heading_window"),                  # jstree=501000073
    BoardSeed(74, "공지사항", "notice", "notice", "heading_window"),                       # jstree=501000074
    BoardSeed(900000409, "쿠도제안게시판", "suggestion", "etc", "heading_window"),          # jstree=1401000409
    BoardSeed(
        900000286, "사내규정", "regulation", "regulation", "article",                     # jstree=1401000286
        use_mecab_parallel=True,
    ),
    BoardSeed(900000327, "사내양식함", "form-archive", "form", "whole"),                   # jstree=1401000327
    BoardSeed(900000325, "뉴스클리핑", "news-clipping", "etc", "whole"),                   # jstree=1401000325
    BoardSeed(900000306, "월례회의자료", "monthly-meeting", "meeting", "heading_window"),   # jstree=1401000306
    BoardSeed(900000070, "독서게시판", "reading", "etc", "whole"),                         # jstree=1401000070
    BoardSeed(900000326, "회사소개서", "company-intro", "etc", "whole"),                   # jstree=1401000326
    BoardSeed(900000439, "외국어 신청", "language-apply", "form", "whole"),                # jstree=1401000439
    BoardSeed(900000575, "ERP 설치 매뉴얼", "erp-install-manual", "manual", "heading_window"),   # jstree=1401000575
    BoardSeed(900000577, "ERP 사용 매뉴얼", "erp-usage-manual", "manual", "heading_window"),     # jstree=1401000577
    BoardSeed(900000578, "ERP 인사평가 매뉴얼", "erp-hr-eval-manual", "manual", "heading_window"),  # jstree=1401000578
    BoardSeed(900000606, "ERP 사용자 교육", "erp-user-training", "manual", "heading_window"),    # jstree=1401000606
    BoardSeed(
        900000605, "그룹웨어 매뉴얼/OJT", "groupware-manual-ojt", "manual", "heading_window",   # jstree=1401000605
    ),
    BoardSeed(900000668, "화상회의 매뉴얼", "video-conf-manual", "manual", "heading_window"),    # jstree=1401000668
    BoardSeed(900000669, "자격증 축하금 LIST", "cert-reward-list", "etc", "table"),          # jstree=1401000669
    BoardSeed(900000679, "버크만진단 참고자료", "birkman-reference", "etc", "whole"),          # jstree=1401000679
    BoardSeed(900000704, "임직원 교육·설문결과", "staff-training-survey", "etc", "whole"),      # jstree=1401000704
)
