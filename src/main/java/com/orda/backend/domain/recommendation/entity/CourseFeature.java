package com.orda.backend.domain.recommendation.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

@Entity
@Table(name = "course_features")
@Getter
@NoArgsConstructor
public class CourseFeature {

    @Id
    @Column(name = "course_id")
    private String courseId;

    @Column(name = "total_distance_m", nullable = false)
    private Double totalDistanceM;

    @Column(name = "total_elevation_gain_m", nullable = false)
    private Double totalElevationGainM;

    @Column(name = "total_elevation_loss_m", nullable = false)
    private Double totalElevationLossM;

    @Column(name = "avg_slope_percent", nullable = false)
    private Double avgSlopePercent;

    @Column(name = "max_slope_percent", nullable = false)
    private Double maxSlopePercent;

    @Column(name = "avg_difficulty_score", nullable = false)
    private Double avgDifficultyScore;

    @Column(name = "edge_count", nullable = false)
    private Integer edgeCount;

    @Column(name = "summit_id")
    private String summitId;

    @Column(name = "cluster_id", nullable = false)
    private Integer clusterId;

    @Column(name = "feature_vector", nullable = false, columnDefinition = "TEXT")
    private String featureVector;

    @Column(name = "created_at", nullable = false)
    private LocalDateTime createdAt;

    @Column(name = "updated_at", nullable = false)
    private LocalDateTime updatedAt;
}
