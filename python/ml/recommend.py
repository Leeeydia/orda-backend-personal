"""코사인 유사도 기반 코스 추천 함수.

알고리즘:
  1. course_features 전체를 DB에서 로드해 StandardScaler로 정규화
  2. 입력 코스(또는 사용자 centroid)의 같은 cluster_id 코스들을 후보로 선정
  3. 후보가 limit 미만이면 전체 코스로 확장(cluster 소규모 fallback)
  4. 코사인 유사도 내림차순 top N 반환

실행:
  python -m ml.recommend --course-id "지리산_0000000001.gpx"
  python -m ml.recommend --user-id 1
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import psycopg2
from sklearn.preprocessing import StandardScaler

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

_PYTHON_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PYTHON_ROOT / "scripts" / "c_analyze"))

from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD  # noqa: E402

FEATURE_COLUMNS = [
    "total_distance_m",
    "total_elevation_gain_m",
    "total_elevation_loss_m",
    "avg_slope_percent",
    "max_slope_percent",
    "avg_difficulty_score",
]

LOAD_SQL = """
SELECT
    course_id, summit_id, cluster_id,
    total_distance_m, total_elevation_gain_m, total_elevation_loss_m,
    avg_slope_percent, max_slope_percent, avg_difficulty_score,
    feature_vector
FROM course_features
ORDER BY course_id
"""

SUMMIT_NAME_SQL = """
SELECT summit_id, name FROM summit_points WHERE summit_id = ANY(%s)
"""

USER_SUMMIT_SQL = """
SELECT DISTINCT sv.summit_id
FROM hiking_sessions hs
JOIN summit_verifications sv ON hs.session_id = sv.session_id
WHERE hs.user_id = %s
"""

COURSE_BY_SUMMIT_SQL = """
SELECT course_id FROM course_features WHERE summit_id = ANY(%s)
"""


@dataclass
class CourseRow:
    course_id: str
    summit_id: str | None
    cluster_id: int
    raw_vector: list[float]


@dataclass
class RecommendResult:
    course_id: str
    summit_id: str | None
    summit_name: str | None
    total_distance_m: float
    total_elevation_gain_m: float
    avg_slope_percent: float
    avg_difficulty_score: float
    similarity_score: float
    cluster_id: int


def _connect() -> psycopg2.extensions.connection:
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASSWORD,
    )


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _parse_vector(fv_str: str) -> list[float]:
    return json.loads(fv_str)


def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


class RecommendEngine:
    """DB에서 course_features를 로드하고 코사인 유사도 추천을 수행한다."""

    def __init__(self, conn: psycopg2.extensions.connection) -> None:
        self._conn = conn
        self._rows: list[CourseRow] = []
        self._scaled: np.ndarray = np.array([])
        self._scaler: StandardScaler = StandardScaler()
        self._index: dict[str, int] = {}
        self._raw_matrix: np.ndarray = np.array([])
        self._extra: dict[str, dict] = {}  # course_id → extra fields for output
        self._summit_names: dict[str, str] = {}

    def load(self) -> None:
        with self._conn.cursor() as cur:
            cur.execute(LOAD_SQL)
            rows_raw = cur.fetchall()

        self._rows = []
        raw_vectors = []
        for r in rows_raw:
            course_id_raw, summit_id, cluster_id, d_m, gain, loss, slope, max_slope, diff, fv_str = r
            course_id = _nfc(course_id_raw)  # DB는 NFD, 비교를 위해 NFC로 통일
            vec = _parse_vector(fv_str)
            self._rows.append(CourseRow(
                course_id=course_id,
                summit_id=summit_id,
                cluster_id=int(cluster_id),
                raw_vector=vec,
            ))
            self._extra[course_id] = {
                "total_distance_m": float(d_m),
                "total_elevation_gain_m": float(gain),
                "avg_slope_percent": float(slope),
                "avg_difficulty_score": float(diff),
                "cluster_id": int(cluster_id),
                "summit_id": summit_id,
            }
            raw_vectors.append(vec)
            self._index[course_id] = len(self._rows) - 1

        self._raw_matrix = np.array(raw_vectors, dtype=float)
        self._scaled = self._scaler.fit_transform(self._raw_matrix)

        # summit_name 일괄 조회
        summit_ids = list({r.summit_id for r in self._rows if r.summit_id})
        if summit_ids:
            with self._conn.cursor() as cur:
                cur.execute(SUMMIT_NAME_SQL, (summit_ids,))
                self._summit_names = {row[0]: row[1] for row in cur.fetchall()}

    def _build_results(
        self,
        query_vec_scaled: np.ndarray,
        candidate_indices: list[int],
        exclude_ids: set[str],
        limit: int,
    ) -> list[RecommendResult]:
        scores: list[tuple[float, int]] = []
        for idx in candidate_indices:
            cid = self._rows[idx].course_id
            if cid in exclude_ids:
                continue
            sim = _cosine_sim(query_vec_scaled, self._scaled[idx])
            scores.append((sim, idx))

        scores.sort(key=lambda x: x[0], reverse=True)

        results = []
        for sim, idx in scores[:limit]:
            row = self._rows[idx]
            ex = self._extra[row.course_id]
            results.append(RecommendResult(
                course_id=row.course_id,
                summit_id=row.summit_id,
                summit_name=self._summit_names.get(row.summit_id) if row.summit_id else None,
                total_distance_m=ex["total_distance_m"],
                total_elevation_gain_m=ex["total_elevation_gain_m"],
                avg_slope_percent=ex["avg_slope_percent"],
                avg_difficulty_score=ex["avg_difficulty_score"],
                similarity_score=round(sim, 6),
                cluster_id=ex["cluster_id"],
            ))
        return results

    def _candidate_indices(
        self, cluster_id: int, exclude_ids: set[str], limit: int
    ) -> tuple[list[int], bool]:
        """같은 cluster 후보 → 부족하면 전체로 확장. fallback 여부도 반환."""
        same = [i for i, r in enumerate(self._rows)
                if r.cluster_id == cluster_id and r.course_id not in exclude_ids]
        if len(same) >= limit:
            return same, False
        # fallback: 전체 풀
        all_idx = [i for i, r in enumerate(self._rows) if r.course_id not in exclude_ids]
        return all_idx, True

    def recommend_by_course(self, course_id: str, limit: int = 5) -> list[RecommendResult]:
        if course_id not in self._index:
            raise ValueError(f"course_id not found: {course_id}")

        idx = self._index[course_id]
        row = self._rows[idx]
        candidates, fallback = self._candidate_indices(row.cluster_id, {course_id}, limit)

        if fallback:
            print(f"  [fallback] cluster {row.cluster_id} 후보 부족 → 전체 코스 풀로 확장")

        return self._build_results(self._scaled[idx], candidates, {course_id}, limit)

    def recommend_by_user(self, user_id: int, limit: int = 5) -> list[RecommendResult]:
        with self._conn.cursor() as cur:
            cur.execute(USER_SUMMIT_SQL, (user_id,))
            verified_summit_ids = [r[0] for r in cur.fetchall()]

        if not verified_summit_ids:
            return []

        with self._conn.cursor() as cur:
            cur.execute(COURSE_BY_SUMMIT_SQL, (verified_summit_ids,))
            visited_course_ids = {_nfc(r[0]) for r in cur.fetchall()}

        if not visited_course_ids:
            return []

        # 방문 코스들의 scaled feature 평균 → centroid
        visited_indices = [self._index[cid] for cid in visited_course_ids if cid in self._index]
        if not visited_indices:
            return []

        centroid_raw = self._raw_matrix[visited_indices].mean(axis=0, keepdims=True)
        centroid_scaled = self._scaler.transform(centroid_raw)[0]

        # centroid와 가장 가까운 cluster 찾기 (스케일된 공간에서 최빈 cluster)
        cluster_ids = [self._rows[i].cluster_id for i in visited_indices]
        from collections import Counter
        dominant_cluster = Counter(cluster_ids).most_common(1)[0][0]

        candidates, fallback = self._candidate_indices(dominant_cluster, visited_course_ids, limit)
        if fallback:
            print(f"  [fallback] cluster {dominant_cluster} 후보 부족 → 전체 코스 풀로 확장")

        return self._build_results(centroid_scaled, candidates, visited_course_ids, limit)


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────

def _print_table(results: list[RecommendResult]) -> None:
    if not results:
        print("  추천 결과 없음")
        return
    header = f"{'course_id':<40} {'summit_name':<20} {'dist_m':>9} {'gain_m':>8} {'sim':>8} {'cluster':>7}"
    print(header)
    print("-" * len(header))
    for r in results:
        sname = (r.summit_name or "-")[:20]
        print(
            f"{r.course_id:<40} {sname:<20} "
            f"{r.total_distance_m:>9.0f} {r.total_elevation_gain_m:>8.0f} "
            f"{r.similarity_score:>8.4f} {r.cluster_id:>7}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="코스 추천 CLI")
    parser.add_argument("--course-id", help="추천 기준 course_id")
    parser.add_argument("--user-id", type=int, help="추천 대상 user_id")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    if not args.course_id and not args.user_id:
        parser.error("--course-id 또는 --user-id 중 하나는 필수입니다")

    conn = _connect()
    try:
        engine = RecommendEngine(conn)
        engine.load()
        print(f"코스 로드 완료: {len(engine._rows)}건\n")

        if args.course_id:
            course_id_arg = _nfc(args.course_id)
            print(f"=== 코스 기반 추천: {course_id_arg} ===")
            idx = engine._index.get(course_id_arg)
            if idx is None:
                print(f"  ❌ 해당 course_id가 없습니다: {course_id_arg}")
                return 1
            row = engine._rows[idx]
            ex = engine._extra[course_id_arg]
            print(
                f"  입력: dist={ex['total_distance_m']:.0f}m, "
                f"gain={ex['total_elevation_gain_m']:.0f}m, "
                f"cluster={row.cluster_id}"
            )
            results = engine.recommend_by_course(course_id_arg, args.limit)
            _print_table(results)

        if args.user_id:
            print(f"\n=== 사용자 기반 추천: user_id={args.user_id} ===")
            results = engine.recommend_by_user(args.user_id, args.limit)
            if not results:
                print("  산행 기록이 쌓이면 추천해드릴게요 (인증 코스 0건)")
            else:
                _print_table(results)

    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
