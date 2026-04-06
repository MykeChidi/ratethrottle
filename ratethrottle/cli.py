"""
RateThrottle - Command Line Interface

CLI for rate limiting management and monitoring with
comprehensive error handling and user-friendly output.
"""

import argparse
import logging
import signal
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Union

if TYPE_CHECKING:
    from .storage_backend import InMemoryStorage, RedisStorage
# Handle both direct execution and package import
try:
    # Try package import first
    from .adaptive import AdaptiveRateLimiter
    from .alerting import AlertDispatcher
    from .analytics import RateThrottleAnalytics
    from .config import ConfigManager
    from .core import RateThrottleCore
    from .ddos import DDoSProtection
    from .exceptions import ConfigurationError
    from .monitoring import RateThrottleMonitor
    from .storage_backend import InMemoryStorage, RedisStorage  # noqa
except ImportError:
    # Direct execution - add parent directory to path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from ratethrottle.adaptive import AdaptiveRateLimiter
    from ratethrottle.alerting import AlertDispatcher
    from ratethrottle.analytics import RateThrottleAnalytics
    from ratethrottle.config import ConfigManager
    from ratethrottle.core import RateThrottleCore
    from ratethrottle.ddos import DDoSProtection
    from ratethrottle.exceptions import ConfigurationError
    from ratethrottle.monitoring import RateThrottleMonitor
    from ratethrottle.storage_backend import InMemoryStorage, RedisStorage  # noqa

logger = logging.getLogger(__name__)


# ============================================
# CLI Utilities
# ============================================


class Colors:
    """ANSI color codes for terminal output"""

    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    END = "\033[0m"


def print_success(message: str) -> None:
    """Print success message"""
    print(f"{Colors.GREEN}✓{Colors.END} {message}")


def print_error(message: str) -> None:
    """Print error message"""
    print(f"{Colors.RED}✗{Colors.END} {message}", file=sys.stderr)


def print_warning(message: str) -> None:
    """Print warning message"""
    print(f"{Colors.YELLOW}⚠{Colors.END} {message}")


def print_info(message: str) -> None:
    """Print info message"""
    print(f"{Colors.BLUE}ℹ{Colors.END} {message}")


def print_header(message: str) -> None:
    """Print section header"""
    print(f"\n{Colors.BOLD}{Colors.CYAN}{message}{Colors.END}")
    print(f"{Colors.CYAN}{'=' * len(message)}{Colors.END}")


# ============================================
# Dashboard
# ============================================


class RateThrottleDashboard:
    """
    Simple terminal dashboard for rate limiting monitoring

    Displays real-time statistics without requiring curses library.
    """

    def __init__(
        self,
        limiter: RateThrottleCore,
        ddos: Optional[DDoSProtection] = None,
        analytics: Optional[RateThrottleAnalytics] = None,
    ):
        """
        Initialize dashboard

        Args:
            limiter: Rate limiter core instance
            ddos: Optional DDoS protection instance
            analytics: Optional analytics instance
        """
        self.limiter = limiter
        self.ddos = ddos
        self.analytics = analytics
        self.running = False

    def start(self, interval: int = 2):
        """
        Start the dashboard

        Args:
            interval: Update interval in seconds
        """
        self.running = True

        print_info("Starting RateThrottle Dashboard...")
        print_info("Press Ctrl+C to exit")
        print()

        try:
            while self.running:
                self._display()
                time.sleep(interval)

        except KeyboardInterrupt:
            print("\n")
            print_info("Dashboard stopped")

    def stop(self):
        """Stop the dashboard"""
        self.running = False

    def _display(self):
        """Display dashboard content"""
        # Clear screen (simple approach)
        print("\033[2J\033[H", end="")

        # Title
        print_header("RATETHROTTLE MONITORING DASHBOARD")

        # Metrics
        print_header("Rate Limiting Metrics")
        metrics = self.limiter.get_metrics()

        print(f"  Total Requests:   {metrics['total_requests']:,}")
        print(f"  Allowed:          {metrics['allowed_requests']:,}")
        print(f"  Blocked:          {metrics['blocked_requests']:,}")
        print(f"  Block Rate:       {metrics['block_rate']:.2f}%")
        print(f"  Active Rules:     {metrics['active_rules']}")
        print(f"  Violations:       {metrics['total_violations']}")

        # Rules
        print_header("Active Rules")
        for name, rule in list(self.limiter.rules.items())[:5]:
            print(f"  {name:20} {rule.limit} req/{rule.window}s ({rule.strategy})")

        if len(self.limiter.rules) > 5:
            print(f"  ... and {len(self.limiter.rules) - 5} more")

        # DDoS Protection
        if self.ddos:
            print_header("DDoS Protection")
            ddos_stats = self.ddos.get_statistics()

            status = "ENABLED" if ddos_stats["enabled"] else "DISABLED"
            print(f"  Status:           {status}")
            print(f"  Blocked IPs:      {ddos_stats['blocked_ips']}")
            print(f"  Whitelisted IPs:  {ddos_stats['whitelisted_ips']}")
            print(f"  Detection Rate:   {ddos_stats.get('detection_rate', 0):.2f}%")

        # Analytics
        if self.analytics:
            print_header("Analytics Summary")
            summary = self.analytics.get_summary()

            print(f"  Unique Clients:   {summary['unique_identifiers']}")
            print(f"  Violation Rate:   {summary['violation_rate']:.2f}%")

        # Recent Violations
        if metrics["recent_violations"]:
            print_header("Recent Violations")
            for v in metrics["recent_violations"][-5:]:
                print(f"  {v.identifier:15} {v.rule_name:20} ({v.timestamp})")

        # Footer
        print()
        print(f"{Colors.CYAN}Last Updated: {time.strftime('%Y-%m-%d %H:%M:%S')}{Colors.END}")
        print(f"{Colors.CYAN}Press Ctrl+C to exit{Colors.END}")


# ============================================
# CLI Command Handlers
# ============================================


class RateThrottleCLI:
    """Command-line interface for RateThrottle"""

    def __init__(self):
        self.config: Optional[ConfigManager] = None
        self.limiter: Optional[RateThrottleCore] = None
        self.ddos: Optional[DDoSProtection] = None
        self.analytics: Optional[RateThrottleAnalytics] = None
        self.adaptive: Optional[AdaptiveRateLimiter] = None
        self.monitor: Optional[RateThrottleMonitor] = None
        self.alerter: Optional[AlertDispatcher] = None
        self._storage: Any = None  # shared storage reference for monitor and alerter

    def _load_config(self, config_file: str) -> None:
        """Load configuration and initialize components"""
        try:
            self.config = ConfigManager(config_file)

            # global log level
            global_cfg = self.config.get_global_config()
            log_level = getattr(logging, global_cfg.get("log_level", "INFO").upper(), logging.INFO)
            logging.getLogger("ratethrottle").setLevel(log_level)

            # storage
            storage_cfg = self.config.get_storage_config()
            storage_type = storage_cfg.get("type", "memory")

            if storage_type == "redis":
                redis_cfg = storage_cfg.get("redis", {})
                storage: Union["RedisStorage", "InMemoryStorage"]
                try:
                    import redis as _redis

                    client = _redis.Redis(
                        host=redis_cfg.get("host", "localhost"),
                        port=int(redis_cfg.get("port", 6379)),
                        db=int(redis_cfg.get("db", 0)),
                        password=redis_cfg.get("password"),
                        socket_timeout=int(redis_cfg.get("socket_timeout", 5)),
                        socket_connect_timeout=int(redis_cfg.get("socket_connect_timeout", 5)),
                        retry_on_timeout=bool(redis_cfg.get("retry_on_timeout", True)),
                        health_check_interval=int(redis_cfg.get("health_check_interval", 30)),
                        max_connections=int(redis_cfg.get("max_connections", 50)),
                    )
                    client.ping()
                    storage = RedisStorage(
                        client,
                        key_prefix=redis_cfg.get("key_prefix", "ratethrottle:"),
                    )
                    print_success("Connected to Redis storage")
                except Exception as exc:
                    print_warning(f"Redis failed ({exc}); falling back to memory")

                    storage = InMemoryStorage()
            else:
                storage = InMemoryStorage()

            self._storage = storage  # keep reference for alerter

            # limiter + rules
            self.limiter = RateThrottleCore(storage=storage)
            for rule in self.config.get_rules():
                try:
                    self.limiter.add_rule(rule)
                except Exception as exc:
                    print_warning(f"Skipping rule '{rule.name}': {exc}")

            # DDoS
            self.ddos = DDoSProtection(self.config.get_ddos_config())

            # analytics
            acfg = self.config.get_analytics_config()
            if acfg.get("enabled", True):
                self.analytics = RateThrottleAnalytics(
                    max_history=int(acfg.get("max_history", 10000)),
                    enable_metadata=bool(acfg.get("enable_metadata", True)),
                    sanitize_data=bool(acfg.get("sanitize_data", True)),
                )

            # adaptive
            adcfg = self.config.get_adaptive_config()
            if adcfg.get("enabled", False):
                self.adaptive = AdaptiveRateLimiter(
                    base_limit=int(adcfg.get("base_limit", 100)),
                    window=int(adcfg.get("window", 60)),
                    learning_rate=float(adcfg.get("learning_rate", 0.1)),
                    anomaly_threshold=float(adcfg.get("anomaly_threshold", 3.0)),
                    trust_enabled=bool(adcfg.get("trust_enabled", True)),
                    min_multiplier=float(adcfg.get("min_multiplier", 0.5)),
                    max_multiplier=float(adcfg.get("max_multiplier", 3.0)),
                    storage=storage,
                )
                persistence = adcfg.get("persistence", {})
                if persistence.get("enabled") and persistence.get("auto_load_on_start"):
                    model_path = persistence.get("filepath", "models/adaptive_model.pkl")
                    if Path(model_path).exists():
                        try:
                            self.adaptive.load_model(model_path)
                            print_success(f"Adaptive model loaded from {model_path}")
                        except Exception as exc:
                            print_warning(f"Could not load adaptive model: {exc}")

            # monitoring
            mcfg = self.config.get_monitoring_config()
            if mcfg.get("enabled", True):
                self.monitor = RateThrottleMonitor(
                    config=mcfg,
                    limiter=self.limiter,
                    ddos=self.ddos,
                    analytics=self.analytics,
                )

            # alerting — FIX: pass storage for distributed cooldown
            alcfg = self.config.get_alerting_config()
            if alcfg.get("enabled", False):
                self.alerter = AlertDispatcher(
                    config=alcfg,
                    storage=self._storage,  # ← distributed cooldown
                )

            # websocket
            wscfg = self.config.get_websocket_config()
            if wscfg.get("enabled", False):
                try:
                    from .websocket import WebSocketLimits, WebSocketRateLimiter

                    self.ws_limiter = WebSocketRateLimiter(
                        limits=WebSocketLimits(
                            connections_per_minute=int(wscfg.get("connections_per_minute", 60)),
                            messages_per_minute=int(wscfg.get("messages_per_minute", 1000)),
                            max_concurrent_connections=int(
                                wscfg.get("max_concurrent_connections", 10)
                            ),
                            max_message_size=int(wscfg.get("max_message_size", 65536)),
                            bytes_per_minute=wscfg.get("bytes_per_minute"),
                        ),
                        storage=storage,
                    )
                    print_success("WebSocket rate limiter configured")
                except ImportError:
                    print_warning("WebSocket dependencies not installed — skipping")

            # gRPC
            grpccfg = self.config.get_grpc_config()
            if grpccfg.get("enabled", False):
                try:
                    from .gRPC import GRPCLimits, GRPCRateLimitInterceptor

                    self.grpc_interceptor = GRPCRateLimitInterceptor(
                        limits=GRPCLimits(
                            requests_per_minute=int(grpccfg.get("requests_per_minute", 1000)),
                            concurrent_requests=int(grpccfg.get("concurrent_requests", 50)),
                            stream_messages_per_minute=int(
                                grpccfg.get("stream_messages_per_minute", 5000)
                            ),
                        ),
                        storage=storage,
                    )
                    print_success("gRPC interceptor configured")
                except ImportError:
                    print_warning("gRPC dependencies not installed — skipping")

            # GraphQL
            gqlcfg = self.config.get_graphql_config()
            if gqlcfg.get("enabled", False):
                try:
                    from .graphQL import GraphQLLimits, GraphQLRateLimiter

                    self.graphql_limiter = GraphQLRateLimiter(
                        limits=GraphQLLimits(
                            queries_per_minute=int(gqlcfg.get("queries_per_minute", 1000)),
                            mutations_per_minute=int(gqlcfg.get("mutations_per_minute", 100)),
                            subscriptions_per_minute=int(
                                gqlcfg.get("subscriptions_per_minute", 50)
                            ),
                            max_complexity=int(gqlcfg.get("max_complexity", 1000)),
                            max_depth=int(gqlcfg.get("max_depth", 15)),
                            field_limits=gqlcfg.get("field_limits") or None,
                        ),
                        storage=storage,
                        custom_field_costs=gqlcfg.get("field_costs") or None,
                    )
                    print_success("GraphQL rate limiter configured")
                except ImportError:
                    print_warning("GraphQL dependencies not installed — skipping")

            print_success(
                f"Config loaded: {len(self.limiter.rules)} rules, "
                f"storage={storage_type}, "
                f"ddos={'on' if self.ddos.enabled else 'off'}"
            )

        except FileNotFoundError:
            print_error(f"Config file not found: {config_file}")
            sys.exit(1)
        except ConfigurationError as exc:
            print_error(f"Configuration error: {exc}")
            sys.exit(1)
        except Exception as exc:
            print_error(f"Failed to load config: {exc}")
            logger.exception("_load_config unexpected error")
            sys.exit(1)

    def run_monitor(self, args) -> None:
        """Run monitoring dashboard"""
        print_header("RateThrottle Monitor")

        self._load_config(args.config)

        assert self.limiter is not None, "Limiter not initialized"  # nosec
        assert self.ddos is not None, "DDoS protection not initialized"  # nosec

        print_info(f"Rules: {len(self.limiter.rules)}")
        if self.ddos:
            print_info(f"DDoS: {'ENABLED' if self.ddos.enabled else 'DISABLED'}")
        if self.monitor:
            print_info(f"Background monitor interval: {self.monitor.interval}s")
        if self.alerter:
            print_info(f"Alerting: {self.alerter}")

        def _shutdown(*_):
            print()
            print_info("Shutting down…")
            _stop_all()
            sys.exit(0)

        def _stop_all():
            if self.monitor:
                self.monitor.stop()
            if self._save_thread and self._save_thread.is_alive():
                self._save_stop.set()
            _save_model_on_exit()

        def _save_model_on_exit():
            if self.config is None or self.adaptive is None:
                return
            adcfg = self.config.get_adaptive_config()
            persistence = adcfg.get("persistence", {})
            if persistence.get("enabled"):
                model_path = persistence.get("filepath", "models/adaptive_model.pkl")
                try:
                    Path(model_path).parent.mkdir(parents=True, exist_ok=True)
                    self.adaptive.export_model(model_path)
                    print_success(f"Adaptive model saved to {model_path}")
                except Exception as exc:
                    print_warning(f"Could not save adaptive model: {exc}")

        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)

        # Start background monitor
        if self.monitor:
            self.monitor.start()

        # Hook alerter into each monitor tick
        if self.monitor and self.alerter:
            monitor = self.monitor
            alerter = self.alerter
            _orig_tick = monitor._tick

            def _tick_with_alerts():
                _orig_tick()
                snap = monitor.latest_snapshot()
                if snap:
                    alerter.check_and_alert(snap)

            setattr(monitor, "_tick", _tick_with_alerts)

        # Periodic adaptive model save in a separate daemon thread
        self._save_stop = threading.Event()
        self._save_thread = None
        if self.adaptive and self.config:
            adcfg = self.config.get_adaptive_config()
            persistence = adcfg.get("persistence", {})
            save_interval = int(persistence.get("auto_save_interval", 0))
            model_path = persistence.get("filepath", "models/adaptive_model.pkl")
            adaptive = self.adaptive

            if persistence.get("enabled") and save_interval > 0:

                def _periodic_save():
                    while not self._save_stop.wait(timeout=save_interval):
                        try:
                            Path(model_path).parent.mkdir(parents=True, exist_ok=True)
                            adaptive.export_model(model_path)
                            logger.info(f"Adaptive model auto-saved to {model_path}")
                        except Exception as exc:
                            logger.warning(f"Adaptive model auto-save failed: {exc}")

                self._save_thread = threading.Thread(
                    target=_periodic_save,
                    name="ratethrottle-adaptive-save",
                    daemon=True,
                )
                self._save_thread.start()
                print_success(
                    f"Adaptive model periodic save: every {save_interval}s → {model_path}"
                )

        # Foreground dashboard
        dashboard = RateThrottleDashboard(self.limiter, self.ddos, self.analytics)
        try:
            dashboard.start(interval=getattr(args, "interval", 2))
        except KeyboardInterrupt:
            print()
            print_info("Monitor stopped")
        finally:
            _stop_all()

    def run_test(self, args):
        """Test rate limiting configuration"""
        print_header("RateThrottle Test")

        self._load_config(args.config)

        assert self.limiter is not None, "Limiter not initialized"  # nosec

        # Validate rule exists
        if args.rule not in self.limiter.rules:
            print_error(f"Rule '{args.rule}' not found")
            print_info(f"Available rules: {', '.join(self.limiter.rules.keys())}")
            sys.exit(1)

        print_info(f"Testing rule: {args.rule}")
        print_info(f"Identifier:   {args.identifier}")
        print_info(f"Requests:     {args.requests}")
        print()

        allowed_count = 0
        blocked_count = 0

        for i in range(args.requests):
            try:
                status = self.limiter.check_rate_limit(args.identifier, args.rule)

                if status.allowed:
                    allowed_count += 1
                    if i % 10 == 0:
                        print_success(
                            f"Request {i+1:4d}: ALLOWED " f"({status.remaining} remaining)"
                        )
                else:
                    blocked_count += 1
                    print_error(
                        f"Request {i+1:4d}: BLOCKED " f"(retry after {status.retry_after}s)"
                    )

                if args.delay:
                    time.sleep(args.delay)

            except Exception as e:
                print_error(f"Request {i+1}: ERROR - {e}")

        # Summary
        print_header("Test Results")
        print(f"  Total Requests:  {args.requests}")
        print(f"  Allowed:         {allowed_count}")
        print(f"  Blocked:         {blocked_count}")
        print(f"  Block Rate:      {(blocked_count/args.requests)*100:.2f}%")

    def run_config(self, args):
        """Manage configuration"""
        print_header("RateThrottle Configuration")

        try:
            self._load_config(args.config)

            assert self.config is not None, "Config not initialized"  # nosec

            if args.show:
                import yaml

                print()
                print(yaml.dump(self.config.to_dict(), default_flow_style=False))

            elif args.validate:
                print_success("Configuration is valid")
                for label, key in [
                    ("Rules", None),
                    ("Storage", "storage.type"),
                    ("DDoS", "ddos_protection.enabled"),
                    ("Adaptive", "adaptive.enabled"),
                    ("Monitoring", "monitoring.enabled"),
                    ("Alerting", "alerting.enabled"),
                    ("WebSocket", "websocket.enabled"),
                    ("gRPC", "grpc.enabled"),
                    ("GraphQL", "graphql.enabled"),
                ]:
                    if key is None:
                        print_info(f"  Rules:      {len(self.config.get_rules())}")
                    else:
                        val = self.config.get(key)
                        print_info(f"  {label+':':<12} {val}")

            elif args.export:
                output_path = Path(args.export)
                self.config.save_config(output_path)
                print_success(f"Configuration exported to {args.export}")

        except Exception as e:
            print_error(f"Configuration error: {e}")
            sys.exit(1)

    def run_manage(self, args):
        """Manage whitelist/blacklist"""
        print_header("RateThrottle List Management")

        self._load_config(args.config)

        assert self.limiter is not None, "Limiter not initialized"  # nosec

        if args.whitelist_add:
            self.limiter.add_to_whitelist(args.whitelist_add)
            print_success(f"Added to whitelist: {args.whitelist_add}")

        elif args.whitelist_remove:
            if self.limiter.remove_from_whitelist(args.whitelist_remove):
                print_success(f"Removed from whitelist: {args.whitelist_remove}")
            else:
                print_warning(f"Not in whitelist: {args.whitelist_remove}")

        elif args.blacklist_add:
            duration = args.duration if args.duration else None
            self.limiter.add_to_blacklist(args.blacklist_add, duration)

            if duration:
                print_success(f"Added to blacklist: {args.blacklist_add} " f"(for {duration}s)")
            else:
                print_success(f"Added to blacklist: {args.blacklist_add} (permanent)")

        elif args.blacklist_remove:
            if self.limiter.remove_from_blacklist(args.blacklist_remove):
                print_success(f"Removed from blacklist: {args.blacklist_remove}")
            else:
                print_warning(f"Not in blacklist: {args.blacklist_remove}")

        elif args.list_all:
            print_info(f"Whitelisted IPs: {len(self.limiter.whitelist)}")
            for ip in sorted(self.limiter.whitelist):
                print(f"  {ip}")

            print()
            print_info(f"Blacklisted IPs: {len(self.limiter.blacklist)}")
            for ip in sorted(self.limiter.blacklist):
                print(f"  {ip}")

    def run_stats(self, args):
        """Show statistics"""
        print_header("RateThrottle Statistics")

        self._load_config(args.config)

        assert self.analytics is not None, "Analytics not initialized"  # nosec

        if args.export:
            try:
                self.analytics.export_report(args.export, include_raw_data=args.raw_data)
                print_success(f"Statistics exported to {args.export}")
            except Exception as e:
                print_error(f"Failed to export statistics: {e}")
                sys.exit(1)

        else:
            # Show summary
            summary = self.analytics.get_summary()

            print_info("Summary")
            print(f"  Total Requests:    {summary['total_requests']:,}")
            print(f"  Total Violations:  {summary['total_violations']:,}")
            print(f"  Unique Clients:    {summary['unique_identifiers']:,}")
            print(f"  Violation Rate:    {summary['violation_rate']:.2f}%")

            # Top violators
            print()
            print_info("Top Violators")
            top = self.analytics.get_top_violators(10)

            if top:
                for i, violator in enumerate(top, 1):
                    print(
                        f"  {i:2d}. {violator['identifier']:20} "
                        f"{violator['violations']:5d} violations"
                    )
            else:
                print("  No violations recorded")

            # Rule statistics
            print()
            print_info("Rule Statistics")
            rule_stats = self.analytics.get_rule_statistics()

            if rule_stats:
                for rule, stats in rule_stats.items():
                    print(f"  {rule:20} {stats['violation_rate']:6.2f}% block rate")
            else:
                print("  No statistics available")


# ============================================
# Main Entry Point
# ============================================


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        prog="ratethrottle",
        description="RateThrottle - Advanced Rate Limiting & DDoS Protection",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start monitoring dashboard
  ratethrottle monitor --config ratethrottle.yaml

  # Test rate limiting
  ratethrottle test --rule api_default --identifier 192.168.1.100 --requests 150

  # Manage lists
  ratethrottle manage --blacklist-add 192.168.1.50 --duration 3600
  ratethrottle manage --whitelist-add 10.0.0.5
  ratethrottle manage --list-all

  # View configuration
  ratethrottle config --show
  ratethrottle config --validate

  # Export statistics
  ratethrottle stats --export report.json
  ratethrottle stats --export full_report.json --raw-data

For more information, visit: https://github.com/MykeChidi/ratethrottle
        """,
    )

    parser.add_argument(
        "--config",
        default="ratethrottle.yaml",
        help="Configuration file path (default: ratethrottle.yaml)",
    )

    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Monitor command
    monitor_parser = subparsers.add_parser("monitor", help="Start monitoring dashboard")
    monitor_parser.add_argument(
        "--interval", type=int, default=2, help="Update interval in seconds (default: 2)"
    )

    # Test command
    test_parser = subparsers.add_parser("test", help="Test rate limiting configuration")
    test_parser.add_argument("--rule", required=True, help="Rule name to test")
    test_parser.add_argument(
        "--identifier", default="test_client", help="Client identifier (default: test_client)"
    )
    test_parser.add_argument(
        "--requests", type=int, default=100, help="Number of requests to send (default: 100)"
    )
    test_parser.add_argument("--delay", type=float, help="Delay between requests in seconds")

    # Config command
    config_parser = subparsers.add_parser("config", help="Manage configuration")
    config_group = config_parser.add_mutually_exclusive_group(required=True)
    config_group.add_argument("--show", action="store_true", help="Show current configuration")
    config_group.add_argument("--validate", action="store_true", help="Validate configuration")
    config_group.add_argument("--export", metavar="FILE", help="Export configuration to file")

    # Manage command
    manage_parser = subparsers.add_parser("manage", help="Manage whitelist and blacklist")
    manage_group = manage_parser.add_mutually_exclusive_group(required=True)
    manage_group.add_argument(
        "--whitelist-add", metavar="IDENTIFIER", help="Add identifier to whitelist"
    )
    manage_group.add_argument(
        "--whitelist-remove", metavar="IDENTIFIER", help="Remove identifier from whitelist"
    )
    manage_group.add_argument(
        "--blacklist-add", metavar="IDENTIFIER", help="Add identifier to blacklist"
    )
    manage_group.add_argument(
        "--blacklist-remove", metavar="IDENTIFIER", help="Remove identifier from blacklist"
    )
    manage_group.add_argument(
        "--list-all", action="store_true", help="List all whitelisted and blacklisted identifiers"
    )
    manage_parser.add_argument(
        "--duration", type=int, help="Block duration in seconds (for blacklist-add)"
    )

    # Stats command
    stats_parser = subparsers.add_parser("stats", help="View and export statistics")
    stats_parser.add_argument("--export", metavar="FILE", help="Export statistics to file")
    stats_parser.add_argument("--raw-data", action="store_true", help="Include raw data in export")

    # Parse arguments
    args = parser.parse_args()

    # Setup logging
    if args.verbose:
        logging.basicConfig(
            level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
    else:
        logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    # Check if command was provided
    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Create CLI instance and run command
    cli = RateThrottleCLI()

    try:
        if args.command == "monitor":
            cli.run_monitor(args)
        elif args.command == "test":
            cli.run_test(args)
        elif args.command == "config":
            cli.run_config(args)
        elif args.command == "manage":
            cli.run_manage(args)
        elif args.command == "stats":
            cli.run_stats(args)

    except KeyboardInterrupt:
        print("\n")
        print_info("Interrupted by user")
        sys.exit(0)
    except Exception as e:
        print_error(f"Error: {e}")
        if args.verbose:
            import traceback

            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    sys.exit(main())
