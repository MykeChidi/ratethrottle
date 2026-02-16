"""
RateThrottle - Configuration Management

Production-grade configuration management with validation,
defaults, and flexible loading options.
"""

import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml

from .core import RateThrottleRule
from .exceptions import ConfigurationError

logger = logging.getLogger(__name__)


@dataclass
class RuleConfig:
    """
    Configuration for a single rule with validation

    Attributes:
        name: Rule identifier
        limit: Maximum requests allowed
        window: Time window in seconds
        scope: Scope of the limit ('ip', 'user', 'endpoint', 'global')
        strategy: Rate limiting strategy
        block_duration: How long to block after limit exceeded
        burst: Burst allowance (for token bucket)
        paths: Optional list of paths this rule applies to
        methods: Optional list of HTTP methods this rule applies to
    """

    name: str
    limit: int
    window: int
    scope: str = "ip"
    strategy: str = "sliding_window"
    block_duration: int = 300
    burst: Optional[int] = None
    paths: Optional[List[str]] = None
    methods: Optional[List[str]] = None

    def __post_init__(self):
        """Validate rule configuration"""
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

        valid_scopes = {"ip", "user", "endpoint", "global"}
        if self.scope not in valid_scopes:
            raise ConfigurationError(
                f"Rule '{self.name}': invalid scope '{self.scope}'. "
                f"Valid options: {', '.join(valid_scopes)}"
            )

        valid_strategies = {"token_bucket", "leaky_bucket", "fixed_window", "sliding_window"}
        if self.strategy not in valid_strategies:
            raise ConfigurationError(
                f"Rule '{self.name}': invalid strategy '{self.strategy}'. "
                f"Valid options: {', '.join(valid_strategies)}"
            )

        if self.burst is not None and self.burst < self.limit:
            raise ConfigurationError(
                f"Rule '{self.name}': burst ({self.burst}) cannot be less than limit ({self.limit})"
            )

        if self.methods:
            valid_methods = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}
            invalid_methods = [m for m in self.methods if m.upper() not in valid_methods]
            if invalid_methods:
                raise ConfigurationError(
                    f"Rule '{self.name}': invalid HTTP methods: {', '.join(invalid_methods)}"
                )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return asdict(self)


class ConfigManager:
    """
    Manages RateThrottle configuration with validation and defaults

    Features:
        - YAML configuration file loading
        - Environment variable overrides
        - Configuration validation
        - Default values
        - Hot-reloading support

    Examples:
        >>> # Load from file
        >>> config = ConfigManager('ratethrottle.yaml')
        >>> rules = config.get_rules()
        >>>
        >>> # Programmatic configuration
        >>> config = ConfigManager()
        >>> config.set('global.enabled', True)
        >>> config.add_rule_config({
        ...     'name': 'api',
        ...     'limit': 100,
        ...     'window': 60
        ... })
    """

    DEFAULT_CONFIG = {
        "storage": {
            "type": "memory",
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
        "global": {
            "enabled": True,
            "default_strategy": "sliding_window",
            "headers_enabled": True,
            "log_violations": True,
            "log_level": "INFO",
        },
        "rules": [
            {
                "name": "default",
                "limit": 1000,
                "window": 3600,
                "strategy": "sliding_window",
                "block_duration": 300,
            }
        ],
        "ddos_protection": {
            "enabled": True,
            "threshold": 10000,
            "window": 60,
            "auto_block": True,
            "block_duration": 3600,
            "suspicious_threshold": 0.5,
            "max_unique_endpoints": 50,
        },
        "monitoring": {
            "enabled": True,
            "metrics_port": 9090,
            "export_prometheus": False,
            "dashboard_enabled": True,
        },
        "alerts": {
            "enabled": False,
            "webhook_url": None,
            "email": {
                "enabled": False,
                "smtp_host": "smtp.gmail.com",
                "smtp_port": 587,
                "smtp_user": "",
                "smtp_password": "",  # nosec B105
                "from_addr": "",
                "to_addrs": [],
            },
        },
    }

    def __init__(self, config_file: Optional[Union[str, Path]] = None):
        """
        Initialize configuration manager

        Args:
            config_file: Path to YAML configuration file (optional)

        Raises:
            ConfigurationError: If configuration file is invalid
        """
        self.config_file = Path(config_file) if config_file else None
        self.config = self._deep_copy(self.DEFAULT_CONFIG)

        if self.config_file:
            if not self.config_file.exists():
                raise ConfigurationError(f"Configuration file not found: {self.config_file}")
            self.load_config()
        else:
            logger.info("Using default configuration")

    def _deep_copy(self, obj: Any) -> Any:
        """Deep copy configuration dict"""
        if isinstance(obj, dict):
            return {k: self._deep_copy(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._deep_copy(v) for v in obj]
        return obj

    def load_config(self) -> None:
        """
        Load configuration from file

        Raises:
            ConfigurationError: If file cannot be loaded or is invalid
        """
        if not self.config_file:
            raise ConfigurationError("No configuration file specified")

        try:
            with open(self.config_file, "r") as f:
                user_config = yaml.safe_load(f)

            if user_config is None:
                logger.warning(f"Empty configuration file: {self.config_file}")
                return

            if not isinstance(user_config, dict):
                raise ConfigurationError(
                    f"Configuration must be a dictionary, got {type(user_config).__name__}"
                )

            # Merge with defaults
            self._merge_config(self.config, user_config)

            # Validate
            self.validate()

            logger.info(f"Configuration loaded from {self.config_file}")

        except yaml.YAMLError as e:
            raise ConfigurationError(f"Failed to parse YAML configuration: {e}") from e
        except Exception as e:
            raise ConfigurationError(f"Failed to load configuration: {e}") from e

    def save_config(self, path: Optional[Union[str, Path]] = None) -> None:
        """
        Save configuration to file

        Args:
            path: Path to save to (uses config_file if not specified)

        Raises:
            ConfigurationError: If save fails
        """
        save_path = Path(path) if path else self.config_file

        if not save_path:
            raise ConfigurationError("No save path specified")

        try:
            # Ensure directory exists
            save_path.parent.mkdir(parents=True, exist_ok=True)

            with open(save_path, "w") as f:
                yaml.dump(self.config, f, default_flow_style=False, sort_keys=False)

            logger.info(f"Configuration saved to {save_path}")

        except Exception as e:
            raise ConfigurationError(f"Failed to save configuration: {e}") from e

    def _merge_config(self, base: Dict[str, Any], update: Dict[str, Any]) -> None:
        """Recursively merge configurations"""
        for key, value in update.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._merge_config(base[key], value)
            else:
                base[key] = value

    def validate(self) -> None:
        """
        Validate configuration

        Raises:
            ConfigurationError: If configuration is invalid
        """
        # Validate storage type
        storage_type = self.config.get("storage", {}).get("type")
        valid_storage = {"memory", "redis"}
        if storage_type not in valid_storage:
            raise ConfigurationError(
                f"Invalid storage type: {storage_type}. "
                f"Valid options: {', '.join(valid_storage)}"
            )

        # Validate rules
        rules = self.config.get("rules", [])
        if not isinstance(rules, list):
            raise ConfigurationError("'rules' must be a list")

        if not rules:
            logger.warning("No rules defined in configuration")

        # Validate each rule
        for i, rule_data in enumerate(rules):
            try:
                RuleConfig(**rule_data)
            except TypeError as e:
                raise ConfigurationError(f"Invalid rule #{i+1}: {e}") from e

        # Validate DDoS protection thresholds
        ddos = self.config.get("ddos_protection", {})
        if ddos.get("enabled"):
            threshold = ddos.get("threshold", 0)
            if threshold <= 0:
                raise ConfigurationError(f"DDoS threshold must be positive, got {threshold}")

        logger.debug("Configuration validation passed")

    def get_rules(self) -> List[RateThrottleRule]:
        """
        Get all configured rules as RateThrottleRule objects

        Returns:
            List of RateThrottleRule instances

        Raises:
            ConfigurationError: If rule configuration is invalid
        """
        rules = []

        for rule_config_data in self.config.get("rules", []):
            try:
                # Create config object for validation
                rule_config = RuleConfig(**rule_config_data)

                # Create actual rule
                rule = RateThrottleRule(
                    name=rule_config.name,
                    limit=rule_config.limit,
                    window=rule_config.window,
                    scope=rule_config.scope,
                    strategy=rule_config.strategy,
                    block_duration=rule_config.block_duration,
                    burst=rule_config.burst,
                )

                rules.append(rule)

            except Exception as e:
                raise ConfigurationError(
                    f"Failed to create rule '{rule_config_data.get('name', 'unknown')}': {e}"
                ) from e

        return rules

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value by dot-notation path

        Args:
            key: Configuration key (e.g., 'storage.type')
            default: Default value if key not found

        Returns:
            Configuration value or default

        Examples:
            >>> config.get('storage.type')
            'memory'
            >>> config.get('storage.redis.host')
            'localhost'
            >>> config.get('nonexistent.key', 'default')
            'default'
        """
        keys = key.split(".")
        value = self.config

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def set(self, key: str, value: Any) -> None:
        """
        Set configuration value by dot-notation path

        Args:
            key: Configuration key (e.g., 'storage.type')
            value: Value to set

        Examples:
            >>> config.set('storage.type', 'redis')
            >>> config.set('storage.redis.host', '10.0.0.1')
        """
        keys = key.split(".")
        target = self.config

        for k in keys[:-1]:
            if k not in target:
                target[k] = {}
            target = target[k]

        target[keys[-1]] = value
        logger.debug(f"Set config: {key} = {value}")

    def add_rule_config(self, rule_data: Dict[str, Any]) -> None:
        """
        Add a rule to configuration

        Args:
            rule_data: Rule configuration dictionary

        Raises:
            ConfigurationError: If rule is invalid
        """
        # Validate rule
        try:
            RuleConfig(**rule_data)
        except Exception as e:
            raise ConfigurationError(f"Invalid rule configuration: {e}") from e

        if "rules" not in self.config:
            self.config["rules"] = []

        # Check for duplicate name
        rule_name = rule_data.get("name")
        existing_names = [r.get("name") for r in self.config["rules"]]
        if rule_name in existing_names:
            raise ConfigurationError(f"Rule with name '{rule_name}' already exists")

        self.config["rules"].append(rule_data)
        logger.info(f"Added rule configuration: {rule_name}")

    def remove_rule_config(self, rule_name: str) -> bool:
        """
        Remove a rule from configuration

        Args:
            rule_name: Name of rule to remove

        Returns:
            True if removed, False if not found
        """
        if "rules" not in self.config:
            return False

        initial_count = len(self.config["rules"])
        self.config["rules"] = [r for r in self.config["rules"] if r.get("name") != rule_name]

        removed = len(self.config["rules"]) < initial_count
        if removed:
            logger.info(f"Removed rule configuration: {rule_name}")

        return removed

    def get_storage_config(self) -> Dict[str, Any]:
        """Get storage configuration"""
        result = self.config.get("storage", {})
        return result if isinstance(result, dict) else {}

    def get_ddos_config(self) -> Dict[str, Any]:
        """Get DDoS protection configuration"""
        result = self.config.get("ddos_protection", {})
        return result if isinstance(result, dict) else {}

    def get_monitoring_config(self) -> Dict[str, Any]:
        """Get monitoring configuration"""
        result = self.config.get("monitoring", {})
        return result if isinstance(result, dict) else {}

    def get_alerts_config(self) -> Dict[str, Any]:
        """Get alerts configuration"""
        result = self.config.get("alerts", {})
        return result if isinstance(result, dict) else {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary"""
        return self._deep_copy(self.config)  # type: ignore

    def __repr__(self) -> str:
        """String representation"""
        rule_count = len(self.config.get("rules", []))
        storage_type = self.config.get("storage", {}).get("type", "unknown")
        return f"ConfigManager(rules={rule_count}, storage={storage_type})"
