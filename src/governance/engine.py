"""
Governance Engine for AgenticAML.

This module enforces the human-in-the-loop and automated control framework
required by CBN AML/CFT guidelines and FATF Recommendations.

The GovernanceEngine is called between EVERY agent stage so that no agent
output can bypass compliance controls. Each gate is evaluated independently
and its result is logged to the immutable audit trail regardless of outcome.

Controls evaluated (in order):
  1. Confidence Gate       — low-confidence agent outputs go to human review
                             rather than being acted upon automatically
  2. Materiality Gate      — large-value transactions require additional review
                             (CBN enhanced due diligence threshold)
  3. Sanctions Block       — confirmed sanctions hits auto-block and notify
                             senior compliance officer (CBN mandate)
  4. Human-in-the-Loop     — SAR filing ALWAYS requires human approval;
                             agents can only draft, never file
  5. Escalation Chain      — critical/high risk patterns escalate to the
                             appropriate compliance role
  6. KYC Escalation        — KYC failures escalate to compliance officer
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import aiosqlite

from src.governance.rules import RULES, get_risk_tier_for_amount
from src.governance.audit import log_governance_decision
from src.models import GovernanceDecision, GovernanceResult


class GovernanceEngine:
    """Evaluate governance controls for an agent output.

    Each check writes an immutable audit log entry regardless of whether
    it passes or fails — this ensures that 'clean' decisions are as
    well-evidenced as interventions, satisfying CBN's requirement for a
    complete decision chain.
    """

    def __init__(self, db: aiosqlite.Connection):
        # Database connection is injected so the engine shares the same
        # connection/transaction as the calling agent, guaranteeing that
        # agent decisions and governance decisions are persisted atomically.
        self.db = db

    # ------------------------------------------------------------------
    # Top-level evaluation
    # ------------------------------------------------------------------

    async def evaluate(
        self,
        stage: str,
        entity_type: str,
        entity_id: str,
        agent_output: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> GovernanceResult:
        """Run all applicable governance checks for a given agent stage.

        Stage-to-gate mapping:
        - All stages with a 'confidence' key → confidence_gate
        - transaction_monitor, pattern_analyzer (with amount) → materiality_gate
        - sanctions_screener → sanctions_block
        - sar_generator → human_in_the_loop
        - pattern_analyzer → escalation_chain
        - kyc_verifier → kyc_escalation

        Returns a GovernanceResult that aggregates all gate outcomes.
        The pipeline uses `blocked` to stop immediately and `escalated`
        to route to human review.
        """
        context = context or {}
        decisions: List[GovernanceDecision] = []

        # 1. Confidence Gate applies to every agent that reports a confidence
        # score. A score below 0.7 (configurable via CONFIDENCE_GATE_THRESHOLD)
        # means the agent is uncertain and a human should review before acting.
        if "confidence" in agent_output:
            dec = await self._check_confidence_gate(
                entity_type, entity_id, agent_output["confidence"], stage
            )
            decisions.append(dec)

        # 2. Materiality Gate applies to transaction and pattern stages because
        # those are the stages that evaluate transaction amounts. Large amounts
        # (default NGN 50M+) trigger additional review per CBN materiality rules.
        if stage in ("transaction_monitor", "pattern_analyzer"):
            amount = context.get("amount", 0)
            if amount:
                dec = await self._check_materiality_gate(entity_type, entity_id, amount, stage)
                decisions.append(dec)

        # 3. Sanctions Block applies only after the sanctions screener runs.
        # The recommendation is 'block', 'review', or 'clear' — 'block' triggers
        # an immediate auto-block per CBN mandate. 'review' requires human
        # confirmation before any action is taken.
        if stage == "sanctions_screener":
            recommendation = agent_output.get("overall_recommendation", "clear")
            dec = await self._check_sanctions_block(entity_type, entity_id, recommendation)
            decisions.append(dec)

        # 4. Human-in-the-Loop applies unconditionally to every SAR.
        # The AI can draft a SAR but CANNOT file it — a human compliance
        # officer must review and approve before the SAR is submitted to NFIU.
        if stage == "sar_generator":
            dec = await self._check_hitl_sar(entity_type, entity_id)
            decisions.append(dec)

        # 5. Escalation Chain applies after pattern analysis. Critical risk
        # mandates escalation to the Compliance Officer; high risk requires
        # a Senior Analyst review. These thresholds align with FATF R.20
        # (reporting suspicious transactions) and CBN's tiered escalation policy.
        if stage == "pattern_analyzer":
            risk_level = agent_output.get("overall_risk", "low")
            dec = await self._check_escalation(entity_type, entity_id, risk_level)
            decisions.append(dec)

        # 6. KYC Escalation applies after KYC verification. Failed KYC must
        # immediately escalate to the Compliance Officer. Incomplete KYC flags
        # the account for analyst review and may trigger account restrictions.
        if stage == "kyc_verifier":
            kyc_status = agent_output.get("kyc_status", "pending")
            dec = await self._check_kyc_escalation(entity_type, entity_id, kyc_status)
            decisions.append(dec)

        # Aggregate outcomes across all gates
        all_passed = all(d.passed for d in decisions)
        # blocked=True if any gate issued a hard block (sanctions match)
        blocked = any(d.action_taken == "block" for d in decisions)
        # escalated=True if any gate requires human intervention
        escalated = any(d.requires_human for d in decisions)

        return GovernanceResult(
            all_passed=all_passed,
            decisions=decisions,
            escalated=escalated,
            blocked=blocked,
        )

    # ------------------------------------------------------------------
    # Individual gate checks
    # ------------------------------------------------------------------

    async def _check_confidence_gate(
        self, entity_type: str, entity_id: str, confidence: float, stage: str
    ) -> GovernanceDecision:
        """Enforce the minimum confidence threshold before acting on agent output.

        Threshold is 0.7 (configurable via CONFIDENCE_GATE_THRESHOLD env var).
        A score below 0.7 means the agent itself is not sufficiently certain —
        acting on uncertain AI output without human review could produce
        false positives (customer harm) or false negatives (regulatory risk).
        """
        threshold = RULES.confidence_gate
        passed = confidence >= threshold
        requires_human = not passed
        reason = (
            f"Confidence {confidence:.2f} meets threshold {threshold:.2f}"
            if passed
            else f"Confidence {confidence:.2f} below threshold {threshold:.2f}: escalating to human review"
        )
        action = "escalate_to_human" if requires_human else None

        await log_governance_decision(
            self.db,
            gate="confidence_gate",
            entity_type=entity_type,
            entity_id=entity_id,
            passed=passed,
            reason=reason,
            requires_human=requires_human,
            action_taken=action,
        )

        return GovernanceDecision(
            passed=passed,
            gate="confidence_gate",
            reason=reason,
            requires_human=requires_human,
            action_taken=action,
        )

    async def _check_materiality_gate(
        self, entity_type: str, entity_id: str, amount: float, stage: str
    ) -> GovernanceDecision:
        """Enforce the materiality threshold for high-value transactions.

        Default threshold is NGN 50M (configurable via MATERIALITY_THRESHOLD).
        Transactions above this amount require additional human review,
        reflecting CBN's enhanced due diligence requirements for large-value
        transactions and the increased risk of significant financial crime.
        """
        threshold = RULES.thresholds.materiality_threshold
        # passed=True means the amount is BELOW the threshold (normal)
        passed = amount < threshold
        requires_human = not passed
        reason = (
            f"Amount NGN {amount:,.2f} is below materiality threshold NGN {threshold:,.2f}"
            if passed
            else f"Amount NGN {amount:,.2f} exceeds materiality threshold NGN {threshold:,.2f}: additional review required"
        )
        action = "additional_review" if requires_human else None

        await log_governance_decision(
            self.db,
            gate="materiality_gate",
            entity_type=entity_type,
            entity_id=entity_id,
            passed=passed,
            reason=reason,
            requires_human=requires_human,
            action_taken=action,
        )

        return GovernanceDecision(
            passed=passed,
            gate="materiality_gate",
            reason=reason,
            requires_human=requires_human,
            action_taken=action,
        )

    async def _check_sanctions_block(
        self, entity_type: str, entity_id: str, recommendation: str
    ) -> GovernanceDecision:
        """Enforce automatic blocking of confirmed sanctions matches.

        CBN AML/CFT circular mandates that Nigerian financial institutions
        MUST freeze assets and block transactions for confirmed sanctions
        matches without delay. AUTO_BLOCK_SANCTIONS=true enables this
        automatic enforcement (default: true).

        Three outcomes:
        - 'block': confirmed match → automatic block + senior officer alert
        - 'review': partial/strong match → human review before any action
        - 'clear': no match → pass through

        The 'review' path still passes (passed=True) but requires_human=True
        so the pipeline can continue with human oversight rather than stopping.
        """
        if recommendation == "block" and RULES.thresholds.auto_block_sanctions:
            passed = False
            requires_human = True
            reason = "Confirmed sanctions match: transaction BLOCKED per CBN mandate. Senior compliance officer confirmation required."
            action = "block"
        elif recommendation == "review":
            passed = True
            requires_human = True
            reason = "Partial/strong sanctions match: human review required before proceeding."
            action = "escalate_to_human"
        else:
            passed = True
            requires_human = False
            reason = "No sanctions match: cleared."
            action = None

        await log_governance_decision(
            self.db,
            gate="sanctions_block",
            entity_type=entity_type,
            entity_id=entity_id,
            passed=passed,
            reason=reason,
            requires_human=requires_human,
            action_taken=action,
        )

        return GovernanceDecision(
            passed=passed,
            gate="sanctions_block",
            reason=reason,
            requires_human=requires_human,
            action_taken=action,
        )

    async def _check_hitl_sar(
        self, entity_type: str, entity_id: str
    ) -> GovernanceDecision:
        """Enforce mandatory human-in-the-loop for all SAR filings.

        CBN AML/CFT guidelines and NFIU requirements both mandate that a
        qualified human compliance officer reviews and approves every SAR/STR
        before it is filed with the NFIU. This gate always returns
        requires_human=True — there is no code path that allows auto-filing.

        The gate passes (passed=True) because the SAR has been successfully
        drafted. The requires_human=True flag routes it to the human approval
        queue rather than stopping the pipeline.
        """
        reason = "SAR filing ALWAYS requires mandatory human approval per CBN mandate and NFIU requirements."
        await log_governance_decision(
            self.db,
            gate="human_in_the_loop",
            entity_type=entity_type,
            entity_id=entity_id,
            passed=True,
            reason=reason,
            requires_human=True,
            action_taken="await_human_approval",
        )
        return GovernanceDecision(
            passed=True,
            gate="human_in_the_loop",
            reason=reason,
            requires_human=True,
            action_taken="await_human_approval",
        )

    async def _check_escalation(
        self, entity_type: str, entity_id: str, risk_level: str
    ) -> GovernanceDecision:
        """Enforce risk-tiered escalation after pattern analysis.

        Critical risk: mandatory escalation to Compliance Officer AND SAR
        assessment. This maps to FATF Recommendation 20 (suspicious transaction
        reporting) and CBN's requirement for immediate action on high-risk cases.

        High risk: Senior Analyst review required. The Analyst can then decide
        whether to escalate further or open a case.

        Medium/Low risk: standard monitoring continues without escalation.
        """
        requires_human = risk_level in ("critical", "high")
        passed = True  # Escalation is a routing decision, not a block
        if risk_level == "critical":
            reason = "CRITICAL risk assessment: mandatory escalation to compliance officer and SAR assessment."
            action = "escalate_critical"
        elif risk_level == "high":
            reason = "HIGH risk assessment: senior analyst review required."
            action = "escalate_high"
        else:
            reason = f"Risk level {risk_level}: standard monitoring applies."
            action = None

        await log_governance_decision(
            self.db,
            gate="escalation_chain",
            entity_type=entity_type,
            entity_id=entity_id,
            passed=passed,
            reason=reason,
            requires_human=requires_human,
            action_taken=action,
        )

        return GovernanceDecision(
            passed=passed,
            gate="escalation_chain",
            reason=reason,
            requires_human=requires_human,
            action_taken=action,
        )

    async def _check_kyc_escalation(
        self, entity_type: str, entity_id: str, kyc_status: str
    ) -> GovernanceDecision:
        """Enforce escalation for KYC failures and incomplete profiles.

        KYC failures (missing 3+ required fields or invalid BVN/NIN) are
        treated as a hard failure — passed=False — because CBN Tier-3 account
        regulations prohibit transacting when identity cannot be verified.

        KYC incomplete cases are routed for analyst review (passed=True,
        requires_human=True) because the customer may be mid-onboarding;
        the system flags rather than blocks while documentation is collected.
        """
        requires_human = kyc_status in ("failed", "incomplete")
        # Only 'failed' status causes the gate to fail (could block transactions)
        passed = kyc_status not in ("failed",)
        if kyc_status == "failed":
            reason = "KYC FAILED: automatic escalation to compliance officer."
            action = "escalate_to_compliance"
        elif kyc_status == "incomplete":
            reason = "KYC INCOMPLETE: analyst review required. Account restrictions may apply."
            action = "flag_for_review"
        else:
            reason = f"KYC status {kyc_status}: no escalation required."
            action = None

        await log_governance_decision(
            self.db,
            gate="kyc_escalation",
            entity_type=entity_type,
            entity_id=entity_id,
            passed=passed,
            reason=reason,
            requires_human=requires_human,
            action_taken=action,
        )

        return GovernanceDecision(
            passed=passed,
            gate="kyc_escalation",
            reason=reason,
            requires_human=requires_human,
            action_taken=action,
        )
