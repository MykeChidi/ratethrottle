"""
Tests for alerting module
"""

import importlib.util
import os
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

try:
    from ratethrottle.alerting import AlertDispatcher
except ModuleNotFoundError:
    spec = importlib.util.spec_from_file_location(
        "ratethrottle.alerting",
        Path(__file__).resolve().parents[1] / "ratethrottle" / "alerting.py",
    )
    alerting = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(alerting)
    AlertDispatcher = alerting.AlertDispatcher


class DummyStorage:
    def __init__(self):
        self._store = {}

    def exists(self, key):
        return key in self._store

    def set(self, key, value, ttl=None):
        self._store[key] = (value, ttl)


def test_disabled_dispatcher_does_nothing():
    dispatcher = AlertDispatcher({"enabled": False})
    dispatcher._dispatch = Mock()

    dispatcher.check_and_alert(
        {"limiter": {"block_rate": 100.0}, "analytics": {"total_violations": 10}, "ddos": {"detection_rate": 10.0}}
    )

    dispatcher._dispatch.assert_not_called()


def test_build_payload_contains_expected_fields():
    dispatcher = AlertDispatcher({"enabled": True})
    payload = dispatcher._build_payload(
        "warning",
        "block_rate_exceeded",
        "test_rule",
        12.5,
        10.0,
        {"blocked_ips": 3},
    )

    assert payload["severity"] == "warning"
    assert "block_rate_exceeded" in payload["event"]
    assert payload["rule"] == "test_rule"
    assert payload["details"]["blocked_ips"] == 3
    assert payload["icon"] == "🟡"


def test_send_respects_local_cooldown():
    dispatched = []

    def fake_dispatch(payload, severity):
        dispatched.append((payload, severity))
        return ["webhook"]

    dispatcher = AlertDispatcher({"enabled": True, "cooldown_seconds": 1000})
    dispatcher._dispatch = fake_dispatch

    dispatcher.send("warning", "block_rate_exceeded", value=20.0, threshold=10.0)
    dispatcher.send("warning", "block_rate_exceeded", value=20.0, threshold=10.0)

    assert len(dispatched) == 1


def test_send_uses_storage_for_cooldown():
    storage = DummyStorage()
    dispatcher = AlertDispatcher({"enabled": True, "cooldown_seconds": 1000}, storage=storage)
    dispatcher._dispatch = Mock(return_value=["webhook"])

    dispatcher.send("critical", "ddos_score_exceeded", value=0.9, threshold=0.8)

    assert dispatcher._dispatch.called
    assert any(key.startswith("rt:alert_cd:") for key in storage._store)


def test_slack_dispatch_uses_environment_webhook(monkeypatch):
    monkeypatch.setenv("RT_SLACK_WEBHOOK_URL", "https://example.com/api/slack")

    sent = []

    def fake_http_post(url, body, extra_headers=None, timeout=10):
        sent.append((url, body, extra_headers, timeout))

    dispatcher = AlertDispatcher(
        {
            "enabled": True,
            "slack": {"enabled": True, "channel": "#alerts", "username": "RateThrottle"},
        }
    )
    dispatcher._http_post = fake_http_post

    dispatcher.send("warning", "block_rate_exceeded", value=10.0, threshold=5.0)

    assert sent[0][0] == "https://example.com/api/slack"
    assert sent[0][1]["attachments"][0]["fields"][0]["title"] == "Event"


def test_webhook_dispatch_raises_without_url():
    dispatcher = AlertDispatcher({"enabled": True, "webhook": {"enabled": True}})

    with pytest.raises(ValueError, match="Webhook url not configured"):
        dispatcher._send_webhook({"event": "test"})


def test_pagerduty_dispatch_raises_without_routing_key(monkeypatch):
    monkeypatch.delenv("RT_PAGERDUTY_KEY", raising=False)
    dispatcher = AlertDispatcher({"enabled": True, "pagerduty": {"enabled": True}})

    with pytest.raises(ValueError, match="PagerDuty routing_key not configured"):
        dispatcher._send_pagerduty({"event": "test", "timestamp": "now", "message": "m"}, "critical")
