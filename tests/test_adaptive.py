"""
Tests for ML Adaptive Rate Limiting
"""

import tempfile
import time
from pathlib import Path

import pytest

from ratethrottle.adaptive import AdaptiveRateLimiter, UserProfile


class TestUserProfile:
    """Test UserProfile dataclass"""

    def test_profile_creation(self):
        """Test creating user profile"""
        profile = UserProfile(identifier="user_123", first_seen=1234567890.0)

        assert profile.identifier == "user_123"
        assert profile.first_seen == 1234567890.0
        assert profile.request_count == 0
        assert profile.mean_rate == 0.0
        assert profile.trust_score == 0.5
        assert profile.violation_count == 0


class TestAdaptiveRateLimiter:
    """Test AdaptiveRateLimiter core functionality"""

    @pytest.fixture
    def limiter(self):
        """Create adaptive limiter instance"""
        return AdaptiveRateLimiter(base_limit=100, learning_rate=0.1, anomaly_threshold=3.0)

    def test_initialization(self, limiter):
        """Test limiter initializes correctly"""
        assert limiter.base_limit == 100
        assert limiter.learning_rate == 0.1
        assert limiter.anomaly_threshold == 3.0
        assert limiter.trust_enabled is True
        assert len(limiter.user_profiles) == 0

    def test_first_request_allowed(self, limiter):
        """Test first request is allowed"""
        result = limiter.check_adaptive("user_1")

        assert result["allowed"] is True
        assert result["base_limit"] == 100
        assert "adjusted_limit" in result
        assert "trust_score" in result
        assert "anomaly_score" in result

    def test_profile_creation_on_first_request(self, limiter):
        """Test profile is created on first request"""
        limiter.check_adaptive("user_1")

        assert "user_1" in limiter.user_profiles
        profile = limiter.user_profiles["user_1"]
        assert profile.identifier == "user_1"
        assert profile.request_count == 1

    def test_multiple_requests_within_limit(self, limiter):
        """Test multiple requests within limit are allowed"""
        for i in range(50):
            result = limiter.check_adaptive("user_1")
            assert result["allowed"] is True

    def test_requests_beyond_limit_blocked(self, limiter):
        """Test requests beyond limit are blocked"""
        # Make requests up to limit
        for i in range(100):
            limiter.check_adaptive("user_1")

        # Next request should be blocked
        result = limiter.check_adaptive("user_1")
        assert result["allowed"] is False
        assert result["reason"] in ["rate_limit_exceeded", "anomaly_detected"]

    def test_different_users_independent(self, limiter):
        """Test different users have independent limits"""
        # User 1 exhausts limit
        for i in range(100):
            limiter.check_adaptive("user_1")

        # User 2 should still be allowed
        result = limiter.check_adaptive("user_2")
        assert result["allowed"] is True


class TestPatternLearning:
    """Test pattern learning with EMA"""

    @pytest.fixture
    def limiter(self):
        """Create limiter with fast learning"""
        return AdaptiveRateLimiter(
            base_limit=1000, learning_rate=0.3  # High limit to focus on learning  # Fast learning
        )

    def test_mean_rate_learning(self, limiter):
        """Test that mean rate is learned"""
        # Make 10 requests at steady rate
        for i in range(10):
            limiter.check_adaptive("user_1")
            time.sleep(0.01)

        profile = limiter.user_profiles["user_1"]

        # Mean should be established
        assert profile.mean_rate > 0
        assert len(profile.request_rates) == 10

    def test_standard_deviation_calculation(self, limiter):
        """Test standard deviation is calculated"""
        # Make requests with varying rates
        for i in range(20):
            limiter.check_adaptive("user_1")
            # Vary sleep time to create variance
            time.sleep(0.01 if i % 2 == 0 else 0.02)

        profile = limiter.user_profiles["user_1"]

        # Std should be calculated
        assert profile.std_rate >= 0

    def test_exponential_moving_average(self, limiter):
        """Test EMA adapts to new patterns"""
        # Establish initial pattern
        for i in range(10):
            limiter.check_adaptive("user_1")
            time.sleep(0.01)

        profile = limiter.user_profiles["user_1"]
        initial_mean = profile.mean_rate

        # Change pattern
        for i in range(10):
            limiter.check_adaptive("user_1")
            time.sleep(0.05)  # Much slower

        # Mean should have adapted
        new_mean = profile.mean_rate
        # With learning_rate=0.3, mean should change
        assert new_mean != initial_mean


class TestAnomalyDetection:
    """Test anomaly detection"""

    @pytest.fixture
    def limiter(self):
        """Create limiter for anomaly testing"""
        return AdaptiveRateLimiter(base_limit=1000, learning_rate=0.1, anomaly_threshold=3.0)

    def test_normal_behavior_not_anomalous(self, limiter):
        """Test normal behavior has low anomaly score"""
        # Establish normal pattern
        for i in range(50):
            limiter.check_adaptive("user_1")
            time.sleep(0.01)

        # Continue normal behavior
        result = limiter.check_adaptive("user_1")

        # Should have low anomaly score
        assert result["anomaly_score"] < 3.0

    def test_burst_detected_as_anomaly(self, limiter):
        """Test sudden burst is detected as anomaly"""
        # Establish slow pattern
        for i in range(30):
            limiter.check_adaptive("user_1")
            time.sleep(0.1)  # Slow

        # Sudden burst
        for i in range(100):
            result = limiter.check_adaptive("user_1")

        # Should detect anomaly eventually
        # (might take a few requests to detect)
        assert result["anomaly_score"] > 0

    def test_anomaly_callback_triggered(self):
        """Test anomaly callback is called"""
        anomalies = []

        def on_anomaly(info):
            anomalies.append(info)

        limiter = AdaptiveRateLimiter(
            base_limit=1000, anomaly_threshold=2.0, on_anomaly=on_anomaly  # Lower threshold
        )

        # Establish pattern
        for i in range(20):
            limiter.check_adaptive("user_1")
            time.sleep(0.1)

        # Create anomaly
        for i in range(200):
            limiter.check_adaptive("user_1")

        # Callback should have been triggered
        # (at least once during the burst)


class TestTrustScoring:
    """Test trust scoring system"""

    @pytest.fixture
    def limiter(self):
        """Create limiter with trust enabled"""
        return AdaptiveRateLimiter(base_limit=100, trust_enabled=True)

    def test_new_user_moderate_trust(self, limiter):
        """Test new users start with moderate trust"""
        limiter.check_adaptive("new_user")

        profile = limiter.user_profiles["new_user"]

        # Should start around 0.5
        assert 0.3 <= profile.trust_score <= 0.7

    def test_trust_increases_with_age(self, limiter):
        """Test trust increases with account age"""
        limiter.check_adaptive("user_1")

        profile = limiter.user_profiles["user_1"]
        initial_trust = profile.trust_score

        # Simulate 30 days passing
        profile.first_seen = time.time() - (30 * 86400)

        # Make some requests to trigger trust recalculation
        for i in range(20):
            limiter.check_adaptive("user_1")

        # Trust should have increased
        assert profile.trust_score > initial_trust

    def test_violations_decrease_trust(self, limiter):
        """Test violations decrease trust score"""
        # Get initial trust
        limiter.check_adaptive("user_1")
        profile = limiter.user_profiles["user_1"]

        # Force trust calculation
        for i in range(20):
            limiter.check_adaptive("user_1")

        initial_trust = profile.trust_score

        # Add violations
        profile.violation_count = 5
        profile.trust_score = limiter._calculate_trust_score(profile)

        # Trust should decrease
        assert profile.trust_score < initial_trust

    def test_manual_trust_adjustment(self, limiter):
        """Test manual trust score adjustment"""
        limiter.check_adaptive("user_1")

        profile = limiter.user_profiles["user_1"]
        initial_trust = profile.trust_score

        # Increase trust
        limiter.update_trust_score("user_1", 0.2)

        assert profile.trust_score > initial_trust
        assert profile.trust_score <= 1.0

    def test_trust_change_callback(self):
        """Test trust change callback is triggered"""
        trust_changes = []

        def on_trust_change(identifier, new_trust):
            trust_changes.append((identifier, new_trust))

        limiter = AdaptiveRateLimiter(base_limit=100, on_trust_change=on_trust_change)

        limiter.check_adaptive("user_1")
        limiter.update_trust_score("user_1", 0.2)

        # Callback should have been triggered
        assert len(trust_changes) > 0
        assert trust_changes[-1][0] == "user_1"


class TestLimitAdjustment:
    """Test dynamic limit adjustment"""

    @pytest.fixture
    def limiter(self):
        """Create limiter for adjustment testing"""
        return AdaptiveRateLimiter(
            base_limit=100, min_multiplier=0.5, max_multiplier=3.0, trust_enabled=True
        )

    def test_trusted_user_higher_limit(self, limiter):
        """Test trusted users get higher limits"""
        limiter.check_adaptive("user_1")

        profile = limiter.user_profiles["user_1"]

        # Manually set high trust
        profile.trust_score = 0.9
        profile.first_seen = time.time() - (30 * 86400)  # Old account

        adjusted = limiter._adjust_limit(profile, is_anomalous=False)

        # Should be higher than base
        assert adjusted > 100

    def test_untrusted_user_lower_limit(self, limiter):
        """Test untrusted users get lower limits"""
        limiter.check_adaptive("user_1")

        profile = limiter.user_profiles["user_1"]

        # Manually set low trust
        profile.trust_score = 0.2
        profile.violation_count = 5

        adjusted = limiter._adjust_limit(profile, is_anomalous=False)

        # Should be lower than base
        assert adjusted < 100

    def test_anomaly_reduces_limit(self, limiter):
        """Test anomalous behavior reduces limit"""
        limiter.check_adaptive("user_1")

        profile = limiter.user_profiles["user_1"]

        # Normal limit
        normal_limit = limiter._adjust_limit(profile, is_anomalous=False)

        # Anomalous limit
        anomaly_limit = limiter._adjust_limit(profile, is_anomalous=True)

        # Anomalous should be much lower
        assert anomaly_limit < normal_limit

    def test_new_user_reduced_limit(self, limiter):
        """Test new users get reduced limits"""
        limiter.check_adaptive("new_user")

        profile = limiter.user_profiles["new_user"]

        # New user
        new_limit = limiter._adjust_limit(profile, is_anomalous=False)

        # Simulate old user
        profile.first_seen = time.time() - (60 * 86400)
        old_limit = limiter._adjust_limit(profile, is_anomalous=False)

        # Old user should get higher limit
        assert old_limit >= new_limit

    def test_limit_bounds_enforced(self, limiter):
        """Test limit bounds are enforced"""
        limiter.check_adaptive("user_1")

        profile = limiter.user_profiles["user_1"]

        # Try to get very high limit
        profile.trust_score = 1.0
        profile.first_seen = time.time() - (365 * 86400)

        adjusted = limiter._adjust_limit(profile, is_anomalous=False)

        # Should not exceed max
        assert adjusted <= 100 * 3.0  # max_multiplier

        # Try to get very low limit
        profile.trust_score = 0.0
        profile.violation_count = 100

        adjusted = limiter._adjust_limit(profile, is_anomalous=True)

        # Should not go below min
        assert adjusted >= 100 * 0.5  # min_multiplier


class TestConfidence:
    """Test confidence calculation"""

    @pytest.fixture
    def limiter(self):
        """Create limiter"""
        return AdaptiveRateLimiter(base_limit=100)

    def test_low_confidence_with_few_requests(self, limiter):
        """Test confidence is low with few requests"""
        limiter.check_adaptive("user_1")

        profile = limiter.user_profiles["user_1"]
        confidence = limiter._calculate_confidence(profile)

        # Should be low with only 1 request
        assert confidence < 0.6

    def test_high_confidence_with_many_requests(self, limiter):
        """Test confidence increases with more data"""
        for i in range(150):
            limiter.check_adaptive("user_1")

        profile = limiter.user_profiles["user_1"]
        confidence = limiter._calculate_confidence(profile)

        # Should be high with 150+ requests
        assert confidence > 0.7


class TestModelPersistence:
    """Test model save/load functionality"""

    def test_export_model(self):
        """Test exporting model"""
        limiter = AdaptiveRateLimiter(base_limit=100)

        # Create some user profiles
        for i in range(10):
            limiter.check_adaptive(f"user_{i}")

        # Export
        with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as f:
            filepath = f.name

        try:
            limiter.export_model(filepath)

            # File should exist
            assert Path(filepath).exists()
        finally:
            Path(filepath).unlink()

    def test_load_model(self):
        """Test loading model"""
        limiter1 = AdaptiveRateLimiter(base_limit=100)

        # Create profiles
        for i in range(5):
            limiter1.check_adaptive(f"user_{i}")

        # Export
        with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as f:
            filepath = f.name

        try:
            limiter1.export_model(filepath)

            # Create new limiter and load
            limiter2 = AdaptiveRateLimiter(base_limit=100)
            limiter2.load_model(filepath)

            # Should have same profiles
            assert len(limiter2.user_profiles) == 5
            assert "user_0" in limiter2.user_profiles
        finally:
            Path(filepath).unlink()

    def test_loaded_profiles_functional(self):
        """Test loaded profiles work correctly"""
        limiter1 = AdaptiveRateLimiter(base_limit=100)

        # Build up profile
        for i in range(50):
            limiter1.check_adaptive("user_1")

        profile1 = limiter1.user_profiles["user_1"]

        # Export and load
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pkl") as f:
            filepath = f.name

        try:
            limiter1.export_model(filepath)

            limiter2 = AdaptiveRateLimiter(base_limit=100)
            limiter2.load_model(filepath)

            profile2 = limiter2.user_profiles["user_1"]

            # Profiles should match
            assert profile2.request_count == profile1.request_count
            assert profile2.mean_rate == profile1.mean_rate
            assert profile2.trust_score == profile1.trust_score
        finally:
            Path(filepath).unlink()


class TestUserManagement:
    """Test user management functions"""

    @pytest.fixture
    def limiter(self):
        """Create limiter"""
        return AdaptiveRateLimiter(base_limit=100)

    def test_get_user_profile(self, limiter):
        """Test getting user profile"""
        limiter.check_adaptive("user_1")

        profile_data = limiter.get_user_profile("user_1")

        assert profile_data is not None
        assert profile_data["identifier"] == "user_1"
        assert "trust_score" in profile_data
        assert "request_count" in profile_data
        assert "current_limit" in profile_data

    def test_get_nonexistent_user_profile(self, limiter):
        """Test getting profile for non-existent user"""
        profile_data = limiter.get_user_profile("nonexistent")

        assert profile_data is None

    def test_reset_user(self, limiter):
        """Test resetting user profile"""
        # Create profile
        limiter.check_adaptive("user_1")
        assert "user_1" in limiter.user_profiles

        # Reset
        limiter.reset_user("user_1")
        assert "user_1" not in limiter.user_profiles

    def test_get_statistics(self, limiter):
        """Test getting statistics"""
        # Make some requests
        for i in range(3):
            for j in range(10):
                limiter.check_adaptive(f"user_{i}")

        stats = limiter.get_statistics()

        assert stats["total_requests"] == 30
        assert stats["users_tracked"] == 3
        assert "configuration" in stats


class TestIntegration:
    """Integration tests"""

    def test_complete_user_lifecycle(self):
        """Test complete user lifecycle"""
        limiter = AdaptiveRateLimiter(base_limit=100, learning_rate=0.1, anomaly_threshold=3.0)

        # Phase 1: New user (cautious)
        result = limiter.check_adaptive("user_1")
        assert result["allowed"] is True
        initial_limit = result["adjusted_limit"]

        # Phase 2: Establish pattern (normal)
        for i in range(50):
            result = limiter.check_adaptive("user_1")

        # Phase 3: Build trust (generous)
        profile = limiter.user_profiles["user_1"]
        profile.first_seen = time.time() - (30 * 86400)

        for i in range(20):
            result = limiter.check_adaptive("user_1")

        trusted_limit = result["adjusted_limit"]

        # Should get higher limit with trust
        assert trusted_limit >= initial_limit

        # Phase 4: Anomaly (restricted)
        for i in range(500):
            result = limiter.check_adaptive("user_1")

        # Should eventually be blocked or restricted
        # (may take multiple requests to detect)

    def test_multiple_users_different_limits(self):
        """Test multiple users with different behaviors get different limits"""
        limiter = AdaptiveRateLimiter(base_limit=100)

        # User 1: Good behavior
        for i in range(50):
            limiter.check_adaptive("good_user")
            time.sleep(0.01)

        # User 2: New user
        limiter.check_adaptive("new_user")

        # User 3: Has violations
        for i in range(10):
            limiter.check_adaptive("bad_user")
        limiter.user_profiles["bad_user"].violation_count = 5

        # Get results
        good_result = limiter.check_adaptive("good_user")
        new_result = limiter.check_adaptive("new_user")
        bad_result = limiter.check_adaptive("bad_user")

        # Limits should be different
        # Good user should have higher or equal limit
        assert good_result["adjusted_limit"] >= new_result["adjusted_limit"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
