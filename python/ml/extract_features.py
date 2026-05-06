"""trail_edges에서 source_gpx 단위로 코스별 feature 6종을 집계해 CSV로 저장한다.

실행: backend/python/ 디렉토리에서 `python -m ml.extract_features`
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import psycopg2

# Windows 콘솔(cp949)에서 한글/이모지가 깨지는 것을 방지
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

# scripts/c_analyze/config.py 재사용 (해당 폴더는 패키지가 아니라 단일 모듈)
_PYTHON_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PYTHON_ROOT / "scripts" / "c_analyze"))

from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD  # noqa: E402

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
OUTPUT_PATH = OUTPUT_DIR / "course_features.csv"

EXPECTED_ROW_COUNT = 5003

FEATURE_COLUMNS = [
    "total_distance_m",
    "total_elevation_gain_m",
    "total_elevation_loss_m",
    "avg_slope_percent",
    "max_slope_percent",
    "avg_difficulty_score",
]

# CLAUDE.md §8-1 feature_vector 순서를 따른다.
# avg/max_slope_percent는 단순 집계(거리 가중 X, 절댓값 변환 X) — 데이터 분포 보고 향후 조정.
QUERY = """
SELECT
    source_gpx                                                                      AS course_id,
    SUM(distance_m)                                                                 AS total_distance_m,
    SUM(CASE WHEN elevation_diff_m > 0 THEN  elevation_diff_m ELSE 0 END)           AS total_elevation_gain_m,
    SUM(CASE WHEN elevation_diff_m < 0 THEN -elevation_diff_m ELSE 0 END)           AS total_elevation_loss_m,
    AVG(slope_percent)                                                              AS avg_slope_percent,
    MAX(slope_percent)                                                              AS max_slope_percent,
    AVG(difficulty_score)                                                           AS avg_difficulty_score,
    COUNT(*)                                                                        AS edge_count,
    COUNT(nearest_summit_id)                                                        AS summit_matched_edge_count
FROM trail_edges
WHERE source_gpx IS NOT NULL
GROUP BY source_gpx
ORDER BY source_gpx
"""


def fetch_features() -> pd.DataFrame:
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )
    try:
        return pd.read_sql(QUERY, conn)
    finally:
        conn.close()


def report_nan(df: pd.DataFrame) -> None:
    nan_mask = df[FEATURE_COLUMNS].isna().any(axis=1)
    nan_count = int(nan_mask.sum())
    print(f"[NaN 검증] NaN 포함 코스 수: {nan_count}")
    if nan_count > 0:
        nan_rows = df.loc[nan_mask, ["course_id", *FEATURE_COLUMNS]]
        print("  NaN 발생 코스 (최대 20건):")
        print(nan_rows.head(20).to_string(index=False))


def report_summit_match(df: pd.DataFrame) -> None:
    total_edges = int(df["edge_count"].sum())
    matched_edges = int(df["summit_matched_edge_count"].sum())
    rate = (matched_edges / total_edges * 100.0) if total_edges else 0.0
    print(
        f"[summit 매칭률] nearest_summit_id 보유 edge: "
        f"{matched_edges}/{total_edges} ({rate:.2f}%)"
    )


def main() -> int:
    print(f"DB 연결: {DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME}")
    print("[1/3] trail_edges에서 코스별 feature 집계 중...")
    df = fetch_features()
    row_count = len(df)
    print(f"  distinct course_id 수: {row_count}")
    if row_count != EXPECTED_ROW_COUNT:
        print(f"  ⚠️  예상값({EXPECTED_ROW_COUNT})과 다름")

    print("[2/3] 검증")
    report_nan(df)
    report_summit_match(df)

    print("[3/3] CSV 저장")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_df = df[["course_id", *FEATURE_COLUMNS, "edge_count"]]
    out_df.to_csv(OUTPUT_PATH, index=False)
    print(f"  저장 완료: {OUTPUT_PATH}")
    print("  sample (head 5):")
    print(out_df.head().to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
