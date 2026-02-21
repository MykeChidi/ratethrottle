"""
RateThrottle - DDoS Protection Layer

DDoS detection and mitigation with advanced traffic
analysis and false positive prevention.
"""

import logging
import time
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

from .exceptions import ConfigurationError

logger = logging.getLogger(__name__)


@dataclass
class TrafficPattern:
    """
    Represents analyzed traffic pattern

    Attributes:
        identifier: Client identifier being analyzed
        request_rate: Requests per second
        unique_endpoints: Number of unique endpoints accessed
        suspicious_score: Suspicion score (0.0 to 1.0)
        is_suspicious: Whether pattern is considered suspicious
        analysis_window: Time window analyzed in seconds
        timestamp: When analysis was performed
        metadata: Additional context information
    """

    identifier: str
    request_rate: float
    unique_endpoints: int
    suspicious_score: float
    is_suspicious: bool
    analysis_window: int
    timestamp: float
    metadata: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return asdict(self)


class DDoSProtection:
    """
    Advanced DDoS detection and mitigation

    Features:
        - Traffic pattern analysis
        - Suspicious activity detection
        - Automatic blocking
        - False positive prevention
        - Configurable thresholds
        - Statistics tracking

    Detection Methods:
        - High request rate detection
        - Scanning behavior detection (many unique endpoints)
        - Burst pattern detection
        - Uniform interval detection (bot behavior)

    Examples:
        >>> ddos = DDoSProtection({
        ...     'enabled': True,
        ...     'threshold': 10000,
        ...     'window': 60,
        ...     'auto_block': True
        ... })
        >>> pattern = ddos.analyze_traffic('192.168.1.100', '/api/data')
        >>> if pattern.is_suspicious:
        ...     print(f"Suspicious! Score: {pattern.suspicious_score}")
    """

    # Default configuration
    DEFAULT_CONFIG = {
        "enabled": True,
        "threshold": 10000,  # requests per window
        "window": 60,  # seconds
        "auto_block": True,
        "block_duration": 3600,
        "suspicious_threshold": 0.5,  # 0.0 to 1.0
        "max_unique_endpoints": 50,
        "burst_threshold": 100,  # requests in short time
        "burst_window": 10,  # seconds
        "min_interval_threshold": 0.1,  # seconds
        "whitelist_on_good_behavior": True,
        "good_behavior_threshold": 1000,  # requests without issues
    }

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize DDoS protection

        Args:
            config: Configuration dictionary

        Raises:
            ConfigurationError: If configuration is invalid
        """
        # Merge with defaults
        self.config = self.DEFAULT_CONFIG.copy()
        if config:
            self.config.update(config)

        # Validate configuration
        self._validate_config()

        # Extract frequently used config
        self.enabled = self.config["enabled"]
        self.threshold = self.config["threshold"]
        self.window = self.config["window"]
        self.auto_block = self.config["auto_block"]
        self.block_duration = self.config["block_duration"]
        self.suspicious_threshold = self.config["suspicious_threshold"]
        self.max_unique_endpoints = self.config["max_unique_endpoints"]

        # Tracking data structures
        self.request_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=10000))
        self.endpoint_tracking: Dict[str, Set[str]] = defaultdict(set)
        self.blocked_ips: Set[str] = set()
        self.block_expiry: Dict[str, float] = {}
        self.suspicious_patterns: List[TrafficPattern] = []
        self.good_behavior_counts: Dict[str, int] = defaultdict(int)
        self.whitelisted_ips: Set[str] = set()

        # Statistics
        self.stats = {
            "total_analyzed": 0,
            "suspicious_detected": 0,
            "auto_blocked": 0,
            "false_positives_prevented": 0,
        }

        logger.info(
            f"DDoS Protection initialized: "
            f"enabled={self.enabled}, threshold={self.threshold}/{self.window}s"
        )

    def _validate_config(self) -> None:
        """Validate configuration parameters"""
        if self.config["threshold"] <= 0:
            raise ConfigurationError(
                f"DDoS threshold must be positive, got {self.config['threshold']}"
            )

        if self.config["window"] <= 0:
            raise ConfigurationError(f"DDoS window must be positive, got {self.config['window']}")

        if not 0 <= self.config["suspicious_threshold"] <= 1:
            raise ConfigurationError(
                f"Suspicious threshold must be 0-1, got {self.config['suspicious_threshold']}"
            )

        if self.config["block_duration"] < 0:
            raise ConfigurationError(
                f"Block duration cannot be negative, got {self.config['block_duration']}"
            )

    def analyze_traffic(
        self,
        identifier: str,
        endpoint: str,
        timestamp: Optional[float] = None,
        user_agent: Optional[str] = None,
        method: Optional[str] = None,
    ) -> TrafficPattern:
        """
        Analyze traffic pattern for potential DDoS

        Args:
            identifier: Client identifier (IP, user, etc.)
            endpoint: Requested endpoint
            timestamp: Request timestamp (default: now)
            user_agent: Optional user agent string
            method: Optional HTTP method

        Returns:
            TrafficPattern with analysis results

        Examples:
            >>> pattern = ddos.analyze_traffic(
            ...     '192.168.1.100',
            ...     '/api/data',
            ...     user_agent='Mozilla/5.0...',
            ...     method='GET'
            ... )
            >>> if pattern.is_suspicious:
            ...     print(f"Suspicious activity: score {pattern.suspicious_score}")
        """
        if not self.enabled:
            return TrafficPattern(
                identifier=identifier,
                request_rate=0.0,
                unique_endpoints=0,
                suspicious_score=0.0,
                is_suspicious=False,
                analysis_window=int(self.window),
                timestamp=time.time(),
            )

        now = timestamp or time.time()

        # Check if already blocked and expired
        self._cleanup_expired_blocks(now)

        # Check if whitelisted
        if identifier in self.whitelisted_ips:
            return TrafficPattern(
                identifier=identifier,
                request_rate=0.0,
                unique_endpoints=0,
                suspicious_score=0.0,
                is_suspicious=False,
                analysis_window=int(self.window),
                timestamp=now,
                metadata={"whitelisted": 1.0},
            )

        # Record request
        self.request_history[identifier].append(now)
        self.endpoint_tracking[identifier].add(endpoint)
        self.stats["total_analyzed"] += 1

        # Get recent requests within window
        recent_requests = [ts for ts in self.request_history[identifier] if now - ts < self.window]

        # Calculate metrics
        request_rate = len(recent_requests) / self.window
        unique_endpoints = len(self.endpoint_tracking[identifier])

        # Calculate suspicion score
        suspicious_score, score_breakdown = self._calculate_suspicion_score(
            identifier=identifier,
            request_rate=request_rate,
            unique_endpoints=unique_endpoints,
            recent_requests=recent_requests,
            now=now,
            user_agent=user_agent,
            method=method,
        )

        is_suspicious = suspicious_score >= self.suspicious_threshold

        # Create pattern
        pattern = TrafficPattern(
            identifier=identifier,
            request_rate=request_rate,
            unique_endpoints=unique_endpoints,
            suspicious_score=suspicious_score,
            is_suspicious=is_suspicious,
            analysis_window=int(self.window),
            timestamp=now,
            metadata=score_breakdown,
        )

        # Handle suspicious activity
        if is_suspicious:
            self.stats["suspicious_detected"] += 1
            self._handle_suspicious_activity(pattern)
        else:
            # Track good behavior
            self._track_good_behavior(identifier)

        return pattern

    def _calculate_suspicion_score(
        self,
        identifier: str,
        request_rate: float,
        unique_endpoints: int,
        recent_requests: List[float],
        now: float,
        user_agent: Optional[str],
        method: Optional[str],
    ) -> Tuple[float, Dict[str, float]]:
        """
        Calculate suspicion score based on multiple factors

        Returns:
            Tuple of (total_score, score_breakdown)
        """
        score_breakdown = {}
        total_score = 0.0

        # Factor 1: High request rate (0-40% of score)
        rate_threshold = self.threshold / self.window
        if request_rate > rate_threshold:
            rate_score = min(0.4, 0.4 * (request_rate / rate_threshold - 1))
            total_score += rate_score
            score_breakdown["high_rate"] = rate_score
            logger.debug(
                f"{identifier}: High rate detected: "
                f"{request_rate:.2f} req/s (threshold: {rate_threshold:.2f})"
            )
        elif request_rate > rate_threshold * 0.5:
            rate_score = 0.2 * (request_rate / (rate_threshold * 0.5) - 1)
            total_score += rate_score
            score_breakdown["elevated_rate"] = rate_score

        # Factor 2: Too many unique endpoints (scanning behavior) (0-30% of score)
        if unique_endpoints > self.max_unique_endpoints:
            endpoint_score = min(0.3, 0.3 * (unique_endpoints / self.max_unique_endpoints - 1))
            total_score += endpoint_score
            score_breakdown["many_endpoints"] = endpoint_score
            logger.debug(
                f"{identifier}: Scanning behavior: " f"{unique_endpoints} unique endpoints"
            )
        elif unique_endpoints > self.max_unique_endpoints * 0.5:
            endpoint_score = 0.15 * (unique_endpoints / (self.max_unique_endpoints * 0.5) - 1)
            total_score += endpoint_score
            score_breakdown["elevated_endpoints"] = endpoint_score

        # Factor 3: Burst detection (0-20% of score)
        if len(recent_requests) >= 10:
            burst_window = self.config.get("burst_window", 10)
            burst_threshold = self.config.get("burst_threshold", 100)

            # Count requests in last burst_window seconds
            burst_count = sum(1 for ts in recent_requests if now - ts < burst_window)

            if burst_count > burst_threshold:
                burst_score = min(0.2, 0.2 * (burst_count / burst_threshold - 1))
                total_score += burst_score
                score_breakdown["burst"] = burst_score
                logger.debug(
                    f"{identifier}: Burst detected: " f"{burst_count} requests in {burst_window}s"
                )

        # Factor 4: Uniform intervals (bot behavior) (0-20% of score)
        if len(recent_requests) >= 20:
            intervals = [
                recent_requests[i + 1] - recent_requests[i] for i in range(len(recent_requests) - 1)
            ]

            if intervals:
                avg_interval = sum(intervals) / len(intervals)
                min_threshold = self.config.get("min_interval_threshold", 0.1)

                # Very uniform intervals suggest bot
                if avg_interval < min_threshold:
                    uniform_score = 0.2
                    total_score += uniform_score
                    score_breakdown["uniform_intervals"] = uniform_score
                    logger.debug(
                        f"{identifier}: Bot-like behavior: " f"avg interval {avg_interval:.3f}s"
                    )

                # All recent requests with very short intervals
                recent_intervals = intervals[-20:]
                if all(interval < 0.5 for interval in recent_intervals):
                    rapid_score = 0.1
                    total_score += rapid_score
                    score_breakdown["rapid_succession"] = rapid_score

        # Factor 5: Missing or suspicious user agent (0-10% of score)
        if user_agent:
            # Simple user agent validation
            suspicious_agents = ["bot", "crawler", "spider", "scraper"]
            if any(agent in user_agent.lower() for agent in suspicious_agents):
                agent_score = 0.05
                total_score += agent_score
                score_breakdown["suspicious_agent"] = agent_score
        else:
            # No user agent provided
            no_agent_score = 0.1
            total_score += no_agent_score
            score_breakdown["no_user_agent"] = no_agent_score

        # Cap at 1.0
        total_score = min(1.0, total_score)

        return total_score, score_breakdown

    def _handle_suspicious_activity(self, pattern: TrafficPattern) -> None:
        """Handle detected suspicious activity"""
        # Record pattern
        self.suspicious_patterns.append(pattern)

        # Cleanup old patterns (keep last hour)
        cutoff = pattern.timestamp - 3600
        self.suspicious_patterns = [p for p in self.suspicious_patterns if p.timestamp > cutoff]

        logger.warning(
            f"Suspicious activity: {pattern.identifier} "
            f"(score: {pattern.suspicious_score:.2f}, "
            f"rate: {pattern.request_rate:.2f} req/s, "
            f"endpoints: {pattern.unique_endpoints})"
        )

        # Auto-block if configured and not already blocked
        if self.auto_block and pattern.identifier not in self.blocked_ips:
            # Check for repeated suspicious behavior
            recent_suspicious = [
                p
                for p in self.suspicious_patterns
                if p.identifier == pattern.identifier
                and pattern.timestamp - p.timestamp < 300  # Last 5 minutes
            ]

            # Block if multiple suspicious events or very high score
            if len(recent_suspicious) >= 3 or pattern.suspicious_score >= 0.8:
                self.block_ip(pattern.identifier, int(self.block_duration))
                self.stats["auto_blocked"] += 1
                logger.warning(
                    f"Auto-blocked: {pattern.identifier} " f"(duration: {self.block_duration}s)"
                )

    def _track_good_behavior(self, identifier: str) -> None:
        """Track good behavior for whitelisting"""
        if not self.config.get("whitelist_on_good_behavior"):
            return

        self.good_behavior_counts[identifier] += 1

        threshold = self.config.get("good_behavior_threshold", 1000)

        # Whitelist after sustained good behavior
        if self.good_behavior_counts[identifier] >= threshold:
            if identifier not in self.whitelisted_ips:
                self.whitelisted_ips.add(identifier)
                logger.info(
                    f"Auto-whitelisted {identifier} after " f"{threshold} requests of good behavior"
                )
                self.stats["false_positives_prevented"] += 1

    def _cleanup_expired_blocks(self, now: float) -> None:
        """Remove expired blocks"""
        expired = [ip for ip, expiry in self.block_expiry.items() if expiry <= now]

        for ip in expired:
            self.blocked_ips.discard(ip)
            del self.block_expiry[ip]
            logger.info(f"Block expired: {ip}")

    def block_ip(self, identifier: str, duration: Optional[int] = None) -> None:
        """
        Block an IP address

        Args:
            identifier: Client identifier to block
            duration: Block duration in seconds (None for permanent)

        Examples:
            >>> ddos.block_ip('192.168.1.100', 3600)  # Block for 1 hour
            >>> ddos.block_ip('10.0.0.1')  # Permanent block
        """
        self.blocked_ips.add(identifier)

        if duration:
            self.block_expiry[identifier] = time.time() + duration
            logger.warning(f"Blocked {identifier} for {duration}s")
        else:
            logger.warning(f"Permanently blocked {identifier}")

        # Reset good behavior count
        self.good_behavior_counts[identifier] = 0

    def unblock_ip(self, identifier: str) -> bool:
        """
        Unblock an IP address

        Args:
            identifier: Client identifier to unblock

        Returns:
            True if was blocked and now unblocked, False if wasn't blocked
        """
        was_blocked = identifier in self.blocked_ips

        if was_blocked:
            self.blocked_ips.discard(identifier)
            self.block_expiry.pop(identifier, None)
            logger.info(f"Unblocked {identifier}")

        return was_blocked

    def is_blocked(self, identifier: str, now: Optional[float] = None) -> bool:
        """
        Check if identifier is currently blocked

        Args:
            identifier: Client identifier to check
            now: Current timestamp (default: time.time())

        Returns:
            True if blocked, False otherwise
        """
        if identifier not in self.blocked_ips:
            return False

        # Check if block expired
        if identifier in self.block_expiry:
            now = now or time.time()
            if self.block_expiry[identifier] <= now:
                self.unblock_ip(identifier)
                return False

        return True

    def whitelist_ip(self, identifier: str) -> None:
        """
        Add IP to whitelist (never blocked)

        Args:
            identifier: Client identifier to whitelist
        """
        self.whitelisted_ips.add(identifier)

        # Remove from blocked if present
        if identifier in self.blocked_ips:
            self.unblock_ip(identifier)

        logger.info(f"Whitelisted {identifier}")

    def remove_from_whitelist(self, identifier: str) -> bool:
        """
        Remove IP from whitelist

        Args:
            identifier: Client identifier to remove

        Returns:
            True if was whitelisted, False otherwise
        """
        was_whitelisted = identifier in self.whitelisted_ips

        if was_whitelisted:
            self.whitelisted_ips.discard(identifier)
            logger.info(f"Removed from whitelist: {identifier}")

        return was_whitelisted

    def get_statistics(self) -> Dict:
        """
        Get DDoS protection statistics

        Returns:
            Dictionary with statistics

        Examples:
            >>> stats = ddos.get_statistics()
            >>> print(f"Blocked IPs: {stats['blocked_ips']}")
            >>> print(f"Detection rate: {stats['detection_rate']:.2f}%")
        """
        now = time.time()
        self._cleanup_expired_blocks(now)

        # Calculate detection rate
        detection_rate = 0.0
        if self.stats["total_analyzed"] > 0:
            detection_rate = self.stats["suspicious_detected"] / self.stats["total_analyzed"] * 100

        return {
            "enabled": self.enabled,
            "blocked_ips": len(self.blocked_ips),
            "whitelisted_ips": len(self.whitelisted_ips),
            "suspicious_patterns_detected": len(self.suspicious_patterns),
            "monitored_identifiers": len(self.request_history),
            "total_analyzed": self.stats["total_analyzed"],
            "suspicious_detected": self.stats["suspicious_detected"],
            "auto_blocked": self.stats["auto_blocked"],
            "detection_rate": detection_rate,
            "false_positives_prevented": self.stats["false_positives_prevented"],
            "recent_suspicious": [
                {
                    "identifier": p.identifier,
                    "rate": f"{p.request_rate:.2f} req/s",
                    "score": f"{p.suspicious_score:.2f}",
                    "endpoints": p.unique_endpoints,
                    "time": datetime.fromtimestamp(p.timestamp).strftime("%H:%M:%S"),
                }
                for p in self.suspicious_patterns[-10:]
            ],
        }

    def reset_statistics(self) -> None:
        """Reset all statistics (keeps blocks and whitelist)"""
        self.stats = {
            "total_analyzed": 0,
            "suspicious_detected": 0,
            "auto_blocked": 0,
            "false_positives_prevented": 0,
        }
        logger.info("DDoS statistics reset")

    def clear_history(self, identifier: Optional[str] = None) -> None:
        """
        Clear request history

        Args:
            identifier: Specific identifier to clear (None for all)
        """
        if identifier:
            self.request_history.pop(identifier, None)
            self.endpoint_tracking.pop(identifier, None)
            self.good_behavior_counts.pop(identifier, None)
            logger.info(f"Cleared history for {identifier}")
        else:
            self.request_history.clear()
            self.endpoint_tracking.clear()
            self.good_behavior_counts.clear()
            logger.info("Cleared all history")

    def get_pattern_for_identifier(self, identifier: str) -> Optional[TrafficPattern]:
        """
        Get most recent pattern for identifier

        Args:
            identifier: Client identifier

        Returns:
            Most recent TrafficPattern or None
        """
        patterns = [p for p in reversed(self.suspicious_patterns) if p.identifier == identifier]

        return patterns[0] if patterns else None

    def export_report(self) -> Dict:
        """
        Export comprehensive report

        Returns:
            Dictionary with full report data
        """
        stats = self.get_statistics()

        return {
            "generated_at": datetime.now().isoformat(),
            "configuration": self.config,
            "statistics": stats,
            "blocked_ips": list(self.blocked_ips),
            "whitelisted_ips": list(self.whitelisted_ips),
            "suspicious_patterns": [p.to_dict() for p in self.suspicious_patterns[-50:]],
        }

    def __repr__(self) -> str:
        """String representation"""
        return (
            f"DDoSProtection(enabled={self.enabled}, "
            f"blocked={len(self.blocked_ips)}, "
            f"monitored={len(self.request_history)})"
        )
