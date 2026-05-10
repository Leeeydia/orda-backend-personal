package com.orda.backend.domain.recommendation.service;

import com.orda.backend.domain.recommendation.dto.response.RecommendedCourseResponse;
import com.orda.backend.domain.recommendation.entity.CourseFeature;
import com.orda.backend.domain.recommendation.repository.CourseFeatureRepository;
import jakarta.annotation.PostConstruct;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.*;
import java.util.stream.Collectors;

@Slf4j
@Service
@RequiredArgsConstructor
public class RecommendationService {

    private final CourseFeatureRepository courseFeatureRepository;

    // ── 기동 시 메모리 캐시 (읽기 전용, @PostConstruct 이후 불변) ──
    private List<CourseFeature> allCourses = List.of();
    private double[][] featureVectors;                    // allCourses[i]의 raw feature
    private Map<String, Integer> courseIndexMap = Map.of(); // course_id → 배열 인덱스
    private Map<String, String> summitNameMap = Map.of();   // summit_id → name

    @PostConstruct
    public void loadCache() {
        try {
            List<CourseFeature> courses = courseFeatureRepository.findAll();
            double[][] vectors = new double[courses.size()][];
            Map<String, Integer> indexMap = new HashMap<>(courses.size() * 2);

            for (int i = 0; i < courses.size(); i++) {
                vectors[i] = parseFeatureVector(courses.get(i).getFeatureVector());
                indexMap.put(courses.get(i).getCourseId(), i);
            }

            Map<String, String> nameMap = new HashMap<>();
            courseFeatureRepository.findAllSummitNamePairs().forEach(row -> {
                if (row[0] != null && row[1] != null) {
                    nameMap.put((String) row[0], (String) row[1]);
                }
            });

            this.allCourses = List.copyOf(courses);
            this.featureVectors = vectors;
            this.courseIndexMap = Map.copyOf(indexMap);
            this.summitNameMap = Map.copyOf(nameMap);

            log.info("[Recommendation] 캐시 로드 완료 — 코스 {}건, summit {}건",
                    courses.size(), nameMap.size());
        } catch (Exception e) {
            log.error("[Recommendation] 캐시 로드 실패 — 추천 기능 비활성화", e);
        }
    }

    @Transactional(readOnly = true)
    public List<RecommendedCourseResponse> getRecommendations(Long userId, int limit) {
        if (allCourses.isEmpty()) {
            return List.of();
        }

        // 1. 사용자가 인증한 summit_id 목록 (hiking_sessions → summit_verifications)
        List<String> verifiedSummitIds = courseFeatureRepository.findVerifiedSummitIdsByUserId(userId);
        if (verifiedSummitIds.isEmpty()) {
            return List.of();
        }

        // 2. summit_id로 매칭되는 코스 (in-memory 탐색)
        Set<String> summitIdSet = new HashSet<>(verifiedSummitIds);
        Set<String> visitedCourseIds = new HashSet<>();
        for (CourseFeature cf : allCourses) {
            if (cf.getSummitId() != null && summitIdSet.contains(cf.getSummitId())) {
                visitedCourseIds.add(cf.getCourseId());
            }
        }
        if (visitedCourseIds.isEmpty()) {
            return List.of();
        }

        // 3. 방문 코스들의 feature 평균 (centroid)
        double[] centroid = centroidOf(visitedCourseIds);

        // 4. 방문 코스의 최빈 cluster
        int dominantCluster = dominantCluster(visitedCourseIds);

        // 5. 후보 인덱스 선정 (같은 cluster → 부족하면 전체 풀 fallback)
        List<Integer> candidates = candidateIndices(dominantCluster, visitedCourseIds, limit);

        // 6. 코사인 유사도 계산 → 내림차순 정렬 → top N
        return candidates.stream()
                .map(idx -> Map.entry(idx, cosine(centroid, featureVectors[idx])))
                .sorted(Map.Entry.<Integer, Double>comparingByValue().reversed())
                .limit(limit)
                .map(e -> toResponse(allCourses.get(e.getKey()), e.getValue()))
                .collect(Collectors.toList());
    }

    private double[] centroidOf(Set<String> courseIds) {
        double[] sum = new double[6];
        int count = 0;
        for (String cid : courseIds) {
            Integer idx = courseIndexMap.get(cid);
            if (idx != null) {
                double[] v = featureVectors[idx];
                for (int i = 0; i < 6; i++) sum[i] += v[i];
                count++;
            }
        }
        if (count > 1) {
            for (int i = 0; i < 6; i++) sum[i] /= count;
        }
        return sum;
    }

    private int dominantCluster(Set<String> courseIds) {
        Map<Integer, Long> freq = new HashMap<>();
        for (String cid : courseIds) {
            Integer idx = courseIndexMap.get(cid);
            if (idx != null) {
                freq.merge(allCourses.get(idx).getClusterId(), 1L, Long::sum);
            }
        }
        return freq.entrySet().stream()
                .max(Map.Entry.comparingByValue())
                .map(Map.Entry::getKey)
                .orElse(0);
    }

    private List<Integer> candidateIndices(int clusterId, Set<String> excludeIds, int limit) {
        List<Integer> sameCluster = new ArrayList<>();
        for (int i = 0; i < allCourses.size(); i++) {
            CourseFeature cf = allCourses.get(i);
            if (cf.getClusterId() == clusterId && !excludeIds.contains(cf.getCourseId())) {
                sameCluster.add(i);
            }
        }
        if (sameCluster.size() >= limit) {
            return sameCluster;
        }
        // fallback: 전체 풀 (cluster 2처럼 코스 수가 너무 적은 경우)
        log.debug("[Recommendation] cluster {} 후보 {}건 < limit {} → 전체 풀 fallback",
                clusterId, sameCluster.size(), limit);
        List<Integer> all = new ArrayList<>(allCourses.size());
        for (int i = 0; i < allCourses.size(); i++) {
            if (!excludeIds.contains(allCourses.get(i).getCourseId())) {
                all.add(i);
            }
        }
        return all;
    }

    private RecommendedCourseResponse toResponse(CourseFeature cf, double similarity) {
        return RecommendedCourseResponse.builder()
                .courseId(cf.getCourseId())
                .summitId(cf.getSummitId())
                .summitName(cf.getSummitId() != null ? summitNameMap.get(cf.getSummitId()) : null)
                .totalDistanceM(cf.getTotalDistanceM())
                .totalElevationGainM(cf.getTotalElevationGainM())
                .avgSlopePercent(cf.getAvgSlopePercent())
                .avgDifficultyScore(cf.getAvgDifficultyScore())
                .similarityScore(Math.round(similarity * 1_000_000.0) / 1_000_000.0)
                .clusterId(cf.getClusterId())
                .build();
    }

    private static double cosine(double[] a, double[] b) {
        double dot = 0, normA = 0, normB = 0;
        for (int i = 0; i < a.length; i++) {
            dot += a[i] * b[i];
            normA += a[i] * a[i];
            normB += b[i] * b[i];
        }
        if (normA == 0 || normB == 0) return 0.0;
        return dot / (Math.sqrt(normA) * Math.sqrt(normB));
    }

    // "[v1, v2, null, v4, v5, v6]" 형식 파싱. null은 0.0으로 처리.
    private static double[] parseFeatureVector(String json) {
        String clean = json.trim();
        if (clean.startsWith("[")) clean = clean.substring(1);
        if (clean.endsWith("]")) clean = clean.substring(0, clean.length() - 1);
        String[] parts = clean.split(",");
        double[] vec = new double[parts.length];
        for (int i = 0; i < parts.length; i++) {
            String s = parts[i].trim();
            vec[i] = "null".equalsIgnoreCase(s) ? 0.0 : Double.parseDouble(s);
        }
        return vec;
    }
}
