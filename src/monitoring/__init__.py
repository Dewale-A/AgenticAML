"""
Continuous Monitoring module for AgenticAML.

This package implements Layer 3 of the three-layer verification framework
(ROADMAP Section 1): Watchlist Screening and Continuous Monitoring.

Layer 3 runs entirely on free, locally maintained screening lists with no
external API dependencies. It provides:

1. continuous_monitor.py — Scheduled re-screening engine that periodically
   screens all customers against current list versions. Detects new matches
   on previously clean customers and triggers risk tier upgrades.

2. list_manager.py — Downloads, versions, and checksums screening lists
   from free sources (OFAC SDN, UN Consolidated, Nigerian domestic).
   Uses checksum comparison to avoid re-processing unchanged lists.

All monitoring activity is logged to the monitoring_runs table so the
compliance team can demonstrate screening cadence to CBN examiners.
"""
