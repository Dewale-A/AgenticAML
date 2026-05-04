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

from typing import Any

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
    bvn: str | None = None
    # NIN (National Identity Number) — NIMC-issued 11-digit national ID
    nin: str | None = None
    date_of_birth: str | None = None
    phone: str | None = None
    address: str | None = None
    # individual | corporate — determines required KYC fields and monitoring rules
    account_type: str = "individual"
    risk_tier: RiskTier = "low"
    kyc_status: KycStatus = "pending"
    # 0 = not PEP, 1 = PEP. PEPs require enhanced due diligence per FATF R.12
    pep_status: int = 0


class CustomerCreate(CustomerBase):
    """Request body for creating a new customer. No extra fields needed."""


class Customer(CustomerBase):
    """Full customer record returned from the database, including system fields.

    Dormancy fields (last_transaction_at, is_dormant, dormant_since) are populated
    by the TransactionMonitorAgent as transactions are processed.
    onboarding_status tracks the Agent 0 pre-screening outcome.
    """
    id: str
    # WAT timestamp of the most recent transaction (None if no transactions yet)
    last_transaction_at: str | None = None
    # True if account is currently classified as dormant per CBN AML/CFT Section 4
    is_dormant: int = 0
    # WAT timestamp when dormancy classification first applied
    dormant_since: str | None = None
    # approved | pending_review | pending_escalation | blocked | None (legacy customers)
    onboarding_status: str | None = None
    nationality: str | None = None
    registration_source: str | None = None
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
    counterparty_name: str | None = None
    counterparty_account: str | None = None
    # gt=0 enforces positive amounts at the Pydantic validation layer
    amount: float = Field(gt=0)
    currency: str = "NGN"
    # transfer | cash_deposit | cash_withdrawal | international_wire | mobile_money | pos_payment
    transaction_type: str | None = None
    # branch | mobile_app | internet_banking | atm | pos | ussd
    channel: str | None = None
    # inbound | outbound — direction relative to the monitored account
    direction: str | None = None
    # ISO country code or city/country string used for geo-risk checks
    geo_location: str | None = None
    timestamp: str


class TransactionCreate(TransactionBase):
    """Request body when submitting a transaction for screening."""


class Transaction(TransactionBase):
    """Full transaction record returned from the database."""
    id: str
    # pending | cleared | flagged — set by TransactionMonitorAgent
    status: str
    # 0.0-1.0 composite risk score; None until the monitor agent runs
    risk_score: float | None = None
    created_at: str

    class Config:
        from_attributes = True


class BatchScreenRequest(BaseModel):
    """Request body for batch transaction screening endpoint."""
    transactions: list[TransactionCreate]


# ---------------------------------------------------------------------------
# Alert models
# ---------------------------------------------------------------------------

class AlertBase(BaseModel):
    """Core alert fields. agent_source and alert_type are required because
    every alert must be attributable to a specific agent and carry a
    machine-readable type for analytics.
    """
    transaction_id: str | None = None
    customer_id: str | None = None
    # Which agent raised the alert (e.g., transaction_monitor_agent)
    agent_source: str
    # Machine-readable type (e.g., STRUCTURING, SANCTIONS_MATCH, KYC_INCOMPLETE)
    alert_type: str
    severity: AlertSeverity = "medium"
    description: str | None = None
    # Agent's self-reported confidence (0.0-1.0); used by governance gate
    confidence: float | None = None
    status: AlertStatus = "open"
    assigned_to: str | None = None


class AlertCreate(AlertBase):
    """Request body for manually creating an alert."""


class Alert(AlertBase):
    """Full alert record returned from the database."""
    id: str
    created_at: str
    # Populated when the alert is resolved or marked as false_positive
    resolved_at: str | None = None

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
    aliases: list[str] | None = None
    date_of_birth: str | None = None
    nationality: str | None = None
    address: str | None = None
    customer_id: str | None = None
    transaction_id: str | None = None


class SanctionsMatchResult(BaseModel):
    """A single hit from one sanctions list.

    match_score is the raw fuzzy similarity (0.0-1.0).
    match_type is the categorical interpretation (exact/strong/partial/weak).
    action_taken is the agent's recommended action for this specific match.
    match_category classifies the type of watchlist hit for UI sub-filtering.
    """
    list_name: str
    matched_entity: str
    match_type: MatchType
    match_score: float
    # clear | review | block — exact/strong defaults to block per CBN mandate
    action_taken: RecommendedAction
    # sanctions | pep | adverse_media — drives Watchlist Screening tab sub-filter
    match_category: str = "sanctions"
    # Extra fields from the list entry (nationality, DOB, reason)
    details: dict[str, Any] | None = None


class SanctionsScreenResult(BaseModel):
    """Aggregated result of screening a name against all lists.

    overall_recommendation is the worst-case action across all individual
    matches ('block' takes precedence over 'review' over 'clear').
    """
    name_screened: str
    overall_recommendation: RecommendedAction
    matches: list[SanctionsMatchResult]
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
    alert_id: str | None = None
    customer_id: str | None = None
    # AI-generated draft; human reviewer may edit before filing
    draft_narrative: str | None = None
    # Approved human-edited version; None until approved
    final_narrative: str | None = None
    # AML typology (structuring_smurfing, pep_corruption, layering, etc.)
    typology: str | None = None
    # routine | urgent | critical — maps to NFIU filing priority
    priority: str = "routine"
    status: SarStatus = "draft"
    drafted_by: str = "sar_generator_agent"


class Sar(SarBase):
    """Full SAR record returned from the database."""
    id: str
    # Compliance officer who approved this SAR; None until approval step
    approved_by: str | None = None
    approval_rationale: str | None = None
    # Populated when status changes to 'filed'
    filed_at: str | None = None
    # NFIU-issued reference number assigned upon filing
    nfiu_reference: str | None = None
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
    final_narrative: str | None = None


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
    nfiu_reference: str | None = None


# ---------------------------------------------------------------------------
# Case models
# ---------------------------------------------------------------------------

class CaseBase(BaseModel):
    """Core investigation case fields."""
    alert_id: str | None = None
    customer_id: str | None = None
    # sanctions_investigation | kyc_failure | structuring_investigation | etc.
    case_type: str | None = None
    priority: str = "medium"
    status: CaseStatus = "open"
    assigned_to: str | None = None
    description: str | None = None


class Case(CaseBase):
    """Full case record returned from the database."""
    id: str
    # Free-text resolution recorded when case is closed; required for high-risk cases
    resolution: str | None = None
    created_at: str
    updated_at: str
    closed_at: str | None = None

    class Config:
        from_attributes = True


class CaseStatusUpdate(BaseModel):
    """Request body for updating a case status.

    Governance rule: closing a high/critical case without a resolution
    statement is blocked at the API layer.
    """
    status: CaseStatus
    resolution: str | None = None
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
    threshold: float | None = None
    observed: float | None = None


class TransactionMonitorResult(BaseModel):
    """Output of TransactionMonitorAgent.screen().

    risk_score and confidence are separate:
    - risk_score: how suspicious the transaction is (0.0-1.0)
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
    triggered_rules: list[TriggeredRule]
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
    missing_fields: list[str]
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
    # 0.0-1.0 confidence that this pattern reflects genuine ML activity
    confidence: float
    # FATF typology category for SAR classification
    typology: str
    evidence: list[str]


class PatternAnalyzerResult(BaseModel):
    """Output of PatternAnalyzerAgent.analyze().

    overall_risk is the worst-case risk level across all detected patterns,
    used by the governance engine to trigger escalation and SAR generation.
    """
    customer_id: str
    # low | medium | high | critical — determines downstream actions
    overall_risk: str
    patterns_detected: list[PatternMatch]
    # Human-readable recommended actions for the compliance analyst
    recommended_actions: list[str]
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
    alert_id: str | None
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
    alert_id: str | None
    customer_id: str
    case_type: str
    priority: str
    assigned_to: str
    status: str
    # ISO timestamp by which the case should be resolved per SLA policy
    sla_deadline: str | None
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
    action_taken: str | None = None


class GovernanceResult(BaseModel):
    """Aggregated result of all governance gates for one pipeline stage.

    all_passed is False if any gate failed.
    blocked indicates the transaction should be stopped immediately.
    escalated indicates human review is required before proceeding.
    """
    all_passed: bool
    decisions: list[GovernanceDecision]
    # True if any gate set requires_human=True
    escalated: bool = False
    # True if any gate set action_taken='block' (sanctions match)
    blocked: bool = False


# ---------------------------------------------------------------------------
# Pipeline result
# ---------------------------------------------------------------------------

class PipelineResult(BaseModel):
    """Full output of the 6-agent AML pipeline for a single transaction.

    Agents 4-6 (pattern_result, sar_result, case_result) are Optional because
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
    pattern_result: PatternAnalyzerResult | None = None
    # None if risk score and pattern analysis did not warrant a SAR
    sar_result: SarGeneratorResult | None = None
    # None if neither flagged nor SAR-generating
    case_result: CaseManagerResult | None = None
    governance_decisions: list[GovernanceResult]
    # cleared | flagged | blocked | escalated
    final_status: str
    processing_time_ms: float | None = None


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
    validation_type: str | None = None
    accuracy: float | None = None
    # Concept drift score — measures how much model behaviour has shifted
    drift_score: float | None = None
    # Demographic bias score — detects discriminatory patterns in model output
    bias_score: float | None = None
    # Cross-segment fairness score
    fairness_score: float | None = None
    # Must be independent of the model's development team per CBN guidelines
    human_reviewer: str | None = None
    findings: str | None = None


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
    high_risk_transactions: list[dict[str, Any]] = []


class AlertAnalytics(BaseModel):
    """Alert analytics payload for the compliance dashboard.

    false_positive_rate is false_positives / total_resolved — a key KPI
    for measuring the efficiency of the AML detection system. A high
    false positive rate wastes analyst time; a low rate may indicate
    under-detection.
    """
    total_alerts: int
    # Count of alerts by severity level
    by_severity: dict[str, int]
    # Count of alerts by agent source — shows which agents are most active
    by_agent: dict[str, int]
    # Count of alerts by current status — shows triage queue health
    by_status: dict[str, int]
    # Average hours from alert creation to resolution
    avg_resolution_hours: float | None
    # false_positives / total_resolved — system precision metric
    false_positive_rate: float | None
    # Most frequent alert types — used to identify patterns in ML activity
    top_alert_types: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Onboarding models (Agent 0: OnboardingScreenerAgent)
# ---------------------------------------------------------------------------

class OnboardingRequest(BaseModel):
    """Request body for new customer onboarding pre-screening.

    Agent 0 screens this data against all watchlists BEFORE the customer
    is activated in the system. This gates entry into the AML pipeline per
    CBN KYC Requirements for customer acceptance.

    aliases is a list of known alternative names (maiden name, trade name)
    used to broaden the screening coverage and reduce false negatives from
    name variations.
    """
    name: str
    bvn: str | None = None
    nin: str | None = None
    date_of_birth: str | None = None
    nationality: str | None = None
    phone: str | None = None
    address: str | None = None
    # individual | corporate
    account_type: str = "individual"
    # Known aliases or alternative spellings — screened in addition to the primary name
    aliases: list[str] | None = None
    # branch | online | mobile | agent — affects risk weighting
    registration_source: str | None = None


class OnboardingResult(BaseModel):
    """Result of the Agent 0 onboarding pre-screening pipeline.

    decision values:
    - approved: no watchlist matches, customer can be onboarded at the assigned risk_tier
    - pending_review: weak/partial match requiring analyst review; account activated
      with enhanced monitoring pending resolution
    - pending_escalation: PEP match or adverse media requiring C-suite/MLRO approval
      before activation; account held in queue
    - blocked: confirmed sanctions match; account registration rejected per CBN mandate

    escalation_id is populated when decision is 'pending_escalation', linking this
    onboarding outcome to an escalation record for approver tracking.
    """
    customer_id: str | None = None
    name: str
    decision: str  # approved | pending_review | pending_escalation | blocked
    risk_tier: str = "low"
    # Human-readable explanation of the decision (why it was approved/blocked/escalated)
    decision_reason: str
    # Watchlist matches found during screening (may be empty for approved)
    screening_matches: list[dict[str, Any]] = []
    # ID of the escalation record created if decision is 'pending_escalation'
    escalation_id: str | None = None
    screened_at: str
    audit_logged: bool = True


class OnboardingApprove(BaseModel):
    """Request body for approving a pending_escalation onboarding decision.

    CBN requires documented C-suite or MLRO approval before onboarding a customer
    with a PEP or adverse media match. rationale is mandatory — the empty string
    is rejected by the API.
    """
    approved_by: str
    rationale: str
    # Optionally override the risk tier to 'high' or 'very_high' for approved PEPs
    override_risk_tier: str | None = None


class OnboardingReject(BaseModel):
    """Request body for rejecting a pending_escalation onboarding decision.

    rejected_by and rationale are both mandatory for audit trail completeness.
    The rejection reason must document why the PEP/adverse media match was
    treated as disqualifying in this instance.
    """
    rejected_by: str
    rationale: str


# ---------------------------------------------------------------------------
# Escalation models
# ---------------------------------------------------------------------------

class EscalationCreate(BaseModel):
    """Input for creating an executive escalation record.

    Escalations are created programmatically by Agent 0 and the governance
    engine, but this model is also used for manually creating escalations
    via the API (e.g., a compliance officer escalating a flagged case to MLRO).
    """
    # 'customer_onboarding' | 'transaction' | 'case'
    entity_type: str
    entity_id: str
    # 'pep_match' | 'adverse_media' | 'high_risk_jurisdiction' | etc.
    escalation_reason: str
    # 'head_of_compliance' | 'c_suite' | 'mlro' | 'senior_analyst'
    required_approver_role: str
    assigned_to: str | None = None
    # JSON-serialisable evidence summary — match details, screening scores
    evidence_summary: str | None = None
    # Override default SLA (24h) for urgent escalations
    sla_hours: int = 24


class Escalation(BaseModel):
    """Full escalation record returned from the database."""
    id: str
    entity_type: str
    entity_id: str
    escalation_reason: str
    required_approver_role: str
    # pending | approved | rejected | expired
    current_status: str
    assigned_to: str | None = None
    decision_rationale: str | None = None
    evidence_summary: str | None = None
    created_at: str
    decided_at: str | None = None
    expires_at: str | None = None
    sla_hours: int = 24

    class Config:
        from_attributes = True


class EscalationDecision(BaseModel):
    """Request body for approving or rejecting an escalation.

    rationale is mandatory — CBN requires a documented justification for
    every senior-level compliance decision, whether approving or rejecting.
    decided_by identifies the human approver for the audit trail.
    """
    decided_by: str
    rationale: str


# ---------------------------------------------------------------------------
# Monitoring models (Phase 3: Continuous Monitoring)
# ---------------------------------------------------------------------------

class MonitoringRunCreate(BaseModel):
    """Input for triggering a manual monitoring run.

    run_type defaults to 'manual' for API-triggered runs.
    list_versions optionally specifies which list versions to use;
    if omitted, the latest downloaded versions are used automatically.
    """
    run_type: str = "manual"
    # Optional metadata passed through to the run record (e.g., triggering user)
    metadata: dict[str, Any] | None = None


class MonitoringRun(BaseModel):
    """Full monitoring run record returned from the database."""
    id: str
    # 'scheduled' | 'manual' | 'list_update'
    run_type: str
    started_at: str
    completed_at: str | None = None
    customers_screened: int = 0
    new_matches: int = 0
    risk_upgrades: int = 0
    # 'running' | 'completed' | 'failed'
    status: str
    metadata: str | None = None

    class Config:
        from_attributes = True


class MonitoringStatus(BaseModel):
    """Current continuous monitoring status for the dashboard widget.

    last_run is the most recently completed run summary.
    next_scheduled_run is the ISO timestamp of the next automatic run
    (None if only manual runs are configured).
    """
    last_run: MonitoringRun | None = None
    total_runs: int = 0
    # Customers currently flagged by the monitoring system (not yet resolved)
    active_monitoring_alerts: int = 0
    next_scheduled_run: str | None = None
    monitoring_enabled: bool = True


class ScreeningList(BaseModel):
    """A screening list version record returned from the database."""
    id: str
    # 'ofac_sdn' | 'un_consolidated' | 'nigerian_domestic' | 'internal_pep'
    list_name: str
    version: str | None = None
    last_updated: str
    entry_count: int = 0
    source_url: str | None = None
    checksum: str | None = None

    class Config:
        from_attributes = True


class OnboardingScreenerResult(BaseModel):
    """Internal result type returned by OnboardingScreenerAgent.screen().

    This is the agent-level result model (not the API-level response).
    It mirrors OnboardingResult but is typed separately so the agent's
    return contract is explicit and not mixed with API serialisation concerns.
    """
    customer_id: str | None
    name: str
    decision: str  # approved | pending_review | pending_escalation | blocked
    risk_tier: str
    decision_reason: str
    screening_matches: list[dict[str, Any]]
    escalation_id: str | None
    screened_at: str
    audit_logged: bool = True
