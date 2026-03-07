"""
RateThrottle - ML Adaptive Rate Limiting

Statistical adaptive rate limiting that learns user behavior and automatically
adjusts limits based on patterns, trust scores, and anomaly detection.

This is a basic implementation using statistical methods.
"""

import json
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class UserProfile:
    """
    User behavior profile for adaptive rate limiting

    Attributes:
        identifier: User identifier
        first_seen: When user first appeared
        last_seen: When user last made request
        request_count: Total requests made
        mean_rate: Average request rate (EMA)
        std_rate: Standard deviation of rate
        request_rates: Recent rate measurements
        trust_score: Trust score (0.0 to 1.0)
        violation_count: Number of violations
        good_behavior_days: Days of good behavior
        metadata: Additional user metadata
    """

    identifier: str
    first_seen: float
    last_seen: float = field(default_factory=time.time)
    request_count: int = 0
    mean_rate: float = 0.0
    std_rate: float = 1.0
    request_rates: deque = field(default_factory=lambda: deque(maxlen=100))
    trust_score: float = 0.5
    violation_count: int = 0
    good_behavior_days: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


class AdaptiveRateLimiter:
    """
    ML-based adaptive rate limiter using statistical methods

    Features:
    - Pattern learning with Exponential Moving Average
    - Z-score based anomaly detection
    - Trust scoring system
    - Automatic limit adjustment
    - Model persistence

    Example:
        >>> limiter = AdaptiveRateLimiter(
        ...     base_limit=100,
        ...     learning_rate=0.1,
        ...     anomaly_threshold=3.0
        ... )
        >>>
        >>> result = limiter.check_adaptive('user_123')
        >>> if result['allowed']:
        ...     print(f"Limit: {result['adjusted_limit']}")
        ...     print(f"Trust: {result['trust_score']:.2f}")
    """

    def __init__(
        self,
        base_limit: int = 100,
        window: int = 60,
        learning_rate: float = 0.1,
        anomaly_threshold: float = 3.0,
        trust_enabled: bool = True,
        min_multiplier: float = 0.5,
        max_multiplier: float = 3.0,
        storage=None,
        on_anomaly: Optional[Callable] = None,
        on_trust_change: Optional[Callable] = None,
    ):
        """
        Initialize adaptive rate limiter

        Args:
            base_limit: Base rate limit (starting point)
            window: Time window in seconds
            learning_rate: How fast to adapt (0.0-1.0)
            anomaly_threshold: Z-score threshold for anomalies
            trust_enabled: Enable trust scoring
            min_multiplier: Minimum limit multiplier (e.g., 0.5 = 50%)
            max_multiplier: Maximum limit multiplier (e.g., 3.0 = 300%)
            storage: Storage backend for persistence
            on_anomaly: Callback when anomaly detected
            on_trust_change: Callback when trust score changes
        """
        from .core import RateThrottleCore, RateThrottleRule
        from .storage_backend import InMemoryStorage

        self.base_limit = base_limit
        self.window = window
        self.learning_rate = learning_rate
        self.anomaly_threshold = anomaly_threshold
        self.trust_enabled = trust_enabled
        self.min_multiplier = min_multiplier
        self.max_multiplier = max_multiplier
        self.storage = storage or InMemoryStorage()
        self.on_anomaly = on_anomaly
        self.on_trust_change = on_trust_change

        # Core limiter (fallback)
        self.limiter = RateThrottleCore(storage=self.storage)
        self.limiter.add_rule(RateThrottleRule(name="adaptive", limit=base_limit, window=window))

        # User profiles
        self.user_profiles: Dict[str, UserProfile] = {}

        # Request history for rate calculation
        self.request_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))

        # Statistics
        self.stats = {
            "total_requests": 0,
            "anomalies_detected": 0,
            "limits_adjusted": 0,
            "users_tracked": 0,
        }

        logger.info(
            f"Adaptive rate limiter initialized: "
            f"base_limit={base_limit}, learning_rate={learning_rate}"
        )

    def check_adaptive(
        self, identifier: str, request_metadata: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Check rate limit with ML adaptation

        Args:
            identifier: User/client identifier
            request_metadata: Optional request metadata

        Returns:
            Dict with:
                - allowed (bool): Whether request is allowed
                - adjusted_limit (int): Personalized limit
                - remaining (int): Requests remaining
                - trust_score (float): User trust score
                - anomaly_score (float): Anomaly score
                - confidence (float): Confidence in decision
                - reason (str): Why decision was made
        """
        self.stats["total_requests"] += 1

        # Get or create user profile
        if identifier not in self.user_profiles:
            self.user_profiles[identifier] = self._create_profile(identifier)
            self.stats["users_tracked"] += 1

        profile = self.user_profiles[identifier]

        # Calculate current request rate
        current_rate = self._calculate_current_rate(identifier)

        # Update profile with new data
        self._update_profile(profile, current_rate, request_metadata)

        # Calculate anomaly score
        anomaly_score = self._calculate_anomaly_score(profile, current_rate)

        # Determine if request is anomalous
        is_anomalous = anomaly_score > self.anomaly_threshold

        if is_anomalous:
            self.stats["anomalies_detected"] += 1

            if self.on_anomaly:
                self.on_anomaly(
                    {
                        "identifier": identifier,
                        "anomaly_score": anomaly_score,
                        "current_rate": current_rate,
                        "expected_rate": profile.mean_rate,
                        "timestamp": time.time(),
                    }
                )

        # Adjust limit based on behavior
        adjusted_limit = self._adjust_limit(profile, is_anomalous)

        # Use core limiter to check against adjusted limit
        # Temporarily adjust the rule limit
        original_limit = self.limiter.rules["adaptive"].limit
        self.limiter.rules["adaptive"].limit = adjusted_limit

        status = self.limiter.check_rate_limit(identifier, "adaptive")

        # Restore original limit
        self.limiter.rules["adaptive"].limit = original_limit

        # Update violation count if blocked
        if not status.allowed:
            profile.violation_count += 1

            # Recalculate trust score after violation
            old_trust = profile.trust_score
            profile.trust_score = self._calculate_trust_score(profile)

            if self.on_trust_change and abs(old_trust - profile.trust_score) > 0.05:
                self.on_trust_change(identifier, profile.trust_score)

        # Calculate confidence
        confidence = self._calculate_confidence(profile)

        # Determine reason
        if not status.allowed:
            if is_anomalous:
                reason = "anomaly_detected"
            else:
                reason = "rate_limit_exceeded"
        else:
            reason = "allowed"

        # Log request for learning
        self.request_history[identifier].append(
            {
                "timestamp": time.time(),
                "rate": current_rate,
                "allowed": status.allowed,
                "anomaly_score": anomaly_score,
                "adjusted_limit": adjusted_limit,
            }
        )

        return {
            "allowed": status.allowed,
            "adjusted_limit": adjusted_limit,
            "remaining": status.remaining,
            "trust_score": profile.trust_score,
            "anomaly_score": anomaly_score,
            "confidence": confidence,
            "reason": reason,
            "base_limit": self.base_limit,
            "retry_after": status.retry_after if not status.allowed else 0,
        }

    def _create_profile(self, identifier: str) -> UserProfile:
        """Create new user profile"""
        return UserProfile(identifier=identifier, first_seen=time.time(), last_seen=time.time())

    def _calculate_current_rate(self, identifier: str) -> float:
        """
        Calculate current request rate

        Returns:
            Requests per minute
        """
        now = time.time()
        window_start = now - self.window

        # Count recent requests
        recent_requests = [
            r for r in self.request_history[identifier] if r["timestamp"] > window_start
        ]

        if not recent_requests:
            return 0.0

        # Calculate rate (requests per minute)
        rate = (len(recent_requests) / self.window) * 60

        return rate

    def _update_profile(self, profile: UserProfile, current_rate: float, metadata: Optional[Dict]):
        """Update user profile with new data"""
        profile.last_seen = time.time()
        profile.request_count += 1
        profile.request_rates.append(current_rate)

        # Update mean with Exponential Moving Average
        if profile.mean_rate == 0:
            profile.mean_rate = current_rate
        else:
            profile.mean_rate = (
                1 - self.learning_rate
            ) * profile.mean_rate + self.learning_rate * current_rate

        # Update standard deviation
        if len(profile.request_rates) > 1:
            # Calculate std from recent rates
            rates = list(profile.request_rates)
            mean = sum(rates) / len(rates)
            variance = sum((r - mean) ** 2 for r in rates) / len(rates)
            profile.std_rate = variance**0.5

        # Update trust score periodically
        if profile.request_count % 10 == 0:
            old_trust = profile.trust_score
            profile.trust_score = self._calculate_trust_score(profile)

            if self.on_trust_change and abs(old_trust - profile.trust_score) > 0.05:
                self.on_trust_change(profile.identifier, profile.trust_score)

        # Update metadata
        if metadata:
            profile.metadata.update(metadata)

    def _calculate_anomaly_score(self, profile: UserProfile, current_rate: float) -> float:
        """
        Calculate anomaly score using Z-score

        Returns:
            Z-score (0 = normal, >3 = anomalous)
        """
        if profile.std_rate == 0 or profile.mean_rate == 0:
            return 0.0

        # Z-score: how many standard deviations from mean
        z_score = abs((current_rate - profile.mean_rate) / profile.std_rate)

        return z_score

    def _calculate_trust_score(self, profile: UserProfile) -> float:
        """
        Calculate trust score (0.0 to 1.0)

        Factors:
        - Account age (ramps up over 30 days)
        - Behavior consistency (low variance = high trust)
        - Violation history (penalties for violations)
        - Good behavior bonus (rewards for clean record)
        """
        # Age factor (0 to 30 days)
        age_seconds = time.time() - profile.first_seen
        age_days = age_seconds / 86400
        age_score = min(1.0, age_days / 30)  # Ramps up over 30 days

        # Consistency factor (low variance = consistent = trustworthy)
        if profile.std_rate > 0 and profile.mean_rate > 0:
            cv = profile.std_rate / profile.mean_rate  # Coefficient of variation
            consistency_score = 1.0 / (1.0 + cv)
        else:
            consistency_score = 1.0

        # Violation penalty
        violation_penalty = min(1.0, profile.violation_count * 0.1)
        violation_score = max(0.0, 1.0 - violation_penalty)

        # Good behavior bonus
        good_behavior_bonus = min(0.2, profile.good_behavior_days * 0.01)

        # Combined trust score
        trust_score = (
            age_score * 0.3 + consistency_score * 0.4 + violation_score * 0.3 + good_behavior_bonus
        )

        return max(0.0, min(1.0, trust_score))

    def _adjust_limit(self, profile: UserProfile, is_anomalous: bool) -> int:
        """
        Dynamically adjust rate limit based on behavior

        Returns:
            Adjusted rate limit
        """
        base = self.base_limit

        # Trust multiplier (0.5x to 2.0x)
        if self.trust_enabled:
            trust_multiplier = self.min_multiplier + (
                profile.trust_score * (self.max_multiplier - self.min_multiplier)
            )
        else:
            trust_multiplier = 1.0

        # Anomaly penalty (reduce to 30% if anomalous)
        anomaly_multiplier = 0.3 if is_anomalous else 1.0

        # Age multiplier (new users get lower limits)
        age_days = (time.time() - profile.first_seen) / 86400
        age_multiplier = min(1.0, 0.5 + (age_days / 30) * 0.5)

        # Calculate adjusted limit
        adjusted = int(base * trust_multiplier * anomaly_multiplier * age_multiplier)

        # Enforce bounds
        min_limit = max(1, int(base * self.min_multiplier))
        max_limit = int(base * self.max_multiplier)

        adjusted = max(min_limit, min(adjusted, max_limit))

        if adjusted != base:
            self.stats["limits_adjusted"] += 1

        return adjusted

    def _calculate_confidence(self, profile: UserProfile) -> float:
        """
        Calculate confidence in decision (0.0 to 1.0)

        Higher confidence with:
        - More data points
        - Lower variance
        """
        # Data confidence (more requests = higher confidence)
        data_confidence = min(1.0, profile.request_count / 100)

        # Variance confidence (lower variance = higher confidence)
        if profile.std_rate > 0 and profile.mean_rate > 0:
            cv = profile.std_rate / profile.mean_rate
            variance_confidence = 1.0 / (1.0 + cv)
        else:
            variance_confidence = 1.0

        # Combined confidence
        confidence = (data_confidence + variance_confidence) / 2

        return confidence

    def update_trust_score(self, identifier: str, adjustment: float):
        """
        Manually adjust trust score for a user

        Args:
            identifier: User identifier
            adjustment: Trust adjustment (-1.0 to +1.0)
        """
        if identifier in self.user_profiles:
            profile = self.user_profiles[identifier]
            old_trust = profile.trust_score

            profile.trust_score = max(0.0, min(1.0, profile.trust_score + adjustment))

            if self.on_trust_change:
                self.on_trust_change(identifier, profile.trust_score)

            logger.info(
                f"Trust score adjusted for {identifier}: "
                f"{old_trust:.2f} -> {profile.trust_score:.2f}"
            )

    def get_user_profile(self, identifier: str) -> Optional[Dict[str, Any]]:
        """
        Get user profile information

        Returns:
            Dict with profile data or None if not found
        """
        if identifier not in self.user_profiles:
            return None

        profile = self.user_profiles[identifier]

        return {
            "identifier": identifier,
            "first_seen": datetime.fromtimestamp(profile.first_seen).isoformat(),
            "last_seen": datetime.fromtimestamp(profile.last_seen).isoformat(),
            "age_days": (time.time() - profile.first_seen) / 86400,
            "request_count": profile.request_count,
            "mean_rate": profile.mean_rate,
            "std_rate": profile.std_rate,
            "trust_score": profile.trust_score,
            "violation_count": profile.violation_count,
            "good_behavior_days": profile.good_behavior_days,
            "current_limit": self._adjust_limit(profile, False),
            "metadata": profile.metadata,
        }

    def get_statistics(self) -> Dict[str, Any]:
        """Get limiter statistics"""
        return {
            "total_requests": self.stats["total_requests"],
            "anomalies_detected": self.stats["anomalies_detected"],
            "limits_adjusted": self.stats["limits_adjusted"],
            "users_tracked": self.stats["users_tracked"],
            "configuration": {
                "base_limit": self.base_limit,
                "window": self.window,
                "learning_rate": self.learning_rate,
                "anomaly_threshold": self.anomaly_threshold,
                "trust_enabled": self.trust_enabled,
            },
        }

    def export_model(self, filepath: str):
        """
        Export learned model for persistence

        Args:
            filepath: Path to save model
        """
        model_data = {
            "version": "1.0",
            "timestamp": time.time(),
            "config": {
                "base_limit": self.base_limit,
                "window": self.window,
                "learning_rate": self.learning_rate,
                "anomaly_threshold": self.anomaly_threshold,
                "trust_enabled": self.trust_enabled,
                "min_multiplier": self.min_multiplier,
                "max_multiplier": self.max_multiplier,
            },
            "profiles": {
                identifier: {
                    "identifier": p.identifier,
                    "first_seen": p.first_seen,
                    "last_seen": p.last_seen,
                    "request_count": p.request_count,
                    "mean_rate": p.mean_rate,
                    "std_rate": p.std_rate,
                    "trust_score": p.trust_score,
                    "violation_count": p.violation_count,
                    "good_behavior_days": p.good_behavior_days,
                    "request_rates": list(p.request_rates),
                    "metadata": p.metadata,
                }
                for identifier, p in self.user_profiles.items()
            },
            "stats": self.stats,
        }

        with open(filepath, "w") as f:
            json.dump(model_data, f, indent=2)

        logger.info(f"Model exported to {filepath}")

    def load_model(self, filepath: str):
        """
        Load previously exported model

        Args:
            filepath: Path to load model from
        """
        with open(filepath, "r") as f:
            model_data = json.load(f)

        # Restore profiles
        for identifier, data in model_data["profiles"].items():
            profile = UserProfile(
                identifier=data["identifier"],
                first_seen=data["first_seen"],
                last_seen=data["last_seen"],
                request_count=data["request_count"],
                mean_rate=data["mean_rate"],
                std_rate=data["std_rate"],
                trust_score=data["trust_score"],
                violation_count=data["violation_count"],
                good_behavior_days=data["good_behavior_days"],
                request_rates=deque(data["request_rates"], maxlen=100),
                metadata=data.get("metadata", {}),
            )
            self.user_profiles[identifier] = profile

        # Restore stats
        self.stats = model_data["stats"]

        logger.info(f"Model loaded from {filepath} " f"({len(self.user_profiles)} profiles)")

    def reset_user(self, identifier: str):
        """Reset a user's profile"""
        if identifier in self.user_profiles:
            del self.user_profiles[identifier]
            self.request_history.pop(identifier, None)
            logger.info(f"User profile reset: {identifier}")

    def __repr__(self) -> str:
        return (
            f"AdaptiveRateLimiter("
            f"base_limit={self.base_limit}, "
            f"users={len(self.user_profiles)}, "
            f"anomalies={self.stats['anomalies_detected']})"
        )
