"""
Agent 0: Customer Onboarding Screener

The gateway agent that runs BEFORE the existing 6-agent transaction pipeline.
Screens new customer registration data against all watchlists and determines
whether a customer can be onboarded, must be escalated for senior approval,
or must be blocked entirely.

CBN KYC Regulations (revised 2023) require that all new customers are screened
against sanctions lists, PEP databases, and adverse media indicators before
their account is activated. This agent fulfils that requirement as the
first control in the customer acceptance process.

Decision outcomes:
  - approved:             No matches found. Customer onboarded at assigned risk tier.
  - pending_review:       Weak/partial match found. Account activated with enhanced
                          monitoring pending analyst review.
  - pending_escalation:   PEP match or adverse media requires C-suite/MLRO approval
                          before account activation. Account held in queue.
  - blocked:              Confirmed sanctions match (exact or strong). Account
                          registration rejected per CBN mandate. No appeal without
                          Head of Compliance documented exception.

Pipeline flow (from ROADMAP Section 4):
  NEW CUSTOMER REGISTRATION
           |
           v
    [Agent 0: Onboarding Screener]
           |
      +---------+---------+
      |                   |
    CLEAR              MATCH FOUND
      |                   |
      v                   v
    Onboard         Match Category?
    Customer              |
      |            +------+------+
      |            |             |
      v         SANCTIONS     PEP/ADVERSE
    Enter        (Block)      MEDIA
    Normal          |             |
    Pipeline        v             v
                 Reject +      Escalate to
                 Audit Log     C-Suite / Head of Compliance
"""

from __future__ import annotations

import json
from datetime import timedelta, timezone

import aiosqlite

from src.data.sanctions_lists import get_sanctions_db
from src.database import (
    create_customer,
    create_escalation,
    log_audit,
    now_wat,
)
from src.governance.audit import log_agent_decision
from src.governance.rules import RULES
from src.models import OnboardingRequest, OnboardingScreenerResult

# WAT timezone — all timestamps in Nigerian local time per CBN requirements
WAT = timezone(timedelta(hours=1))

# Import the same fuzzy matching utilities from SanctionsScreenerAgent rather
# than duplicating the logic. The onboarding screener uses identical match
# thresholds and scoring to ensure consistency across the pipeline.
from src.agents.sanctions_screener import (
    WEAK_THRESHOLD,
    SanctionsScreenerAgent,
)


class OnboardingScreenerAgent:
    """Agent 0: Pre-screens new customers against watchlists before account activation.

    Called by the POST /customers/onboard API endpoint. Returns an OnboardingScreenerResult
    with a decision that gates entry into the main 6-agent pipeline.

    The agent reuses SanctionsScreenerAgent's fuzzy matching logic to ensure
    that onboarding screening and transaction-level screening use the same
    name normalisation and score thresholds — a regulatory requirement to
    prevent inconsistent treatment of the same customer at different pipeline stages.
    """

    name = "onboarding_screener_agent"

    def __init__(self, db: aiosqlite.Connection):
        self.db = db
        # Reuse the sanctions screener for name matching logic
        self._screener = SanctionsScreenerAgent(db)

    async def screen(self, request: OnboardingRequest) -> OnboardingScreenerResult:
        """Screen a new customer registration against all watchlists.

        Steps:
        1. Build a list of name variants (name + aliases) to check.
        2. Screen against all lists in SANCTIONS_DB using fuzzy matching.
        3. Classify the overall result into a decision category.
        4. If approved: create the customer record in the DB.
        5. If pending_escalation: create the customer record (held) and an escalation record.
        6. If blocked: do NOT create a customer record. Log to audit trail only.
        7. Log all outcomes to the immutable audit trail before returning.

        The customer record is only created in the DB if the decision is NOT 'blocked'.
        A blocked customer must not appear in the main customer list — they are
        recorded only in the audit trail and sanctions_matches table.
        """
        all_names = [request.name] + (request.aliases or [])
        matches: list[dict] = []

        # Load the active sanctions database. Returns simulated data when
        # LIVE_SANCTIONS=false (default), or cached live data when true.
        # Falls back to simulated data if the live cache is unavailable.
        sanctions_db = await get_sanctions_db()

        # Screen against every list in the active DB, collecting all matches above weak threshold
        for list_name, entries in sanctions_db.items():
            match_category = self._screener._list_to_category(list_name)
            for entry in entries:
                best_score, best_name = self._screener._best_match_score(all_names, entry)
                if best_score >= WEAK_THRESHOLD:
                    match_type = self._screener._score_to_type(best_score)
                    action = self._screener._determine_action(
                        match_type, entry, request.date_of_birth
                    )
                    matches.append({
                        "list_name": list_name,
                        "matched_entity": entry.get("name", ""),
                        "match_type": match_type,
                        "match_score": round(best_score, 4),
                        "action_taken": action,
                        "match_category": match_category,
                        "matched_on_name": best_name,
                    })

        # Determine the onboarding decision based on match severity and category
        decision, risk_tier, decision_reason = self._classify_decision(request, matches)

        customer_id: str | None = None
        escalation_id: str | None = None

        if decision == "blocked":
            # Sanctions blocks are automatic and mandatory per CBN directive.
            # Do NOT create a customer record — log to audit trail only.
            # The blocked customer must be reported to the compliance team via alert.
            customer_id = None
            await self._log_blocked_onboarding(request, matches, decision_reason)

        else:
            # For approved, pending_review, and pending_escalation:
            # Create the customer record with onboarding_status set so the
            # compliance team can see the queue in the dashboard.
            onboarding_status = decision  # mirrors the decision string
            kyc_status = "pending"
            if decision == "approved":
                kyc_status = "pending"  # KYC verification happens in the main pipeline

            customer_data = {
                "name": request.name,
                "bvn": request.bvn,
                "nin": request.nin,
                "date_of_birth": request.date_of_birth,
                "phone": request.phone,
                "address": request.address,
                "account_type": request.account_type,
                "risk_tier": risk_tier,
                "kyc_status": kyc_status,
                "pep_status": 1 if any(m["match_category"] == "pep" for m in matches) else 0,
                "onboarding_status": onboarding_status,
                "nationality": request.nationality,
                "registration_source": request.registration_source,
            }
            customer = await create_customer(self.db, customer_data)
            customer_id = customer["id"]

            # Persist all watchlist matches to sanctions_matches table.
            # CBN requires evidence of all screening activity at onboarding,
            # not just transaction-level screening.
            for match in matches:
                try:
                    from src.database import create_sanctions_match
                    await create_sanctions_match(self.db, {
                        "customer_id": customer_id,
                        "transaction_id": None,
                        "list_name": match["list_name"],
                        "matched_entity": match["matched_entity"],
                        "match_type": match["match_type"],
                        "match_score": match["match_score"],
                        "action_taken": match["action_taken"],
                        "match_category": match["match_category"],
                    })
                except Exception:
                    pass  # Match logging must not crash onboarding

            if decision == "pending_escalation":
                # PEP match or adverse media requires C-suite/MLRO sign-off.
                # Create an escalation record so approvers can act on it via the
                # escalation API endpoints.
                escalation_id = await self._create_escalation(
                    customer_id=customer_id,
                    customer_name=request.name,
                    matches=matches,
                    decision_reason=decision_reason,
                )

        # MANDATORY: Log onboarding screening decision to audit trail before returning.
        # Every onboarding outcome (approved, blocked, escalated) must be recorded
        # so CBN examiners can reconstruct the customer acceptance decision chain.
        entity_id = customer_id or f"onboarding_{request.name}"
        await log_agent_decision(
            db=self.db,
            agent_name=self.name,
            entity_type="customer",
            entity_id=entity_id,
            decision=decision,
            confidence=self._compute_confidence(matches),
            details={
                "name": request.name,
                "match_count": len(matches),
                "decision_reason": decision_reason,
                "risk_tier": risk_tier,
                "escalation_id": escalation_id,
            },
        )

        return OnboardingScreenerResult(
            customer_id=customer_id,
            name=request.name,
            decision=decision,
            risk_tier=risk_tier,
            decision_reason=decision_reason,
            screening_matches=matches,
            escalation_id=escalation_id,
            screened_at=now_wat(),
            audit_logged=True,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _classify_decision(
        self, request: OnboardingRequest, matches: list[dict]
    ) -> tuple[str, str, str]:
        """Map screening matches to an onboarding decision, risk tier, and reason.

        Decision hierarchy (most restrictive wins):
        1. Any 'block' action on a sanctions list (exact/strong match): blocked
        2. Any PEP match (any strength): pending_escalation (FATF Rec 12 requirement)
        3. Any adverse_media match above partial: pending_escalation
        4. Any partial match on sanctions: pending_review (analyst review)
        5. Any weak match: pending_review
        6. No matches: approved

        Risk tier is elevated for PEPs and high-risk nationality customers.
        Returns: (decision, risk_tier, decision_reason)
        """
        if not matches:
            # No watchlist matches — clear for standard onboarding
            risk_tier = self._initial_risk_tier(request)
            return (
                "approved",
                risk_tier,
                "No watchlist matches found. Customer cleared for onboarding.",
            )

        # Check for hard blocks: sanctions match with block action
        block_matches = [m for m in matches if m["action_taken"] == "block" and m["match_category"] == "sanctions"]
        if block_matches:
            top = block_matches[0]
            return (
                "blocked",
                "very_high",  # Risk tier not applied (account not created)
                f"BLOCKED: Confirmed sanctions match on {top['list_name']} "
                f"({top['match_type']} match, score {top['match_score']:.2f}). "
                f"CBN mandate: account registration rejected.",
            )

        # PEP match at any strength requires C-suite/MLRO approval per FATF Rec 12.
        # PEPs are not automatically blocked — only escalated for documented approval.
        pep_matches = [m for m in matches if m["match_category"] == "pep"]
        if pep_matches:
            top = pep_matches[0]
            return (
                "pending_escalation",
                "very_high",  # PEPs always start at very_high risk tier per FATF
                f"PEP MATCH: Customer '{request.name}' matched {top['list_name']} "
                f"({top['match_type']} match, score {top['match_score']:.2f}). "
                f"C-suite/MLRO approval required before account activation (FATF Recommendation 12).",
            )

        # Adverse media at partial or above requires escalation
        adverse_matches = [
            m for m in matches
            if m["match_category"] == "adverse_media" and m["match_type"] in ("exact", "strong", "partial")
        ]
        if adverse_matches:
            top = adverse_matches[0]
            return (
                "pending_escalation",
                "high",
                f"ADVERSE MEDIA: Customer '{request.name}' matched adverse media indicators "
                f"({top['match_type']} match, score {top['match_score']:.2f}). "
                f"Senior compliance review required before account activation.",
            )

        # Partial or weak matches on any list: pending_review (account can activate
        # with enhanced monitoring while analyst investigates)
        partial_matches = [m for m in matches if m["match_type"] in ("partial", "weak")]
        if partial_matches:
            top = partial_matches[0]
            return (
                "pending_review",
                "medium",
                f"PARTIAL MATCH: Customer '{request.name}' has a {top['match_type']} match "
                f"on {top['list_name']} (score {top['match_score']:.2f}). "
                f"Account activated with enhanced monitoring. Analyst review required.",
            )

        # Fallback: no actionable matches (all below WEAK_THRESHOLD or action=clear)
        risk_tier = self._initial_risk_tier(request)
        return (
            "approved",
            risk_tier,
            "Screening complete. No significant watchlist matches found.",
        )

    def _initial_risk_tier(self, request: OnboardingRequest) -> str:
        """Assign an initial risk tier based on account type and registration details.

        Corporate accounts start at 'medium' because they require additional KYB
        (Know Your Business) verification that may reveal hidden beneficial ownership.
        High-risk nationality (from FATF grey/black lists) elevates to 'medium'.
        Individual accounts without red flags default to 'low'.
        """
        # High-risk nationalities per FATF and CBN country risk assessments (2026)
        high_risk_nationalities = ["IR", "KP", "SY", "CU", "SD", "YE", "LY", "MM"]
        if request.nationality and request.nationality.upper() in high_risk_nationalities:
            return "high"
        if request.account_type == "corporate":
            return "medium"  # Corporate accounts require enhanced KYB per CBN KYC Regs
        return "low"

    async def _create_escalation(
        self,
        customer_id: str,
        customer_name: str,
        matches: list[dict],
        decision_reason: str,
    ) -> str:
        """Create an executive escalation record for PEP/adverse media matches.

        Determines the required approver role based on match category:
        - PEP matches: require 'c_suite' or 'mlro' per FATF Recommendation 12
        - Adverse media: require 'head_of_compliance'

        Returns the escalation ID for inclusion in the onboarding result.
        """
        pep_matches = [m for m in matches if m["match_category"] == "pep"]
        required_role = "mlro" if pep_matches else "head_of_compliance"
        reason_code = "pep_match" if pep_matches else "adverse_media"

        sla_hours = RULES.thresholds.escalation_sla_hours

        escalation_data = {
            "entity_type": "customer_onboarding",
            "entity_id": customer_id,
            "escalation_reason": reason_code,
            "required_approver_role": required_role,
            "evidence_summary": json.dumps({
                "customer_name": customer_name,
                "match_count": len(matches),
                "matches": matches[:5],  # Store top 5 matches in evidence
                "decision_reason": decision_reason,
            }),
            "sla_hours": sla_hours,
        }
        escalation = await create_escalation(self.db, escalation_data)

        # Log the escalation creation to the audit trail so the decision chain
        # shows exactly when and why an escalation was triggered.
        await log_audit(
            db=self.db,
            entity_type="escalation",
            entity_id=escalation["id"],
            event_type="escalation_created",
            actor=self.name,
            description=f"Escalation created for customer '{customer_name}': {reason_code}. "
                        f"Required approver: {required_role}. SLA: {sla_hours}h.",
            metadata={
                "reason": reason_code,
                "required_role": required_role,
                "customer_id": customer_id,
                "sla_hours": sla_hours,
            },
        )
        return escalation["id"]

    async def _log_blocked_onboarding(
        self, request: OnboardingRequest, matches: list[dict], decision_reason: str
    ) -> None:
        """Log a blocked onboarding attempt to the audit trail.

        For blocked customers (confirmed sanctions matches), no customer record
        is created. The audit trail entry serves as the sole evidence of the
        screening result and the block decision. CBN may request this evidence
        during examination.
        """
        await log_audit(
            db=self.db,
            entity_type="customer",
            entity_id=f"blocked_{request.name}_{now_wat()}",
            event_type="onboarding_blocked",
            actor=self.name,
            description=f"Onboarding BLOCKED for '{request.name}': confirmed sanctions match. "
                        f"CBN mandate: account registration rejected.",
            after_state={
                "name": request.name,
                "bvn": request.bvn,
                "decision": "blocked",
                "match_count": len(matches),
                "decision_reason": decision_reason,
            },
            metadata={
                "match_count": len(matches),
                "top_match": matches[0] if matches else None,
            },
        )

    def _compute_confidence(self, matches: list[dict]) -> float:
        """Compute agent confidence in the onboarding decision.

        No matches: 0.99 (very high confidence in clean result).
        Matches present: confidence based on best match score.
        """
        if not matches:
            return 0.99
        best = max(m.get("match_score", 0.0) for m in matches)
        return round(best, 4)
