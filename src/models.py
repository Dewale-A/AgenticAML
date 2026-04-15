"""
Pydantic models for AgenticAML.
All amounts in NGN. All timestamps in WAT (UTC+1).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums as literals for simplicity
# ---------------------------------------------------------------------------

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
    name: str
    bvn: Optional[str] = None
    nin: Optional[str] = None
    date_of_birth: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    account_type: str = "individual"
    risk_tier: RiskTier = "low"
    kyc_status: KycStatus = "pending"
    pep_status: int = 0


class CustomerCreate(CustomerBase):
    pass


class Customer(CustomerBase):
    id: str
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class RiskTierUpdate(BaseModel):
    risk_tier: RiskTier
    rationale: str
    approved_by: str


# ---------------------------------------------------------------------------
# Transaction models
# ---------------------------------------------------------------------------

class TransactionBase(BaseModel):
    customer_id: str
    counterparty_name: Optional[str] = None
    counterparty_account: Optional[str] = None
    amount: float = Field(gt=0)
    currency: str = "NGN"
    transaction_type: Optional[str] = None
    channel: Optional[str] = None
    direction: Optional[str] = None
    geo_location: Optional[str] = None
    timestamp: str


class TransactionCreate(TransactionBase):
    pass


class Transaction(TransactionBase):
    id: str
    status: str
    risk_score: Optional[float] = None
    created_at: str

    class Config:
        from_attributes = True


class BatchScreenRequest(BaseModel):
    transactions: List[TransactionCreate]


# ---------------------------------------------------------------------------
# Alert models
# ---------------------------------------------------------------------------

class AlertBase(BaseModel):
    transaction_id: Optional[str] = None
    customer_id: Optional[str] = None
    agent_source: str
    alert_type: str
    severity: AlertSeverity = "medium"
    description: Optional[str] = None
    confidence: Optional[float] = None
    status: AlertStatus = "open"
    assigned_to: Optional[str] = None


class AlertCreate(AlertBase):
    pass


class Alert(AlertBase):
    id: str
    created_at: str
    resolved_at: Optional[str] = None

    class Config:
        from_attributes = True


class AlertAssign(BaseModel):
    assigned_to: str


class AlertResolve(BaseModel):
    rationale: str
    resolution: str = "resolved"


# ---------------------------------------------------------------------------
# Sanctions models
# ---------------------------------------------------------------------------

class SanctionsScreenRequest(BaseModel):
    name: str
    aliases: Optional[List[str]] = None
    date_of_birth: Optional[str] = None
    nationality: Optional[str] = None
    address: Optional[str] = None
    customer_id: Optional[str] = None
    transaction_id: Optional[str] = None


class SanctionsMatchResult(BaseModel):
    list_name: str
    matched_entity: str
    match_type: MatchType
    match_score: float
    action_taken: RecommendedAction
    details: Optional[Dict[str, Any]] = None


class SanctionsScreenResult(BaseModel):
    name_screened: str
    overall_recommendation: RecommendedAction
    matches: List[SanctionsMatchResult]
    screened_at: str


class SanctionsMatchReview(BaseModel):
    decision: str  # approve | dismiss
    reviewed_by: str
    rationale: str


# ---------------------------------------------------------------------------
# SAR models
# ---------------------------------------------------------------------------

class SarBase(BaseModel):
    alert_id: Optional[str] = None
    customer_id: Optional[str] = None
    draft_narrative: Optional[str] = None
    final_narrative: Optional[str] = None
    typology: Optional[str] = None
    priority: str = "routine"
    status: SarStatus = "draft"
    drafted_by: str = "sar_generator_agent"


class Sar(SarBase):
    id: str
    approved_by: Optional[str] = None
    approval_rationale: Optional[str] = None
    filed_at: Optional[str] = None
    nfiu_reference: Optional[str] = None
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class SarApprove(BaseModel):
    approved_by: str
    rationale: str
    final_narrative: Optional[str] = None


class SarReject(BaseModel):
    rejected_by: str
    rationale: str


class SarFile(BaseModel):
    filed_by: str
    nfiu_reference: Optional[str] = None


# ---------------------------------------------------------------------------
# Case models
# ---------------------------------------------------------------------------

class CaseBase(BaseModel):
    alert_id: Optional[str] = None
    customer_id: Optional[str] = None
    case_type: Optional[str] = None
    priority: str = "medium"
    status: CaseStatus = "open"
    assigned_to: Optional[str] = None
    description: Optional[str] = None


class Case(CaseBase):
    id: str
    resolution: Optional[str] = None
    created_at: str
    updated_at: str
    closed_at: Optional[str] = None

    class Config:
        from_attributes = True


class CaseStatusUpdate(BaseModel):
    status: CaseStatus
    resolution: Optional[str] = None
    updated_by: str


class CaseAssign(BaseModel):
    assigned_to: str
    assigned_by: str


# ---------------------------------------------------------------------------
# Agent result models
# ---------------------------------------------------------------------------

class TriggeredRule(BaseModel):
    rule: str
    description: str
    threshold: Optional[float] = None
    observed: Optional[float] = None


class TransactionMonitorResult(BaseModel):
    transaction_id: str
    customer_id: str
    risk_score: float
    confidence: float
    flagged: bool
    triggered_rules: List[TriggeredRule]
    status: str  # flagged | cleared
    audit_logged: bool = True


class KycVerifierResult(BaseModel):
    customer_id: str
    kyc_status: KycStatus
    risk_tier: RiskTier
    missing_fields: List[str]
    verification_confidence: float
    pep_detected: bool
    audit_logged: bool = True


class PatternMatch(BaseModel):
    pattern_name: str
    description: str
    confidence: float
    typology: str
    evidence: List[str]


class PatternAnalyzerResult(BaseModel):
    customer_id: str
    overall_risk: str  # low | medium | high | critical
    patterns_detected: List[PatternMatch]
    recommended_actions: List[str]
    supporting_evidence: str
    audit_logged: bool = True


class SarGeneratorResult(BaseModel):
    sar_id: str
    customer_id: str
    alert_id: Optional[str]
    draft_narrative: str
    typology: str
    priority: str
    status: str = "draft"
    requires_human_approval: bool = True
    audit_logged: bool = True


class CaseManagerResult(BaseModel):
    case_id: str
    alert_id: Optional[str]
    customer_id: str
    case_type: str
    priority: str
    assigned_to: str
    status: str
    sla_deadline: Optional[str]
    audit_logged: bool = True


# ---------------------------------------------------------------------------
# Governance models
# ---------------------------------------------------------------------------

class GovernanceDecision(BaseModel):
    passed: bool
    gate: str
    reason: str
    requires_human: bool = False
    action_taken: Optional[str] = None


class GovernanceResult(BaseModel):
    all_passed: bool
    decisions: List[GovernanceDecision]
    escalated: bool = False
    blocked: bool = False


# ---------------------------------------------------------------------------
# Pipeline result
# ---------------------------------------------------------------------------

class PipelineResult(BaseModel):
    transaction_id: str
    customer_id: str
    monitor_result: TransactionMonitorResult
    kyc_result: KycVerifierResult
    sanctions_result: SanctionsScreenResult
    pattern_result: Optional[PatternAnalyzerResult] = None
    sar_result: Optional[SarGeneratorResult] = None
    case_result: Optional[CaseManagerResult] = None
    governance_decisions: List[GovernanceResult]
    final_status: str  # cleared | flagged | blocked | escalated
    processing_time_ms: Optional[float] = None


# ---------------------------------------------------------------------------
# Model validation
# ---------------------------------------------------------------------------

class ModelValidationCreate(BaseModel):
    model_name: str
    validation_type: Optional[str] = None
    accuracy: Optional[float] = None
    drift_score: Optional[float] = None
    bias_score: Optional[float] = None
    fairness_score: Optional[float] = None
    human_reviewer: Optional[str] = None
    findings: Optional[str] = None


class ModelValidation(ModelValidationCreate):
    id: str
    validated_at: str

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Report models
# ---------------------------------------------------------------------------

class DailyReport(BaseModel):
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
    high_risk_transactions: List[Dict[str, Any]] = []


class AlertAnalytics(BaseModel):
    total_alerts: int
    by_severity: Dict[str, int]
    by_agent: Dict[str, int]
    by_status: Dict[str, int]
    avg_resolution_hours: Optional[float]
    false_positive_rate: Optional[float]
    top_alert_types: List[Dict[str, Any]]
