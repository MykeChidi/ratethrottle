"""
RateThrottle - Alerting
"""

import json
import logging
import os
import smtplib
import ssl
import time
import urllib.request
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class AlertDispatcher:
    """
    Evaluate live metrics against thresholds and dispatch alerts.

      - __init__ accepts an optional storage parameter.
      - _cooled_down / _mark_fired delegate to storage when available,
        falling back to a local dict when storage is None.
    """

    def __init__(self, config: Dict[str, Any], storage=None):
        """
        Args:
            config:  Dict from ConfigManager.get_alerting_config().
            storage: Optional shared StorageBackend (InMemoryStorage or
                     RedisStorage).  Pass the same instance used by
                     RateThrottleCore for distributed cooldown tracking.
        """
        self.enabled = bool(config.get("enabled", False))
        self.cooldown_seconds = int(config.get("cooldown_seconds", 300))

        thresholds = config.get("thresholds", {})
        self.thresholds = {
            "block_rate_warning": float(thresholds.get("block_rate_warning", 5.0)),
            "block_rate_critical": float(thresholds.get("block_rate_critical", 20.0)),
            "violations_per_minute_warning": float(
                thresholds.get("violations_per_minute_warning", 50)
            ),
            "violations_per_minute_critical": float(
                thresholds.get("violations_per_minute_critical", 200)
            ),
            "ddos_score_warning": float(thresholds.get("ddos_score_warning", 0.5)),
            "ddos_score_critical": float(thresholds.get("ddos_score_critical", 0.8)),
        }

        self._slack_cfg = config.get("slack", {})
        self._webhook_cfg = config.get("webhook", {})
        self._email_cfg = config.get("email", {})
        self._pagerduty_cfg = config.get("pagerduty", {})

        # Shared storage for distributed cooldown
        self._storage = storage  # None → local dict
        self._local_cooldown: Dict[str, float] = {}  # fallback only

        # State for violations-per-minute delta
        self._last_check_time: float = time.time()
        self._last_violation_count: int = 0

        logger.info(
            f"AlertDispatcher initialised: enabled={self.enabled}, "
            f"cooldown={self.cooldown_seconds}s, "
            f"distributed={'yes (storage=' + type(storage).__name__ + ')' if storage else 'no (local)'}"  # noqa
        )

    def check_and_alert(self, snapshot: Dict[str, Any]) -> None:
        if not self.enabled:
            return

        limiter_data = snapshot.get("limiter", {})
        analytics_data = snapshot.get("analytics", {})
        ddos_data = snapshot.get("ddos", {})

        # Block rate
        block_rate = float(limiter_data.get("block_rate", 0.0))
        self._evaluate(
            "block_rate",
            block_rate,
            self.thresholds["block_rate_warning"],
            self.thresholds["block_rate_critical"],
            {"block_rate_pct": block_rate},
        )

        # Violations per minute
        now = time.time()
        total_violations = int(analytics_data.get("total_violations", 0))
        elapsed = max(1.0, now - self._last_check_time)
        vpm = (total_violations - self._last_violation_count) / elapsed * 60.0
        self._last_check_time = now
        self._last_violation_count = total_violations

        if vpm > 0:
            self._evaluate(
                "violations_per_minute",
                vpm,
                self.thresholds["violations_per_minute_warning"],
                self.thresholds["violations_per_minute_critical"],
                {"violations_per_minute": round(vpm, 2)},
            )

        # DDoS score
        ddos_score = float(ddos_data.get("detection_rate", 0.0)) / 100.0
        if ddos_score > 0:
            self._evaluate(
                "ddos_score",
                ddos_score,
                self.thresholds["ddos_score_warning"],
                self.thresholds["ddos_score_critical"],
                {
                    "ddos_score": round(ddos_score, 4),
                    "blocked_ips": ddos_data.get("blocked_ips", 0),
                },
            )

    def send(
        self,
        severity: str,
        event: str,
        rule: str = "",
        value: float = 0.0,
        threshold: float = 0.0,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self.enabled:
            return
        if not self._cooled_down(event, severity):
            logger.debug(f"Alert suppressed (cooldown): {event}/{severity}")
            return

        payload = self._build_payload(severity, event, rule, value, threshold, details or {})
        channels_fired = self._dispatch(payload, severity)

        if channels_fired:
            self._mark_fired(event, severity)
            logger.info(
                f"Alert [{severity.upper()}] {event} value={value:.2f} "
                f"threshold={threshold:.2f} via {', '.join(channels_fired)}"
            )

    @staticmethod
    def _cd_key(event: str, severity: str) -> str:
        return f"rt:alert_cd:{event}:{severity}"

    def _cooled_down(self, event: str, severity: str) -> bool:
        """True when it is safe to fire (cooldown has elapsed or not started)."""
        key = self._cd_key(event, severity)
        if self._storage is not None:
            try:
                return not self._storage.exists(key)
            except Exception as exc:
                logger.warning(f"Cooldown read failed ({exc}); allowing alert")
                return True
        # Local fallback
        return (time.time() - self._local_cooldown.get(key, 0.0)) >= self.cooldown_seconds

    def _mark_fired(self, event: str, severity: str) -> None:
        """Record firing so subsequent calls are suppressed during the cooldown window."""
        key = self._cd_key(event, severity)
        if self._storage is not None:
            try:
                self._storage.set(key, "1", ttl=self.cooldown_seconds)
            except Exception as exc:
                logger.warning(f"Cooldown write failed ({exc}); cooldown not set")
        else:
            self._local_cooldown[key] = time.time()

    def _evaluate(
        self,
        metric: str,
        value: float,
        warn_threshold: float,
        crit_threshold: float,
        details: Dict[str, Any],
    ) -> None:
        if value >= crit_threshold:
            self.send(
                "critical",
                f"{metric}_exceeded",
                value=value,
                threshold=crit_threshold,
                details=details,
            )
        elif value >= warn_threshold:
            self.send(
                "warning",
                f"{metric}_exceeded",
                value=value,
                threshold=warn_threshold,
                details=details,
            )

    def _build_payload(
        self,
        severity: str,
        event: str,
        rule: str,
        value: float,
        threshold: float,
        details: Dict[str, Any],
    ) -> Dict[str, Any]:
        icon = "🔴" if severity == "critical" else "🟡"
        return {
            "severity": severity,
            "event": event,
            "rule": rule,
            "value": value,
            "threshold": threshold,
            "timestamp": datetime.now().isoformat(),
            "icon": icon,
            "title": f"{icon} RateThrottle [{severity.upper()}] {event}",
            "message": (
                f"{event} — value {value:.2f} exceeded "
                f"{severity} threshold {threshold:.2f}" + (f" (rule: {rule})" if rule else "")
            ),
            "details": details,
        }

    def _dispatch(self, payload: Dict[str, Any], severity: str) -> List[str]:
        fired: List[str] = []
        for name, fn in [
            ("slack", lambda p: self._send_slack(p)),
            ("webhook", lambda p: self._send_webhook(p)),
            ("email", lambda p: self._send_email(p)),
            ("pagerduty", lambda p: self._send_pagerduty(p, severity)),
        ]:
            if getattr(self, f"_{name}_cfg").get("enabled"):
                try:
                    fn(payload)
                    fired.append(name)
                except Exception as exc:
                    logger.error(f"{name} alert failed: {exc}")
        return fired

    def _send_slack(self, payload: Dict[str, Any]) -> None:
        url = os.environ.get("RT_SLACK_WEBHOOK_URL") or self._slack_cfg.get("webhook_url", "")
        if not url:
            raise ValueError("Slack webhook_url not configured")
        self._http_post(
            url,
            {
                "channel": self._slack_cfg.get("channel", "#alerts"),
                "username": self._slack_cfg.get("username", "RateThrottle"),
                "text": payload["title"],
                "attachments": [
                    {
                        "color": "danger" if payload["severity"] == "critical" else "warning",
                        "fields": [
                            {"title": "Event", "value": payload["event"], "short": True},
                            {
                                "title": "Severity",
                                "value": payload["severity"].upper(),
                                "short": True,
                            },
                            {
                                "title": "Value",
                                "value": str(round(payload["value"], 3)),
                                "short": True,
                            },
                            {
                                "title": "Threshold",
                                "value": str(payload["threshold"]),
                                "short": True,
                            },
                            {"title": "Time", "value": payload["timestamp"], "short": False},
                        ]
                        + [
                            {"title": k, "value": str(v), "short": True}
                            for k, v in payload["details"].items()
                        ],
                    }
                ],
            },
        )

    def _send_webhook(self, payload: Dict[str, Any]) -> None:
        url = self._webhook_cfg.get("url", "")
        if not url:
            raise ValueError("Webhook url not configured")
        self._http_post(
            url,
            payload,
            extra_headers=self._webhook_cfg.get("headers", {}),
            timeout=int(self._webhook_cfg.get("timeout", 10)),
        )

    def _send_email(self, payload: Dict[str, Any]) -> None:
        cfg = self._email_cfg
        to = cfg.get("to_addresses", [])
        if not to:
            raise ValueError("Email to_addresses is empty")
        body = "\n".join(
            [
                payload["message"],
                "",
                f"Timestamp : {payload['timestamp']}",
                f"Event     : {payload['event']}",
                f"Severity  : {payload['severity'].upper()}",
                f"Value     : {payload['value']:.4f}",
                f"Threshold : {payload['threshold']:.4f}",
            ]
            + (
                ["", "Details:"] + [f"  {k}: {v}" for k, v in payload["details"].items()]
                if payload["details"]
                else []
            )
        )
        msg = MIMEMultipart("alternative")
        msg["Subject"] = payload["title"]
        msg["From"] = cfg.get("from_address", "")
        msg["To"] = ", ".join(to)
        msg.attach(MIMEText(body, "plain"))
        host = cfg.get("smtp_host", "localhost")
        port = int(cfg.get("smtp_port", 587))
        use_tls = bool(cfg.get("use_tls", True))
        username = cfg.get("username", "")
        password = os.environ.get("RT_EMAIL_PASSWORD") or cfg.get("password", "")
        with smtplib.SMTP(host, port) as server:
            if use_tls:
                server.ehlo()
                server.starttls(context=ssl.create_default_context())
            if username and password:
                server.login(username, password)
            server.sendmail(msg["From"], to, msg.as_string())

    def _send_pagerduty(self, payload: Dict[str, Any], severity: str) -> None:
        key = os.environ.get("RT_PAGERDUTY_KEY") or self._pagerduty_cfg.get("routing_key", "")
        if not key:
            raise ValueError("PagerDuty routing_key not configured")
        self._http_post(
            "https://events.pagerduty.com/v2/enqueue",
            {
                "routing_key": key,
                "event_action": "trigger",
                "payload": {
                    "summary": payload["message"],
                    "severity": severity,
                    "source": "ratethrottle",
                    "timestamp": payload["timestamp"],
                    "custom_details": {
                        "event": payload["event"],
                        "value": payload["value"],
                        "threshold": payload["threshold"],
                        **payload["details"],
                    },
                },
            },
        )

    @staticmethod
    def _http_post(
        url: str,
        body: Dict[str, Any],
        extra_headers: Optional[Dict[str, str]] = None,
        timeout: int = 10,
    ) -> None:
        data = json.dumps(body, default=str).encode()
        headers = {"Content-Type": "application/json", "User-Agent": "ratethrottle/1.0"}
        if extra_headers:
            headers.update(extra_headers)
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec
            if resp.status not in (200, 201, 202, 204):
                raise RuntimeError(f"HTTP {resp.status} from {url}")

    def __repr__(self) -> str:
        channels = [
            n
            for n, c in [
                ("slack", self._slack_cfg),
                ("webhook", self._webhook_cfg),
                ("email", self._email_cfg),
                ("pagerduty", self._pagerduty_cfg),
            ]
            if c.get("enabled")
        ]
        return (
            f"AlertDispatcher(enabled={self.enabled}, "
            f"channels=[{', '.join(channels) or 'none'}], "
            f"cooldown={self.cooldown_seconds}s, "
            f"distributed={self._storage is not None})"
        )
