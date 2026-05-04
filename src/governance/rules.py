"""
Configurable governance rules for AgenticAML.

This module is the single source of truth for all regulatory thresholds
and policy parameters. All values are loaded from environment variables
at module import time so the same Docker image can be deployed at
different institutions with different regulatory thresholds without
code changes.

Default values align with CBN AML/CFT guidelines and the Money Laundering
(Prevention and Prohibition) Act 2022 (NGN amounts).
"""

import os
from dataclasses import dataclass, field


@dataclass
class ThresholdConfig:
    """Transaction amount thresholds aligned with CBN AML reporting requirements.

    cash_threshold (NGN 5M): CBN requires a Currency Transaction Report (CTR)
    for any single cash transaction ≥ NGN 5,000,000. This is the primary
    structuring/smurfing detection baseline.

    transfer_threshold (NGN 10M): Electronic transfers above this amount trigger
    enhanced monitoring and may require source-of-funds documentation.

    materiality_threshold (NGN 50M): The GovernanceEngine requires additional
    human review for any transaction above this amount, reflecting CBN's
    enhanced due diligence requirements for large-value transactions.

    velocity_window_hours (24h): The standard monitoring window for velocity
    checks. CBN real-time monitoring requirements make 24h the natural unit.

    velocity_max_transactions (10): More than 10 transactions in 24h is flagged
    as velocity abuse. This threshold balances legitimate high-frequency SME
    activity against layering patterns.

    velocity_max_amount (NGN 20M): Cumulative value ceiling within the velocity
    window. Structured to catch distributed layering below the cash threshold.

    structuring_threshold_pct (0.9): Transactions between 90% and 100% of
    the cash threshold are flagged as potential structuring. 90% = NGN 4.5M
    for the default cash_threshold of NGN 5M.

    confidence_gate_threshold (0.7): Minimum agent confidence score before the
    governance engine allows automated action. Below 0.7 = human review.

    auto_block_sanctions (True): When True, the governance engine automatically
    blocks transactions for confirmed sanctions matches (CBN mandate). Set
    to False only in non-production environments for testing.
    """
    cash_threshold: float = float(os.getenv("CASH_THRESHOLD", "5000000"))       # NGN 5M
    transfer_threshold: float = float(os.getenv("TRANSFER_THRESHOLD", "10000000"))  # NGN 10M
    materiality_threshold: float = float(os.getenv("MATERIALITY_THRESHOLD", "50000000"))  # NGN 50M

    velocity_window_hours: int = int(os.getenv("VELOCITY_WINDOW_HOURS", "24"))
    velocity_max_transactions: int = int(os.getenv("VELOCITY_MAX_TRANSACTIONS", "10"))
    velocity_max_amount: float = float(os.getenv("VELOCITY_MAX_AMOUNT", "20000000"))

    # Transactions between structuring_threshold_pct * cash_threshold and
    # cash_threshold are flagged as potential structuring (smurfing).
    structuring_threshold_pct: float = float(os.getenv("STRUCTURING_THRESHOLD_PCT", "0.9"))

    confidence_gate_threshold: float = float(os.getenv("CONFIDENCE_GATE_THRESHOLD", "0.7"))
    # Automatically block transactions on confirmed sanctions matches.
    # CBN mandates immediate freezing without delay for OFAC/UN list hits.
    auto_block_sanctions: bool = os.getenv("AUTO_BLOCK_SANCTIONS", "true").lower() == "true"

    # --- Enhanced transaction monitoring parameters (ROADMAP Phase 1) ---

    # CBN AML/CFT Guidelines Section 4: accounts with no activity for 6 months
    # (180 days) are classified as dormant and subject to special scrutiny on reactivation.
    dormant_threshold_days: int = int(os.getenv("DORMANT_THRESHOLD_DAYS", "180"))

    # Severity level assigned to dormant reactivation alerts. Default 'high'
    # because sudden activity on a long-dormant account is a known money mule indicator.
    dormant_reactivation_severity: str = os.getenv("DORMANT_REACTIVATION_SEVERITY", "high")

    # CBN Risk Assessment Section: new accounts transacting heavily in their first
    # 30 days warrant enhanced scrutiny (classic placement risk indicator).
    new_account_window_days: int = int(os.getenv("NEW_ACCOUNT_WINDOW_DAYS", "30"))

    # Transaction count ceiling for new accounts within new_account_window_days.
    new_account_txn_threshold: int = int(os.getenv("NEW_ACCOUNT_TXN_THRESHOLD", "10"))

    # NGN 5M volume ceiling for new accounts within new_account_window_days.
    new_account_amount_threshold: float = float(os.getenv("NEW_ACCOUNT_AMOUNT_THRESHOLD", "5000000"))

    # Velocity burst multiplier: flag if 24h transaction count exceeds this multiple
    # of the customer's 90-day average daily rate. 3x is statistically anomalous
    # for legitimate accounts and aligns with CBN Risk Assessment Section guidance.
    velocity_burst_multiplier: float = float(os.getenv("VELOCITY_BURST_MULTIPLIER", "3.0"))

    # FATF Recommendation 16: flag accounts where cross-border transactions to high-risk
    # jurisdictions exceed this fraction of monthly transaction volume (30%).
    cross_border_concentration_pct: float = float(os.getenv("CROSS_BORDER_CONCENTRATION_PCT", "0.30"))

    # Window for round-tripping detection: funds that leave and return to the same
    # account via intermediaries within this many days are flagged as potential
    # layering. 30 days covers common invoice-fraud and trade-based ML cycles.
    round_trip_window_days: int = int(os.getenv("ROUND_TRIP_WINDOW_DAYS", "30"))

    # SLA for executive escalations in hours. Default 24h aligns with NFIU STR
    # filing deadline (Money Laundering Prevention and Prohibition Act 2022, Section 6).
    escalation_sla_hours: int = int(os.getenv("ESCALATION_SLA_HOURS", "24"))


@dataclass
class RiskTierConfig:
    """Transaction-amount-based risk tier thresholds for customer classification.

    These thresholds drive the KYC verifier's initial risk tier assignment
    when no prior risk history exists. They are calibrated to Nigerian income
    and business size norms so that SME activity is not over-flagged.

    low_max (NGN 1M): Retail-scale transactions. Standard monitoring applies.
    medium_max (NGN 5M): SME-scale. Enhanced monitoring, standard KYC required.
    high_max (NGN 50M): Large business. Enhanced due diligence required.
    above high_max → critical: HNWI, institutional. Full EDD required.
    """
    # NGN thresholds for tier assignment based on transaction amounts
    low_max: float = 1_000_000       # below 1M -> low
    medium_max: float = 5_000_000    # 1M to 5M -> medium
    high_max: float = 50_000_000     # 5M to 50M -> high
    # above 50M -> critical (very_high in customer risk tier language)


@dataclass
class SlaConfig:
    """SLA response time requirements for compliance investigations.

    These SLA hours are the time window within which a case must be resolved
    after creation. They are tiered by priority to reflect CBN's expectation
    that critical investigations (e.g., terrorism financing links) receive
    immediate attention.

    str_filing_deadline_hours (24h): NFIU requires that Suspicious Transaction
    Reports are filed within 24 hours of the compliance officer's initial
    determination of suspicion. This is a hard statutory deadline under the
    Money Laundering (Prevention and Prohibition) Act 2022.
    """
    # Hours to resolve a case by priority level
    critical_hours: int = 4    # Must resolve within 4 hours (terrorism, sanctions)
    high_hours: int = 24       # Must resolve within 24 hours (structuring, layering)
    medium_hours: int = 72     # Must resolve within 72 hours (standard AML)
    low_hours: int = 168       # Must resolve within 1 week (routine monitoring)

    # NFIU statutory STR filing deadline: 24 hours from initial detection
    str_filing_deadline_hours: int = 24


@dataclass
class GovernanceRules:
    """Top-level governance policy combining all sub-configurations.

    This is the single object consumed by agents and the governance engine.
    The RULES singleton (below) is instantiated once at module load and
    shared across all agents to ensure consistent policy application.
    """
    thresholds: ThresholdConfig = field(default_factory=ThresholdConfig)
    risk_tiers: RiskTierConfig = field(default_factory=RiskTierConfig)
    sla: SlaConfig = field(default_factory=SlaConfig)

    # Sanctions match types that REQUIRE human review before action is taken.
    # 'strong' and 'partial' matches have enough uncertainty that a human
    # should confirm before a block is executed, to avoid false positives.
    sanctions_human_review_types: list[str] = field(
        default_factory=lambda: ["strong", "partial"]
    )

    # Agent outputs below this confidence score are routed to human review
    # rather than acting automatically. Mirrors ThresholdConfig.confidence_gate_threshold
    # but stored here for governance engine access without deep dict traversal.
    confidence_gate: float = float(os.getenv("CONFIDENCE_GATE_THRESHOLD", "0.7"))

    # Risk levels that MUST trigger SAR assessment.
    # 'critical' is the only automatic trigger; 'high' prompts analyst review
    # who may then initiate a SAR. Only 'critical' is mandatory.
    mandatory_sar_risk_levels: list[str] = field(
        default_factory=lambda: ["critical"]
    )

    # Roles permitted to approve SARs for NFIU filing.
    # Only senior compliance roles can approve SARs — this prevents junior
    # analysts from filing without oversight (CBN MLRO requirement).
    sar_approver_roles: list[str] = field(
        default_factory=lambda: ["compliance_officer", "senior_compliance_officer", "mlro"]
    )

    # Roles permitted to confirm a sanctions block.
    # Sanctions blocks have major customer impact; senior officer confirmation
    # ensures accuracy before an account is frozen.
    sanctions_block_confirmer_roles: list[str] = field(
        default_factory=lambda: ["senior_compliance_officer", "mlro"]
    )

    # Roles permitted to close a high-risk case.
    # Prevents premature case closure by junior staff on sensitive investigations.
    high_risk_case_close_roles: list[str] = field(
        default_factory=lambda: ["senior_compliance_officer", "mlro", "compliance_officer"]
    )


# Module-level singleton. All agents import RULES directly rather than
# instantiating GovernanceRules themselves — this guarantees that all agents
# use the same policy object and that env-var overrides apply uniformly.
RULES = GovernanceRules()


def get_risk_tier_for_amount(amount: float) -> str:
    """Map a transaction amount to a risk tier using the configured thresholds.

    Used by the pattern analyzer and KYC verifier to assign an initial risk
    tier when only transaction amount information is available (e.g., during
    onboarding before full KYC is complete).

    Returns: 'low' | 'medium' | 'high' | 'critical'
    """
    cfg = RULES.risk_tiers
    if amount < cfg.low_max:
        return "low"
    elif amount < cfg.medium_max:
        return "medium"
    elif amount < cfg.high_max:
        return "high"
    return "critical"


def get_sla_hours(priority: str) -> int:
    """Return the SLA resolution window in hours for a given case priority.

    Falls back to medium_hours for unrecognised priority strings to ensure
    all cases have a defined SLA even if an unknown priority value is passed.
    """
    cfg = RULES.sla
    return {
        "critical": cfg.critical_hours,
        "high": cfg.high_hours,
        "medium": cfg.medium_hours,
        "low": cfg.low_hours,
    }.get(priority, cfg.medium_hours)
