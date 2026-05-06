"""course_features.csv를 표준화한 뒤 K-Means 클러스터링과 PCA 시각화를 수행한다.

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


def evaluate_k(X: np.ndarray) -> dict[int, dict]:
    results: dict[int, dict] = {}
    print("[K-Means] K별 inertia / silhouette:")
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


def main() -> int:
    if not INPUT_CSV.exists():
        print(f"입력 파일이 없습니다: {INPUT_CSV}")
        print("먼저 `python -m ml.extract_features`를 실행하세요.")
        return 1

    print(f"[1/5] 데이터 로드: {INPUT_CSV}")
    df = load_and_impute(INPUT_CSV)
    print(f"  코스 수: {len(df)}")

    print("[2/5] 정규화 (StandardScaler)")
    scaler = StandardScaler()
    X = scaler.fit_transform(df[FEATURE_COLUMNS].values)

    print(f"[3/5] K-Means 평가 (K={K_VALUES})")
    results = evaluate_k(X)

    print("[4/5] 시각화 저장")
    plot_comparison(results, CLUSTER_COMPARISON_PNG)
    print(f"  저장: {CLUSTER_COMPARISON_PNG}")
    pc1, pc2 = plot_pca(X, results, OUTPUT_DIR)
    for k in K_VALUES:
        print(f"  저장: {OUTPUT_DIR / f'pca_k{k}.png'}")
    print(
        f"  PCA 설명력: PC1={pc1 * 100:.2f}%, PC2={pc2 * 100:.2f}%, "
        f"누적={(pc1 + pc2) * 100:.2f}%"
    )

    print("[5/5] 최적 K 선정 및 클러스터 결과 저장")
    best_k = select_best_k(results)
    out_df = df[["course_id"]].copy()
    out_df["cluster_id"] = results[best_k]["labels"]
    out_df.to_csv(COURSE_CLUSTERS_CSV, index=False)
    print(f"  저장: {COURSE_CLUSTERS_CSV} (K={best_k})")
    print("  cluster_id 분포:")
    counts = out_df["cluster_id"].value_counts().sort_index()
    for cid, cnt in counts.items():
        print(f"    cluster {cid}: {cnt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
