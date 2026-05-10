package com.orda.backend.domain.recommendation.dto.response;

import lombok.Builder;
import lombok.Getter;

@Getter
@Builder
public class RecommendedCourseResponse {

    private String courseId;
    private String summitId;
    private String summitName;
    private Double totalDistanceM;
    private Double totalElevationGainM;
    private Double avgSlopePercent;
    private Double avgDifficultyScore;
    private Double similarityScore;
    private Integer clusterId;
}
