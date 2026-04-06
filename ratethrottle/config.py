"""
RateThrottle - Configuration Management

Three configuration sources, evaluated in this order (later wins):

  1. DEFAULT_CONFIG  — hardcoded safe defaults, always present.
  2. YAML file       — operator-supplied overrides via ConfigManager(path).
  3. Environment     — production secrets and per-environment toggles,
                       applied on top of whatever the file says.
  4. Redis           — live / hot-reload config for distributed deployments,
                       loaded via ConfigManager.load_from_redis(client).

Sensitive channel credentials (Slack URL, email password, PagerDuty key)
are intentionally only read from the environment, never from the YAML file,
so secrets cannot be committed to version control by accident.
"""

import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, cast

import yaml

from .core import RateThrottleRule
from .exceptions import ConfigurationError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# RuleConfig dataclass  (unchanged from original)
# ---------------------------------------------------------------------------


@dataclass
class RuleConfig:
    """
    Configuration for a single rule with validation.

    Attributes:
        name:           Rule identifier
        limit:          Maximum requests allowed
        window:         Time window in seconds
        scope:          ip | user | endpoint | global
        strategy:       token_bucket | leaky_bucket | fixed_window |
                        sliding_window | sliding_counter
        block_duration: Seconds to block after limit exceeded
        burst:          Burst allowance (token_bucket only; must be >= limit)
        paths:          Optional list of URL paths this rule applies to
        methods:        Optional list of HTTP methods this rule applies to
    """

    name: str
    limit: int
    window: int
    scope: str = "ip"
    strategy: str = "sliding_counter"
    block_duration: int = 300
    burst: Optional[int] = None
    paths: Optional[List[str]] = None
    methods: Optional[List[str]] = None

    _VALID_SCOPES = frozenset({"ip", "user", "endpoint", "global"})
    _VALID_STRATEGIES = frozenset(
        {
            "token_bucket",
            "leaky_bucket",
            "fixed_window",
            "sliding_window",
            "sliding_counter",
        }
    )
    _VALID_METHODS = frozenset(
        {
            "GET",
            "POST",
            "PUT",
            "DELETE",
            "PATCH",
            "HEAD",
            "OPTIONS",
        }
    )

    def __post_init__(self) -> None:
        if not self.name:
            raise ConfigurationError("Rule name cannot be empty")
        if self.limit <= 0:
            raise ConfigurationError(
                f"Rule '{self.name}': limit must be positive, got {self.limit}"
            )
        if self.window <= 0:
            raise ConfigurationError(
                f"Rule '{self.name}': window must be positive, got {self.window}"
            )
        if self.block_duration < 0:
            raise ConfigurationError(f"Rule '{self.name}': block_duration cannot be negative")
        if self.scope not in self._VALID_SCOPES:
            raise ConfigurationError(
                f"Rule '{self.name}': invalid scope '{self.scope}'. "
                f"Valid: {', '.join(sorted(self._VALID_SCOPES))}"
            )
        if self.strategy not in self._VALID_STRATEGIES:
            raise ConfigurationError(
                f"Rule '{self.name}': invalid strategy '{self.strategy}'. "
                f"Valid: {', '.join(sorted(self._VALID_STRATEGIES))}"
            )
        if self.burst is not None and self.burst < self.limit:
            raise ConfigurationError(
                f"Rule '{self.name}': burst ({self.burst}) cannot be less than "
                f"limit ({self.limit})"
            )
        if self.methods:
            bad = [m for m in self.methods if m.upper() not in self._VALID_METHODS]
            if bad:
                raise ConfigurationError(
                    f"Rule '{self.name}': invalid HTTP methods: {', '.join(bad)}"
                )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Helper used by ConfigManager._ENV_MAP — must be defined before the class.
# ---------------------------------------------------------------------------


def _bool(value: str) -> bool:
    """Coerce a string environment variable to bool."""
    if value.lower() in {"1", "true", "yes", "on"}:
        return True
    if value.lower() in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Cannot interpret {value!r} as a boolean")


# ---------------------------------------------------------------------------
# ConfigManager
# ---------------------------------------------------------------------------


class ConfigManager:
    """
    Manages RateThrottle configuration with validation, defaults, environment
    variable overrides, and optional Redis-backed live config.

    Load order (later sources override earlier ones):
        1. DEFAULT_CONFIG
        2. YAML file  (if path provided)
        3. Environment variables  (always applied)
        4. Redis      (if load_from_redis() is called)

    Examples:
        >>> # File + env overrides (typical production)
        >>> config = ConfigManager('ratethrottle.yaml')
        >>> rules = config.get_rules()

        >>> # Programmatic only (embedded use)
        >>> config = ConfigManager()
        >>> config.set('global.log_level', 'DEBUG')

        >>> # Distributed — hot-reload from Redis
        >>> import redis
        >>> config = ConfigManager('ratethrottle.yaml')
        >>> config.load_from_redis(redis.Redis(...))
    """

    # ------------------------------------------------------------------
    # DEFAULT_CONFIG — every key the code reads must be present here.
    # Values are safe for a local dev environment; production overrides
    # come from the YAML file and/or environment variables.
    # ------------------------------------------------------------------

    DEFAULT_CONFIG: Dict[str, Any] = {
        # ----------------------------------------------------------------
        # STORAGE
        # ----------------------------------------------------------------
        "storage": {
            "type": "memory",  # "memory" | "redis"
            "redis": {
                "host": "localhost",
                "port": 6379,
                "db": 0,
                "password": None,  # nosec B105
                "key_prefix": "ratethrottle:",
                "max_connections": 50,
                "socket_timeout": 5,
                "socket_connect_timeout": 5,
                "retry_on_timeout": True,
                "health_check_interval": 30,
            },
        },
        # ----------------------------------------------------------------
        # GLOBAL
        # ----------------------------------------------------------------
        "global": {
            "enabled": True,
            "default_strategy": "sliding_counter",
            "headers_enabled": True,
            "log_violations": True,
            "log_level": "INFO",
        },
        # ----------------------------------------------------------------
        # RULES
        # A minimal catch-all rule.  Production deployments should replace
        # this with explicit per-endpoint rules in the YAML.
        # ----------------------------------------------------------------
        "rules": [
            {
                "name": "default",
                "limit": 1000,
                "window": 3600,
                "strategy": "sliding_counter",
                "scope": "ip",
                "block_duration": 300,
            }
        ],
        # ----------------------------------------------------------------
        # DDOS PROTECTION
        # Keys are flat — DDoSProtection does config.update(user_dict).
        # ----------------------------------------------------------------
        "ddos_protection": {
            "enabled": True,
            "threshold": 10000,  # max req/window before flagging
            "window": 60,
            "auto_block": True,
            "block_duration": 3600,
            "suspicious_threshold": 0.5,  # 0.0–1.0
            "max_unique_endpoints": 50,
            "burst_threshold": 100,
            "burst_window": 10,
            "min_interval_threshold": 0.1,  # avg req interval (s); below = bot
            "whitelist_on_good_behavior": True,
            "good_behavior_threshold": 1000,
            "max_tracked_identifiers": 100_000,  # LRU cap (fix #1)
        },
        # ----------------------------------------------------------------
        # ADAPTIVE RATE LIMITER
        # ----------------------------------------------------------------
        "adaptive": {
            "enabled": False,
            "base_limit": 100,
            "window": 60,
            "learning_rate": 0.1,  # EMA alpha, range (0, 1]
            "anomaly_threshold": 3.0,  # z-score threshold
            "trust_enabled": True,
            "min_multiplier": 0.5,
            "max_multiplier": 3.0,
            "persistence": {
                "enabled": False,
                "filepath": "models/adaptive_model.json",
                "auto_save_interval": 3600,  # seconds; 0 = disabled
                "auto_load_on_start": True,
            },
        },
        # ----------------------------------------------------------------
        # WEBSOCKET
        # Keys map 1:1 to WebSocketLimits dataclass fields.
        # ----------------------------------------------------------------
        "websocket": {
            "enabled": False,
            "connections_per_minute": 60,
            "messages_per_minute": 1000,
            "max_concurrent_connections": 10,
            "max_message_size": 65536,  # bytes (64 KB)
            "bytes_per_minute": None,
        },
        # ----------------------------------------------------------------
        # GRPC
        # Keys map 1:1 to GRPCLimits dataclass fields.
        # ----------------------------------------------------------------
        "grpc": {
            "enabled": False,
            "requests_per_minute": 1000,
            "concurrent_requests": 50,
            "stream_messages_per_minute": 5000,
        },
        # ----------------------------------------------------------------
        # GRAPHQL
        # Primary keys → GraphQLLimits; field_costs → ComplexityAnalyzer.
        # ----------------------------------------------------------------
        "graphql": {
            "enabled": False,
            "queries_per_minute": 1000,
            "mutations_per_minute": 100,
            "subscriptions_per_minute": 50,
            "max_complexity": 1000,
            "max_depth": 15,
            "field_limits": {},  # {field_name: req/min}
            "field_costs": {},  # {field_name: complexity_int}
        },
        # ----------------------------------------------------------------
        # ANALYTICS
        # ----------------------------------------------------------------
        "analytics": {
            "enabled": True,
            "max_history": 10000,
            "enable_metadata": True,
            "sanitize_data": True,
        },
        # ----------------------------------------------------------------
        # MONITORING  (RateThrottleMonitor)
        # ----------------------------------------------------------------
        "monitoring": {
            "enabled": True,
            "interval": 60,  # seconds between snapshots
            "log_metrics": True,
            "export_json": False,
            "export_path": "metrics/metrics.json",
        },
        # ----------------------------------------------------------------
        # ALERTING  (AlertDispatcher)
        # Credentials are intentionally absent here — they must come from
        # environment variables (RT_SLACK_WEBHOOK_URL, etc.) so they are
        # never committed to the YAML file.
        # ----------------------------------------------------------------
        "alerting": {
            "enabled": False,
            "cooldown_seconds": 300,
            "thresholds": {
                "block_rate_warning": 5.0,
                "block_rate_critical": 20.0,
                "violations_per_minute_warning": 50,
                "violations_per_minute_critical": 200,
                "ddos_score_warning": 0.5,
                "ddos_score_critical": 0.8,
            },
            "slack": {
                "enabled": False,
                "webhook_url": "",  # set via RT_SLACK_WEBHOOK_URL
                "channel": "#alerts",
                "username": "RateThrottle",
            },
            "webhook": {
                "enabled": False,
                "url": "",  # set via RT_WEBHOOK_URL
                "headers": {},
                "timeout": 10,
            },
            "email": {
                "enabled": False,
                "smtp_host": "localhost",
                "smtp_port": 587,
                "use_tls": True,
                "username": "",
                "password": "",  # nosec B105 — use RT_EMAIL_PASSWORD
                "from_address": "",
                "to_addresses": [],
            },
            "pagerduty": {
                "enabled": False,
                "routing_key": "",  # set via RT_PAGERDUTY_KEY
            },
        },
    }

    # ------------------------------------------------------------------
    # Environment variable map:
    #   env_var_name → (dot.notation.config.key, type_coercer)
    # Applied after YAML merge so env always wins.
    # ------------------------------------------------------------------
    _ENV_MAP: Dict[str, tuple] = {
        # Storage
        "RT_STORAGE_TYPE": ("storage.type", str),
        "RT_REDIS_HOST": ("storage.redis.host", str),
        "RT_REDIS_PORT": ("storage.redis.port", int),
        "RT_REDIS_DB": ("storage.redis.db", int),
        "RT_REDIS_PASSWORD": ("storage.redis.password", str),
        "RT_REDIS_KEY_PREFIX": ("storage.redis.key_prefix", str),
        # Global
        "RT_ENABLED": ("global.enabled", _bool),
        "RT_LOG_LEVEL": ("global.log_level", str),
        "RT_HEADERS_ENABLED": ("global.headers_enabled", _bool),
        # DDoS
        "RT_DDOS_ENABLED": ("ddos_protection.enabled", _bool),
        "RT_DDOS_THRESHOLD": ("ddos_protection.threshold", int),
        "RT_DDOS_BLOCK_DURATION": ("ddos_protection.block_duration", int),
        # Adaptive
        "RT_ADAPTIVE_ENABLED": ("adaptive.enabled", _bool),
        # Monitoring
        "RT_MONITORING_ENABLED": ("monitoring.enabled", _bool),
        "RT_MONITORING_INTERVAL": ("monitoring.interval", int),
        # Alerting
        "RT_ALERTING_ENABLED": ("alerting.enabled", _bool),
        # Alerting secrets — written to the config dict so AlertDispatcher
        # can read them; the _apply_env method handles these explicitly
        # because they live in nested channel sub-dicts.
        "RT_SLACK_WEBHOOK_URL": ("alerting.slack.webhook_url", str),
        "RT_WEBHOOK_URL": ("alerting.webhook.url", str),
        "RT_EMAIL_PASSWORD": ("alerting.email.password", str),
        "RT_PAGERDUTY_KEY": ("alerting.pagerduty.routing_key", str),
    }

    # ------------------------------------------------------------------
    # Constructor
    # ------------------------------------------------------------------

    def __init__(self, config_file: Optional[Union[str, Path]] = None):
        """
        Initialise ConfigManager.

        Args:
            config_file: Path to a YAML file (optional).  If omitted,
                         only DEFAULT_CONFIG and environment variables
                         are used.

        Raises:
            ConfigurationError: If the file cannot be parsed or the
                                resulting config fails validation.
        """
        self.config_file = Path(config_file) if config_file else None
        self.config: Dict[str, Any] = self._deep_copy(self.DEFAULT_CONFIG)

        if self.config_file:
            if not self.config_file.exists():
                self.save_config(self.config_file)
                logger.info(
                    f"Configuration file not found; wrote default config to {self.config_file}"
                )
            else:
                self._load_yaml()
        else:
            logger.info("No config file — using defaults + environment variables")

        self._apply_env()
        self.validate()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load_yaml(self) -> None:
        """Parse YAML file and deep-merge into self.config."""
        assert self.config_file is not None  # nosec
        try:
            with open(self.config_file, "r", encoding="utf-8-sig") as fh:
                user_config = yaml.safe_load(fh)

            if user_config is None:
                logger.warning(f"Empty config file: {self.config_file}")
                return

            if not isinstance(user_config, dict):
                raise ConfigurationError(
                    f"Config file must be a dictionary, " f"got {type(user_config).__name__}"
                )

            self._merge_config(self.config, user_config)
            logger.info(f"Configuration loaded from {self.config_file}")

        except UnicodeDecodeError as exc:
            raise ConfigurationError(
                f"Failed to read config file {self.config_file}: {exc}"
            ) from exc
        except yaml.YAMLError as exc:
            raise ConfigurationError(f"Failed to parse YAML: {self.config_file}: {exc}") from exc

    def load_config(self) -> None:
        """
        Reload configuration from the YAML file and re-apply env overrides.

        Can be called at runtime to pick up file changes (manual hot-reload).
        Raises ConfigurationError if no file was specified.
        """
        if not self.config_file:
            raise ConfigurationError("No configuration file specified")
        self.config = self._deep_copy(self.DEFAULT_CONFIG)
        self._load_yaml()
        self._apply_env()
        self.validate()
        logger.info("Configuration reloaded")

    def load_from_redis(self, redis_client, key: str = "ratethrottle:config") -> None:
        """
        Load (and merge) configuration stored as a JSON/YAML string in Redis.

        This is the distributed hot-reload path.  Operators update the Redis
        key (e.g. via a dashboard or deployment script); every worker calls
        this method on a schedule to pick up changes without restarting.

        The Redis value is expected to be a YAML or JSON document.  It is
        deep-merged on top of the current config (file + defaults), so only
        the keys that need to differ from the file need to be present.

        Args:
            redis_client: A connected redis.Redis instance.
            key:          Redis key holding the config document.

        Raises:
            ConfigurationError: If the key is missing, the document cannot
                                be parsed, or validation fails.

        Example:
            >>> import redis, json
            >>> r = redis.Redis()
            >>> r.set('ratethrottle:config', json.dumps({
            ...     'ddos_protection': {'threshold': 50000},
            ...     'alerting': {'enabled': True},
            ... }))
            >>> config.load_from_redis(r)
        """
        try:
            raw = redis_client.get(key)
        except Exception as exc:
            raise ConfigurationError(
                f"Failed to read config from Redis key '{key}': {exc}"
            ) from exc

        if raw is None:
            raise ConfigurationError(f"Config key '{key}' not found in Redis")

        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            # yaml.safe_load handles both YAML and JSON
            remote_config = yaml.safe_load(raw)
        except Exception as exc:
            raise ConfigurationError(f"Failed to parse Redis config document: {exc}") from exc

        if not isinstance(remote_config, dict):
            raise ConfigurationError(
                f"Redis config must be a mapping, got {type(remote_config).__name__}"
            )

        self._merge_config(self.config, remote_config)
        # Re-apply env so secrets always win even after a Redis reload
        self._apply_env()
        self.validate()
        logger.info(f"Configuration merged from Redis key '{key}'")

    def _apply_env(self) -> None:
        """
        Apply environment variable overrides to self.config.

        Only variables that are actually set in the environment are applied;
        unset variables leave the corresponding config key unchanged.
        """
        for env_var, (config_key, coerce) in self._ENV_MAP.items():
            raw = os.environ.get(env_var)
            if raw is None:
                continue
            try:
                value = coerce(raw)
            except (ValueError, TypeError) as exc:
                logger.warning(
                    f"Ignoring {env_var}={raw!r}: cannot coerce to " f"{coerce.__name__}: {exc}"
                )
                continue
            self._set_by_path(config_key, value)
            logger.debug(f"Config override from env: {config_key} = {value!r}")

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> None:
        """
        Validate the current configuration in full.

        Raises:
            ConfigurationError: On the first validation failure found.
        """
        self._validate_storage()
        self._validate_global()
        self._validate_rules()
        self._validate_ddos()
        self._validate_adaptive()
        self._validate_monitoring()
        self._validate_alerting()
        logger.debug("Configuration validation passed")

    def _validate_storage(self) -> None:
        storage_type = self.config.get("storage", {}).get("type")
        if storage_type not in {"memory", "redis"}:
            raise ConfigurationError(
                f"Invalid storage type: {storage_type!r}. "
                f"storage.type must be 'memory' or 'redis'"
            )
        if storage_type == "redis":
            redis_cfg = self.config["storage"].get("redis", {})
            port = redis_cfg.get("port", 6379)
            if not (1 <= int(port) <= 65535):
                raise ConfigurationError(f"storage.redis.port must be 1–65535, got {port}")

    def _validate_global(self) -> None:
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        level = self.config.get("global", {}).get("log_level", "INFO").upper()
        if level not in valid_levels:
            raise ConfigurationError(
                f"global.log_level must be one of {sorted(valid_levels)}, got {level!r}"
            )
        valid_strategies = {
            "token_bucket",
            "leaky_bucket",
            "fixed_window",
            "sliding_window",
            "sliding_counter",
        }
        strategy = self.config.get("global", {}).get("default_strategy", "sliding_counter")
        if strategy not in valid_strategies:
            raise ConfigurationError(
                f"global.default_strategy '{strategy}' is not valid. "
                f"Valid: {', '.join(sorted(valid_strategies))}"
            )

    def _validate_rules(self) -> None:
        rules = self.config.get("rules", [])
        if not isinstance(rules, list):
            raise ConfigurationError("'rules' must be a list")
        if not rules:
            logger.warning("No rules defined in configuration")
        names: set = set()
        for i, rule_data in enumerate(rules):
            if not isinstance(rule_data, dict):
                raise ConfigurationError(f"Rule #{i + 1} must be a mapping")
            try:
                RuleConfig(**rule_data)
            except TypeError as exc:
                raise ConfigurationError(f"Rule #{i + 1} invalid: {exc}") from exc
            name = rule_data.get("name", "")
            if name in names:
                raise ConfigurationError(f"Duplicate rule name: '{name}'")
            names.add(name)

    def _validate_ddos(self) -> None:
        ddos = self.config.get("ddos_protection", {})
        if not ddos.get("enabled", True):
            return
        threshold = ddos.get("threshold", 0)
        if int(threshold) <= 0:
            raise ConfigurationError(f"DDoS threshold must be positive, got {threshold}")
        suspicious = float(ddos.get("suspicious_threshold", 0.5))
        if not 0.0 <= suspicious <= 1.0:
            raise ConfigurationError(
                f"ddos_protection.suspicious_threshold must be 0.0–1.0, " f"got {suspicious}"
            )
        cap = int(ddos.get("max_tracked_identifiers", 100_000))
        if cap < 100:
            raise ConfigurationError("ddos_protection.max_tracked_identifiers must be at least 100")

    def _validate_adaptive(self) -> None:
        adp = self.config.get("adaptive", {})
        if not adp.get("enabled", False):
            return
        lr = float(adp.get("learning_rate", 0.1))
        if not 0.0 < lr <= 1.0:
            raise ConfigurationError(f"adaptive.learning_rate must be in (0, 1], got {lr}")
        mn = float(adp.get("min_multiplier", 0.5))
        mx = float(adp.get("max_multiplier", 3.0))
        if mn > mx:
            raise ConfigurationError(
                f"adaptive.min_multiplier ({mn}) must be <= max_multiplier ({mx})"
            )
        if mn <= 0:
            raise ConfigurationError(f"adaptive.min_multiplier must be positive, got {mn}")

    def _validate_monitoring(self) -> None:
        mon = self.config.get("monitoring", {})
        if not mon.get("enabled", True):
            return
        interval = int(mon.get("interval", 60))
        if interval <= 0:
            raise ConfigurationError(f"monitoring.interval must be positive, got {interval}")

    def _validate_alerting(self) -> None:
        alrt = self.config.get("alerting", {})
        if not alrt.get("enabled", False):
            return
        cooldown = int(alrt.get("cooldown_seconds", 300))
        if cooldown < 0:
            raise ConfigurationError(
                f"alerting.cooldown_seconds cannot be negative, got {cooldown}"
            )
        thresholds = alrt.get("thresholds", {})
        for warn_key, crit_key in [
            ("block_rate_warning", "block_rate_critical"),
            ("violations_per_minute_warning", "violations_per_minute_critical"),
            ("ddos_score_warning", "ddos_score_critical"),
        ]:
            warn = float(thresholds.get(warn_key, 0))
            crit = float(thresholds.get(crit_key, 0))
            if warn > crit:
                raise ConfigurationError(
                    f"alerting.thresholds.{warn_key} ({warn}) must be <= " f"{crit_key} ({crit})"
                )

    # ------------------------------------------------------------------
    # Typed section getters
    # (each returns a plain dict; components own their own parsing)
    # ------------------------------------------------------------------

    def get_storage_config(self) -> Dict[str, Any]:
        """Return the storage section."""
        return dict(self.config.get("storage", {}))

    def get_global_config(self) -> Dict[str, Any]:
        """Return the global section."""
        return dict(self.config.get("global", {}))

    def get_ddos_config(self) -> Dict[str, Any]:
        """Return the ddos_protection section (flat, as DDoSProtection expects)."""
        return dict(self.config.get("ddos_protection", {}))

    def get_adaptive_config(self) -> Dict[str, Any]:
        """Return the adaptive section."""
        return dict(self.config.get("adaptive", {}))

    def get_websocket_config(self) -> Dict[str, Any]:
        """Return the websocket section."""
        return dict(self.config.get("websocket", {}))

    def get_grpc_config(self) -> Dict[str, Any]:
        """Return the grpc section."""
        return dict(self.config.get("grpc", {}))

    def get_graphql_config(self) -> Dict[str, Any]:
        """Return the graphql section."""
        return dict(self.config.get("graphql", {}))

    def get_analytics_config(self) -> Dict[str, Any]:
        """Return the analytics section."""
        return dict(self.config.get("analytics", {}))

    def get_monitoring_config(self) -> Dict[str, Any]:
        """Return the monitoring section."""
        return dict(self.config.get("monitoring", {}))

    def get_alerting_config(self) -> Dict[str, Any]:
        """Return the alerting section."""
        return dict(self.config.get("alerting", {}))

    def get_rules(self) -> List[RateThrottleRule]:
        """
        Return all configured rules as RateThrottleRule instances.

        Raises:
            ConfigurationError: If any rule fails validation.
        """
        rules: List[RateThrottleRule] = []
        for rule_data in self.config.get("rules", []):
            try:
                rc = RuleConfig(**rule_data)
                rules.append(
                    RateThrottleRule(
                        name=rc.name,
                        limit=rc.limit,
                        window=rc.window,
                        scope=rc.scope,
                        strategy=rc.strategy,
                        block_duration=rc.block_duration,
                        burst=rc.burst,
                    )
                )
            except Exception as exc:
                raise ConfigurationError(
                    f"Failed to create rule " f"'{rule_data.get('name', 'unknown')}': {exc}"
                ) from exc
        return rules

    # ------------------------------------------------------------------
    # Generic get / set (dot-notation)
    # ------------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a config value by dot-notation path.

        Examples:
            >>> config.get('storage.type')           # 'memory'
            >>> config.get('storage.redis.host')     # 'localhost'
            >>> config.get('nonexistent.key', 42)    # 42
        """
        return self._get_by_path(key, default)

    def set(self, key: str, value: Any) -> None:
        """
        Set a config value by dot-notation path.

        Examples:
            >>> config.set('storage.type', 'redis')
            >>> config.set('global.log_level', 'DEBUG')
        """
        self._set_by_path(key, value)
        logger.debug(f"Config set: {key} = {value!r}")

    # ------------------------------------------------------------------
    # Rule management helpers
    # ------------------------------------------------------------------

    def add_rule_config(self, rule_data: Dict[str, Any]) -> None:
        """
        Add a rule to the configuration (validates before adding).

        Raises:
            ConfigurationError: If rule is invalid or name already exists.
        """
        try:
            RuleConfig(**rule_data)
        except Exception as exc:
            raise ConfigurationError(f"Invalid rule configuration: {exc}") from exc

        existing = [r.get("name") for r in self.config.get("rules", [])]
        if rule_data.get("name") in existing:
            raise ConfigurationError(f"Rule '{rule_data['name']}' already exists")

        self.config.setdefault("rules", []).append(rule_data)
        logger.info(f"Added rule: {rule_data.get('name')}")

    def remove_rule_config(self, rule_name: str) -> bool:
        """
        Remove a rule by name.

        Returns:
            True if removed, False if not found.
        """
        before = len(self.config.get("rules", []))
        self.config["rules"] = [
            r for r in self.config.get("rules", []) if r.get("name") != rule_name
        ]
        removed = len(self.config["rules"]) < before
        if removed:
            logger.info(f"Removed rule: {rule_name}")
        return removed

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_config(self, path: Optional[Union[str, Path]] = None) -> None:
        """
        Save the current (merged) configuration to a YAML file.

        Note: sensitive values already injected from environment variables
        will be written to the file.  Pass a safe path and restrict file
        permissions accordingly (chmod 600).

        Args:
            path: Destination path.  Defaults to the file this instance
                  was loaded from.

        Raises:
            ConfigurationError: If no path is available or the write fails.
        """
        save_path = Path(path) if path else self.config_file
        if not save_path:
            raise ConfigurationError("No save path specified")
        try:
            save_path.parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, "w", encoding="utf-8") as fh:
                yaml.safe_dump(
                    self.config,
                    fh,
                    default_flow_style=False,
                    sort_keys=False,
                    allow_unicode=True,
                )
            logger.info(f"Configuration saved to {save_path}")
        except Exception as exc:
            raise ConfigurationError(f"Failed to save configuration: {exc}") from exc

    def to_dict(self) -> Dict[str, Any]:
        """Return a deep copy of the current configuration."""
        return cast(Dict[str, Any], self._deep_copy(self.config))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _deep_copy(self, obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: self._deep_copy(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._deep_copy(v) for v in obj]
        return obj

    def _merge_config(self, base: Dict[str, Any], update: Dict[str, Any]) -> None:
        """Recursively merge *update* into *base* in place."""
        for key, value in update.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._merge_config(base[key], value)
            else:
                base[key] = value

    def _get_by_path(self, key: str, default: Any = None) -> Any:
        node = self.config
        for part in key.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return default
        return node

    def _set_by_path(self, key: str, value: Any) -> None:
        parts = key.split(".")
        node = self.config
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

    def __repr__(self) -> str:
        rule_count = len(self.config.get("rules", []))
        storage_type = self.config.get("storage", {}).get("type", "unknown")
        return f"ConfigManager(rules={rule_count}, storage={storage_type!r})"
