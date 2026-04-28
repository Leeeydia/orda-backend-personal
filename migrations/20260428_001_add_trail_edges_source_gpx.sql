-- trail_edges.source_gpx 컬럼 + 인덱스 추가 (멱등)
-- 배경: schema.sql/db.sql에는 이미 정의되어 있으나 실제 DB에 미반영.
--       추천 기능에서 같은 GPX에서 나온 edge들을 하나의 코스로 묶는 식별자.

ALTER TABLE trail_edges
    ADD COLUMN IF NOT EXISTS source_gpx TEXT;

CREATE INDEX IF NOT EXISTS idx_trail_edges_source_gpx
    ON trail_edges (source_gpx);
