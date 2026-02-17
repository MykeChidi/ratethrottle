"""
RateThottle Module entry point.

Allows you to run the package as a module.
    python -m ratethrottle
"""

import sys


def main():
    """Main entry point for the package."""
    try:
        from .cli import main as cli_main

        sys.exit(cli_main())
    except ImportError as e:
        print(f"Error importing CLI: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
