"""
Executive Escalation Workflow for AgenticAML.

This module manages the lifecycle of escalation records created when automated
agents encounter decisions that require senior human approval before proceeding.

Escalations are created for:
1. PEP (Politically Exposed Person) customer onboarding — requires C-suite or MLRO approval
   per FATF Recommendation 12 and CBN AML/CFT guidelines.
2. Adverse media matches at onboarding — requires Head of Compliance approval.
3. High-risk transaction patterns flagged by the Pattern Analyzer — requires
   Senior Analyst or Compliance Officer review per CBN tiered escalation policy.

SLA tracking:
- Default SLA: 24 hours (aligns with NFIU STR filing deadline).
- Critical escalations (terrorism financing, confirmed PEP corruption): 4 hours.
- All SLA deadlines stored in the escalations table as `expires_at` (WAT).
- Overdue escalations (past expires_at and still 'pending') are surfaced in the
  governance dashboard and trigger automated compliance officer notifications.

Governance controls enforced:
- Only users with the required_approver_role can act on an escalation.
- Decision rationale is mandatory for both approve and reject.
- All decisions are logged to the immutable audit trail.
- Approved PEP onboarding updates the customer's onboarding_status to 'approved'
  and elevates risk_tier to reflect the PEP EDD requirement.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import aiosqlite

from src.database import (
    get_customer,
    get_escalation,
    list_escalations,
    log_audit,
    now_wat,
    update_customer,
    update_escalation,
)
from src.governance.audit import log_human_decision

# WAT timezone — all SLA calculations in Nigerian local time
WAT = timezone(timedelta(hours=1))


class EscalationWorkflow:
    """Manages the approve/reject lifecycle for executive escalation records.

    Each method logs to the audit trail BEFORE modifying the database record
    so that even if the DB update fails, the intent is captured immutably.
    This ordering satisfies CBN's requirement for a complete decision chain
    that cannot be altered retroactively.
    """

    def __init__(self, db: aiosqlite.Connection):
        # Injected DB connection shared with the calling API handler
        self.db = db

    async def approve(
        self, escalation_id: str, decided_by: str, rationale: str
    ) -> dict[str, Any]:
        """Approve an escalation and update the underlying entity accordingly.

        Approval actions by entity_type:
        - customer_onboarding: update customer onboarding_status to 'approved'
          and ensure risk_tier reflects PEP enhanced due diligence requirement.
        - transaction: (future) update transaction status to allow processing.
        - case: (future) close or advance the case per governance workflow.

        Returns the updated escalation record.

        Raises ValueError if the escalation is not in 'pending' status.
        """
        escalation = await get_escalation(self.db, escalation_id)
        if not escalation:
            raise ValueError(f"Escalation {escalation_id} not found")
        if escalation["current_status"] != "pending":
            raise ValueError(
                f"Escalation {escalation_id} is already {escalation['current_status']} — cannot re-approve"
            )

        ts = now_wat()

        # MANDATORY: Log the human decision to the audit trail BEFORE updating the record.
        # The audit entry proves that a qualified human (decided_by) made this approval
        # decision with documented rationale — the core CBN human-in-the-loop requirement.
        await log_human_decision(
            db=self.db,
            entity_type="escalation",
            entity_id=escalation_id,
            event_type="escalation_approved",
            actor=decided_by,
            decision="approved",
            rationale=rationale,
            before_state={"current_status": "pending"},
            after_state={"current_status": "approved", "decided_by": decided_by},
        )

        # Update escalation record to 'approved' with decision metadata
        updated = await update_escalation(self.db, escalation_id, {
            "current_status": "approved",
            "decision_rationale": rationale,
            "assigned_to": decided_by,
            "decided_at": ts,
        })

        # Propagate the approval to the underlying entity
        await self._apply_approval(escalation, decided_by, rationale)

        return updated

    async def reject(
        self, escalation_id: str, decided_by: str, rationale: str
    ) -> dict[str, Any]:
        """Reject an escalation and block the underlying entity.

        Rejection actions by entity_type:
        - customer_onboarding: update customer onboarding_status to 'blocked'
          (a rejected PEP application results in account rejection).
        - Other entity types: logged but no automatic state change.

        Returns the updated escalation record.

        Raises ValueError if the escalation is not in 'pending' status.
        """
        escalation = await get_escalation(self.db, escalation_id)
        if not escalation:
            raise ValueError(f"Escalation {escalation_id} not found")
        if escalation["current_status"] != "pending":
            raise ValueError(
                f"Escalation {escalation_id} is already {escalation['current_status']} — cannot re-reject"
            )

        ts = now_wat()

        # Log the rejection decision to the audit trail before modifying the record
        await log_human_decision(
            db=self.db,
            entity_type="escalation",
            entity_id=escalation_id,
            event_type="escalation_rejected",
            actor=decided_by,
            decision="rejected",
            rationale=rationale,
            before_state={"current_status": "pending"},
            after_state={"current_status": "rejected", "decided_by": decided_by},
        )

        updated = await update_escalation(self.db, escalation_id, {
            "current_status": "rejected",
            "decision_rationale": rationale,
            "assigned_to": decided_by,
            "decided_at": ts,
        })

        # Propagate the rejection to the underlying entity
        await self._apply_rejection(escalation, decided_by, rationale)

        return updated

    async def get_pending_escalations(
        self, required_approver_role: str | None = None, limit: int = 100
    ) -> list[dict]:
        """Return pending escalations, optionally filtered by required approver role.

        Used by the dashboard to show each compliance role only the escalations
        they are authorised and responsible to decide. An MLRO sees MLRO-level
        escalations; a senior analyst sees analyst-level escalations.

        Also annotates each record with is_overdue based on the expires_at
        timestamp so the UI can render SLA breach indicators.
        """
        escalations = await list_escalations(
            self.db,
            current_status="pending",
            required_approver_role=required_approver_role,
            limit=limit,
        )
        now = datetime.now(WAT)
        for esc in escalations:
            # Compute SLA breach status for dashboard urgency indicators
            expires_at_str = esc.get("expires_at")
            if expires_at_str:
                try:
                    expires_at = datetime.fromisoformat(expires_at_str)
                    if expires_at.tzinfo is None:
                        expires_at = expires_at.replace(tzinfo=WAT)
                    esc["is_overdue"] = now > expires_at
                    esc["hours_remaining"] = round((expires_at - now).total_seconds() / 3600, 1)
                except (ValueError, TypeError):
                    esc["is_overdue"] = False
                    esc["hours_remaining"] = None
            else:
                esc["is_overdue"] = False
                esc["hours_remaining"] = None
        return escalations

    async def expire_overdue_escalations(self) -> int:
        """Mark all pending escalations past their SLA deadline as 'expired'.

        Called by a scheduled job or on-demand. Expired escalations remain in
        the DB as a compliance record — they are never deleted. The compliance
        officer must still take action on expired escalations, but they are
        now flagged as SLA breaches for management reporting.

        Returns the count of escalations marked as expired.
        """
        all_pending = await list_escalations(self.db, current_status="pending", limit=1000)
        now = datetime.now(WAT)
        expired_count = 0

        for esc in all_pending:
            expires_at_str = esc.get("expires_at")
            if not expires_at_str:
                continue
            try:
                expires_at = datetime.fromisoformat(expires_at_str)
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=WAT)
                if now > expires_at:
                    # SLA has breached — mark as expired and log the SLA failure
                    await update_escalation(self.db, esc["id"], {"current_status": "expired"})
                    await log_audit(
                        db=self.db,
                        entity_type="escalation",
                        entity_id=esc["id"],
                        event_type="escalation_expired",
                        actor="governance_engine",
                        description=f"Escalation SLA BREACHED: {esc['escalation_reason']} for "
                                    f"entity {esc['entity_id']}. Required approver: "
                                    f"{esc['required_approver_role']}.",
                        metadata={"entity_type": esc["entity_type"], "entity_id": esc["entity_id"]},
                    )
                    expired_count += 1
            except (ValueError, TypeError):
                pass

        return expired_count

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _apply_approval(
        self, escalation: dict, decided_by: str, rationale: str
    ) -> None:
        """Apply the downstream effects of an approval decision.

        For customer_onboarding escalations: activate the customer account
        with onboarding_status='approved' and ensure PEP customers have
        risk_tier='very_high' per FATF Enhanced Due Diligence requirements.
        """
        entity_type = escalation.get("entity_type")
        entity_id = escalation.get("entity_id")

        if entity_type == "customer_onboarding":
            customer = await get_customer(self.db, entity_id)
            if customer:
                updates: dict[str, Any] = {"onboarding_status": "approved"}
                # PEP customers approved for onboarding must be at very_high risk tier
                # per FATF Recommendation 12 Enhanced Due Diligence requirement.
                if customer.get("pep_status") == 1:
                    updates["risk_tier"] = "very_high"
                await update_customer(self.db, entity_id, updates)

                # Log the account activation event so the compliance team can see
                # the full approval chain: escalation -> human decision -> account active
                await log_audit(
                    db=self.db,
                    entity_type="customer",
                    entity_id=entity_id,
                    event_type="onboarding_approved",
                    actor=decided_by,
                    description=f"Customer onboarding APPROVED by {decided_by}: {rationale}",
                    metadata={"decided_by": decided_by, "rationale": rationale},
                )

    async def _apply_rejection(
        self, escalation: dict, decided_by: str, rationale: str
    ) -> None:
        """Apply the downstream effects of a rejection decision.

        For customer_onboarding escalations: update onboarding_status to 'blocked'
        so the customer cannot transact and the dashboard shows the rejection.
        The customer record is preserved (not deleted) for audit purposes.
        """
        entity_type = escalation.get("entity_type")
        entity_id = escalation.get("entity_id")

        if entity_type == "customer_onboarding":
            customer = await get_customer(self.db, entity_id)
            if customer:
                await update_customer(self.db, entity_id, {"onboarding_status": "blocked"})
                await log_audit(
                    db=self.db,
                    entity_type="customer",
                    entity_id=entity_id,
                    event_type="onboarding_rejected",
                    actor=decided_by,
                    description=f"Customer onboarding REJECTED by {decided_by}: {rationale}",
                    metadata={"decided_by": decided_by, "rationale": rationale},
                )
