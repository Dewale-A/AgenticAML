"""
Tests for the AgenticAML Governance Engine, Rules, and Audit Trail.

Validates:
  - GovernanceEngine gate checks (confidence, materiality, sanctions, HITL, escalation, KYC)
  - GovernanceResult model fields
  - RULES configuration and helper functions
  - Audit trail helpers (log_agent_decision, log_governance_decision, log_human_decision, etc.)
"""

import os
import asyncio
import pytest

os.environ["DB_PATH"] = "/tmp/test_governance_aml.db"
os.environ["SEED_ON_START"] = "false"
os.environ["CASH_THRESHOLD"] = "5000000"
os.environ["TRANSFER_THRESHOLD"] = "10000000"
os.environ["MATERIALITY_THRESHOLD"] = "50000000"
os.environ["CONFIDENCE_GATE_THRESHOLD"] = "0.7"
os.environ["AUTO_BLOCK_SANCTIONS"] = "true"

from src.database import (
    init_db,
    get_db,
    create_customer,
    create_transaction,
    get_audit_trail,
    now_wat,
    new_id,
)
from src.governance.engine import GovernanceEngine
from src.governance.rules import (
    RULES,
    GovernanceRules,
    ThresholdConfig,
    RiskTierConfig,
    SlaConfig,
    get_risk_tier_for_amount,
    get_sla_hours,
)
from src.governance.audit import (
    log_agent_decision,
    log_governance_decision,
    log_human_decision,
    log_sanctions_screening,
    log_sar_lifecycle,
    log_case_lifecycle,
)


# ---------------------------------------------------------------------------
# Session fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session", autouse=True)
async def setup_db():
    try:
        os.remove("/tmp/test_governance_aml.db")
    except FileNotFoundError:
        pass
    await init_db()
    yield
    try:
        os.remove("/tmp/test_governance_aml.db")
    except FileNotFoundError:
        pass


@pytest.fixture
async def db():
    async with get_db() as conn:
        yield conn


@pytest.fixture(scope="session")
async def seed_entities():
    """Seed a customer and transaction for governance tests."""
    async with get_db() as db:
        await create_customer(db, {
            "id": "gov_cust_001",
            "name": "Governance Test Customer",
            "bvn": "55566677788",
            "nin": "66677788899",
            "date_of_birth": "1985-05-15",
            "phone": "+2348099887766",
            "address": "5 Broad Street, Lagos",
            "account_type": "individual",
            "risk_tier": "low",
            "kyc_status": "pending",
        })
        await create_transaction(db, {
            "id": "gov_txn_001",
            "customer_id": "gov_cust_001",
            "amount": 75_000_000.0,
            "currency": "NGN",
            "transaction_type": "transfer",
            "channel": "internet_banking",
            "direction": "outbound",
            "geo_location": "Lagos, NG",
            "timestamp": now_wat(),
            "status": "pending",
        })


# ---------------------------------------------------------------------------
# Tests: Governance Rules Configuration
# ---------------------------------------------------------------------------

class TestGovernanceRules:

    def test_rules_singleton_exists(self):
        """RULES singleton must be a GovernanceRules instance."""
        assert isinstance(RULES, GovernanceRules)

    def test_threshold_config_defaults(self):
        """ThresholdConfig defaults must match CBN standards."""
        cfg = RULES.thresholds
        assert cfg.cash_threshold == 5_000_000.0        # NGN 5M
        assert cfg.transfer_threshold == 10_000_000.0   # NGN 10M
        assert cfg.materiality_threshold == 50_000_000.0  # NGN 50M
        assert cfg.velocity_window_hours == 24
        assert cfg.velocity_max_transactions == 10
        assert cfg.confidence_gate_threshold == 0.7
        assert cfg.auto_block_sanctions is True

    def test_risk_tier_config(self):
        """RiskTierConfig must define tier boundaries correctly."""
        cfg = RULES.risk_tiers
        assert cfg.low_max == 1_000_000       # Below 1M is low
        assert cfg.medium_max == 5_000_000    # 1M-5M is medium
        assert cfg.high_max == 50_000_000     # 5M-50M is high

    def test_sla_config(self):
        """SLA hours must meet CBN/NFIU requirements."""
        cfg = RULES.sla
        assert cfg.critical_hours == 4
        assert cfg.high_hours == 24
        assert cfg.str_filing_deadline_hours == 24  # NFIU requirement

    def test_sar_approver_roles(self):
        """SAR approval must be restricted to authorized roles."""
        assert "compliance_officer" in RULES.sar_approver_roles
        assert "senior_compliance_officer" in RULES.sar_approver_roles
        assert "mlro" in RULES.sar_approver_roles

    def test_sanctions_block_confirmer_roles(self):
        """Sanctions block confirmation must require senior roles."""
        assert "senior_compliance_officer" in RULES.sanctions_block_confirmer_roles
        assert "mlro" in RULES.sanctions_block_confirmer_roles

    def test_mandatory_sar_risk_levels(self):
        """Critical risk must trigger mandatory SAR assessment."""
        assert "critical" in RULES.mandatory_sar_risk_levels

    def test_sanctions_human_review_types(self):
        """Strong and partial matches must require human review."""
        assert "strong" in RULES.sanctions_human_review_types
        assert "partial" in RULES.sanctions_human_review_types


class TestRiskTierHelper:

    def test_low_amount(self):
        assert get_risk_tier_for_amount(500_000) == "low"
        assert get_risk_tier_for_amount(0) == "low"
        assert get_risk_tier_for_amount(999_999) == "low"

    def test_medium_amount(self):
        assert get_risk_tier_for_amount(1_000_000) == "medium"
        assert get_risk_tier_for_amount(3_500_000) == "medium"
        assert get_risk_tier_for_amount(4_999_999) == "medium"

    def test_high_amount(self):
        assert get_risk_tier_for_amount(5_000_000) == "high"
        assert get_risk_tier_for_amount(25_000_000) == "high"
        assert get_risk_tier_for_amount(49_999_999) == "high"

    def test_critical_amount(self):
        assert get_risk_tier_for_amount(50_000_000) == "critical"
        assert get_risk_tier_for_amount(100_000_000) == "critical"
        assert get_risk_tier_for_amount(500_000_000) == "critical"


class TestSlaHelper:

    def test_sla_critical(self):
        assert get_sla_hours("critical") == 4

    def test_sla_high(self):
        assert get_sla_hours("high") == 24

    def test_sla_medium(self):
        assert get_sla_hours("medium") == 72

    def test_sla_low(self):
        assert get_sla_hours("low") == 168

    def test_sla_unknown_defaults_to_medium(self):
        assert get_sla_hours("unknown_priority") == 72


# ---------------------------------------------------------------------------
# Tests: GovernanceEngine Gate Checks
# ---------------------------------------------------------------------------

class TestGovernanceEngineConfidenceGate:

    @pytest.mark.asyncio
    async def test_high_confidence_passes(self, db, seed_entities):
        """Confidence above threshold (0.7) must pass the confidence gate."""
        gov = GovernanceEngine(db)
        result = await gov.evaluate(
            stage="transaction_monitor",
            entity_type="transaction",
            entity_id="gov_txn_001",
            agent_output={"confidence": 0.85, "flagged": True, "risk_score": 0.6},
            context={"amount": 3_000_000},
        )

        confidence_decision = next(d for d in result.decisions if d.gate == "confidence_gate")
        assert confidence_decision.passed is True
        assert confidence_decision.requires_human is False

    @pytest.mark.asyncio
    async def test_low_confidence_fails_and_escalates(self, db, seed_entities):
        """Confidence below threshold (0.7) must fail and require human review."""
        gov = GovernanceEngine(db)
        result = await gov.evaluate(
            stage="transaction_monitor",
            entity_type="transaction",
            entity_id="gov_txn_001",
            agent_output={"confidence": 0.4, "flagged": True, "risk_score": 0.5},
            context={"amount": 3_000_000},
        )

        confidence_decision = next(d for d in result.decisions if d.gate == "confidence_gate")
        assert confidence_decision.passed is False
        assert confidence_decision.requires_human is True
        assert confidence_decision.action_taken == "escalate_to_human"

    @pytest.mark.asyncio
    async def test_boundary_confidence_exact_threshold_passes(self, db, seed_entities):
        """Confidence exactly at threshold must pass."""
        gov = GovernanceEngine(db)
        result = await gov.evaluate(
            stage="transaction_monitor",
            entity_type="transaction",
            entity_id="gov_txn_001",
            agent_output={"confidence": 0.7},
            context={"amount": 1_000_000},
        )

        confidence_decision = next(d for d in result.decisions if d.gate == "confidence_gate")
        assert confidence_decision.passed is True


class TestGovernanceEngineMaterialityGate:

    @pytest.mark.asyncio
    async def test_below_materiality_threshold_passes(self, db, seed_entities):
        """Amount below NGN 50M must pass materiality gate without human review."""
        gov = GovernanceEngine(db)
        result = await gov.evaluate(
            stage="transaction_monitor",
            entity_type="transaction",
            entity_id="gov_txn_001",
            agent_output={"confidence": 0.9},
            context={"amount": 10_000_000},
        )

        materiality_decision = next(d for d in result.decisions if d.gate == "materiality_gate")
        assert materiality_decision.passed is True
        assert materiality_decision.requires_human is False

    @pytest.mark.asyncio
    async def test_above_materiality_threshold_requires_review(self, db, seed_entities):
        """Amount above NGN 50M must trigger materiality gate and require human review."""
        gov = GovernanceEngine(db)
        result = await gov.evaluate(
            stage="transaction_monitor",
            entity_type="transaction",
            entity_id="gov_txn_001",
            agent_output={"confidence": 0.9},
            context={"amount": 75_000_000},
        )

        materiality_decision = next(d for d in result.decisions if d.gate == "materiality_gate")
        assert materiality_decision.passed is False
        assert materiality_decision.requires_human is True
        assert materiality_decision.action_taken == "additional_review"

    @pytest.mark.asyncio
    async def test_materiality_gate_not_applied_outside_relevant_stages(self, db, seed_entities):
        """Materiality gate must NOT apply to kyc_verifier stage."""
        gov = GovernanceEngine(db)
        result = await gov.evaluate(
            stage="kyc_verifier",
            entity_type="customer",
            entity_id="gov_cust_001",
            agent_output={"confidence": 0.9, "kyc_status": "verified"},
            context={"amount": 100_000_000},  # Large amount but wrong stage
        )

        gate_names = [d.gate for d in result.decisions]
        assert "materiality_gate" not in gate_names


class TestGovernanceEngineSanctionsBlock:

    @pytest.mark.asyncio
    async def test_clear_recommendation_passes(self, db, seed_entities):
        """Sanctions clear recommendation must pass without blocking."""
        gov = GovernanceEngine(db)
        result = await gov.evaluate(
            stage="sanctions_screener",
            entity_type="transaction",
            entity_id="gov_txn_001",
            agent_output={
                "overall_recommendation": "clear",
                "matches": [],
                "confidence": 0.99,
            },
        )

        sanctions_decision = next(d for d in result.decisions if d.gate == "sanctions_block")
        assert sanctions_decision.passed is True
        assert sanctions_decision.requires_human is False
        assert result.blocked is False

    @pytest.mark.asyncio
    async def test_block_recommendation_auto_blocks(self, db, seed_entities):
        """Confirmed sanctions match must auto-block the transaction (CBN mandate)."""
        gov = GovernanceEngine(db)
        result = await gov.evaluate(
            stage="sanctions_screener",
            entity_type="transaction",
            entity_id="gov_txn_001",
            agent_output={
                "overall_recommendation": "block",
                "matches": [{"list_name": "OFAC", "match_type": "exact", "match_score": 1.0}],
                "confidence": 0.99,
            },
        )

        sanctions_decision = next(d for d in result.decisions if d.gate == "sanctions_block")
        assert sanctions_decision.passed is False
        assert sanctions_decision.action_taken == "block"
        assert result.blocked is True

    @pytest.mark.asyncio
    async def test_review_recommendation_requires_human(self, db, seed_entities):
        """Partial sanctions match (review) must require human review."""
        gov = GovernanceEngine(db)
        result = await gov.evaluate(
            stage="sanctions_screener",
            entity_type="transaction",
            entity_id="gov_txn_001",
            agent_output={
                "overall_recommendation": "review",
                "matches": [{"list_name": "UN", "match_type": "partial", "match_score": 0.75}],
                "confidence": 0.75,
            },
        )

        sanctions_decision = next(d for d in result.decisions if d.gate == "sanctions_block")
        assert sanctions_decision.requires_human is True
        assert result.blocked is False  # review != block


class TestGovernanceEngineHumanInTheLoop:

    @pytest.mark.asyncio
    async def test_sar_always_requires_human_approval(self, db, seed_entities):
        """SAR stage must ALWAYS require human approval - no exceptions."""
        gov = GovernanceEngine(db)
        result = await gov.evaluate(
            stage="sar_generator",
            entity_type="sar",
            entity_id="gov_sar_001",
            agent_output={
                "sar_id": "gov_sar_001",
                "status": "draft",
                "requires_human_approval": True,
            },
        )

        hitl_decision = next(d for d in result.decisions if d.gate == "human_in_the_loop")
        assert hitl_decision.requires_human is True
        assert hitl_decision.action_taken == "await_human_approval"
        assert result.escalated is True


class TestGovernanceEngineEscalationChain:

    @pytest.mark.asyncio
    async def test_critical_risk_escalates(self, db, seed_entities):
        """Critical pattern risk must trigger mandatory escalation."""
        gov = GovernanceEngine(db)
        result = await gov.evaluate(
            stage="pattern_analyzer",
            entity_type="customer",
            entity_id="gov_cust_001",
            agent_output={
                "overall_risk": "critical",
                "confidence": 0.9,
                "patterns_detected": [],
            },
            context={"amount": 10_000_000},
        )

        escalation_decision = next(d for d in result.decisions if d.gate == "escalation_chain")
        assert escalation_decision.requires_human is True
        assert escalation_decision.action_taken == "escalate_critical"

    @pytest.mark.asyncio
    async def test_high_risk_requires_senior_review(self, db, seed_entities):
        """High risk pattern must require senior analyst review."""
        gov = GovernanceEngine(db)
        result = await gov.evaluate(
            stage="pattern_analyzer",
            entity_type="customer",
            entity_id="gov_cust_001",
            agent_output={
                "overall_risk": "high",
                "confidence": 0.85,
                "patterns_detected": [],
            },
            context={"amount": 5_000_000},
        )

        escalation_decision = next(d for d in result.decisions if d.gate == "escalation_chain")
        assert escalation_decision.requires_human is True
        assert escalation_decision.action_taken == "escalate_high"

    @pytest.mark.asyncio
    async def test_low_risk_no_escalation(self, db, seed_entities):
        """Low risk pattern must not trigger escalation."""
        gov = GovernanceEngine(db)
        result = await gov.evaluate(
            stage="pattern_analyzer",
            entity_type="customer",
            entity_id="gov_cust_001",
            agent_output={
                "overall_risk": "low",
                "confidence": 0.9,
                "patterns_detected": [],
            },
            context={"amount": 500_000},
        )

        escalation_decision = next(d for d in result.decisions if d.gate == "escalation_chain")
        assert escalation_decision.requires_human is False
        assert escalation_decision.action_taken is None


class TestGovernanceEngineKycEscalation:

    @pytest.mark.asyncio
    async def test_failed_kyc_escalates(self, db, seed_entities):
        """Failed KYC must auto-escalate to compliance officer."""
        gov = GovernanceEngine(db)
        result = await gov.evaluate(
            stage="kyc_verifier",
            entity_type="customer",
            entity_id="gov_cust_001",
            agent_output={
                "kyc_status": "failed",
                "confidence": 0.3,
                "risk_tier": "high",
            },
        )

        kyc_decision = next(d for d in result.decisions if d.gate == "kyc_escalation")
        assert kyc_decision.passed is False
        assert kyc_decision.requires_human is True
        assert kyc_decision.action_taken == "escalate_to_compliance"

    @pytest.mark.asyncio
    async def test_incomplete_kyc_flagged_for_review(self, db, seed_entities):
        """Incomplete KYC must require analyst review."""
        gov = GovernanceEngine(db)
        result = await gov.evaluate(
            stage="kyc_verifier",
            entity_type="customer",
            entity_id="gov_cust_001",
            agent_output={
                "kyc_status": "incomplete",
                "confidence": 0.6,
                "risk_tier": "medium",
            },
        )

        kyc_decision = next(d for d in result.decisions if d.gate == "kyc_escalation")
        assert kyc_decision.requires_human is True
        assert kyc_decision.action_taken == "flag_for_review"

    @pytest.mark.asyncio
    async def test_verified_kyc_no_escalation(self, db, seed_entities):
        """Verified KYC must not require escalation."""
        gov = GovernanceEngine(db)
        result = await gov.evaluate(
            stage="kyc_verifier",
            entity_type="customer",
            entity_id="gov_cust_001",
            agent_output={
                "kyc_status": "verified",
                "confidence": 0.92,
                "risk_tier": "low",
            },
        )

        kyc_decision = next(d for d in result.decisions if d.gate == "kyc_escalation")
        assert kyc_decision.passed is True
        assert kyc_decision.requires_human is False


class TestGovernanceEngineResultModel:

    @pytest.mark.asyncio
    async def test_all_passed_when_no_issues(self, db, seed_entities):
        """GovernanceResult.all_passed should be True when all gates pass."""
        gov = GovernanceEngine(db)
        result = await gov.evaluate(
            stage="transaction_monitor",
            entity_type="transaction",
            entity_id="gov_txn_001",
            agent_output={"confidence": 0.9},
            context={"amount": 500_000},
        )

        assert result.all_passed is True
        assert result.blocked is False

    @pytest.mark.asyncio
    async def test_result_has_decisions_list(self, db, seed_entities):
        """GovernanceResult must include a list of gate decisions."""
        gov = GovernanceEngine(db)
        result = await gov.evaluate(
            stage="transaction_monitor",
            entity_type="transaction",
            entity_id="gov_txn_001",
            agent_output={"confidence": 0.8},
            context={"amount": 1_000_000},
        )

        assert isinstance(result.decisions, list)
        assert len(result.decisions) >= 1

    @pytest.mark.asyncio
    async def test_each_decision_has_required_fields(self, db, seed_entities):
        """Each GovernanceDecision must have gate, passed, reason, requires_human."""
        gov = GovernanceEngine(db)
        result = await gov.evaluate(
            stage="sanctions_screener",
            entity_type="transaction",
            entity_id="gov_txn_001",
            agent_output={"overall_recommendation": "clear", "confidence": 0.95},
        )

        for decision in result.decisions:
            assert isinstance(decision.gate, str)
            assert isinstance(decision.passed, bool)
            assert isinstance(decision.reason, str)
            assert isinstance(decision.requires_human, bool)

    @pytest.mark.asyncio
    async def test_governance_decisions_logged_to_audit_trail(self, db, seed_entities):
        """Every governance gate evaluation must produce an audit trail entry."""
        txn_id = new_id()
        await create_transaction(db, {
            "id": txn_id,
            "customer_id": "gov_cust_001",
            "amount": 1_000_000.0,
            "currency": "NGN",
            "transaction_type": "transfer",
            "channel": "mobile_app",
            "direction": "outbound",
            "geo_location": "Lagos, NG",
            "timestamp": now_wat(),
            "status": "pending",
        })

        gov = GovernanceEngine(db)
        await gov.evaluate(
            stage="transaction_monitor",
            entity_type="transaction",
            entity_id=txn_id,
            agent_output={"confidence": 0.85},
            context={"amount": 1_000_000},
        )

        audit = await get_audit_trail(db, entity_id=txn_id)
        gov_entries = [e for e in audit if e["event_type"] == "governance_check"]
        assert len(gov_entries) >= 1
        assert all(e["actor"] == "governance_engine" for e in gov_entries)


# ---------------------------------------------------------------------------
# Tests: Audit Trail Helpers
# ---------------------------------------------------------------------------

class TestAuditTrailHelpers:

    @pytest.mark.asyncio
    async def test_log_agent_decision(self, db, seed_entities):
        """log_agent_decision must create an audit entry with agent_decision event type."""
        entity_id = new_id()
        await log_agent_decision(
            db=db,
            agent_name="transaction_monitor_agent",
            entity_type="transaction",
            entity_id=entity_id,
            decision="flagged",
            confidence=0.85,
            details={"amount": 7_000_000, "currency": "NGN"},
            risk_score=0.72,
        )

        audit = await get_audit_trail(db, entity_id=entity_id)
        assert len(audit) == 1
        entry = audit[0]
        assert entry["event_type"] == "agent_decision"
        assert entry["actor"] == "transaction_monitor_agent"
        assert entry["entity_id"] == entity_id

    @pytest.mark.asyncio
    async def test_log_governance_decision(self, db, seed_entities):
        """log_governance_decision must create a governance_check audit entry."""
        entity_id = new_id()
        await log_governance_decision(
            db=db,
            gate="confidence_gate",
            entity_type="transaction",
            entity_id=entity_id,
            passed=True,
            reason="Confidence 0.85 meets threshold 0.70",
            requires_human=False,
            action_taken=None,
        )

        audit = await get_audit_trail(db, entity_id=entity_id)
        assert len(audit) == 1
        entry = audit[0]
        assert entry["event_type"] == "governance_check"
        assert entry["actor"] == "governance_engine"

    @pytest.mark.asyncio
    async def test_log_human_decision(self, db, seed_entities):
        """log_human_decision must create a human decision audit entry."""
        entity_id = new_id()
        await log_human_decision(
            db=db,
            entity_type="sar",
            entity_id=entity_id,
            event_type="sar_approval",
            actor="compliance_officer_adaeze",
            decision="approved",
            rationale="Evidence of structuring is sufficient for SAR filing",
            before_state={"status": "draft"},
            after_state={"status": "approved"},
        )

        audit = await get_audit_trail(db, entity_id=entity_id)
        assert len(audit) == 1
        entry = audit[0]
        assert entry["event_type"] == "sar_approval"
        assert entry["actor"] == "compliance_officer_adaeze"

    @pytest.mark.asyncio
    async def test_log_sanctions_screening(self, db, seed_entities):
        """log_sanctions_screening must create a sanctions_screening audit entry."""
        entity_id = new_id()
        await log_sanctions_screening(
            db=db,
            entity_id=entity_id,
            name_screened="Abubakar Shekau",
            lists_checked=["OFAC", "UN", "CBN_DOMESTIC"],
            match_count=1,
            recommendation="block",
        )

        audit = await get_audit_trail(db, entity_id=entity_id)
        assert len(audit) == 1
        entry = audit[0]
        assert entry["event_type"] == "sanctions_screening"
        assert entry["actor"] == "sanctions_screener_agent"

    @pytest.mark.asyncio
    async def test_log_sar_lifecycle(self, db, seed_entities):
        """log_sar_lifecycle must create sar_ prefixed event entries."""
        sar_id = new_id()
        await log_sar_lifecycle(
            db=db,
            sar_id=sar_id,
            event="drafted",
            actor="sar_generator_agent",
            details={"typology": "structuring_smurfing", "priority": "urgent"},
        )

        audit = await get_audit_trail(db, entity_id=sar_id)
        assert len(audit) == 1
        entry = audit[0]
        assert entry["event_type"] == "sar_drafted"

    @pytest.mark.asyncio
    async def test_log_case_lifecycle(self, db, seed_entities):
        """log_case_lifecycle must create case_ prefixed event entries."""
        case_id = new_id()
        await log_case_lifecycle(
            db=db,
            case_id=case_id,
            event="created",
            actor="case_manager_agent",
            details={"priority": "high", "assigned_to": "Ngozi Adeyemi"},
        )

        audit = await get_audit_trail(db, entity_id=case_id)
        assert len(audit) == 1
        entry = audit[0]
        assert entry["event_type"] == "case_created"

    @pytest.mark.asyncio
    async def test_audit_trail_is_append_only(self, db, seed_entities):
        """Audit entries must accumulate - never be deleted or overwritten."""
        entity_id = new_id()

        # Write 3 entries
        for i in range(3):
            await log_agent_decision(
                db=db,
                agent_name=f"agent_{i}",
                entity_type="transaction",
                entity_id=entity_id,
                decision=f"decision_{i}",
                confidence=0.8,
            )

        audit = await get_audit_trail(db, entity_id=entity_id)
        assert len(audit) == 3

        # Add one more - total must be 4
        await log_agent_decision(
            db=db,
            agent_name="agent_3",
            entity_type="transaction",
            entity_id=entity_id,
            decision="decision_3",
            confidence=0.9,
        )

        audit_after = await get_audit_trail(db, entity_id=entity_id)
        assert len(audit_after) == 4

    @pytest.mark.asyncio
    async def test_audit_entries_have_timestamps(self, db, seed_entities):
        """Every audit entry must have a non-empty timestamp."""
        entity_id = new_id()
        await log_agent_decision(
            db=db,
            agent_name="test_agent",
            entity_type="transaction",
            entity_id=entity_id,
            decision="cleared",
            confidence=0.9,
        )

        audit = await get_audit_trail(db, entity_id=entity_id)
        for entry in audit:
            assert entry.get("timestamp") is not None
            assert entry["timestamp"] != ""

    @pytest.mark.asyncio
    async def test_audit_entries_have_actor(self, db, seed_entities):
        """Every audit entry must record the actor (agent or human)."""
        entity_id = new_id()
        await log_agent_decision(
            db=db,
            agent_name="kyc_verifier_agent",
            entity_type="customer",
            entity_id=entity_id,
            decision="verified",
            confidence=0.95,
        )

        audit = await get_audit_trail(db, entity_id=entity_id)
        assert audit[0]["actor"] == "kyc_verifier_agent"


# ---------------------------------------------------------------------------
# Tests: Full Pipeline Governance Integration
# ---------------------------------------------------------------------------

class TestGovernancePipelineIntegration:

    @pytest.mark.asyncio
    async def test_multiple_stages_accumulate_decisions(self, db, seed_entities):
        """Running governance on multiple stages should produce decisions from all stages."""
        gov = GovernanceEngine(db)
        entity_id = "gov_txn_001"

        # Stage 1: transaction monitor
        result_1 = await gov.evaluate(
            stage="transaction_monitor",
            entity_type="transaction",
            entity_id=entity_id,
            agent_output={"confidence": 0.9},
            context={"amount": 2_000_000},
        )

        # Stage 2: kyc_verifier
        result_2 = await gov.evaluate(
            stage="kyc_verifier",
            entity_type="customer",
            entity_id="gov_cust_001",
            agent_output={"kyc_status": "verified", "confidence": 0.92},
        )

        # Stage 3: sanctions_screener
        result_3 = await gov.evaluate(
            stage="sanctions_screener",
            entity_type="transaction",
            entity_id=entity_id,
            agent_output={"overall_recommendation": "clear", "confidence": 0.99},
        )

        assert len(result_1.decisions) >= 1
        assert len(result_2.decisions) >= 1
        assert len(result_3.decisions) >= 1

    @pytest.mark.asyncio
    async def test_sanctions_block_produces_blocked_result(self, db, seed_entities):
        """A sanctions block must set GovernanceResult.blocked = True."""
        gov = GovernanceEngine(db)
        result = await gov.evaluate(
            stage="sanctions_screener",
            entity_type="transaction",
            entity_id="gov_txn_001",
            agent_output={"overall_recommendation": "block", "confidence": 0.99},
        )

        assert result.blocked is True
        assert result.escalated is True

    @pytest.mark.asyncio
    async def test_low_confidence_plus_high_materiality_both_fire(self, db, seed_entities):
        """Low confidence AND high materiality should both trigger their respective gates."""
        gov = GovernanceEngine(db)
        result = await gov.evaluate(
            stage="transaction_monitor",
            entity_type="transaction",
            entity_id="gov_txn_001",
            agent_output={"confidence": 0.4},
            context={"amount": 80_000_000},
        )

        gate_names = [d.gate for d in result.decisions]
        assert "confidence_gate" in gate_names
        assert "materiality_gate" in gate_names

        confidence_dec = next(d for d in result.decisions if d.gate == "confidence_gate")
        materiality_dec = next(d for d in result.decisions if d.gate == "materiality_gate")

        assert confidence_dec.passed is False
        assert materiality_dec.passed is False
        assert result.escalated is True
