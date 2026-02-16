"""
RateThrottle - Analytics and Reporting

Production-grade analytics for rate limiting with comprehensive
reporting, data sanitization, and export capabilities.
"""

import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from .exceptions import ConfigurationError

logger = logging.getLogger(__name__)


class RateThrottleAnalytics:
    """
    Analytics and reporting for rate limiting behavior

    Features:
        - Violation tracking with metadata
        - Request logging and analysis
        - Top violators identification
        - Temporal analysis (timeline, patterns)
        - Rule statistics and performance
        - Data sanitization for privacy
        - Export capabilities (JSON, CSV)

    Examples:
        >>> analytics = RateThrottleAnalytics(max_history=10000)
        >>> analytics.record_request('192.168.1.1', 'api', True)
        >>> analytics.record_violation(violation)
        >>>
        >>> # Get insights
        >>> top_violators = analytics.get_top_violators(10)
        >>> timeline = analytics.get_violation_timeline(hours=24)
        >>>
        >>> # Export report
        >>> analytics.export_report('report.json')
    """

    def __init__(
        self, max_history: int = 10000, enable_metadata: bool = True, sanitize_data: bool = True
    ):
        """
        Initialize analytics

        Args:
            max_history: Maximum number of records to keep
            enable_metadata: Whether to store request metadata
            sanitize_data: Whether to sanitize sensitive data

        Raises:
            ConfigurationError: If max_history is invalid
        """
        if max_history <= 0:
            raise ConfigurationError(f"max_history must be positive, got {max_history}")

        self.max_history = max_history
        self.enable_metadata = enable_metadata
        self.sanitize_data = sanitize_data

        # Data storage
        self.violations: List[Dict] = []
        self.requests: List[Dict] = []

        # Aggregated statistics
        self.stats = {
            "total_requests": 0,
            "total_violations": 0,
            "unique_identifiers": set(),
            "rules_triggered": defaultdict(int),
            "violations_by_hour": defaultdict(int),
            "blocked_identifiers": set(),
        }

        logger.info(
            f"Analytics initialized: max_history={max_history}, " f"sanitize={sanitize_data}"
        )

    def _sanitize_identifier(self, identifier: str) -> str:
        """
        Sanitize identifier for privacy

        Args:
            identifier: Raw identifier (IP, user ID, etc.)

        Returns:
            Sanitized identifier
        """
        if not self.sanitize_data:
            return identifier

        # For IP addresses, mask last octet
        if "." in identifier:
            parts = identifier.split(".")
            if len(parts) == 4:
                return f"{parts[0]}.{parts[1]}.{parts[2]}.xxx"

        # For other identifiers, show first/last chars
        if len(identifier) > 8:
            return f"{identifier[:4]}...{identifier[-4:]}"

        return "****"

    def _sanitize_metadata(self, metadata: Optional[Dict]) -> Dict:
        """
        Sanitize metadata to remove sensitive information

        Args:
            metadata: Raw metadata dictionary

        Returns:
            Sanitized metadata dictionary
        """
        if not metadata:
            return {}

        if not self.sanitize_data:
            return metadata.copy()

        # List of keys to remove
        sensitive_keys = {
            "password",
            "token",
            "api_key",
            "secret",
            "authorization",
            "cookie",
            "session",
        }

        sanitized = {}
        for key, value in metadata.items():
            key_lower = key.lower()

            # Skip sensitive keys
            if any(sensitive in key_lower for sensitive in sensitive_keys):
                sanitized[key] = "***REDACTED***"
            else:
                sanitized[key] = value

        return sanitized

    def _maintain_history_limit(self, collection: List) -> None:
        """Maintain history size limit"""
        if len(collection) > self.max_history:
            # Remove oldest entries
            excess = len(collection) - self.max_history
            del collection[:excess]

    def record_request(
        self, identifier: str, rule_name: str, allowed: bool, metadata: Optional[Dict] = None
    ) -> None:
        """
        Record a rate limit check request

        Args:
            identifier: Client identifier
            rule_name: Rule that was applied
            allowed: Whether request was allowed
            metadata: Optional request metadata

        Examples:
            >>> analytics.record_request(
            ...     '192.168.1.1',
            ...     'api_default',
            ...     True,
            ...     {'endpoint': '/api/data', 'method': 'GET'}
            ... )
        """
        try:
            # Create record
            record = {
                "timestamp": datetime.now().isoformat(),
                "identifier": (
                    self._sanitize_identifier(identifier) if self.sanitize_data else identifier
                ),
                "rule": rule_name,
                "allowed": allowed,
            }

            # Add metadata if enabled
            if self.enable_metadata and metadata:
                record["metadata"] = self._sanitize_metadata(metadata)

            # Store record
            self.requests.append(record)
            self._maintain_history_limit(self.requests)

            # Update statistics
            self.stats["total_requests"] += 1
            self.stats["unique_identifiers"].add(identifier)
            self.stats["rules_triggered"][rule_name] += 1

            if not allowed:
                self.stats["blocked_identifiers"].add(identifier)

            logger.debug(
                f"Recorded request: {identifier} -> {rule_name} "
                f"({'allowed' if allowed else 'blocked'})"
            )

        except Exception as e:
            logger.error(f"Error recording request: {e}")

    def record_violation(self, violation) -> None:
        """
        Record a rate limit violation

        Args:
            violation: RateThrottleViolation object or dict

        Examples:
            >>> analytics.record_violation(violation_object)
        """
        try:
            # Convert to dict if needed
            if hasattr(violation, "to_dict"):
                violation_dict = violation.to_dict()
            elif isinstance(violation, dict):
                violation_dict = violation.copy()
            else:
                logger.error(f"Invalid violation type: {type(violation)}")
                return

            # Sanitize identifier
            if "identifier" in violation_dict and self.sanitize_data:
                original_id = violation_dict["identifier"]
                violation_dict["_original_identifier"] = original_id
                violation_dict["identifier"] = self._sanitize_identifier(original_id)

            # Sanitize metadata
            if "metadata" in violation_dict:
                violation_dict["metadata"] = self._sanitize_metadata(violation_dict["metadata"])

            # Store violation
            self.violations.append(violation_dict)
            self._maintain_history_limit(self.violations)

            # Update statistics
            self.stats["total_violations"] += 1

            # Track violations by hour
            if "timestamp" in violation_dict:
                try:
                    dt = datetime.fromisoformat(violation_dict["timestamp"])
                    hour_key = dt.strftime("%Y-%m-%d %H:00")
                    self.stats["violations_by_hour"][hour_key] += 1
                except (ValueError, TypeError):
                    pass

            logger.debug(
                f"Recorded violation: {violation_dict.get('identifier')} -> "
                f"{violation_dict.get('rule_name')}"
            )

        except Exception as e:
            logger.error(f"Error recording violation: {e}")

    def get_top_violators(self, limit: int = 10, time_window: Optional[int] = None) -> List[Dict]:
        """
        Get top violators by violation count

        Args:
            limit: Maximum number of violators to return
            time_window: Optional time window in seconds (None for all time)

        Returns:
            List of dicts with identifier and violation count

        Examples:
            >>> # Top 10 violators all time
            >>> top = analytics.get_top_violators(10)
            >>>
            >>> # Top 5 violators in last hour
            >>> top = analytics.get_top_violators(5, time_window=3600)
        """
        try:
            # Filter by time window if specified
            violations_to_analyze = self.violations

            if time_window:
                cutoff = datetime.now() - timedelta(seconds=time_window)
                violations_to_analyze = [
                    v
                    for v in self.violations
                    if "timestamp" in v and datetime.fromisoformat(v["timestamp"]) > cutoff
                ]

            # Count violations per identifier
            violator_counts = defaultdict(int)
            for violation in violations_to_analyze:
                identifier = violation.get("_original_identifier") or violation.get(
                    "identifier", "unknown"
                )
                violator_counts[identifier] += 1

            # Sort and limit
            top_violators = [
                {"identifier": k, "violations": v}
                for k, v in sorted(violator_counts.items(), key=lambda x: x[1], reverse=True)[
                    :limit
                ]
            ]

            logger.debug(f"Retrieved top {len(top_violators)} violators")
            return top_violators

        except Exception as e:
            logger.error(f"Error getting top violators: {e}")
            return []

    def get_violation_timeline(self, hours: int = 24, granularity: str = "hour") -> Dict[str, int]:
        """
        Get violation timeline

        Args:
            hours: Number of hours to analyze
            granularity: Time granularity ('hour', 'day', 'minute')

        Returns:
            Dictionary mapping timestamps to violation counts

        Examples:
            >>> # Hourly violations for last 24 hours
            >>> timeline = analytics.get_violation_timeline(24, 'hour')
            >>> # {'2025-02-13 10:00': 5, '2025-02-13 11:00': 8, ...}
        """
        try:
            cutoff = datetime.now() - timedelta(hours=hours)

            # Format string based on granularity
            if granularity == "minute":
                time_format = "%Y-%m-%d %H:%M"
            elif granularity == "hour":
                time_format = "%Y-%m-%d %H:00"
            elif granularity == "day":
                time_format = "%Y-%m-%d"
            else:
                logger.warning(f"Invalid granularity: {granularity}, using 'hour'")
                time_format = "%Y-%m-%d %H:00"

            # Count violations by time bucket
            timeline = defaultdict(int)
            for violation in self.violations:
                if "timestamp" not in violation:
                    continue

                try:
                    timestamp = datetime.fromisoformat(violation["timestamp"])
                    if timestamp > cutoff:
                        time_key = timestamp.strftime(time_format)
                        timeline[time_key] += 1
                except (ValueError, TypeError):
                    continue

            # Sort by timestamp
            sorted_timeline = dict(sorted(timeline.items()))

            logger.debug(f"Generated timeline: {len(sorted_timeline)} time buckets")
            return sorted_timeline

        except Exception as e:
            logger.error(f"Error generating timeline: {e}")
            return {}

    def get_rule_statistics(self) -> Dict[str, Dict]:
        """
        Get statistics per rule

        Returns:
            Dictionary mapping rule names to statistics

        Examples:
            >>> stats = analytics.get_rule_statistics()
            >>> print(stats['api_default']['violation_rate'])
        """
        try:
            stats = defaultdict(
                lambda: {
                    "total_requests": 0,
                    "allowed": 0,
                    "blocked": 0,
                    "violation_rate": 0.0,
                    "unique_identifiers": set(),
                }
            )

            # Analyze requests
            for request in self.requests:
                rule = request.get("rule", "unknown")
                stats[rule]["total_requests"] += 1

                if request.get("allowed", False):
                    stats[rule]["allowed"] += 1
                else:
                    stats[rule]["blocked"] += 1

                identifier = request.get("identifier")
                if identifier:
                    stats[rule]["unique_identifiers"].add(identifier)

            # Calculate violation rates and convert sets to counts
            result = {}
            for rule, data in stats.items():
                total = data["total_requests"]
                if total > 0:
                    data["violation_rate"] = (data["blocked"] / total) * 100

                # Convert set to count
                data["unique_identifiers"] = len(data["unique_identifiers"])

                result[rule] = data

            logger.debug(f"Generated statistics for {len(result)} rules")
            return result

        except Exception as e:
            logger.error(f"Error generating rule statistics: {e}")
            return {}

    def get_summary(self) -> Dict[str, Any]:
        """
        Get summary statistics

        Returns:
            Dictionary with summary statistics
        """
        return {
            "total_requests": self.stats["total_requests"],
            "total_violations": self.stats["total_violations"],
            "unique_identifiers": len(self.stats["unique_identifiers"]),
            "blocked_identifiers": len(self.stats["blocked_identifiers"]),
            "violation_rate": (
                (self.stats["total_violations"] / self.stats["total_requests"] * 100)
                if self.stats["total_requests"] > 0
                else 0.0
            ),
            "most_triggered_rule": (
                max(self.stats["rules_triggered"].items(), key=lambda x: x[1])[0]
                if self.stats["rules_triggered"]
                else None
            ),
            "records_stored": {"requests": len(self.requests), "violations": len(self.violations)},
        }

    def export_report(
        self, filename: str = "ratethrottle_report.json", include_raw_data: bool = False
    ) -> None:
        """
        Export comprehensive analytics report

        Args:
            filename: Output filename
            include_raw_data: Whether to include raw request/violation data

        Raises:
            IOError: If file cannot be written

        Examples:
            >>> # Export summary report
            >>> analytics.export_report('report.json')
            >>>
            >>> # Export with raw data
            >>> analytics.export_report('full_report.json', include_raw_data=True)
        """
        try:
            report = {
                "generated_at": datetime.now().isoformat(),
                "configuration": {
                    "max_history": self.max_history,
                    "metadata_enabled": self.enable_metadata,
                    "data_sanitized": self.sanitize_data,
                },
                "summary": self.get_summary(),
                "top_violators": self.get_top_violators(20),
                "violation_timeline_24h": self.get_violation_timeline(24),
                "violation_timeline_7d": self.get_violation_timeline(168, "day"),
                "rule_statistics": self.get_rule_statistics(),
            }

            # Include raw data if requested
            if include_raw_data:
                report["raw_data"] = {
                    "requests": self.requests[-1000:],  # Last 1000
                    "violations": self.violations[-500:],  # Last 500
                }

            # Write to file
            output_path = Path(filename)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            with open(output_path, "w") as f:
                json.dump(report, f, indent=2, default=str)

            logger.info(f"Report exported to {filename}")

        except Exception as e:
            logger.error(f"Error exporting report: {e}")
            raise IOError(f"Failed to export report: {e}") from e

    def export_csv(
        self, filename: str = "ratethrottle_violations.csv", data_type: str = "violations"
    ) -> None:
        """
        Export data as CSV

        Args:
            filename: Output filename
            data_type: Type of data to export ('violations' or 'requests')

        Raises:
            IOError: If file cannot be written
        """
        try:
            import csv

            # Select data to export
            if data_type == "violations":
                data = self.violations
            elif data_type == "requests":
                data = self.requests
            else:
                raise ValueError(f"Invalid data_type: {data_type}")

            if not data:
                logger.warning(f"No {data_type} data to export")
                return

            # Get all possible fields
            all_fields = set()
            for record in data:
                all_fields.update(record.keys())

            # Remove nested fields (like metadata)
            fields = sorted(
                [f for f in all_fields if not isinstance(data[0].get(f), (dict, list, set))]
            )

            # Write CSV
            output_path = Path(filename)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            with open(output_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(data)

            logger.info(f"CSV exported to {filename} ({len(data)} records)")

        except Exception as e:
            logger.error(f"Error exporting CSV: {e}")
            raise IOError(f"Failed to export CSV: {e}") from e

    def clear_old_data(self, days: int = 30) -> int:
        """
        Clear data older than specified days

        Args:
            days: Number of days to keep

        Returns:
            Number of records cleared
        """
        try:
            cutoff = datetime.now() - timedelta(days=days)

            # Filter violations
            initial_violations = len(self.violations)
            self.violations = [
                v
                for v in self.violations
                if "timestamp" in v and datetime.fromisoformat(v["timestamp"]) > cutoff
            ]

            # Filter requests
            initial_requests = len(self.requests)
            self.requests = [
                r
                for r in self.requests
                if "timestamp" in r and datetime.fromisoformat(r["timestamp"]) > cutoff
            ]

            cleared = (initial_violations - len(self.violations)) + (
                initial_requests - len(self.requests)
            )

            logger.info(f"Cleared {cleared} records older than {days} days")
            return cleared

        except Exception as e:
            logger.error(f"Error clearing old data: {e}")
            return 0

    def reset(self) -> None:
        """Reset all analytics data"""
        self.violations.clear()
        self.requests.clear()
        self.stats = {
            "total_requests": 0,
            "total_violations": 0,
            "unique_identifiers": set(),
            "rules_triggered": defaultdict(int),
            "violations_by_hour": defaultdict(int),
            "blocked_identifiers": set(),
        }
        logger.info("Analytics data reset")

    def __repr__(self) -> str:
        """String representation"""
        return (
            f"RateThrottleAnalytics("
            f"requests={len(self.requests)}, "
            f"violations={len(self.violations)})"
        )
