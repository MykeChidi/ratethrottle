"""
Tests for monitoring module
"""

import importlib.util
import json
from pathlib import Path

import pytest

try:
    from ratethrottle.monitoring import RateThrottleMonitor
except ModuleNotFoundError:
    spec = importlib.util.spec_from_file_location(
        "ratethrottle.monitoring",
        Path(__file__).resolve().parents[1] / "ratethrottle" / "monitoring.py",
    )
    monitoring = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(monitoring)
    RateThrottleMonitor = monitoring.RateThrottleMonitor


class DummyLimiter:
    def __init__(self, metrics):
        self._metrics = metrics

    def get_metrics(self):
        return self._metrics


class DummyDDoS:
    def __init__(self, statistics):
        self._statistics = statistics

    def get_statistics(self):
        return self._statistics


class DummyAnalytics:
    def __init__(self, summary):
        self._summary = summary

    def get_summary(self):
        return self._summary


class BrokenSource:
    def get_metrics(self):
        raise RuntimeError("boom")


def test_invalid_interval_raises_value_error():
    with pytest.raises(ValueError, match="monitoring.interval must be positive"):
        RateThrottleMonitor({"interval": 0})


def test_snapshot_now_collects_all_sources():
    limiter = DummyLimiter({"total_requests": 10, "blocked_requests": 2, "block_rate": 20.0})
    ddos = DummyDDoS({"blocked_ips": 1, "detection_rate": 5.0})
    analytics = DummyAnalytics({"unique_identifiers": 4, "violation_rate": 25.0})

    monitor = RateThrottleMonitor(
        {
            "enabled": True,
            "interval": 1,
            "log_metrics": False,
            "export_json": False,
        },
        limiter=limiter,
        ddos=ddos,
        analytics=analytics,
    )

    snapshot = monitor.snapshot_now()

    assert "timestamp" in snapshot
    assert snapshot["limiter"]["total_requests"] == 10
    assert snapshot["ddos"]["blocked_ips"] == 1
    assert snapshot["analytics"]["violation_rate"] == 25.0


def test_snapshot_now_handles_source_errors():
    monitor = RateThrottleMonitor(
        {"interval": 1, "log_metrics": False, "export_json": False},
        limiter=BrokenSource(),
    )

    snapshot = monitor.snapshot_now()

    assert "limiter" in snapshot
    assert snapshot["limiter"]["error"] == "boom"


def test_export_json_writes_file(tmp_path):
    export_path = tmp_path / "metrics" / "metrics.json"
    monitor = RateThrottleMonitor(
        {
            "interval": 1,
            "log_metrics": False,
            "export_json": True,
            "export_path": str(export_path),
        },
        limiter=DummyLimiter({"total_requests": 1, "blocked_requests": 0, "block_rate": 0.0}),
    )

    snapshot = monitor.snapshot_now()
    monitor._write_json(snapshot)

    assert export_path.exists()
    loaded = json.loads(export_path.read_text())
    assert loaded["limiter"]["total_requests"] == 1


def test_latest_snapshot_returns_latest_value():
    monitor = RateThrottleMonitor(
        {"interval": 1, "log_metrics": False, "export_json": False},
        limiter=DummyLimiter({"total_requests": 5, "blocked_requests": 1, "block_rate": 20.0}),
    )

    monitor._tick()
    latest = monitor.latest_snapshot()

    assert latest["limiter"]["blocked_requests"] == 1
    assert "timestamp" in latest
