# DB Migrations

Flyway/Liquibase 같은 마이그레이션 도구를 쓰지 않는다 (`spring.jpa.hibernate.ddl-auto: none`).
스키마 변경은 이 폴더의 SQL 파일을 **psql로 직접 실행**해서 반영한다.

## 파일 네이밍

```
YYYYMMDD_NNN_설명.sql
```

- `YYYYMMDD`: 작성 날짜 (예: `20260428`)
- `NNN`: 같은 날짜 내 순번 (`001`부터)
- `설명`: 영문 snake_case 짧게 (예: `add_trail_edges_source_gpx`)

예: `20260428_001_add_trail_edges_source_gpx.sql`

## 작성 규칙

- **멱등하게 작성**한다. 여러 번 실행해도 안전해야 함.
  - `ADD COLUMN IF NOT EXISTS`
  - `CREATE INDEX IF NOT EXISTS`
  - `DROP ... IF EXISTS`
- DROP/파괴적 변경은 파일 상단에 주석으로 명시.
- 파일 상단에 **변경 이유**를 한국어 주석으로 남긴다.

## 적용 방법

```bash
psql -h localhost -U postgres -d orda -f migrations/20260428_001_add_trail_edges_source_gpx.sql
```

## 참고

- `db.sql` (백엔드 루트): 전체 스키마 부트스트랩용 (DROP TABLE 포함, **파괴적**).
  로컬 초기 세팅 또는 전부 다시 만들 때만 사용.
- `python/scripts/c_analyze/schema.sql`: C단계 PostGIS 적재용 스키마 정의 원본.
- 이 폴더(`migrations/`): 운영/개발 DB에 **누적 적용**할 변경 사항.
