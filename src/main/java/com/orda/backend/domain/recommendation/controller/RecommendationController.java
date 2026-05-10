package com.orda.backend.domain.recommendation.controller;

import com.orda.backend.common.response.ApiResponse;
import com.orda.backend.domain.recommendation.dto.response.RecommendedCourseResponse;
import com.orda.backend.domain.recommendation.service.RecommendationService;
import com.orda.backend.security.CustomUserDetails;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/recommendations")
@RequiredArgsConstructor
public class RecommendationController {

    private final RecommendationService recommendationService;

    @GetMapping("/courses")
    public ResponseEntity<ApiResponse<List<RecommendedCourseResponse>>> getRecommendedCourses(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @RequestParam(defaultValue = "5") int limit) {

        List<RecommendedCourseResponse> results =
                recommendationService.getRecommendations(userDetails.getUserId(), limit);

        if (results.isEmpty()) {
            return ResponseEntity.ok(
                    ApiResponse.success("산행 기록이 쌓이면 추천해드릴게요", List.of()));
        }
        return ResponseEntity.ok(
                ApiResponse.success("코스 추천 조회 성공", results));
    }
}
