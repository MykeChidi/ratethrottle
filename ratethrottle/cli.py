"""
RateThrottle - Command Line Interface

CLI for rate limiting management and monitoring with
comprehensive error handling and user-friendly output.
"""

import argparse
import logging
import signal
import sys
import time
from pathlib import Path
from typing import Optional

# Handle both direct execution and package import
try:
    # Try package import first
    from .analytics import RateThrottleAnalytics
    from .config import ConfigManager
    from .core import RateThrottleCore
    from .ddos import DDoSProtection
    from .exceptions import ConfigurationError
except ImportError:
    # Direct execution - add parent directory to path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from ratethrottle.analytics import RateThrottleAnalytics
    from ratethrottle.config import ConfigManager
    from ratethrottle.core import RateThrottleCore
    from ratethrottle.ddos import DDoSProtection
    from ratethrottle.exceptions import ConfigurationError

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

    def _load_config(self, config_file: str):
        """Load configuration"""
        try:
            self.config = ConfigManager(config_file)
            self.limiter = RateThrottleCore()

            # Add rules from config
            for rule in self.config.get_rules():
                self.limiter.add_rule(rule)

            # Setup DDoS protection
            ddos_config = self.config.get_ddos_config()
            self.ddos = DDoSProtection(ddos_config)

            # Setup analytics
            self.analytics = RateThrottleAnalytics()

            print_success(f"Loaded {len(self.limiter.rules)} rules from {config_file}")

        except FileNotFoundError:
            print_error(f"Configuration file not found: {config_file}")
            sys.exit(1)
        except ConfigurationError as e:
            print_error(f"Configuration error: {e}")
            sys.exit(1)
        except Exception as e:
            print_error(f"Failed to load configuration: {e}")
            sys.exit(1)

    def run_monitor(self, args):
        """Run monitoring dashboard"""
        print_header("RateThrottle Monitor")

        self._load_config(args.config)

        assert self.limiter is not None, "Limiter not initialized"  # nosec
        assert self.ddos is not None, "DDoS protection not initialized"  # nosec

        print_info(f"Rules loaded: {len(self.limiter.rules)}")
        print_info(f"DDoS Protection: {'ENABLED' if self.ddos.enabled else 'DISABLED'}")

        # Setup signal handler
        def signal_handler(sig, frame):
            print("\n")
            print_info("Shutting down...")
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)

        # Start dashboard
        assert self.limiter is not None, "Limiter not initialized"  # nosec
        dashboard = RateThrottleDashboard(self.limiter, self.ddos, self.analytics)

        try:
            dashboard.start(interval=args.interval if hasattr(args, "interval") else 2)
        except KeyboardInterrupt:
            print("\n")
            print_info("Monitor stopped")

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
        print_info(f"Identifier: {args.identifier}")
        print_info(f"Requests: {args.requests}")
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
                print_info(f"  Rules: {len(self.config.get_rules())}")
                print_info(f"  Storage: {self.config.get('storage.type')}")
                print_info(
                    f"  DDoS: {'ENABLED' if self.config.get('ddos_protection.enabled') else 'DISABLED'}"  # noqa
                )

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
    main()
