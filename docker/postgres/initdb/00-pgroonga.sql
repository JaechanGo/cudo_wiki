-- 폴백 전용 (정본 = alembic 0001_extensions). [R12]
-- 컨테이너 최초 init(빈 데이터 디렉토리)에서만 실행되는 보조 멱등 생성.
-- 운영/검증의 정본은 `alembic upgrade head` 이며, 본 파일은 이중 안전망.
CREATE EXTENSION IF NOT EXISTS pgroonga;
