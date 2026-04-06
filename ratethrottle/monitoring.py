"""
RateThrottle - Monitoring
"""

import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class RateThrottleMonitor:
    """
    Background thread that snapshots metrics at a fixed wall-clock rate.

    Collects from three optional sources:
        limiter.get_metrics()       → total/allowed/blocked/block_rate
        ddos.get_statistics()       → blocked IPs, detection_rate, etc.
        analytics.get_summary()     → unique clients, violation_rate, etc.

    Snapshot structure:
        {
            "timestamp": "<ISO 8601>",
            "limiter":   { ... },
            "ddos":      { ... },   # present only when ddos supplied
            "analytics": { ... },   # present only when analytics supplied
        }

    AlertDispatcher.check_and_alert() accepts this dict directly.
    """

    def __init__(
        self,
        config: Dict[str, Any],
        limiter=None,
        ddos=None,
        analytics=None,
    ):
        self.enabled = bool(config.get("enabled", True))
        self.interval = int(config.get("interval", 60))
        self.log_metrics = bool(config.get("log_metrics", True))
        self.export_json = bool(config.get("export_json", False))
        self.export_path = Path(config.get("export_path", "metrics/metrics.json"))

        self.limiter = limiter
        self.ddos = ddos
        self.analytics = analytics

        if self.interval <= 0:
            raise ValueError(f"monitoring.interval must be positive, got {self.interval}")

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._latest: Dict[str, Any] = {}

        logger.info(
            f"RateThrottleMonitor initialised: "
            f"interval={self.interval}s, log={self.log_metrics}, "
            f"export_json={self.export_json}"
        )

    def start(self) -> None:
        """Start the background monitoring thread (idempotent)."""
        if not self.enabled:
            logger.info("Monitoring disabled — not starting")
            return
        if self._thread and self._thread.is_alive():
            logger.warning("Monitor already running")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, name="ratethrottle-monitor", daemon=True)
        self._thread.start()
        logger.info("RateThrottleMonitor started")

    def stop(self) -> None:
        """Signal the background thread to stop and wait for it."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=self.interval + 5)
            self._thread = None
        logger.info("RateThrottleMonitor stopped")

    def latest_snapshot(self) -> Dict[str, Any]:
        """Return the most recent snapshot (empty dict before first tick)."""
        with self._lock:
            return dict(self._latest)

    def snapshot_now(self) -> Dict[str, Any]:
        """Collect a snapshot immediately (synchronous, always safe to call)."""
        snapshot: Dict[str, Any] = {"timestamp": datetime.now().isoformat()}

        if self.limiter is not None:
            try:
                snapshot["limiter"] = self.limiter.get_metrics()
            except Exception as exc:
                logger.error(f"Monitor: limiter.get_metrics() failed: {exc}")
                snapshot["limiter"] = {"error": str(exc)}

        if self.ddos is not None:
            try:
                snapshot["ddos"] = self.ddos.get_statistics()
            except Exception as exc:
                logger.error(f"Monitor: ddos.get_statistics() failed: {exc}")
                snapshot["ddos"] = {"error": str(exc)}

        if self.analytics is not None:
            try:
                snapshot["analytics"] = self.analytics.get_summary()
            except Exception as exc:
                logger.error(f"Monitor: analytics.get_summary() failed: {exc}")
                snapshot["analytics"] = {"error": str(exc)}

        return snapshot

    def _loop(self) -> None:
        """
        Fixed-rate background loop.

        We track the *intended* next-tick time and sleep only for what
        remains after the tick completes.  If a tick overshoots by a full
        interval we skip ahead rather than attempting catch-up.
        """
        logger.debug("Monitor thread started")
        next_tick = time.monotonic() + self.interval

        while not self._stop_event.is_set():
            tick_start = time.monotonic()
            try:
                self._tick()
            except Exception as exc:
                logger.error(f"Monitor tick error: {exc}")

            now = time.monotonic()

            # How long until the next scheduled tick?
            sleep_for = next_tick - now
            if sleep_for <= 0:
                # Tick was slow; skip to next aligned boundary
                skipped = int(-sleep_for / self.interval) + 1
                if skipped > 1:
                    logger.warning(
                        f"Monitor tick took {now - tick_start:.2f}s; "
                        f"skipping {skipped - 1} interval(s)"
                    )
                next_tick += skipped * self.interval
                sleep_for = next_tick - time.monotonic()

            if sleep_for > 0:
                self._stop_event.wait(timeout=sleep_for)

            next_tick += self.interval

        logger.debug("Monitor thread exiting")

    def _tick(self) -> None:
        snapshot = self.snapshot_now()
        with self._lock:
            self._latest = snapshot
        if self.log_metrics:
            self._log_snapshot(snapshot)
        if self.export_json:
            self._write_json(snapshot)

    def _log_snapshot(self, snapshot: Dict[str, Any]) -> None:
        parts = [f"ts={snapshot['timestamp']}"]
        lm = snapshot.get("limiter", {})
        if lm and "error" not in lm:
            parts.append(
                f"requests={lm.get('total_requests', 0)} "
                f"blocked={lm.get('blocked_requests', 0)} "
                f"block_rate={lm.get('block_rate', 0.0):.2f}%"
            )
        dd = snapshot.get("ddos", {})
        if dd and "error" not in dd:
            parts.append(
                f"ddos_blocked_ips={dd.get('blocked_ips', 0)} "
                f"detection_rate={dd.get('detection_rate', 0.0):.2f}%"
            )
        an = snapshot.get("analytics", {})
        if an and "error" not in an:
            parts.append(
                f"unique_clients={an.get('unique_identifiers', 0)} "
                f"violation_rate={an.get('violation_rate', 0.0):.2f}%"
            )
        logger.info("RateThrottle metrics | " + " | ".join(parts))

    def _write_json(self, snapshot: Dict[str, Any]) -> None:
        try:
            self.export_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.export_path.with_suffix(".tmp")
            with open(tmp, "w") as fh:
                json.dump(snapshot, fh, indent=2, default=str)
            tmp.replace(self.export_path)  # atomic replace
        except Exception as exc:
            logger.error(f"Monitor: failed to write {self.export_path}: {exc}")

    def __repr__(self) -> str:
        running = self._thread is not None and self._thread.is_alive()
        return f"RateThrottleMonitor(interval={self.interval}s, running={running})"
