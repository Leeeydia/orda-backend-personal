"""course_features.csv를 표준화한 뒤 K-Means 클러스터링과 PCA 시각화를 수행한다.

전처리 정책:
1) NaN은 컬럼 평균으로 imputation.
2) long-tail인 거리/고도 컬럼에 log1p 적용 (slope/difficulty는 부호·스케일 유지).
3) log1p만으로 클러스터 분포가 한 클러스터 40% 이상으로 쏠리면
   feature 전체에 winsorization(1%/99%)을 추가 적용해 재시도.

실행: backend/python/ 디렉토리에서 `python -m ml.cluster`
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

# Windows 콘솔(cp949)에서 한글이 깨지는 것을 방지
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
INPUT_CSV = OUTPUT_DIR / "course_features.csv"
CLUSTER_COMPARISON_PNG = OUTPUT_DIR / "cluster_comparison.png"
COURSE_CLUSTERS_CSV = OUTPUT_DIR / "course_clusters.csv"

K_VALUES = [3, 5, 7, 9, 11]
RANDOM_STATE = 42

# CLAUDE.md §8-1 feature_vector 순서
FEATURE_COLUMNS = [
    "total_distance_m",
    "total_elevation_gain_m",
    "total_elevation_loss_m",
    "avg_slope_percent",
    "max_slope_percent",
    "avg_difficulty_score",
]

# long-tail 분포라 log1p로 분산을 압축한다.
# slope/difficulty는 부호 정보를 유지하기 위해 변환하지 않는다.
LOG_TRANSFORM_COLUMNS = [
    "total_distance_m",
    "total_elevation_gain_m",
    "total_elevation_loss_m",
]

# winsorization 분위수 (양쪽 1%)
WINSORIZE_LOWER_Q = 0.01
WINSORIZE_UPPER_Q = 0.99

# 한 클러스터가 이 비율을 넘으면 winsorize를 추가 적용해 재시도한다.
MAX_CLUSTER_RATIO_THRESHOLD = 0.40


def load_and_impute(path: Path) -> pd.DataFrame:
    """CSV 로드 후 NaN을 컬럼 평균으로 대체한다. 적용된 코스/평균값을 로그로 출력한다."""
    df = pd.read_csv(path)
    nan_mask = df[FEATURE_COLUMNS].isna().any(axis=1)
    nan_courses = df.loc[nan_mask, "course_id"].tolist()

    means: dict[str, float] = {}
    for col in FEATURE_COLUMNS:
        m = float(df[col].mean())
        means[col] = m
        df[col] = df[col].fillna(m)

    if nan_courses:
        print(f"[Imputation] NaN을 컬럼 평균으로 대체한 코스 {len(nan_courses)}건:")
        for cid in nan_courses:
            print(f"  - {cid}")
        print("[Imputation] 사용한 컬럼별 평균값:")
        for col, m in means.items():
            print(f"  {col}: {m:.4f}")
    else:
        print("[Imputation] NaN 없음")
    return df


def apply_log1p(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in LOG_TRANSFORM_COLUMNS:
        df[col] = np.log1p(df[col])
    return df


def apply_winsorize(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    df = df.copy()
    for col in columns:
        lo = float(df[col].quantile(WINSORIZE_LOWER_Q))
        hi = float(df[col].quantile(WINSORIZE_UPPER_Q))
        df[col] = df[col].clip(lower=lo, upper=hi)
    return df


def standardize(df: pd.DataFrame) -> np.ndarray:
    return StandardScaler().fit_transform(df[FEATURE_COLUMNS].values)


def cluster_distribution(labels: np.ndarray) -> tuple[list[tuple[int, int]], float]:
    """labels의 (cluster_id, count) 리스트와 최대 비율을 반환한다."""
    unique, counts = np.unique(labels, return_counts=True)
    pairs = sorted(zip(unique.tolist(), counts.tolist()), key=lambda x: x[0])
    total = int(counts.sum())
    max_ratio = float(counts.max()) / total if total else 0.0
    return pairs, max_ratio


def print_distribution(label: str, labels: np.ndarray) -> float:
    pairs, max_ratio = cluster_distribution(labels)
    total = sum(c for _, c in pairs)
    print(f"  [{label}] cluster_id 분포 (max ratio={max_ratio * 100:.1f}%):")
    for cid, cnt in pairs:
        print(f"    cluster {cid}: {cnt} ({cnt / total * 100:.1f}%)")
    return max_ratio


def evaluate_k(X: np.ndarray, label: str) -> dict[int, dict]:
    results: dict[int, dict] = {}
    print(f"[K-Means] K별 inertia / silhouette ({label}):")
    for k in K_VALUES:
        km = KMeans(n_clusters=k, random_state=RANDOM_STATE, n_init=10)
        labels = km.fit_predict(X)
        sil = float(silhouette_score(X, labels))
        results[k] = {
            "labels": labels,
            "inertia": float(km.inertia_),
            "silhouette": sil,
        }
        print(f"  K={k}: inertia={km.inertia_:>10.2f}, silhouette={sil:.4f}")
    return results


def plot_comparison(results: dict[int, dict], path: Path) -> None:
    ks = sorted(results.keys())
    inertias = [results[k]["inertia"] for k in ks]
    sils = [results[k]["silhouette"] for k in ks]

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    axes[0].plot(ks, inertias, marker="o")
    axes[0].set_xlabel("K")
    axes[0].set_ylabel("Inertia (SSE)")
    axes[0].set_title("Elbow Method")
    axes[0].grid(True, alpha=0.3)

    axes[1].plot(ks, sils, marker="o", color="orange")
    axes[1].set_xlabel("K")
    axes[1].set_ylabel("Silhouette Score")
    axes[1].set_title("Silhouette Score by K")
    axes[1].grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def plot_pca(X: np.ndarray, results: dict[int, dict], output_dir: Path) -> tuple[float, float]:
    pca = PCA(n_components=2, random_state=RANDOM_STATE)
    X2 = pca.fit_transform(X)
    ev = pca.explained_variance_ratio_

    for k, res in results.items():
        labels = res["labels"]
        fig, ax = plt.subplots(figsize=(8, 6))
        scatter = ax.scatter(X2[:, 0], X2[:, 1], c=labels, cmap="tab10", s=8, alpha=0.7)
        ax.set_xlabel(f"PC1 ({ev[0] * 100:.1f}%)")
        ax.set_ylabel(f"PC2 ({ev[1] * 100:.1f}%)")
        ax.set_title(f"K-Means PCA (K={k})")
        legend = ax.legend(*scatter.legend_elements(), title="cluster", loc="best", fontsize=8)
        ax.add_artist(legend)
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        fig.savefig(output_dir / f"pca_k{k}.png", dpi=120)
        plt.close(fig)
    return float(ev[0]), float(ev[1])


def select_best_k(results: dict[int, dict]) -> int:
    """silhouette score 최댓값을 기준으로 최적 K를 선정한다."""
    best_k = max(results.keys(), key=lambda k: results[k]["silhouette"])
    print("\n[최적 K 선정 — 기준: silhouette score 최댓값]")
    for k in sorted(results.keys()):
        marker = "  <-- 선택" if k == best_k else ""
        print(
            f"  K={k}: silhouette={results[k]['silhouette']:.4f}, "
            f"inertia={results[k]['inertia']:.2f}{marker}"
        )
    print(f"  -> 최적 K = {best_k}")
    return best_k


def best_k_max_ratio(results: dict[int, dict]) -> tuple[int, float]:
    best_k = max(results.keys(), key=lambda k: results[k]["silhouette"])
    _, max_ratio = cluster_distribution(results[best_k]["labels"])
    return best_k, max_ratio


def main() -> int:
    if not INPUT_CSV.exists():
        print(f"입력 파일이 없습니다: {INPUT_CSV}")
        print("먼저 `python -m ml.extract_features`를 실행하세요.")
        return 1

    print(f"[1/6] 데이터 로드: {INPUT_CSV}")
    df_raw = load_and_impute(INPUT_CSV)
    print(f"  코스 수: {len(df_raw)}")

    print("[2/6] 변환 1: log1p 적용 (3개 컬럼: distance, elevation gain/loss)")
    df_log = apply_log1p(df_raw)
    X_log = standardize(df_log)

    print("[3/6] K-Means 평가 (log1p)")
    results_log = evaluate_k(X_log, label="log1p")
    best_k_log, max_ratio_log = best_k_max_ratio(results_log)
    print(
        f"  log1p 최적 K={best_k_log}, "
        f"max cluster ratio={max_ratio_log * 100:.1f}%"
    )
    print_distribution(f"log1p / K={best_k_log}", results_log[best_k_log]["labels"])

    if max_ratio_log > MAX_CLUSTER_RATIO_THRESHOLD:
        print(
            f"\n[4/6] 변환 2 추가: winsorize(1%/99%) "
            f"(max ratio {max_ratio_log * 100:.1f}% > "
            f"{MAX_CLUSTER_RATIO_THRESHOLD * 100:.0f}% 임계 초과)"
        )
        df_final = apply_winsorize(df_log, FEATURE_COLUMNS)
        X_final = standardize(df_final)
        results_final = evaluate_k(X_final, label="log1p + winsorize")
        transform_label = "log1p + winsorize(1%/99%)"
    else:
        print(
            f"\n[4/6] log1p만으로 분포 양호 "
            f"(max ratio {max_ratio_log * 100:.1f}% <= "
            f"{MAX_CLUSTER_RATIO_THRESHOLD * 100:.0f}%) — winsorize 생략"
        )
        X_final = X_log
        results_final = results_log
        transform_label = "log1p only"

    print(f"\n[5/6] 시각화 저장 (최종 변환: {transform_label})")
    plot_comparison(results_final, CLUSTER_COMPARISON_PNG)
    print(f"  저장: {CLUSTER_COMPARISON_PNG}")
    pc1, pc2 = plot_pca(X_final, results_final, OUTPUT_DIR)
    for k in K_VALUES:
        print(f"  저장: {OUTPUT_DIR / f'pca_k{k}.png'}")
    print(
        f"  PCA 설명력: PC1={pc1 * 100:.2f}%, PC2={pc2 * 100:.2f}%, "
        f"누적={(pc1 + pc2) * 100:.2f}%"
    )

    print("[6/6] 최적 K 선정 및 클러스터 결과 저장")
    best_k = select_best_k(results_final)
    out_df = df_raw[["course_id"]].copy()
    out_df["cluster_id"] = results_final[best_k]["labels"]
    out_df.to_csv(COURSE_CLUSTERS_CSV, index=False)
    print(f"  저장: {COURSE_CLUSTERS_CSV} (K={best_k})")

    print("\n=== 최종 결과 ===")
    print(f"  변환: {transform_label}")
    print(f"  최적 K: {best_k}")
    print_distribution(f"final / K={best_k}", results_final[best_k]["labels"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
