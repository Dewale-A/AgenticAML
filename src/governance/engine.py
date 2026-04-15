"""
Governance Engine for AgenticAML.
Runs between every agent stage. Enforces controls mandated by CBN and FATF.

Controls evaluated:
  1. Confidence Gate       - low-confidence outputs go to human review
  2. Materiality Gate      - large amounts require additional review
  3. Sanctions Block       - confirmed sanctions hits auto-block
  4. Human-in-the-Loop     - SAR filing and high-risk decisions require human approval
  5. Escalation Chain      - risk-tiered escalation with SLA tracking
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import aiosqlite

from src.governance.rules import RULES, get_risk_tier_for_amount
from src.governance.audit import log_governance_decision
from src.models import GovernanceDecision, GovernanceResult


class GovernanceEngine:
    """
    Evaluate governance controls for an agent output.
    Each check is logged to the audit trail regardless of outcome.
    """

    def __init__(self, db: aiosqlite.Connection):
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
        """Run all applicable governance checks for a given stage."""
        context = context or {}
        decisions: List[GovernanceDecision] = []

        # 1. Confidence Gate (applies to all agent outputs)
        if "confidence" in agent_output:
            dec = await self._check_confidence_gate(
                entity_type, entity_id, agent_output["confidence"], stage
            )
            decisions.append(dec)

        # 2. Materiality Gate (Transaction Monitor and Pattern Analyzer)
        if stage in ("transaction_monitor", "pattern_analyzer"):
            amount = context.get("amount", 0)
            if amount:
                dec = await self._check_materiality_gate(entity_type, entity_id, amount, stage)
                decisions.append(dec)

        # 3. Sanctions Block
        if stage == "sanctions_screener":
            recommendation = agent_output.get("overall_recommendation", "clear")
            dec = await self._check_sanctions_block(entity_type, entity_id, recommendation)
            decisions.append(dec)

        # 4. Human-in-the-Loop (SAR)
        if stage == "sar_generator":
            dec = await self._check_hitl_sar(entity_type, entity_id)
            decisions.append(dec)

        # 5. Escalation Chain (pattern analyzer critical)
        if stage == "pattern_analyzer":
            risk_level = agent_output.get("overall_risk", "low")
            dec = await self._check_escalation(entity_type, entity_id, risk_level)
            decisions.append(dec)

        # 6. Risk Tier check for KYC
        if stage == "kyc_verifier":
            kyc_status = agent_output.get("kyc_status", "pending")
            dec = await self._check_kyc_escalation(entity_type, entity_id, kyc_status)
            decisions.append(dec)

        all_passed = all(d.passed for d in decisions)
        blocked = any(d.action_taken == "block" for d in decisions)
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
        threshold = RULES.thresholds.materiality_threshold
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
        requires_human = risk_level in ("critical", "high")
        passed = True
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
        requires_human = kyc_status in ("failed", "incomplete")
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
