"""추천 API 검증용 테스트 데이터 시딩 스크립트.

시나리오:
  user_id 1 — cluster 0 (짧은 평지) 코스 3개 인증
  user_id 2 — cluster 3 (긴 산악)   코스 3개 인증
  user_id 3 — 인증 0건 (변경 없음)

멱등성:
  이미 시드된 user(hiking_sessions 있음)는 --reset 없이 재실행하면 스킵.
  --reset 시 해당 user의 sessions + verifications 삭제 후 재시딩.

실행:
  python -m ml.seed_test_data
  python -m ml.seed_test_data --reset
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

import psycopg2
import psycopg2.extras

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

_PYTHON_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PYTHON_ROOT / "scripts" / "c_analyze"))

from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD  # noqa: E402

# 시딩 대상
SEED_TARGETS = [
    {"user_id": 1, "cluster_id": 0, "label": "짧은 평지"},
    {"user_id": 2, "cluster_id": 3, "label": "긴 산악"},
]
COURSES_PER_USER = 3
SEEDED_USER_IDS = [t["user_id"] for t in SEED_TARGETS]

CANDIDATES_SQL = """
SELECT cf.course_id, cf.summit_id
FROM course_features cf
WHERE cf.cluster_id = %(cluster_id)s
  AND cf.summit_id IS NOT NULL
ORDER BY cf.total_distance_m ASC
LIMIT %(limit)s
"""

SUMMIT_GEOM_SQL = """
SELECT ST_AsText(geom) FROM summit_points WHERE summit_id = %s
"""

TRAIL_GEOM_SQL = """
SELECT ST_AsText(ST_StartPoint(geom)), ST_AsText(ST_EndPoint(geom))
FROM trail_edges
WHERE source_gpx = %s
ORDER BY edge_id
LIMIT 1
"""

INSERT_SESSION_SQL = """
INSERT INTO hiking_sessions (user_id, status, started_at, ended_at, created_at)
VALUES (%s, 'COMPLETED', %s, %s, %s)
RETURNING session_id
"""

INSERT_VERIFICATION_SQL = """
INSERT INTO summit_verifications
    (session_id, summit_id, distance_to_summit_m, verification_method, verified_at, geom)
VALUES (%s, %s, %s, 'gps', %s, ST_GeomFromText(%s, 4326))
ON CONFLICT (session_id, summit_id, verification_method) DO NOTHING
"""

SESSION_COUNT_SQL = """
SELECT COUNT(*) FROM hiking_sessions WHERE user_id = %s
"""

USER_EXISTS_SQL = """
SELECT COUNT(*) FROM users WHERE user_id = %s
"""

DELETE_VERIFICATIONS_SQL = """
DELETE FROM summit_verifications
WHERE session_id IN (
    SELECT session_id FROM hiking_sessions WHERE user_id = %s
)
"""

DELETE_SESSIONS_SQL = """
DELETE FROM hiking_sessions WHERE user_id = %s
"""

VERIFY_SQL = """
SELECT hs.user_id, COUNT(sv.verification_id) AS verif_count
FROM hiking_sessions hs
LEFT JOIN summit_verifications sv ON hs.session_id = sv.session_id
WHERE hs.user_id = ANY(%s)
GROUP BY hs.user_id
ORDER BY hs.user_id
"""


def _connect() -> psycopg2.extensions.connection:
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASSWORD,
    )


def _random_started_at() -> datetime:
    """최근 7일 내 임의 시각."""
    offset_seconds = random.randint(0, 7 * 24 * 3600)
    return datetime.now() - timedelta(seconds=offset_seconds)


def _check_users(conn, user_ids: list[int]) -> None:
    """존재하지 않는 user_id가 있으면 에러 출력 후 종료."""
    with conn.cursor() as cur:
        missing = []
        for uid in user_ids:
            cur.execute(USER_EXISTS_SQL, (uid,))
            if cur.fetchone()[0] == 0:
                missing.append(uid)
    if missing:
        print(f"  ❌ 존재하지 않는 user_id: {missing}")
        print("  해당 user를 먼저 INSERT하세요.")
        sys.exit(1)


def _already_seeded(conn, user_id: int) -> int:
    """해당 user의 hiking_sessions 건수를 반환."""
    with conn.cursor() as cur:
        cur.execute(SESSION_COUNT_SQL, (user_id,))
        return cur.fetchone()[0]


def _reset_user(conn, user_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(DELETE_VERIFICATIONS_SQL, (user_id,))
        v_cnt = cur.rowcount
        cur.execute(DELETE_SESSIONS_SQL, (user_id,))
        s_cnt = cur.rowcount
    print(f"  [reset] user_id={user_id}: sessions {s_cnt}건, verifications {v_cnt}건 삭제")


def _get_candidates(conn, cluster_id: int, limit: int) -> list[tuple[str, str]]:
    """(course_id, summit_id) 리스트 반환."""
    with conn.cursor() as cur:
        cur.execute(CANDIDATES_SQL, {"cluster_id": cluster_id, "limit": limit})
        return cur.fetchall()


def _get_summit_geom(conn, summit_id: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute(SUMMIT_GEOM_SQL, (summit_id,))
        row = cur.fetchone()
        return row[0] if row else None


def _get_trail_endpoints(conn, course_id: str) -> tuple[str | None, str | None]:
    with conn.cursor() as cur:
        cur.execute(TRAIL_GEOM_SQL, (course_id,))
        row = cur.fetchone()
        if row:
            return row[0], row[1]
        return None, None


def _seed_user(conn, user_id: int, cluster_id: int, label: str) -> tuple[int, int]:
    """한 user에 대해 시딩 수행. (inserted_sessions, inserted_verifs) 반환."""
    candidates = _get_candidates(conn, cluster_id, COURSES_PER_USER)
    if len(candidates) < COURSES_PER_USER:
        print(f"  ⚠️  cluster {cluster_id} 후보 부족: {len(candidates)}건")

    inserted_sessions = 0
    inserted_verifs = 0

    with conn.cursor() as cur:
        for course_id, summit_id in candidates:
            started_at = _random_started_at()
            ended_at = started_at + timedelta(minutes=random.randint(30, 90))

            cur.execute(INSERT_SESSION_SQL, (
                user_id, started_at, ended_at, started_at,
            ))
            session_id = cur.fetchone()[0]
            inserted_sessions += 1

            summit_geom = _get_summit_geom(conn, summit_id)
            if summit_geom is None:
                print(f"    ⚠️  summit geom 없음: {summit_id} — verif 스킵")
                continue

            verified_at = ended_at - timedelta(minutes=random.randint(1, 10))
            distance = round(random.uniform(5.0, 49.9), 1)

            cur.execute(INSERT_VERIFICATION_SQL, (
                session_id, summit_id, distance, verified_at, summit_geom,
            ))
            if cur.rowcount > 0:
                inserted_verifs += 1
            else:
                print(f"    [skip] 이미 존재: session={session_id}, summit={summit_id}")

    return inserted_sessions, inserted_verifs


def _print_verify(conn) -> None:
    all_ids = SEEDED_USER_IDS + [3]
    with conn.cursor() as cur:
        cur.execute(VERIFY_SQL, (all_ids,))
        rows = cur.fetchall()

    print("\n=== 시딩 후 user별 인증 코스 수 ===")
    for user_id, count in rows:
        print(f"  user_id={user_id}: {count}건")
    if not any(uid in [r[0] for r in rows] for uid in [3]):
        print(f"  user_id=3: 0건 (hiking_sessions 없음)")

    print("\n=== 추천 검증 명령어 ===")
    for uid in [1, 2, 3]:
        print(f"  python -m ml.recommend --user-id {uid}")


def main() -> int:
    parser = argparse.ArgumentParser(description="추천 검증용 테스트 데이터 시딩")
    parser.add_argument(
        "--reset", action="store_true",
        help="기존 시드 데이터 삭제 후 재시딩",
    )
    args = parser.parse_args()

    random.seed()  # 실행마다 다른 시각 생성

    print(f"DB: {DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME}")
    conn = _connect()
    try:
        print("[0/3] user 존재 확인")
        _check_users(conn, SEEDED_USER_IDS)
        print(f"  OK: user_id {SEEDED_USER_IDS} 존재 확인")

        print("[1/3] 기존 시드 데이터 확인")
        needs_seed: list[dict] = []
        for target in SEED_TARGETS:
            uid = target["user_id"]
            count = _already_seeded(conn, uid)
            if count > 0 and not args.reset:
                print(f"  user_id={uid}: 이미 {count}건 존재 — 스킵 (--reset으로 재시딩)")
            else:
                if count > 0 and args.reset:
                    _reset_user(conn, uid)
                needs_seed.append(target)

        if not needs_seed:
            _print_verify(conn)
            return 0

        print(f"[2/3] 시딩 ({len(needs_seed)}명)")
        total_sessions = 0
        total_verifs = 0
        for target in needs_seed:
            uid, cid, label = target["user_id"], target["cluster_id"], target["label"]
            print(f"  user_id={uid} ({label}, cluster {cid})")
            s, v = _seed_user(conn, uid, cid, label)
            print(f"    → sessions {s}건, verifications {v}건 INSERT")
            total_sessions += s
            total_verifs += v

        conn.commit()
        print(f"\n  커밋 완료: sessions {total_sessions}건, verifications {total_verifs}건")

        print("[3/3] 검증")
        _print_verify(conn)

    except Exception as exc:
        conn.rollback()
        print(f"  ❌ 오류 — 롤백: {exc}")
        raise
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
