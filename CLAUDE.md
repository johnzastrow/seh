# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SolarEdge Harvest (seh) - A Python project to download data from SolarEdge solar monitoring servers and store it in a relational database. Supports MariaDB, PostgreSQL, and SQLite.

## Commands

Run with uv:
```bash
uv run python main.py
```

## Architecture

The project connects to the SolarEdge Monitoring API to retrieve installation data and stores it in a relational database. Key design goals:

- Support multiple database backends (MariaDB, PostgreSQL, SQLite)
- Handle API rate limiting and retries
- Log errors and timestamps of data retrieval
- Create database views for simplified querying
- Run on a scheduled basis (cron-compatible)

## Reference Resources

- SolarEdge Monitoring API: https://knowledge-center.solaredge.com/sites/kc/files/se_monitoring_api.pdf
- Reference implementations: solaredge-interface, solaredge-go, solaredgeoptimizers on GitHub
