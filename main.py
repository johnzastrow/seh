#!/usr/bin/env python3
"""Main entry point for SolarEdge Harvest.

This file allows running the application directly with:
    uv run python main.py

For full CLI usage, use:
    uv run seh --help
"""

from seh.cli import cli

if __name__ == "__main__":
    cli()
