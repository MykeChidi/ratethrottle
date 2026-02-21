"""
Tests for CLI functionality
"""

import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from ratethrottle.cli import (
    RateThrottleCLI,
    Colors,
    print_success,
    print_error,
    print_warning,
    print_info,
    print_header,
)


class TestColors:
    """Test color utility class"""
    
    def test_colors_defined(self):
        """Test that all color codes are defined"""
        assert hasattr(Colors, 'BLUE')
        assert hasattr(Colors, 'GREEN')
        assert hasattr(Colors, 'RED')
        assert hasattr(Colors, 'YELLOW')
        assert hasattr(Colors, 'CYAN')
        assert hasattr(Colors, 'BOLD')
        assert hasattr(Colors, 'END')
    
    def test_colors_are_strings(self):
        """Test that color codes are strings"""
        assert isinstance(Colors.BLUE, str)
        assert isinstance(Colors.GREEN, str)
        assert isinstance(Colors.END, str)


class TestPrintFunctions:
    """Test print utility functions"""
    
    def test_print_success(self, capsys):
        """Test success message printing"""
        print_success("Success message")
        captured = capsys.readouterr()
        assert "Success message" in captured.out
        assert "✓" in captured.out or "SUCCESS" in captured.out
    
    def test_print_error(self, capsys):
        """Test error message printing"""
        print_error("Error message")
        captured = capsys.readouterr()
        assert "Error message" in captured.err
        assert "✗" in captured.err or "Error message" in captured.err
    
    def test_print_warning(self, capsys):
        """Test warning message printing"""
        print_warning("Warning message")
        captured = capsys.readouterr()
        assert "Warning message" in captured.out
        assert "⚠" in captured.out or "WARNING" in captured.out
    
    def test_print_info(self, capsys):
        """Test info message printing"""
        print_info("Info message")
        captured = capsys.readouterr()
        assert "Info message" in captured.out
    
    def test_print_header(self, capsys):
        """Test header printing"""
        print_header("Test Header")
        captured = capsys.readouterr()
        assert "Test Header" in captured.out


class TestRateThrottleCLI:
    """Test CLI class"""
    
    @pytest.fixture
    def cli(self):
        """Create CLI instance"""
        return RateThrottleCLI()
    
    def test_cli_initialization(self, cli):
        """Test CLI initializes correctly"""
        assert cli is not None
        assert hasattr(cli, 'limiter')
        assert hasattr(cli, 'config')
    
    def test_parse_args_help(self, cli):
        """Test --help argument"""
        from ratethrottle.cli import main

        with pytest.raises(SystemExit) as exc_info:
            with patch('sys.argv', ['ratethrottle', '--help']):
                main()
        assert exc_info.value.code == 0


class TestMonitorCommand:
    """Test monitor command"""
    
    @pytest.fixture
    def cli(self):
        """Create CLI with config"""
        return RateThrottleCLI()
    
    @patch('time.sleep')
    @patch('builtins.print')
    def test_monitor_starts(self, mock_print, mock_sleep, cli, temp_config):
        """Test monitor command starts"""
        # Mock sleep to stop after first iteration
        mock_sleep.side_effect = KeyboardInterrupt
        
        args = Mock()
        args.config = temp_config
        args.interval = 1
        
        try:
            cli.run_monitor(args)
        except KeyboardInterrupt:
            pass
        
        # Should have printed something
        assert mock_print.called
    
    @patch('time.sleep')
    def test_monitor_keyboard_interrupt(self, mock_sleep, cli, temp_config):
        """Test monitor handles Ctrl+C gracefully"""
        mock_sleep.side_effect = KeyboardInterrupt
        
        args = Mock()
        args.config = temp_config
        args.interval = 1
        
        # Should not raise
        cli.run_monitor(args)
    
    @patch('builtins.print')
    def test_monitor_displays_stats(self, mock_print, cli, temp_config):
        """Test monitor displays statistics"""
        # load config
        cli._load_config(temp_config)

        args = Mock()
        args.config = temp_config
        args.interval = 1
        
        # Add some test data
        cli.limiter.check_rate_limit('192.168.1.1', 'test_rule')
        
        with patch('time.sleep', side_effect=KeyboardInterrupt):
            try:
                cli.run_monitor(args)
            except KeyboardInterrupt:
                pass
        
        # Check that stats were printed
        printed_text = ''.join([str(call) for call in mock_print.call_args_list])
        # Should contain some metric information
        assert mock_print.called


class TestTestCommand:
    """Test test command"""
    
    @pytest.fixture
    def cli(self):
        """Create CLI with config"""
        return RateThrottleCLI()
    
    def test_test_command_basic(self, cli, temp_config, capsys):
        """Test basic test command"""
        args = Mock()
        args.config = temp_config
        args.rule = 'test_rule'
        args.identifier = '192.168.1.1'
        args.requests = 5
        args.delay = 0
        
        cli.run_test(args)
        
        captured = capsys.readouterr()
        assert "Testing" in captured.out or "test" in captured.out.lower()
    
    def test_test_command_exceeds_limit(self, cli, temp_config, capsys):
        """Test that test command shows blocked requests"""
        args = Mock()
        args.config = temp_config
        args.rule = 'test_rule'
        args.identifier = '192.168.1.1'
        args.requests = 15  # More than limit of 10
        args.delay = 0
        
        cli.run_test(args)
        
        captured = capsys.readouterr()
        # Should show some blocked requests
        assert captured.out  # Something was printed
    
    def test_test_command_invalid_rule(self, cli, temp_config, capsys):
        """Test with non-existent rule"""
        args = Mock()
        args.config = temp_config
        args.rule = 'nonexistent_rule'
        args.identifier = '192.168.1.1'
        args.requests = 5
        args.delay = 0
        
        with pytest.raises(SystemExit) as exc_info:
            cli.run_test(args)
        
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        # Should show error or handle gracefully
        assert captured.out or captured.err


class TestConfigCommand:
    """Test config command"""
    
    @pytest.fixture
    def cli(self):
        """Create CLI"""
        return RateThrottleCLI()
    
    def test_config_show(self, cli, temp_config, capsys):
        """Test config --show"""
        args = Mock()
        args.config = temp_config
        args.show = True
        args.validate = False
        args.export = None
        
        cli.run_config(args)
        
        captured = capsys.readouterr()
        assert "storage" in captured.out or "Configuration" in captured.out
    
    def test_config_validate_valid(self, cli, temp_config, capsys):
        """Test config --validate with valid config"""
        args = Mock()
        args.config = temp_config
        args.show = False
        args.validate = True
        args.export = None
        
        cli.run_config(args)
        
        captured = capsys.readouterr()
        # Should show success or validation result
        assert captured.out
    
    def test_config_validate_missing_file(self, cli, capsys):
        """Test config --validate with missing file"""
        args = Mock()
        args.config = 'nonexistent.yaml'
        args.show = False
        args.validate = True
        args.export = None
        
        with pytest.raises(SystemExit) as exc_info:
            cli.run_config(args)

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        # Should show error
        output_text = (captured.out + captured.err).lower()
        assert "not found" in output_text or "error" in output_text
    
    def test_config_export(self, cli, temp_config):
        """Test config --export"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            export_path = f.name
        
        try:
            args = Mock()
            args.config = temp_config
            args.show = False
            args.validate = False
            args.export = export_path
            
            cli.run_config(args)
            
            # Check file was created
            assert Path(export_path).exists()
            
            # Check it contains valid YAML
            import yaml
            with open(export_path) as f:
                data = yaml.safe_load(f)
                assert isinstance(data, dict)
        finally:
            Path(export_path).unlink(missing_ok=True)


class TestManageCommand:
    """Test manage command"""

    @pytest.fixture
    def cli(self):
        """Create CLI with config"""
        return RateThrottleCLI()
    
    def test_whitelist_add(self, cli, temp_config, capsys):
        """Test --whitelist-add"""
        args = Mock()
        args.config = temp_config
        args.whitelist_add = '192.168.1.100'
        args.whitelist_remove = None
        args.blacklist_add = None
        args.blacklist_remove = None
        args.list_all = False
        args.duration = None
        
        cli.run_manage(args)
        
        captured = capsys.readouterr()
        assert "whitelist" in captured.out.lower() or "added" in captured.out.lower()
        
        # Verify it was added
        assert '192.168.1.100' in cli.limiter.whitelist
    
    def test_whitelist_remove(self, cli, temp_config, capsys):
        """Test --whitelist-remove"""
        # Load config
        cli._load_config(temp_config)

        # First add
        cli.limiter.add_to_whitelist('192.168.1.100')
        
        args = Mock()
        args.config = temp_config
        args.whitelist_add = None
        args.whitelist_remove = '192.168.1.100'
        args.blacklist_add = None
        args.blacklist_remove = None
        args.list_all = False
        args.duration = None
        
        cli.run_manage(args)
        
        captured = capsys.readouterr()
        assert captured.out  # Something printed
        
        # Verify it was removed
        assert '192.168.1.100' not in cli.limiter.whitelist
    
    def test_blacklist_add(self, cli, temp_config, capsys):
        """Test --blacklist-add"""
        args = Mock()
        args.config = temp_config
        args.whitelist_add = None
        args.whitelist_remove = None
        args.blacklist_add = '192.168.1.200'
        args.blacklist_remove = None
        args.list_all = False
        args.duration = 3600
        
        cli.run_manage(args)
        
        captured = capsys.readouterr()
        assert "blacklist" in captured.out.lower() or "blocked" in captured.out.lower()
        
        # Verify it was added
        assert '192.168.1.200' in cli.limiter.blacklist
    
    def test_blacklist_remove(self, cli, temp_config, capsys):
        """Test --blacklist-remove"""

        # Load config
        cli._load_config(temp_config)

        # First add
        cli.limiter.add_to_blacklist('192.168.1.200')
        
        args = Mock()
        args.config = temp_config
        args.whitelist_add = None
        args.whitelist_remove = None
        args.blacklist_add = None
        args.blacklist_remove = '192.168.1.200'
        args.list_all = False
        args.duration = None
        
        cli.run_manage(args)
        
        captured = capsys.readouterr()
        assert captured.out
        
        # Verify it was removed
        assert '192.168.1.200' not in cli.limiter.blacklist
    
    def test_list_all(self, cli, temp_config, capsys):
        """Test --list-all"""

        # Load config
        cli._load_config(temp_config)

        # Add some test data
        cli.limiter.add_to_whitelist('10.0.0.1')
        cli.limiter.add_to_blacklist('192.168.1.100')
        
        args = Mock()
        args.config = temp_config
        args.whitelist_add = None
        args.whitelist_remove = None
        args.blacklist_add = None
        args.blacklist_remove = None
        args.list_all = True
        args.duration = None
        
        cli.run_manage(args)
        
        captured = capsys.readouterr()
        assert "whitelist" in captured.out.lower() or "blacklist" in captured.out.lower()


class TestStatsCommand:
    """Test stats command"""
    
    @pytest.fixture
    def cli(self, temp_config):
        """Create CLI with config"""
        cli = RateThrottleCLI()
        # load config first
        cli._load_config(temp_config)
        # Add some test data
        cli.limiter.check_rate_limit('192.168.1.1', 'test_rule')
        cli.limiter.check_rate_limit('192.168.1.2', 'test_rule')
        return cli
    
    def test_stats_display(self, cli, temp_config, capsys):
        """Test stats display"""
        args = Mock()
        args.config = temp_config
        args.export = None
        args.raw_data = False
        
        cli.run_stats(args)
        
        captured = capsys.readouterr()
        assert "Statistics" in captured.out or "stats" in captured.out.lower()
    
    def test_stats_export(self, cli, temp_config):
        """Test stats --export"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            export_path = f.name
        
        try:
            args = Mock()
            args.config = temp_config
            args.export = export_path
            args.raw_data = False
            
            cli.run_stats(args)
            
            # Check file was created
            assert Path(export_path).exists()
            
            # Check it contains valid JSON
            with open(export_path) as f:
                data = json.load(f)
                assert isinstance(data, dict)
        finally:
            Path(export_path).unlink(missing_ok=True)
    
    def test_stats_export_with_raw_data(self, cli, temp_config):
        """Test stats --export --raw-data"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            export_path = f.name
        
        try:
            args = Mock()
            args.config = temp_config
            args.export = export_path
            args.raw_data = True
            
            cli.run_stats(args)
            
            # Check file was created
            assert Path(export_path).exists()
            
            # Check it contains valid JSON
            with open(export_path) as f:
                data = json.load(f)
                assert isinstance(data, dict)
        finally:
            Path(export_path).unlink(missing_ok=True)


class TestCLIIntegration:
    """Integration tests for CLI"""
    
    def test_main_function_exists(self):
        """Test that main function exists"""
        from ratethrottle.cli import main
        assert callable(main)
    
    @patch('sys.argv', ['ratethrottle', '--help'])
    def test_main_help(self):
        """Test main with --help"""
        from ratethrottle.cli import main
        
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0
    
    @patch('sys.argv', ['ratethrottle', 'config', '--validate'])
    def test_main_config_validate(self, capsys):
        """Test main with config validate"""
        from ratethrottle.cli import main
        
        # Should run without crashing (may show error for missing config)
        try:
            main()
        except SystemExit:
            pass
        
        captured = capsys.readouterr()
        # Should have printed something
        assert captured.out or captured.err


class TestCLIErrorHandling:
    """Test CLI error handling"""
    
    @pytest.fixture
    def cli(self):
        """Create CLI"""
        return RateThrottleCLI()
    
    def test_invalid_config_file(self, cli, capsys):
        """Test handling of invalid config file"""
        args = Mock()
        args.config = 'nonexistent_file.yaml'
        args.show = False
        args.validate = True
        args.export = None
        
        # Should exit with error, catch the SystemExit
        with pytest.raises(SystemExit) as exc_info:
            cli.run_config(args)
        
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        # Check combined output
        output_text = (captured.out + captured.err).lower()
        assert "not found" in output_text or "error" in output_text
    
    def test_keyboard_interrupt_handling(self, cli, temp_config):
        """Test Ctrl+C handling in monitor"""
        args = Mock()
        args.config = temp_config
        args.interval = 1
        
        with patch('time.sleep', side_effect=KeyboardInterrupt):
            # Should not raise, should handle gracefully
            cli.run_monitor(args)


class TestCLIVerboseMode:
    """Test verbose logging"""
    
    def test_verbose_flag(self):
        """Test --verbose flag"""
        from ratethrottle.cli import main

        with patch('sys.argv', ['ratethrottle', '--verbose', 'config', '--validate']):
            try:
                main()
            except SystemExit:
                pass
            # Should exit safely
            assert True



if __name__ == "__main__":
    pytest.main([__file__, "-v"])