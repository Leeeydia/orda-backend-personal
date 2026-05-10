# ORDA - Claude Code 작업 가이드

이 레포는 ORDA(한국 등산 기록 앱)의 **개인 실험용 포크**다.
팀 레포는 발표용으로 보존, 이 레포는 ML 추천 기능 개발용.

---

## 1. 프로젝트 개요

- **앱**: GPS 추적, 정상 인증, 난이도 지도 기반 등산 기록 앱
- **현재 작업**: ML 기반 코스 추천 (사용자가 다닌 코스와 비슷한 코스 추천)
- **추천 단위**: 코스 (산이 아니라 GPX 단위)
- **알고리즘**: K-Means + 코사인 유사도 (K값은 실험 후 확정)

---

## 2. 기술 스택

### 백엔드
- Spring Boot 3.5, Java 17, JPA
- PostgreSQL + PostGIS (DB명: `orda`)
- `ddl-auto: none` (스키마 변경은 SQL 직접 실행)
- 인증: JWT + `@AuthenticationPrincipal CustomUserDetails`
  - `userDetails.getUserId()` 로 userId 추출

### 프론트
- React 19, axios
- 상태 관리: useState + useEffect (React Query 미사용)

### ML
- Python (venv)
- 위치: `python/` 폴더

---

## 3. 백엔드 패키지 구조 (검증 완료)

루트 패키지: `com.orda.backend`

```
src/main/java/com/orda/backend/
├── BackendApplication.java
├── common/
│   ├── response/
│   │   └── ApiResponse.java        # ApiResponse.success(msg, data) / ApiResponse.fail(msg)
│   └── exception/
│       ├── BusinessException.java
│       └── GlobalExceptionHandler.java
├── security/
│   └── CustomUserDetails.java      # @AuthenticationPrincipal 주입용
└── domain/
    ├── hiking/
    ├── mountain/                   # MountainController, Top100MountainResponse 등
    ├── stats/
    ├── summit/
    ├── trail/
    └── user/
```

**recommendation 패키지는 없음** — ML 작업 시 `domain/recommendation/` 신규 생성 필요.

각 도메인 내부 구조:
```
{도메인}/
├── controller/
├── service/
├── repository/
├── entity/
├── dto/
│   ├── request/
│   └── response/
└── model/  # 도메인 내부 계산용 (선택)
```

---

## 4. Python 폴더 구조

```
python/
├── data/
│   ├── raw/dem/nasadem/
│   └── interim/
│       ├── a_output/   # A 담당자 산출물 (summit, public_trail)
│       └── b_output/   # B 단계 산출물 (source_gpx 포함)
├── scripts/c_analyze/
│   ├── run_pipeline.py
│   └── load_to_postgis.py
└── ml/                 # 추천 ML 작업 폴더 (예정)
```

---

## 5. 백엔드 응답 규칙

### 5-1. 모든 API는 ApiResponse로 감싼다 (통일됨, 검증 완료)

```java
ResponseEntity<ApiResponse<SomeResponseDto>>
```

```json
{
  "success": true,
  "message": "조회 성공",
  "data": { ... }
}
```

- 성공: `ApiResponse.success("메시지", data)`
- 실패: `ApiResponse.fail("메시지")`
- 메시지는 **한국어** 사용 (기존 컨벤션)

### 5-2. 지도용 API는 GeoJSON

```java
ResponseEntity<ApiResponse<GeoJsonFeatureCollectionResponse>>
```

좌표 순서: `[longitude, latitude]` (경도 먼저)

---

## 6. 네이밍/코드 규칙

| 항목 | 규칙 | 예시 |
|------|------|------|
| 필드 | camelCase | `userId`, `summitName` |
| ID | `xxxId` | `courseId`, `summitId` |
| 거리 | `xxxM` (미터) | `distanceM`, `totalDistanceM` |
| 시간 | `xxxSec` | `durationSec` |
| 빈 결과 | `Collections.emptyList()` | |
| 에러 | `BusinessException throw` | |

---

## 7. 실제 DB 스키마 (검증 완료)

### 7-1. 데이터 현황

| 테이블 | 건수 |
|--------|------|
| `trail_edges` | 25,719 |
| `trail_nodes` | 28,063 |
| `summit_points` | 16,371 |
| `hiking_sessions` | 35 |
| `summit_verifications` | 27 |
| `users` | 5 |

### 7-2. trail_edges (ML 입력 핵심 테이블)

```
edge_id           TEXT PK
source_gpx        TEXT          -- 코스 식별자 (현재 데이터 미적재 상태)
start_node_id     TEXT FK
end_node_id       TEXT FK
distance_m        DOUBLE PRECISION
elevation_start_m DOUBLE PRECISION
elevation_end_m   DOUBLE PRECISION
elevation_diff_m  DOUBLE PRECISION
slope_percent     DOUBLE PRECISION
difficulty_score  DOUBLE PRECISION
difficulty        TEXT
surface           TEXT
nearest_summit_id TEXT
qa_status         TEXT
geom              GEOMETRY(LineString, 4326)
```

`source_gpx` 컬럼 + 인덱스는 schema에 이미 존재. **데이터 적재만 안 된 상태.**

### 7-3. user_id 타입

`users.user_id BIGINT` → 백엔드 DTO에서 `Long` 사용.

---

## 8. ML 추천 작업 정보

### 8-1. course_features 테이블 (마이그레이션 SQL 작성 완료 — DB 적용은 사용자 직접)

> ⚠️ 아래 스키마는 **사용자가 결정한 안**이며, 실제 ML 실험 후 조정될 수 있음.

```sql
CREATE TABLE course_features (
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
CREATE INDEX idx_course_features_cluster ON course_features(cluster_id);
CREATE INDEX idx_course_features_summit ON course_features(summit_id);
```

`feature_vector` 순서 (고정 안):
```
[total_distance_m, total_elevation_gain_m, total_elevation_loss_m,
 avg_slope_percent, max_slope_percent, avg_difficulty_score]
```

### 8-2. 추천 API 명세 (미확정 — 사용자 결정 후 진행)

> ⚠️ 아래 명세는 인계 문서에 있던 **안**이며, 백엔드 코드에는 아직 없음.
> 구현 전 사용자가 최종 확정해야 함.

- **엔드포인트(안)**: `GET /api/recommendations/courses?limit=5`
- **인증**: JWT (`@AuthenticationPrincipal`로 userId 추출)
- **응답 필드(안)**:
  - `courseId`, `summitId`, `summitName`
  - `totalDistanceM`, `totalElevationGainM`
  - `avgSlopePercent`, `avgDifficultyScore`
  - `similarityScore`, `clusterId`
- **fallback(안)** (다닌 코스 0건): 빈 배열 + 메시지 "산행 기록이 쌓이면 추천해드릴게요"

### 8-3. 미확정 결정사항

다음은 사용자 본인이 최종 확정 후 진행:
- K-Means의 K값 (인계 문서 K=7 → ML 실험 결과 **K=5 확정**)
- 매칭 안 된 엣지 처리 (인계 문서: 평균값 imputation)
- 추천 표시 위치 (인계 문서: 마이페이지)
- 협업 필터링 폐기 여부 (사용자 5명, 데이터 부족)

---

## 9. Python 환경변수

```
ORDA_DB_HOST=localhost
ORDA_DB_PORT=5432
ORDA_DB_NAME=orda
ORDA_DB_USER=postgres
ORDA_DB_PASSWORD=0000
ORDA_DB_SSLMODE=disable
ORDA_POSTGIS_SCHEMA=public
ORDA_ALLOW_DESTRUCTIVE_LOAD=true
```

---

## 10. 작업 규칙 (중요)

### 10-1. 커밋
- **커밋/푸시는 사용자가 직접 한다**. Claude Code는 절대 커밋하지 말 것.
- 작업 완료 시 **변경 파일 목록 + 커밋 메시지만** 제안한다.
- 관련 없는 변경은 커밋 분리 제안.
- 커밋 메시지 형식: `type: 한글 설명`
  - `feat`: 새로운 기능
  - `fix`: 버그 수정
  - `chore`: 설정, 문서, 기타
  - `refactor`: 리팩토링

### 10-2. 응답 스타일
- 추측은 명시: "추측입니다", "잘 모르겠습니다"
- 임의 결정 금지. 애매하면 사용자에게 물어볼 것.
- 답변 짧게, 본질만.

### 10-3. 파일 구조
- 과하게 세분화하지 않는다.
- hooks, api 파일은 도메인 단위로 통합 (예: `useHiking.ts` 하나에 start/end/verify).

---

## 11. 현재 브랜치

```
feat/ml-recommendation  ⭐ 작업 중
```

부모: `dev` (보호됨, A 담당자의 `feat/major-peak-gpx-network` 머지 완료)
