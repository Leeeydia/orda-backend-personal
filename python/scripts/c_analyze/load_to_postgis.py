from __future__ import annotations

import json
from typing import Any

import psycopg2
from psycopg2.extras import execute_values

from config import (
    DB_HOST,
    DB_PORT,
    DB_NAME,
    DB_USER,
    DB_PASSWORD,
    NODE_ELEVATION_PATH,
    FINAL_TRAIL_DATASET_PATH,
    SUMMIT_POINTS_PATH,
)
from pipeline import read_geojson_features


def get_connection():
    """PostgreSQL 접속 연결을 반환한다."""
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )


# ──────────────────────────────────────────────
# 유틸
# ──────────────────────────────────────────────

def table_exists(cursor, table_name: str) -> bool:
    """public 스키마에 해당 테이블이 존재하는지 확인한다."""
    cursor.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = %s)",
        (table_name,),
    )
    return cursor.fetchone()[0]


# ──────────────────────────────────────────────
# 적재 함수
# ──────────────────────────────────────────────

def load_nodes(cursor, features: list[dict[str, Any]]) -> int:
    """node_with_elevation.geojson → trail_nodes 테이블에 배치 적재한다."""
    sql = """
          INSERT INTO trail_nodes (
              node_id, node_type, degree,
              elevation_m, elevation_status, qa_status,
              geom
          ) VALUES %s
              ON CONFLICT (node_id) DO NOTHING
          """

    template = "(%(node_id)s, %(node_type)s, %(degree)s, %(elevation_m)s, %(elevation_status)s, %(qa_status)s, ST_SetSRID(ST_GeomFromGeoJSON(%(geom)s), 4326))"

    rows = []
    for feat in features:
        props = feat.get("properties", {})
        geom = feat.get("geometry")
        if not geom:
            continue

        rows.append({
            "node_id": props.get("node_id"),
            "node_type": props.get("node_type"),
            "degree": props.get("degree"),
            "elevation_m": props.get("elevation_m"),
            "elevation_status": props.get("elevation_status"),
            "qa_status": props.get("qa_status"),
            "geom": json.dumps(geom),
        })

    if not rows:
        return 0

    execute_values(cursor, sql, rows, template=template, page_size=1000)
    return cursor.rowcount


def load_edges(cursor, features: list[dict[str, Any]]) -> int:
    """final_trail_dataset.geojson → trail_edges 테이블에 배치 적재한다."""
    sql = """
          INSERT INTO trail_edges (
              edge_id, source_gpx,
              start_node_id, end_node_id,
              distance_m, elevation_start_m, elevation_end_m,
              elevation_diff_m, slope_percent, difficulty_score, difficulty,
              surface, nearest_summit_id, qa_status,
              geom
          ) VALUES %s
              ON CONFLICT (edge_id) DO NOTHING
          """

    template = "(%(edge_id)s, %(source_gpx)s, %(start_node_id)s, %(end_node_id)s, %(distance_m)s, %(elevation_start_m)s, %(elevation_end_m)s, %(elevation_diff_m)s, %(slope_percent)s, %(difficulty_score)s, %(difficulty)s, %(surface)s, %(nearest_summit_id)s, %(qa_status)s, ST_SetSRID(ST_GeomFromGeoJSON(%(geom)s), 4326))"

    rows = []
    for feat in features:
        props = feat.get("properties", {})
        geom = feat.get("geometry")
        if not geom:
            continue

        rows.append({
            "edge_id": props.get("edge_id"),
            "source_gpx": props.get("source_gpx"),
            "start_node_id": props.get("start_node_id"),
            "end_node_id": props.get("end_node_id"),
            "distance_m": props.get("distance_m"),
            "elevation_start_m": props.get("elevation_start_m"),
            "elevation_end_m": props.get("elevation_end_m"),
            "elevation_diff_m": props.get("elevation_diff_m"),
            "slope_percent": props.get("slope_percent"),
            "difficulty_score": props.get("difficulty_score"),
            "difficulty": props.get("difficulty"),
            "surface": props.get("surface"),
            "nearest_summit_id": props.get("nearest_summit_id"),
            "qa_status": props.get("qa_status"),
            "geom": json.dumps(geom),
        })

    if not rows:
        return 0

    execute_values(cursor, sql, rows, template=template, page_size=1000)
    return cursor.rowcount


def load_summits(cursor, features: list[dict[str, Any]]) -> int:
    """summit_points.geojson → summit_points 테이블에 배치 적재한다."""
    sql = """
          INSERT INTO summit_points (
              summit_id, name, elevation_m,
              source, radius_m,
              geom
          ) VALUES %s
              ON CONFLICT (summit_id) DO NOTHING
          """

    template = "(%(summit_id)s, %(name)s, %(elevation_m)s, %(source)s, %(radius_m)s, ST_SetSRID(ST_GeomFromGeoJSON(%(geom)s), 4326))"

    rows = []
    for feat in features:
        props = feat.get("properties", {})
        geom = feat.get("geometry")
        if not geom:
            continue

        rows.append({
            "summit_id": props.get("summit_id"),
            "name": props.get("name"),
            "elevation_m": props.get("elevation_m"),
            "source": props.get("source"),
            "radius_m": props.get("radius_m"),
            "geom": json.dumps(geom),
        })

    if not rows:
        return 0

    execute_values(cursor, sql, rows, template=template, page_size=1000)
    return cursor.rowcount


# ──────────────────────────────────────────────
# 적재 후 검증
# ──────────────────────────────────────────────

def verify_counts(cursor) -> None:
    """적재 후 각 테이블 row 수를 출력한다."""
    tables = ["trail_nodes", "trail_edges", "summit_points"]

    print("\n[적재 검증]")
    for table in tables:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        print(f"  {table}: {count}행")


def verify_spatial(cursor) -> None:
    """공간 데이터가 정상인지 간단히 확인한다."""
    print("\n[공간 데이터 검증]")

    cursor.execute("SELECT COUNT(*) FROM trail_nodes WHERE geom IS NULL")
    null_nodes = cursor.fetchone()[0]
    print(f"  trail_nodes geom NULL: {null_nodes}개")

    cursor.execute("SELECT COUNT(*) FROM trail_edges WHERE geom IS NULL")
    null_edges = cursor.fetchone()[0]
    print(f"  trail_edges geom NULL: {null_edges}개")

    cursor.execute("SELECT ST_SRID(geom) FROM trail_nodes LIMIT 1")
    row = cursor.fetchone()
    if row:
        print(f"  trail_nodes SRID: {row[0]}")

    cursor.execute("SELECT ST_SRID(geom) FROM trail_edges LIMIT 1")
    row = cursor.fetchone()
    if row:
        print(f"  trail_edges SRID: {row[0]}")

    cursor.execute("""
                   SELECT COUNT(*) FROM trail_edges e
                   WHERE NOT EXISTS (
                       SELECT 1 FROM trail_nodes n WHERE n.node_id = e.start_node_id
                   )
                      OR NOT EXISTS (
                       SELECT 1 FROM trail_nodes n WHERE n.node_id = e.end_node_id
                   )
                   """)
    orphan = cursor.fetchone()[0]
    print(f"  edge → node 참조 실패: {orphan}개")


def verify_source_gpx(cursor) -> None:
    """추천 기능에 필요한 source_gpx 적재 상태를 확인한다."""
    print("\n[GPX 출처 검증]")

    cursor.execute("SELECT COUNT(*) FROM trail_edges")
    total = cursor.fetchone()[0]

    cursor.execute("""
                   SELECT COUNT(*)
                   FROM trail_edges
                   WHERE source_gpx IS NOT NULL
                     AND source_gpx <> ''
                   """)
    with_source_gpx = cursor.fetchone()[0]

    cursor.execute("""
                   SELECT COUNT(DISTINCT source_gpx)
                   FROM trail_edges
                   WHERE source_gpx IS NOT NULL
                     AND source_gpx <> ''
                   """)
    distinct_source_gpx = cursor.fetchone()[0]

    print(f"  source_gpx 있음: {with_source_gpx}개 / 없음: {total - with_source_gpx}개")
    print(f"  distinct source_gpx: {distinct_source_gpx}개")

    cursor.execute("""
                   SELECT source_gpx, COUNT(*) AS edge_count
                   FROM trail_edges
                   WHERE source_gpx IS NOT NULL
                     AND source_gpx <> ''
                   GROUP BY source_gpx
                   ORDER BY edge_count DESC, source_gpx
                       LIMIT 5
                   """)
    rows = cursor.fetchall()

    print("  source_gpx 샘플:")
    for source_gpx, edge_count in rows:
        print(f"    - {source_gpx}: {edge_count}개 edge")


# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────

def main() -> None:
    print("[PostGIS 적재] 시작...")

    print("\n[1] GeoJSON 로딩")
    node_features = read_geojson_features(NODE_ELEVATION_PATH)
    edge_features = read_geojson_features(FINAL_TRAIL_DATASET_PATH)
    summit_features = read_geojson_features(SUMMIT_POINTS_PATH)

    print(f"  nodes: {len(node_features)}개")
    print(f"  edges: {len(edge_features)}개")
    print(f"  summits: {len(summit_features)}개")

    print("\n[2] DB 접속 및 적재")
    conn = get_connection()
    cursor = conn.cursor()

    try:
        print("  기존 데이터 초기화...")

        if table_exists(cursor, "summit_verifications"):
            cursor.execute("TRUNCATE summit_verifications")
            print("    summit_verifications 초기화 완료")

        cursor.execute("TRUNCATE trail_edges, trail_nodes, summit_points CASCADE")
        print("    trail 테이블 초기화 완료")

        node_count = load_nodes(cursor, node_features)
        print(f"  trail_nodes 적재: {node_count}건")

        edge_count = load_edges(cursor, edge_features)
        print(f"  trail_edges 적재: {edge_count}건")

        summit_count = load_summits(cursor, summit_features)
        print(f"  summit_points 적재: {summit_count}건")

        verify_counts(cursor)
        verify_spatial(cursor)
        verify_source_gpx(cursor)

        conn.commit()
        print("\n[완료] 적재 성공, 커밋됨")

    except Exception as e:
        conn.rollback()
        print(f"\n[오류] 적재 실패, 롤백됨: {e}")
        raise

    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()