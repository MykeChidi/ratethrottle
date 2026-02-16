"""
Tests for configuration management
"""

import tempfile
from pathlib import Path

import pytest
import yaml

from ratethrottle.config import ConfigManager, RuleConfig
from ratethrottle.core import RateThrottleRule
from ratethrottle.exceptions import ConfigurationError


class TestRuleConfig:
    """Test RuleConfig dataclass"""

    def test_create_valid_rule(self):
        """Test creating a valid rule config"""
        rule = RuleConfig(name="test", limit=100, window=60)

        assert rule.name == "test"
        assert rule.limit == 100
        assert rule.window == 60
        assert rule.scope == "ip"
        assert rule.strategy == "sliding_window"

    def test_empty_name_raises_error(self):
        """Test that empty name raises error"""
        with pytest.raises(ConfigurationError, match="name cannot be empty"):
            RuleConfig(name="", limit=100, window=60)

    def test_negative_limit_raises_error(self):
        """Test that negative limit raises error"""
        with pytest.raises(ConfigurationError, match="limit must be positive"):
            RuleConfig(name="test", limit=-1, window=60)

    def test_zero_limit_raises_error(self):
        """Test that zero limit raises error"""
        with pytest.raises(ConfigurationError, match="limit must be positive"):
            RuleConfig(name="test", limit=0, window=60)

    def test_negative_window_raises_error(self):
        """Test that negative window raises error"""
        with pytest.raises(ConfigurationError, match="window must be positive"):
            RuleConfig(name="test", limit=100, window=-1)

    def test_negative_block_duration_raises_error(self):
        """Test that negative block duration raises error"""
        with pytest.raises(ConfigurationError, match="block_duration cannot be negative"):
            RuleConfig(name="test", limit=100, window=60, block_duration=-1)

    def test_invalid_scope_raises_error(self):
        """Test that invalid scope raises error"""
        with pytest.raises(ConfigurationError, match="invalid scope"):
            RuleConfig(name="test", limit=100, window=60, scope="invalid")

    def test_invalid_strategy_raises_error(self):
        """Test that invalid strategy raises error"""
        with pytest.raises(ConfigurationError, match="invalid strategy"):
            RuleConfig(name="test", limit=100, window=60, strategy="invalid")

    def test_burst_less_than_limit_raises_error(self):
        """Test that burst < limit raises error"""
        with pytest.raises(ConfigurationError, match="burst.*cannot be less than limit"):
            RuleConfig(name="test", limit=100, window=60, burst=50)

    def test_invalid_http_method_raises_error(self):
        """Test that invalid HTTP method raises error"""
        with pytest.raises(ConfigurationError, match="invalid HTTP methods"):
            RuleConfig(name="test", limit=100, window=60, methods=["INVALID"])

    def test_to_dict(self):
        """Test converting to dictionary"""
        rule = RuleConfig(name="test", limit=100, window=60)
        d = rule.to_dict()

        assert d["name"] == "test"
        assert d["limit"] == 100
        assert d["window"] == 60


class TestConfigManager:
    """Test ConfigManager"""

    def test_initialization_without_file(self):
        """Test initialization without config file"""
        config = ConfigManager()
        assert config.config is not None
        assert "storage" in config.config

    def test_initialization_with_nonexistent_file(self):
        """Test initialization with non-existent file raises error"""
        with pytest.raises(ConfigurationError, match="not found"):
            ConfigManager("nonexistent.yaml")

    def test_load_valid_config(self):
        """Test loading valid configuration"""
        config_data = {
            "storage": {"type": "memory"},
            "rules": [{"name": "api", "limit": 100, "window": 60}],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(config_data, f)
            temp_path = f.name

        try:
            config = ConfigManager(temp_path)
            assert config.get("storage.type") == "memory"
            assert len(config.get_rules()) == 1
        finally:
            Path(temp_path).unlink()

    def test_load_invalid_yaml_raises_error(self):
        """Test loading invalid YAML raises error"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("invalid: yaml: content:")
            temp_path = f.name

        try:
            with pytest.raises(ConfigurationError, match="YAML"):
                ConfigManager(temp_path)
        finally:
            Path(temp_path).unlink()

    def test_load_non_dict_config_raises_error(self):
        """Test loading non-dict config raises error"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(["not", "a", "dict"], f)
            temp_path = f.name

        try:
            with pytest.raises(ConfigurationError, match="must be a dictionary"):
                ConfigManager(temp_path)
        finally:
            Path(temp_path).unlink()

    def test_get_with_dot_notation(self):
        """Test getting values with dot notation"""
        config = ConfigManager()

        assert config.get("storage.type") == "memory"
        assert config.get("global.enabled") is True

    def test_get_with_default(self):
        """Test getting with default value"""
        config = ConfigManager()

        assert config.get("nonexistent.key", "default") == "default"

    def test_set_with_dot_notation(self):
        """Test setting values with dot notation"""
        config = ConfigManager()

        config.set("storage.type", "redis")
        assert config.get("storage.type") == "redis"

        config.set("new.nested.key", "value")
        assert config.get("new.nested.key") == "value"

    def test_get_rules(self):
        """Test getting rules"""
        config = ConfigManager()
        rules = config.get_rules()

        assert len(rules) > 0
        assert all(isinstance(r, RateThrottleRule) for r in rules)

    def test_add_rule_config(self):
        """Test adding a rule"""
        config = ConfigManager()

        rule_data = {"name": "new_rule", "limit": 50, "window": 30}
        config.add_rule_config(rule_data)

        rules = config.get_rules()
        assert any(r.name == "new_rule" for r in rules)

    def test_add_duplicate_rule_raises_error(self):
        """Test adding duplicate rule raises error"""
        config = ConfigManager()

        rule_data = {"name": "default", "limit": 50, "window": 30}

        with pytest.raises(ConfigurationError, match="already exists"):
            config.add_rule_config(rule_data)

    def test_add_invalid_rule_raises_error(self):
        """Test adding invalid rule raises error"""
        config = ConfigManager()

        with pytest.raises(ConfigurationError):
            config.add_rule_config({"name": "bad", "limit": -1, "window": 60})

    def test_remove_rule_config(self):
        """Test removing a rule"""
        config = ConfigManager()

        # Add a rule
        config.add_rule_config({"name": "temp", "limit": 50, "window": 30})

        # Remove it
        result = config.remove_rule_config("temp")
        assert result is True

        # Verify it's gone
        rules = config.get_rules()
        assert not any(r.name == "temp" for r in rules)

    def test_remove_nonexistent_rule(self):
        """Test removing non-existent rule returns False"""
        config = ConfigManager()
        result = config.remove_rule_config("nonexistent")
        assert result is False

    def test_validate_valid_config(self):
        """Test validating valid config"""
        config = ConfigManager()
        config.validate()  # Should not raise

    def test_validate_invalid_storage_type(self):
        """Test validating invalid storage type"""
        config = ConfigManager()
        config.set("storage.type", "invalid")

        with pytest.raises(ConfigurationError, match="Invalid storage type"):
            config.validate()

    def test_validate_invalid_ddos_threshold(self):
        """Test validating invalid DDoS threshold"""
        config = ConfigManager()
        config.set("ddos_protection.enabled", True)
        config.set("ddos_protection.threshold", -1)

        with pytest.raises(ConfigurationError, match="DDoS threshold"):
            config.validate()

    def test_save_config(self):
        """Test saving configuration"""
        config = ConfigManager()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            temp_path = f.name

        try:
            config.save_config(temp_path)
            assert Path(temp_path).exists()

            # Load and verify
            with open(temp_path) as f:
                loaded = yaml.safe_load(f)
            assert "storage" in loaded
        finally:
            Path(temp_path).unlink()

    def test_get_storage_config(self):
        """Test getting storage config"""
        config = ConfigManager()
        storage_config = config.get_storage_config()

        assert "type" in storage_config
        assert "redis" in storage_config

    def test_get_ddos_config(self):
        """Test getting DDoS config"""
        config = ConfigManager()
        ddos_config = config.get_ddos_config()

        assert "enabled" in ddos_config
        assert "threshold" in ddos_config

    def test_get_monitoring_config(self):
        """Test getting monitoring config"""
        config = ConfigManager()
        monitoring_config = config.get_monitoring_config()

        assert "enabled" in monitoring_config

    def test_get_alerts_config(self):
        """Test getting alerts config"""
        config = ConfigManager()
        alerts_config = config.get_alerts_config()

        assert "enabled" in alerts_config

    def test_to_dict(self):
        """Test converting to dictionary"""
        config = ConfigManager()
        d = config.to_dict()

        assert isinstance(d, dict)
        assert "storage" in d
        assert "rules" in d

    def test_repr(self):
        """Test string representation"""
        config = ConfigManager()
        repr_str = repr(config)

        assert "ConfigManager" in repr_str
        assert "rules=" in repr_str
        assert "storage=" in repr_str


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
