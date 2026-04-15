"""
Configurable governance rules for AgenticAML.
Thresholds align with CBN AML/CFT guidelines (NGN amounts).
"""

import os
from dataclasses import dataclass, field
from typing import List


@dataclass
class ThresholdConfig:
    cash_threshold: float = float(os.getenv("CASH_THRESHOLD", "5000000"))       # NGN 5M
    transfer_threshold: float = float(os.getenv("TRANSFER_THRESHOLD", "10000000"))  # NGN 10M
    materiality_threshold: float = float(os.getenv("MATERIALITY_THRESHOLD", "50000000"))  # NGN 50M

    velocity_window_hours: int = int(os.getenv("VELOCITY_WINDOW_HOURS", "24"))
    velocity_max_transactions: int = int(os.getenv("VELOCITY_MAX_TRANSACTIONS", "10"))
    velocity_max_amount: float = float(os.getenv("VELOCITY_MAX_AMOUNT", "20000000"))

    structuring_threshold_pct: float = float(os.getenv("STRUCTURING_THRESHOLD_PCT", "0.9"))

    confidence_gate_threshold: float = float(os.getenv("CONFIDENCE_GATE_THRESHOLD", "0.7"))
    auto_block_sanctions: bool = os.getenv("AUTO_BLOCK_SANCTIONS", "true").lower() == "true"


@dataclass
class RiskTierConfig:
    # NGN thresholds for tier assignment
    low_max: float = 1_000_000       # below 1M -> low
    medium_max: float = 5_000_000    # 1M to 5M -> medium
    high_max: float = 50_000_000     # 5M to 50M -> high
    # above 50M -> critical


@dataclass
class SlaConfig:
    # Hours to resolve by priority
    critical_hours: int = 4
    high_hours: int = 24
    medium_hours: int = 72
    low_hours: int = 168

    # STR filing deadline per NFIU (hours from alert)
    str_filing_deadline_hours: int = 24


@dataclass
class GovernanceRules:
    thresholds: ThresholdConfig = field(default_factory=ThresholdConfig)
    risk_tiers: RiskTierConfig = field(default_factory=RiskTierConfig)
    sla: SlaConfig = field(default_factory=SlaConfig)

    # Sanctions match types that REQUIRE human review before action
    sanctions_human_review_types: List[str] = field(
        default_factory=lambda: ["strong", "partial"]
    )

    # Agent outputs below this confidence go to human review
    confidence_gate: float = float(os.getenv("CONFIDENCE_GATE_THRESHOLD", "0.7"))

    # Risk levels that require mandatory SAR assessment
    mandatory_sar_risk_levels: List[str] = field(
        default_factory=lambda: ["critical"]
    )

    # Roles allowed to approve SARs (human-in-the-loop enforcement)
    sar_approver_roles: List[str] = field(
        default_factory=lambda: ["compliance_officer", "senior_compliance_officer", "mlro"]
    )

    # Roles allowed to confirm sanctions blocks
    sanctions_block_confirmer_roles: List[str] = field(
        default_factory=lambda: ["senior_compliance_officer", "mlro"]
    )

    # Cannot close high-risk case without senior review
    high_risk_case_close_roles: List[str] = field(
        default_factory=lambda: ["senior_compliance_officer", "mlro", "compliance_officer"]
    )


# Singleton instance
RULES = GovernanceRules()


def get_risk_tier_for_amount(amount: float) -> str:
    """Return risk tier based on transaction amount."""
    cfg = RULES.risk_tiers
    if amount < cfg.low_max:
        return "low"
    elif amount < cfg.medium_max:
        return "medium"
    elif amount < cfg.high_max:
        return "high"
    return "critical"


def get_sla_hours(priority: str) -> int:
    """Return SLA hours for a given priority level."""
    cfg = RULES.sla
    return {
        "critical": cfg.critical_hours,
        "high": cfg.high_hours,
        "medium": cfg.medium_hours,
        "low": cfg.low_hours,
    }.get(priority, cfg.medium_hours)
