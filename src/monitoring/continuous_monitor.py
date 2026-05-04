"""
Continuous Monitoring Engine for AgenticAML.

Implements the scheduled re-screening job (Layer 3, ROADMAP Section 1) that
periodically screens all customers against current watchlist versions and
detects new matches that were not present during the customer's last screening.

Key capabilities:
1. Periodic re-screening: all customers screened on a configurable schedule
   (daily, weekly, or on list update). CBN recommends at minimum monthly
   re-screening of all customers.

2. Delta detection: compares current customer base against newly added list
   entries. A customer who was clean at onboarding may appear on a new list
   version — this engine detects that change and triggers an alert.

3. Risk score recalculation: when a customer's screening result changes
   (new match found, match removed), their risk tier is re-evaluated and
   may be upgraded automatically per governance rules.

4. Audit trail: every monitoring run and every new match discovered is logged
   to the immutable audit trail so CBN examiners can verify screening cadence.

Monitoring run lifecycle:
  1. create_monitoring_run() → status='running'
  2. Screen all customers → collect new matches
  3. Create alerts for new matches
  4. Update customer risk tiers if upgraded
  5. update_monitoring_run() → status='completed'
  6. Log summary to audit trail
"""

from __future__ import annotations

import json
from datetime import timedelta, timezone
from typing import Any

import aiosqlite

from src.agents.sanctions_screener import SanctionsScreenerAgent
from src.data.sanctions_lists import SANCTIONS_DB
from src.database import (
    create_alert,
    create_monitoring_run,
    create_sanctions_match,
    list_customers,
    list_sanctions_matches,
    log_audit,
    now_wat,
    update_customer,
    update_monitoring_run,
)
from src.monitoring.list_manager import ListManager

# WAT timezone — all monitoring timestamps in Nigerian local time
WAT = timezone(timedelta(hours=1))

# Risk tier upgrade threshold: a 'strong' or 'exact' new match triggers
# an automatic upgrade to 'very_high' risk. 'partial' upgrades to 'high'.
# This maps to CBN AML/CFT guidelines on enhanced monitoring for high-risk customers.
MATCH_TYPE_TO_RISK_TIER = {
    "exact": "very_high",
    "strong": "very_high",
    "partial": "high",
    "weak": "medium",
}


class ContinuousMonitor:
    """Re-screens all customers against current watchlists and detects new matches.

    Called by POST /monitoring/run (manual trigger) and by the scheduler
    for automated periodic runs. Each run is tracked in the monitoring_runs
    table so the compliance team has a full history of screening cadence.
    """

    def __init__(self, db: aiosqlite.Connection):
        self.db = db
        self._screener = SanctionsScreenerAgent(db)
        self._list_manager = ListManager(db)

    async def run(self, run_type: str = "manual", metadata: dict | None = None) -> dict[str, Any]:
        """Execute a full customer re-screening run.

        Steps:
        1. Refresh list metadata (checksum/version tracking).
        2. Create a monitoring run record with status='running'.
        3. Fetch all customers from the DB.
        4. For each customer: screen against all lists, compare to existing matches.
        5. Create alerts for new matches. Upgrade risk tiers where warranted.
        6. Mark the run as 'completed' with summary counts.
        7. Log the run summary to the audit trail.

        Returns the completed monitoring run record.
        """
        # Refresh list metadata before screening so run record reflects current list versions
        await self._list_manager.refresh_all_lists()

        ts = now_wat()
        run = await create_monitoring_run(self.db, {
            "run_type": run_type,
            "started_at": ts,
            "status": "running",
            "metadata": json.dumps(metadata or {}),
        })
        run_id = run["id"]

        customers_screened = 0
        new_matches = 0
        risk_upgrades = 0

        try:
            # Fetch all customers. In production, this would be batched to avoid
            # loading all customers into memory simultaneously. For the demo with
            # up to ~50 customers, a single fetch is acceptable.
            all_customers = await list_customers(self.db, limit=10000)

            for customer in all_customers:
                customer_id = customer["id"]
                customer_name = customer.get("name", "")

                if not customer_name:
                    continue

                # Screen this customer against all current lists
                aliases = []  # In production: fetch stored aliases for the customer
                screening_result = await self._screen_customer(
                    customer_id=customer_id,
                    name=customer_name,
                    aliases=aliases,
                    date_of_birth=customer.get("date_of_birth"),
                )
                customers_screened += 1

                # Compare new matches against existing match records to find deltas
                delta = await self._find_new_matches(customer_id, screening_result["matches"])
                if delta:
                    new_matches += len(delta)
                    # Create an alert for each new match discovered by monitoring
                    for match in delta:
                        await self._create_monitoring_alert(customer, match, run_id)

                    # Upgrade customer risk tier if any new match warrants it
                    upgraded = await self._maybe_upgrade_risk_tier(customer, delta)
                    if upgraded:
                        risk_upgrades += 1

            # Mark run as completed
            completed_run = await update_monitoring_run(self.db, run_id, {
                "status": "completed",
                "completed_at": now_wat(),
                "customers_screened": customers_screened,
                "new_matches": new_matches,
                "risk_upgrades": risk_upgrades,
            })

            # Log the run summary to the audit trail for regulatory evidence
            await log_audit(
                db=self.db,
                entity_type="monitoring_run",
                entity_id=run_id,
                event_type="monitoring_run_completed",
                actor="continuous_monitor",
                description=f"Monitoring run {run_type} completed: {customers_screened} customers screened, "
                            f"{new_matches} new matches, {risk_upgrades} risk tier upgrades.",
                metadata={
                    "run_type": run_type,
                    "customers_screened": customers_screened,
                    "new_matches": new_matches,
                    "risk_upgrades": risk_upgrades,
                },
            )

            return completed_run

        except Exception as e:
            # Mark run as failed and propagate the error information for debugging.
            # Failed runs are not retried automatically — manual investigation is required.
            await update_monitoring_run(self.db, run_id, {
                "status": "failed",
                "completed_at": now_wat(),
                "customers_screened": customers_screened,
                "metadata": json.dumps({"error": str(e), **(metadata or {})}),
            })
            raise

    async def _screen_customer(
        self,
        customer_id: str,
        name: str,
        aliases: list[str],
        date_of_birth: str | None,
    ) -> dict[str, Any]:
        """Screen a single customer against all SANCTIONS_DB lists.

        Returns a dict with 'matches' list containing all matches above
        the WEAK_THRESHOLD. Uses the same SanctionsScreenerAgent logic
        as transaction-level screening to ensure consistency.
        """
        all_names = [name] + aliases
        matches = []

        for list_name, entries in SANCTIONS_DB.items():
            match_category = self._screener._list_to_category(list_name)
            for entry in entries:
                best_score, best_name = self._screener._best_match_score(all_names, entry)
                if best_score >= 0.55:  # WEAK_THRESHOLD
                    match_type = self._screener._score_to_type(best_score)
                    action = self._screener._determine_action(match_type, entry, date_of_birth)
                    matches.append({
                        "list_name": list_name,
                        "matched_entity": entry.get("name", ""),
                        "match_type": match_type,
                        "match_score": round(best_score, 4),
                        "action_taken": action,
                        "match_category": match_category,
                    })

        return {"customer_id": customer_id, "matches": matches}

    async def _find_new_matches(
        self, customer_id: str, current_matches: list[dict]
    ) -> list[dict]:
        """Compare current screening results to stored matches to find new hits.

        A match is 'new' if no existing record in sanctions_matches has the
        same list_name and matched_entity for this customer. This prevents
        duplicate alerts for the same match across multiple monitoring runs.
        """
        existing = await list_sanctions_matches(self.db, customer_id=customer_id, limit=1000)
        # Build a set of (list_name, matched_entity) tuples for fast lookup
        existing_keys = {
            (m.get("list_name", ""), m.get("matched_entity", "")) for m in existing
        }

        new = []
        for match in current_matches:
            key = (match.get("list_name", ""), match.get("matched_entity", ""))
            if key not in existing_keys:
                new.append(match)

        return new

    async def _create_monitoring_alert(
        self, customer: dict, match: dict, run_id: str
    ) -> None:
        """Create an alert for a new watchlist match discovered during monitoring.

        Alert type is CONTINUOUS_MONITORING_MATCH with severity based on match type:
        - exact/strong: critical
        - partial: high
        - weak: medium

        The alert description includes the run_id so compliance analysts can link
        the alert back to the specific monitoring run that detected it.
        """
        severity_map = {"exact": "critical", "strong": "critical", "partial": "high", "weak": "medium"}
        match_type = match.get("match_type", "weak")
        severity = severity_map.get(match_type, "medium")

        await create_alert(self.db, {
            "customer_id": customer["id"],
            "transaction_id": None,
            "agent_source": "continuous_monitor",
            "alert_type": "CONTINUOUS_MONITORING_MATCH",
            "severity": severity,
            "description": (
                f"NEW WATCHLIST MATCH (Monitoring Run {run_id[:8]}...): "
                f"Customer '{customer.get('name')}' newly matched against {match.get('list_name')} "
                f"({match_type} match, score {match.get('match_score', 0):.2f}). "
                f"Category: {match.get('match_category', 'sanctions')}."
            ),
            "confidence": match.get("match_score", 0.5),
            "status": "open",
        })

        # Also persist the new match to sanctions_matches for the watchlist screening tab
        try:
            await create_sanctions_match(self.db, {
                "customer_id": customer["id"],
                "transaction_id": None,
                "list_name": match.get("list_name", ""),
                "matched_entity": match.get("matched_entity", ""),
                "match_type": match_type,
                "match_score": match.get("match_score"),
                "action_taken": match.get("action_taken", "review"),
                "match_category": match.get("match_category", "sanctions"),
            })
        except Exception:
            pass  # Match persistence must not fail the monitoring run

    async def _maybe_upgrade_risk_tier(
        self, customer: dict, new_matches: list[dict]
    ) -> bool:
        """Upgrade a customer's risk tier if new matches warrant it.

        Returns True if the risk tier was upgraded, False otherwise.

        Risk tier upgrades are one-directional during monitoring — the system
        never auto-downgrades a risk tier. Downgrading requires human approval
        per governance rules (RiskTierUpdate with approved_by field).
        """
        if not new_matches:
            return False

        # Find the worst match type among new matches
        worst_type = max(
            new_matches,
            key=lambda m: {"exact": 4, "strong": 3, "partial": 2, "weak": 1}.get(
                m.get("match_type", "weak"), 1
            ),
        ).get("match_type", "weak")

        target_tier = MATCH_TYPE_TO_RISK_TIER.get(worst_type, "medium")
        current_tier = customer.get("risk_tier", "low")

        # Tier ordering for comparison
        tier_order = {"low": 1, "medium": 2, "high": 3, "very_high": 4}
        if tier_order.get(target_tier, 0) > tier_order.get(current_tier, 0):
            await update_customer(self.db, customer["id"], {"risk_tier": target_tier})
            await log_audit(
                db=self.db,
                entity_type="customer",
                entity_id=customer["id"],
                event_type="risk_tier_upgraded",
                actor="continuous_monitor",
                description=f"Risk tier upgraded from {current_tier} to {target_tier} "
                            f"due to new {worst_type} watchlist match.",
                before_state={"risk_tier": current_tier},
                after_state={"risk_tier": target_tier},
                metadata={"trigger": "continuous_monitoring", "match_type": worst_type},
            )
            return True

        return False
