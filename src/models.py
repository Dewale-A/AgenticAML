"""
Pydantic models for AgenticAML.

These models serve three purposes:
1. FastAPI request/response validation and serialisation.
2. Agent result contracts — each agent returns a typed result model so
   downstream agents and the governance engine receive structured data.
3. Documentation — Pydantic models auto-generate OpenAPI schemas.

All monetary amounts are in NGN. All timestamps are in WAT (UTC+1).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums as literals for simplicity
# ---------------------------------------------------------------------------

# Using plain strings rather than Python Enum classes keeps the models simple
# and avoids serialisation friction with FastAPI's JSON responses. The valid
# values are documented here for reference.

RiskTier = str          # low | medium | high | very_high
KycStatus = str         # pending | verified | incomplete | failed | requires_update
AlertStatus = str       # open | investigating | resolved | false_positive
AlertSeverity = str     # low | medium | high | critical
SarStatus = str         # draft | pending_approval | approved | rejected | filed
CaseStatus = str        # open | investigating | pending_review | closed
MatchType = str         # exact | strong | partial | weak
RecommendedAction = str # clear | review | block


# ---------------------------------------------------------------------------
# Customer models
# ---------------------------------------------------------------------------

class CustomerBase(BaseModel):
    """Shared customer fields used by both create and read models.

    BVN and NIN are Optional because corporate accounts may not have NINs,
    and data may arrive before identity documents are collected. KYC status
    tracks completeness separately from the presence of these fields.
    """
    name: str
    # BVN (Bank Verification Number) — CBN-mandated 11-digit biometric ID
    bvn: Optional[str] = None
    # NIN (National Identity Number) — NIMC-issued 11-digit national ID
    nin: Optional[str] = None
    date_of_birth: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    # individual | corporate — determines required KYC fields and monitoring rules
    account_type: str = "individual"
    risk_tier: RiskTier = "low"
    kyc_status: KycStatus = "pending"
    # 0 = not PEP, 1 = PEP. PEPs require enhanced due diligence per FATF R.12
    pep_status: int = 0


class CustomerCreate(CustomerBase):
    """Request body for creating a new customer. No extra fields needed."""
    pass


class Customer(CustomerBase):
    """Full customer record returned from the database, including system fields."""
    id: str
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class RiskTierUpdate(BaseModel):
    """Request body for a risk-tier change.

    Requires an approved_by field because governance rules prohibit
    automatic risk-tier downgrades — a human must justify the change.
    This is logged to the audit trail as a human decision event.
    """
    risk_tier: RiskTier
    rationale: str
    approved_by: str


# ---------------------------------------------------------------------------
# Transaction models
# ---------------------------------------------------------------------------

class TransactionBase(BaseModel):
    """Core transaction fields.

    amount uses Field(gt=0) to enforce that zero and negative values are
    rejected at the API boundary — there is no legitimate AML scenario
    for a zero-value transaction.
    """
    customer_id: str
    counterparty_name: Optional[str] = None
    counterparty_account: Optional[str] = None
    # gt=0 enforces positive amounts at the Pydantic validation layer
    amount: float = Field(gt=0)
    currency: str = "NGN"
    # transfer | cash_deposit | cash_withdrawal | international_wire | mobile_money | pos_payment
    transaction_type: Optional[str] = None
    # branch | mobile_app | internet_banking | atm | pos | ussd
    channel: Optional[str] = None
    # inbound | outbound — direction relative to the monitored account
    direction: Optional[str] = None
    # ISO country code or city/country string used for geo-risk checks
    geo_location: Optional[str] = None
    timestamp: str


class TransactionCreate(TransactionBase):
    """Request body when submitting a transaction for screening."""
    pass


class Transaction(TransactionBase):
    """Full transaction record returned from the database."""
    id: str
    # pending | cleared | flagged — set by TransactionMonitorAgent
    status: str
    # 0.0–1.0 composite risk score; None until the monitor agent runs
    risk_score: Optional[float] = None
    created_at: str

    class Config:
        from_attributes = True


class BatchScreenRequest(BaseModel):
    """Request body for batch transaction screening endpoint."""
    transactions: List[TransactionCreate]


# ---------------------------------------------------------------------------
# Alert models
# ---------------------------------------------------------------------------

class AlertBase(BaseModel):
    """Core alert fields. agent_source and alert_type are required because
    every alert must be attributable to a specific agent and carry a
    machine-readable type for analytics.
    """
    transaction_id: Optional[str] = None
    customer_id: Optional[str] = None
    # Which agent raised the alert (e.g., transaction_monitor_agent)
    agent_source: str
    # Machine-readable type (e.g., STRUCTURING, SANCTIONS_MATCH, KYC_INCOMPLETE)
    alert_type: str
    severity: AlertSeverity = "medium"
    description: Optional[str] = None
    # Agent's self-reported confidence (0.0–1.0); used by governance gate
    confidence: Optional[float] = None
    status: AlertStatus = "open"
    assigned_to: Optional[str] = None


class AlertCreate(AlertBase):
    """Request body for manually creating an alert."""
    pass


class Alert(AlertBase):
    """Full alert record returned from the database."""
    id: str
    created_at: str
    # Populated when the alert is resolved or marked as false_positive
    resolved_at: Optional[str] = None

    class Config:
        from_attributes = True


class AlertAssign(BaseModel):
    """Request body for assigning an alert to an analyst."""
    assigned_to: str


class AlertResolve(BaseModel):
    """Request body for resolving an alert.

    The resolution field defaults to 'resolved' but can be set to
    'false_positive' to support false positive rate tracking.
    """
    rationale: str
    resolution: str = "resolved"


# ---------------------------------------------------------------------------
# Sanctions models
# ---------------------------------------------------------------------------

class SanctionsScreenRequest(BaseModel):
    """Input to the sanctions screening endpoint.

    Aliases allow screening of known name variants (e.g., Arabic transliterations).
    The date_of_birth field is used as a secondary confirmation signal for
    strong matches to reduce false positives.
    """
    name: str
    aliases: Optional[List[str]] = None
    date_of_birth: Optional[str] = None
    nationality: Optional[str] = None
    address: Optional[str] = None
    customer_id: Optional[str] = None
    transaction_id: Optional[str] = None


class SanctionsMatchResult(BaseModel):
    """A single hit from one sanctions list.

    match_score is the raw fuzzy similarity (0.0–1.0).
    match_type is the categorical interpretation (exact/strong/partial/weak).
    action_taken is the agent's recommended action for this specific match.
    """
    list_name: str
    matched_entity: str
    match_type: MatchType
    match_score: float
    # clear | review | block — exact/strong defaults to block per CBN mandate
    action_taken: RecommendedAction
    # Extra fields from the list entry (nationality, DOB, reason)
    details: Optional[Dict[str, Any]] = None


class SanctionsScreenResult(BaseModel):
    """Aggregated result of screening a name against all lists.

    overall_recommendation is the worst-case action across all individual
    matches ('block' takes precedence over 'review' over 'clear').
    """
    name_screened: str
    overall_recommendation: RecommendedAction
    matches: List[SanctionsMatchResult]
    screened_at: str


class SanctionsMatchReview(BaseModel):
    """Request body for a human reviewing a sanctions match.

    decision is 'approve' (confirm the block) or 'dismiss' (false positive).
    This is a mandatory human-in-the-loop step for all block actions.
    """
    decision: str  # approve | dismiss
    reviewed_by: str
    rationale: str


# ---------------------------------------------------------------------------
# SAR models
# ---------------------------------------------------------------------------

class SarBase(BaseModel):
    """Core SAR fields.

    drafted_by defaults to 'sar_generator_agent' so it's always clear
    that a draft was machine-generated, not human-authored.
    requires_human_approval is always True in SarGeneratorResult — it is
    included here as a design reminder, not a runtime toggle.
    """
    alert_id: Optional[str] = None
    customer_id: Optional[str] = None
    # AI-generated draft; human reviewer may edit before filing
    draft_narrative: Optional[str] = None
    # Approved human-edited version; None until approved
    final_narrative: Optional[str] = None
    # AML typology (structuring_smurfing, pep_corruption, layering, etc.)
    typology: Optional[str] = None
    # routine | urgent | critical — maps to NFIU filing priority
    priority: str = "routine"
    status: SarStatus = "draft"
    drafted_by: str = "sar_generator_agent"


class Sar(SarBase):
    """Full SAR record returned from the database."""
    id: str
    # Compliance officer who approved this SAR; None until approval step
    approved_by: Optional[str] = None
    approval_rationale: Optional[str] = None
    # Populated when status changes to 'filed'
    filed_at: Optional[str] = None
    # NFIU-issued reference number assigned upon filing
    nfiu_reference: Optional[str] = None
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class SarApprove(BaseModel):
    """Request body for the SAR approval endpoint.

    approved_by must identify a human compliance officer — this field is
    logged to the audit trail as evidence of CBN-mandated human review.
    """
    approved_by: str
    rationale: str
    # Optionally replace the draft narrative with a human-edited version
    final_narrative: Optional[str] = None


class SarReject(BaseModel):
    """Request body for rejecting a SAR draft.

    A rejection with rationale is as important as an approval — it shows
    the regulator that the compliance team exercised judgement and found
    the AI's suspicion to be unfounded.
    """
    rejected_by: str
    rationale: str


class SarFile(BaseModel):
    """Request body for filing an approved SAR with NFIU.

    Can optionally supply an NFIU reference if the institution has a
    pre-assigned reference. Otherwise one is auto-generated.
    """
    filed_by: str
    nfiu_reference: Optional[str] = None


# ---------------------------------------------------------------------------
# Case models
# ---------------------------------------------------------------------------

class CaseBase(BaseModel):
    """Core investigation case fields."""
    alert_id: Optional[str] = None
    customer_id: Optional[str] = None
    # sanctions_investigation | kyc_failure | structuring_investigation | etc.
    case_type: Optional[str] = None
    priority: str = "medium"
    status: CaseStatus = "open"
    assigned_to: Optional[str] = None
    description: Optional[str] = None


class Case(CaseBase):
    """Full case record returned from the database."""
    id: str
    # Free-text resolution recorded when case is closed; required for high-risk cases
    resolution: Optional[str] = None
    created_at: str
    updated_at: str
    closed_at: Optional[str] = None

    class Config:
        from_attributes = True


class CaseStatusUpdate(BaseModel):
    """Request body for updating a case status.

    Governance rule: closing a high/critical case without a resolution
    statement is blocked at the API layer.
    """
    status: CaseStatus
    resolution: Optional[str] = None
    updated_by: str


class CaseAssign(BaseModel):
    """Request body for reassigning a case.

    assigned_by is captured so the reassignment is attributable for
    audit purposes (who made the workload routing decision).
    """
    assigned_to: str
    assigned_by: str


# ---------------------------------------------------------------------------
# Agent result models
# ---------------------------------------------------------------------------

class TriggeredRule(BaseModel):
    """A single AML rule that fired during transaction monitoring.

    threshold and observed are included so compliance analysts can see
    exactly how far above (or below) the limit the transaction was.
    """
    rule: str
    description: str
    threshold: Optional[float] = None
    observed: Optional[float] = None


class TransactionMonitorResult(BaseModel):
    """Output of TransactionMonitorAgent.screen().

    risk_score and confidence are separate:
    - risk_score: how suspicious the transaction is (0.0–1.0)
    - confidence: how certain the agent is about its own assessment

    audit_logged=True signals that the result has been committed to the
    immutable audit trail before being returned.
    """
    transaction_id: str
    customer_id: str
    # Composite risk score across all triggered rules and amount multipliers
    risk_score: float
    # Agent certainty about the risk_score (based on number of rules triggered)
    confidence: float
    flagged: bool
    triggered_rules: List[TriggeredRule]
    status: str  # flagged | cleared
    audit_logged: bool = True


class KycVerifierResult(BaseModel):
    """Output of KycVerifierAgent.verify().

    missing_fields is a list of required field names that are absent,
    allowing the customer service team to request specific documents.
    """
    customer_id: str
    kyc_status: KycStatus
    risk_tier: RiskTier
    # Fields that are required but absent from the customer record
    missing_fields: List[str]
    verification_confidence: float
    pep_detected: bool
    audit_logged: bool = True


class PatternMatch(BaseModel):
    """A single behavioural pattern detected by PatternAnalyzerAgent.

    typology is the FATF/FATF-GIABA money laundering category (e.g.,
    structuring_smurfing, layering, pep_corruption) — used to populate
    the SAR typology field.

    evidence is a list of human-readable strings linking the pattern to
    specific transactions — this forms the evidence section of the SAR.
    """
    pattern_name: str
    description: str
    # 0.0–1.0 confidence that this pattern reflects genuine ML activity
    confidence: float
    # FATF typology category for SAR classification
    typology: str
    evidence: List[str]


class PatternAnalyzerResult(BaseModel):
    """Output of PatternAnalyzerAgent.analyze().

    overall_risk is the worst-case risk level across all detected patterns,
    used by the governance engine to trigger escalation and SAR generation.
    """
    customer_id: str
    # low | medium | high | critical — determines downstream actions
    overall_risk: str
    patterns_detected: List[PatternMatch]
    # Human-readable recommended actions for the compliance analyst
    recommended_actions: List[str]
    # Summary of evidence combining transaction counts, patterns, and LLM analysis
    supporting_evidence: str
    audit_logged: bool = True


class SarGeneratorResult(BaseModel):
    """Output of SarGeneratorAgent.generate().

    requires_human_approval is always True — this field exists to make the
    governance constraint explicit in the API response so callers cannot
    accidentally treat the draft as ready to file.
    """
    sar_id: str
    customer_id: str
    alert_id: Optional[str]
    draft_narrative: str
    typology: str
    priority: str
    status: str = "draft"
    # Always True — no code path should set this to False
    requires_human_approval: bool = True
    audit_logged: bool = True


class CaseManagerResult(BaseModel):
    """Output of CaseManagerAgent.create_and_assign().

    sla_deadline is an ISO timestamp calculated from the priority level and
    SlaConfig. Compliance supervisors can filter by this field to identify
    at-risk cases.
    """
    case_id: str
    alert_id: Optional[str]
    customer_id: str
    case_type: str
    priority: str
    assigned_to: str
    status: str
    # ISO timestamp by which the case should be resolved per SLA policy
    sla_deadline: Optional[str]
    audit_logged: bool = True


# ---------------------------------------------------------------------------
# Governance models
# ---------------------------------------------------------------------------

class GovernanceDecision(BaseModel):
    """Result of a single governance gate check.

    passed=False means the gate blocked the action (e.g., sanctions block).
    requires_human=True means human review is required before proceeding
    (e.g., confidence gate, human-in-the-loop for SAR).
    action_taken records what the governance engine did as a result.
    """
    passed: bool
    gate: str
    reason: str
    requires_human: bool = False
    # None | escalate_to_human | additional_review | block | escalate_critical | etc.
    action_taken: Optional[str] = None


class GovernanceResult(BaseModel):
    """Aggregated result of all governance gates for one pipeline stage.

    all_passed is False if any gate failed.
    blocked indicates the transaction should be stopped immediately.
    escalated indicates human review is required before proceeding.
    """
    all_passed: bool
    decisions: List[GovernanceDecision]
    # True if any gate set requires_human=True
    escalated: bool = False
    # True if any gate set action_taken='block' (sanctions match)
    blocked: bool = False


# ---------------------------------------------------------------------------
# Pipeline result
# ---------------------------------------------------------------------------

class PipelineResult(BaseModel):
    """Full output of the 6-agent AML pipeline for a single transaction.

    Agents 4–6 (pattern_result, sar_result, case_result) are Optional because
    they are only invoked when the transaction is flagged or the customer is
    high-risk. Cleared low-risk transactions skip these expensive stages.

    governance_decisions is a list of GovernanceResult, one per agent stage
    that was executed — provides a full decision chain for audit purposes.
    """
    transaction_id: str
    customer_id: str
    monitor_result: TransactionMonitorResult
    kyc_result: KycVerifierResult
    sanctions_result: SanctionsScreenResult
    # None if transaction was cleared and customer is low-risk
    pattern_result: Optional[PatternAnalyzerResult] = None
    # None if risk score and pattern analysis did not warrant a SAR
    sar_result: Optional[SarGeneratorResult] = None
    # None if neither flagged nor SAR-generating
    case_result: Optional[CaseManagerResult] = None
    governance_decisions: List[GovernanceResult]
    # cleared | flagged | blocked | escalated
    final_status: str
    processing_time_ms: Optional[float] = None


# ---------------------------------------------------------------------------
# Model validation
# ---------------------------------------------------------------------------

class ModelValidationCreate(BaseModel):
    """Request body for recording a CBN annual model validation.

    CBN BSD/DIR/PUB/LAB/019/002 requires independent annual validation of
    all AI models used in AML compliance. This model captures the metrics
    and reviewer details required by the standard.
    """
    model_name: str
    # annual_cbn_validation | quarterly_review | ad_hoc
    validation_type: Optional[str] = None
    accuracy: Optional[float] = None
    # Concept drift score — measures how much model behaviour has shifted
    drift_score: Optional[float] = None
    # Demographic bias score — detects discriminatory patterns in model output
    bias_score: Optional[float] = None
    # Cross-segment fairness score
    fairness_score: Optional[float] = None
    # Must be independent of the model's development team per CBN guidelines
    human_reviewer: Optional[str] = None
    findings: Optional[str] = None


class ModelValidation(ModelValidationCreate):
    """Full model validation record returned from the database."""
    id: str
    validated_at: str

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Report models
# ---------------------------------------------------------------------------

class DailyReport(BaseModel):
    """Structure for the daily compliance summary report.

    Generated by CaseManagerAgent.generate_daily_report(). Provides a
    snapshot for the Compliance Officer's morning review and for automated
    CBN regulatory reporting.
    """
    report_date: str
    total_transactions: int
    flagged_transactions: int
    cleared_transactions: int
    alerts_generated: int
    alerts_resolved: int
    sars_drafted: int
    sars_filed: int
    sanctions_blocks: int
    open_cases: int
    # List of high-risk transaction summaries for the morning escalation review
    high_risk_transactions: List[Dict[str, Any]] = []


class AlertAnalytics(BaseModel):
    """Alert analytics payload for the compliance dashboard.

    false_positive_rate is false_positives / total_resolved — a key KPI
    for measuring the efficiency of the AML detection system. A high
    false positive rate wastes analyst time; a low rate may indicate
    under-detection.
    """
    total_alerts: int
    # Count of alerts by severity level
    by_severity: Dict[str, int]
    # Count of alerts by agent source — shows which agents are most active
    by_agent: Dict[str, int]
    # Count of alerts by current status — shows triage queue health
    by_status: Dict[str, int]
    # Average hours from alert creation to resolution
    avg_resolution_hours: Optional[float]
    # false_positives / total_resolved — system precision metric
    false_positive_rate: Optional[float]
    # Most frequent alert types — used to identify patterns in ML activity
    top_alert_types: List[Dict[str, Any]]
