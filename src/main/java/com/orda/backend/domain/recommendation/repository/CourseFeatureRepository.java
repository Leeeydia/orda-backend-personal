package com.orda.backend.domain.recommendation.repository;

import com.orda.backend.domain.recommendation.entity.CourseFeature;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;

public interface CourseFeatureRepository extends JpaRepository<CourseFeature, String> {

    @Query(value = """
            SELECT DISTINCT sv.summit_id
            FROM hiking_sessions hs
            JOIN summit_verifications sv ON hs.session_id = sv.session_id
            WHERE hs.user_id = :userId
            """, nativeQuery = true)
    List<String> findVerifiedSummitIdsByUserId(@Param("userId") Long userId);

    @Query(value = "SELECT summit_id, name FROM summit_points WHERE summit_id IS NOT NULL",
            nativeQuery = true)
    List<Object[]> findAllSummitNamePairs();
}
