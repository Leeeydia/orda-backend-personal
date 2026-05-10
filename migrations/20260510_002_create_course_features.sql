-- course_features 테이블 생성 (멱등)
-- 배경: ML 추천 1~2단계(feature 추출 + K-Means 클러스터링) 산출물을 적재하기 위한 테이블.
--       trail_edges에서 source_gpx 단위로 집계한 feature 6종 + cluster_id + 대표 summit_id를 저장한다.
-- 참고: CLAUDE.md §8-1 스키마 그대로.

CREATE TABLE IF NOT EXISTS course_features (
    course_id              TEXT PRIMARY KEY,
    total_distance_m       DOUBLE PRECISION NOT NULL,
    total_elevation_gain_m DOUBLE PRECISION NOT NULL,
    total_elevation_loss_m DOUBLE PRECISION NOT NULL,
    avg_slope_percent      DOUBLE PRECISION NOT NULL,
    max_slope_percent      DOUBLE PRECISION NOT NULL,
    avg_difficulty_score   DOUBLE PRECISION NOT NULL,
    edge_count             INTEGER NOT NULL,
    summit_id              TEXT,
    cluster_id             INTEGER NOT NULL,
    feature_vector         TEXT NOT NULL,
    created_at             TIMESTAMP NOT NULL DEFAULT now(),
    updated_at             TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_course_features_cluster
    ON course_features (cluster_id);

CREATE INDEX IF NOT EXISTS idx_course_features_summit
    ON course_features (summit_id);
