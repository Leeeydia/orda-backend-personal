"""course_features + course_clusters CSV를 합쳐 course_features 테이블에 적재한다.

- feature_vector: 정규화 전 원본 값 6개를 JSON 문자열로 저장 (CLAUDE.md §8-1 순서)
- summit_id: trail_edges에서 코스별 nearest_summit_id 최빈값 (NULL 코스는 NULL 유지)
- UPSERT: ON CONFLICT (course_id) DO UPDATE — 재실행 안전
- 트랜잭션 보호: 실패 시 전체 롤백

실행: backend/python/ 디렉토리에서 `python -m ml.load_to_db`
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

_PYTHON_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PYTHON_ROOT / "scripts" / "c_analyze"))

from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD  # noqa: E402

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
FEATURES_CSV = OUTPUT_DIR / "course_features.csv"
CLUSTERS_CSV = OUTPUT_DIR / "course_clusters.csv"

FEATURE_COLUMNS = [
    "total_distance_m",
    "total_elevation_gain_m",
    "total_elevation_loss_m",
    "avg_slope_percent",
    "max_slope_percent",
    "avg_difficulty_score",
]

CHECK_TABLE_SQL = """
SELECT COUNT(*) FROM information_schema.tables
WHERE table_schema = 'public' AND table_name = 'course_features'
"""

SUMMIT_SQL = """
SELECT source_gpx AS course_id, nearest_summit_id
FROM trail_edges
WHERE source_gpx IS NOT NULL
  AND nearest_summit_id IS NOT NULL
"""

# created_at/updated_at은 template에서 now()로 직접 삽입
UPSERT_SQL = """
INSERT INTO course_features (
    course_id,
    total_distance_m, total_elevation_gain_m, total_elevation_loss_m,
    avg_slope_percent, max_slope_percent, avg_difficulty_score,
    edge_count, summit_id, cluster_id, feature_vector,
    created_at, updated_at
) VALUES %s
ON CONFLICT (course_id) DO UPDATE SET
    total_distance_m       = EXCLUDED.total_distance_m,
    total_elevation_gain_m = EXCLUDED.total_elevation_gain_m,
    total_elevation_loss_m = EXCLUDED.total_elevation_loss_m,
    avg_slope_percent      = EXCLUDED.avg_slope_percent,
    max_slope_percent      = EXCLUDED.max_slope_percent,
    avg_difficulty_score   = EXCLUDED.avg_difficulty_score,
    edge_count             = EXCLUDED.edge_count,
    summit_id              = EXCLUDED.summit_id,
    cluster_id             = EXCLUDED.cluster_id,
    feature_vector         = EXCLUDED.feature_vector,
    updated_at             = now()
"""
UPSERT_TEMPLATE = "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())"


def connect() -> psycopg2.extensions.connection:
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASSWORD,
    )


def check_table_exists(conn) -> bool:
    with conn.cursor() as cur:
        cur.execute(CHECK_TABLE_SQL)
        return cur.fetchone()[0] > 0


def fetch_summit_mode(conn) -> dict[str, str]:
    """코스별 nearest_summit_id 최빈값을 {course_id: summit_id} 딕셔너리로 반환."""
    df = pd.read_sql(SUMMIT_SQL, conn)
    if df.empty:
        return {}
    mode_series = (
        df.groupby("course_id")["nearest_summit_id"]
        .agg(lambda s: s.mode().iloc[0])
    )
    return mode_series.to_dict()


def load_and_merge() -> pd.DataFrame:
    features = pd.read_csv(FEATURES_CSV)
    clusters = pd.read_csv(CLUSTERS_CSV)
    df = features.merge(clusters, on="course_id", how="inner")
    missing = len(features) - len(df)
    if missing:
        print(f"  ⚠️  cluster 없는 코스 {missing}건 제외됨")
    return df


def impute(df: pd.DataFrame) -> pd.DataFrame:
    nan_count = int(df[FEATURE_COLUMNS].isna().any(axis=1).sum())
    if nan_count:
        print(f"  [Imputation] NaN 포함 코스 {nan_count}건 — 컬럼 평균으로 대체")
        for col in FEATURE_COLUMNS:
            df[col] = df[col].fillna(float(df[col].mean()))
    else:
        print("  [Imputation] NaN 없음")
    return df


def make_feature_vector(row: pd.Series) -> str:
    vals = []
    for col in FEATURE_COLUMNS:
        v = row[col]
        vals.append(None if (v is None or (isinstance(v, float) and np.isnan(v))) else float(v))
    return json.dumps(vals)


def build_rows(df: pd.DataFrame, summit_map: dict) -> list[tuple]:
    rows = []
    for _, row in df.iterrows():
        course_id = str(row["course_id"])
        rows.append((
            course_id,
            float(row["total_distance_m"]),
            float(row["total_elevation_gain_m"]),
            float(row["total_elevation_loss_m"]),
            float(row["avg_slope_percent"]),
            float(row["max_slope_percent"]),
            float(row["avg_difficulty_score"]),
            int(row["edge_count"]),
            summit_map.get(course_id),       # None이면 NULL
            int(row["cluster_id"]),
            make_feature_vector(row),
        ))
    return rows


def verify(conn) -> None:
    print("\n=== 적재 검증 ===")
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM course_features")
        total = cur.fetchone()[0]
        print(f"  총 row 수: {total} (기대: 5003)")

        cur.execute(
            "SELECT cluster_id, COUNT(*) FROM course_features "
            "GROUP BY cluster_id ORDER BY cluster_id"
        )
        print("  cluster별 분포:")
        for cluster_id, cnt in cur.fetchall():
            pct = cnt / total * 100 if total else 0.0
            print(f"    cluster {cluster_id}: {cnt} ({pct:.1f}%)")

        cur.execute("SELECT COUNT(*) FROM course_features WHERE summit_id IS NULL")
        null_summit = cur.fetchone()[0]
        null_pct = null_summit / total * 100 if total else 0.0
        print(f"  summit_id NULL: {null_summit}/{total} ({null_pct:.1f}%)")

        cur.execute("SELECT COUNT(*) FROM course_features WHERE feature_vector IS NULL")
        null_fv = cur.fetchone()[0]
        print(f"  feature_vector NULL: {null_fv}건")

        cur.execute(
            "SELECT COUNT(*) FROM course_features WHERE feature_vector NOT LIKE '[%'"
        )
        bad_fv = cur.fetchone()[0]
        if bad_fv:
            print(f"  ⚠️  feature_vector 형식 이상 (JSON 배열 아님): {bad_fv}건")
        else:
            print("  feature_vector 형식 정상")


def main() -> int:
    print(f"DB: {DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME}")

    conn = connect()
    try:
        print("[0/4] 테이블 존재 여부 확인")
        if not check_table_exists(conn):
            print("  ❌ course_features 테이블 없음 — 마이그레이션 먼저 실행하세요")
            print("  migrations/20260510_002_create_course_features.sql")
            return 1
        print("  OK")

        print("[1/4] CSV 로드 및 병합")
        df = load_and_merge()
        df = impute(df)
        print(f"  코스 수: {len(df)}")

        print("[2/4] trail_edges에서 코스별 최빈 summit_id 조회")
        summit_map = fetch_summit_mode(conn)
        matched = sum(1 for cid in df["course_id"] if cid in summit_map)
        print(f"  summit_id 매칭: {matched}/{len(df)}")

        print("[3/4] UPSERT (트랜잭션)")
        rows = build_rows(df, summit_map)
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur, UPSERT_SQL, rows, template=UPSERT_TEMPLATE, page_size=500
            )
        conn.commit()
        print(f"  커밋 완료: {len(rows)}건")

        print("[4/4] 검증")
        verify(conn)

    except Exception as exc:
        conn.rollback()
        print(f"  ❌ 오류 발생 — 롤백: {exc}")
        raise
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
