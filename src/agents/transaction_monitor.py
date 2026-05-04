"""
Agent 1: Transaction Monitor

The first agent in the 6-stage AML pipeline. Applies rule-based threshold
monitoring to individual transactions in real time.

CBN requires real-time transaction monitoring for all Tier-3 accounts and
for any transaction above the cash reporting threshold (NGN 5M). This agent
fulfils that requirement by checking each transaction against configurable
rules before it is processed.

Detection rules implemented:
  1.  CASH_THRESHOLD           — cash txns >= NGN 5M (CBN Currency Transaction Report trigger)
  2.  TRANSFER_THRESHOLD       — transfers >= NGN 10M (enhanced monitoring trigger)
  3.  VELOCITY_COUNT           — >10 transactions in 24h window (layering indicator)
  4.  VELOCITY_AMOUNT          — >NGN 20M cumulative in 24h (large-value velocity)
  5.  STRUCTURING              — multiple cash txns just below the cash threshold (smurfing)
  6.  DORMANT_REACTIVATION     — sudden activity after 180+ days dormancy (CBN Section 4)
  7.  ROUND_AMOUNT             — large round-number transactions (classic ML indicator)
  8.  HIGH_RISK_GEOGRAPHY      — transactions involving FATF high-risk jurisdictions
  9.  INTERNATIONAL_WIRE       — large cross-border wires requiring enhanced due diligence
  10. VELOCITY_BURST           — frequency spike >3x customer's 90-day baseline in 24h
  11. CROSS_BORDER_CONCENTRATION — >30% of monthly volume to high-risk jurisdictions (FATF R.16)
  12. ROUND_TRIP_DETECTION     — funds leaving and returning via intermediaries within 30 days
  13. NEW_ACCOUNT_RAPID_ACTIVITY — >10 txns or >NGN 5M within first 30 days of account opening
  14. COUNTERPARTY_RISK        — transaction with a previously flagged counterparty
  15. TIME_OF_DAY_ANOMALY      — transaction outside customer's established time-of-day pattern
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import aiosqlite

from src.database import (
    get_customer,
    get_customer_transactions,
    now_wat,
    update_customer,
    update_transaction_status,
)
from src.governance.audit import log_agent_decision
from src.governance.rules import RULES
from src.models import TransactionMonitorResult, TriggeredRule

# WAT timezone used for timestamp comparisons — ensures velocity windows
# and dormancy checks are evaluated against Nigerian business time.
WAT = timezone(timedelta(hours=1))

# Cache threshold values at module load for performance (avoid dict lookups
# in the hot path where every transaction is screened).
CASH_THRESHOLD = RULES.thresholds.cash_threshold          # NGN 5M
TRANSFER_THRESHOLD = RULES.thresholds.transfer_threshold  # NGN 10M
VELOCITY_WINDOW = RULES.thresholds.velocity_window_hours  # 24h
VELOCITY_MAX_TXN = RULES.thresholds.velocity_max_transactions  # 10 txns
VELOCITY_MAX_AMT = RULES.thresholds.velocity_max_amount   # NGN 20M
STRUCTURING_PCT = RULES.thresholds.structuring_threshold_pct   # 0.9 (90%)

# Enhanced monitoring thresholds (ROADMAP Phase 1).
# These are read once at module load so env-var changes require a restart,
# which is acceptable for threshold parameters in an enterprise AML context.
DORMANT_THRESHOLD_DAYS = RULES.thresholds.dormant_threshold_days          # 180 days
DORMANT_SEVERITY = RULES.thresholds.dormant_reactivation_severity         # 'high'
NEW_ACCOUNT_WINDOW = RULES.thresholds.new_account_window_days             # 30 days
NEW_ACCOUNT_TXN_LIMIT = RULES.thresholds.new_account_txn_threshold        # 10 txns
NEW_ACCOUNT_AMT_LIMIT = RULES.thresholds.new_account_amount_threshold     # NGN 5M
VELOCITY_BURST_MULT = RULES.thresholds.velocity_burst_multiplier          # 3.0x
CROSS_BORDER_PCT = RULES.thresholds.cross_border_concentration_pct        # 0.30 (30%)
ROUND_TRIP_WINDOW = RULES.thresholds.round_trip_window_days               # 30 days

# FATF/CBN high-risk jurisdictions (updated list including OFAC-sanctioned countries
# and FATF grey-list additions as of 2026). Used by multiple rule checks.
HIGH_RISK_GEOS = ["IR", "KP", "SY", "CU", "SD", "YE", "LY", "MM", "RU", "BY"]


class TransactionMonitorAgent:
    name = "transaction_monitor_agent"

    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def screen(self, transaction: dict[str, Any]) -> TransactionMonitorResult:
        """Screen a single transaction against all configured AML rules.

        This is the primary screening method, called for every transaction
        in the pipeline. It runs all rule checks, computes a composite risk
        score, updates the transaction status in the DB, and logs to the
        audit trail before returning.

        Returns a TransactionMonitorResult with:
        - risk_score: 0.0-1.0 composite risk score
        - triggered_rules: list of all rules that fired
        - status: 'flagged' or 'cleared'
        - confidence: agent certainty about its risk assessment
        """
        txn_id = transaction["id"]
        customer_id = transaction.get("customer_id", "")
        amount = float(transaction.get("amount", 0))
        currency = transaction.get("currency", "NGN")
        txn_type = transaction.get("transaction_type", "transfer")
        channel = transaction.get("channel", "unknown")
        direction = transaction.get("direction", "outbound")
        geo_location = transaction.get("geo_location", "")
        timestamp_str = transaction.get("timestamp", now_wat())

        triggered_rules: list[TriggeredRule] = []
        # risk_factors are individual rule scores combined by _compute_risk_score()
        risk_factors: list[float] = []

        # 1. Cash threshold check
        # CBN requires a Currency Transaction Report (CTR) for any cash
        # transaction ≥ NGN 5M. This rule flags such transactions for CTR
        # generation and enhanced review.
        if txn_type in ("cash_deposit", "cash_withdrawal") and amount >= CASH_THRESHOLD:
            triggered_rules.append(
                TriggeredRule(
                    rule="CASH_THRESHOLD",
                    description=f"Cash transaction of NGN {amount:,.2f} exceeds NGN {CASH_THRESHOLD:,.2f} reporting threshold",
                    threshold=CASH_THRESHOLD,
                    observed=amount,
                )
            )
            risk_factors.append(0.6)

        # 2. Transfer threshold check
        # Large electronic transfers above NGN 10M trigger enhanced monitoring.
        # International wires have a lower practical threshold due to cross-border
        # risk exposure (see rule 9 below).
        if txn_type in ("transfer", "international_wire") and amount >= TRANSFER_THRESHOLD:
            triggered_rules.append(
                TriggeredRule(
                    rule="TRANSFER_THRESHOLD",
                    description=f"Transfer of NGN {amount:,.2f} exceeds NGN {TRANSFER_THRESHOLD:,.2f} threshold",
                    threshold=TRANSFER_THRESHOLD,
                    observed=amount,
                )
            )
            risk_factors.append(0.55)

        # 3-6. Velocity, structuring, and dormancy checks require transaction history
        if customer_id:
            recent_txns = await self._get_recent_transactions(customer_id, VELOCITY_WINDOW)
            txn_count = len(recent_txns)
            total_recent_amt = sum(float(t.get("amount", 0)) for t in recent_txns)

            # 3. Velocity count check
            # More than 10 transactions in 24h is an indicator of layering —
            # breaking a large sum into many smaller transactions across
            # multiple accounts or time periods.
            if txn_count >= VELOCITY_MAX_TXN:
                triggered_rules.append(
                    TriggeredRule(
                        rule="VELOCITY_COUNT",
                        description=f"{txn_count} transactions in {VELOCITY_WINDOW}h window (max: {VELOCITY_MAX_TXN})",
                        threshold=float(VELOCITY_MAX_TXN),
                        observed=float(txn_count),
                    )
                )
                risk_factors.append(0.5)

            # 4. Velocity amount check
            # Even if individual transactions are below reporting thresholds,
            # cumulative velocity above NGN 20M in 24h suggests coordinated
            # layering activity.
            if total_recent_amt >= VELOCITY_MAX_AMT:
                triggered_rules.append(
                    TriggeredRule(
                        rule="VELOCITY_AMOUNT",
                        description=f"Total NGN {total_recent_amt:,.2f} in {VELOCITY_WINDOW}h (max: NGN {VELOCITY_MAX_AMT:,.2f})",
                        threshold=VELOCITY_MAX_AMT,
                        observed=total_recent_amt,
                    )
                )
                risk_factors.append(0.55)

            # 5. Structuring detection
            # More than 2 cash transactions between 90% and 100% of the cash
            # threshold is a classic structuring (smurfing) pattern — deliberately
            # keeping amounts just below the reporting threshold to avoid CTR
            # filing. The 3-transaction minimum reduces false positives from
            # legitimate recurring payments.
            structuring_hits = self._detect_structuring(recent_txns, CASH_THRESHOLD)
            if structuring_hits > 2:
                triggered_rules.append(
                    TriggeredRule(
                        rule="STRUCTURING",
                        description=f"{structuring_hits} transactions detected just below NGN {CASH_THRESHOLD:,.2f} threshold (potential smurfing/structuring)",
                        threshold=float(structuring_hits),
                        observed=float(structuring_hits),
                    )
                )
                risk_factors.append(0.75)

            # 6. Dormant account reactivation detection (enhanced — 180-day threshold).
            # CBN AML/CFT Guidelines Section 4 defines dormancy as 6 months (180 days)
            # of inactivity. Reactivation with immediate high-value transactions is a
            # strong money mule and account-takeover indicator. This check is more
            # precise than the previous 90-day version and persists dormancy state
            # to the customer record so continuous monitoring can track it.
            dormant_result = await self.check_dormant_reactivation(customer_id, transaction)
            if dormant_result["triggered"]:
                severity_note = "(high-risk: >1 year inactive)" if dormant_result.get("days_inactive", 0) > 365 else ""
                triggered_rules.append(
                    TriggeredRule(
                        rule="DORMANT_REACTIVATION",
                        description=f"Account reactivated after {dormant_result.get('days_inactive', 0)} days of inactivity {severity_note}".strip(),
                        threshold=float(DORMANT_THRESHOLD_DAYS),
                        observed=float(dormant_result.get("days_inactive", 0)),
                    )
                )
                risk_factors.append(0.65 if dormant_result.get("days_inactive", 0) > 365 else 0.55)

            # 10. Velocity burst detection (new — ROADMAP Phase 1).
            # A sudden spike in transaction frequency vs. the customer's 90-day
            # baseline is a behavioural anomaly. A 3x burst in 24h indicates
            # possible account compromise or rapid layering activity.
            burst_result = await self._check_velocity_burst(customer_id, txn_count)
            if burst_result["triggered"]:
                triggered_rules.append(
                    TriggeredRule(
                        rule="VELOCITY_BURST",
                        description=f"Transaction frequency {burst_result['observed']:.1f}x baseline in 24h (threshold: {VELOCITY_BURST_MULT}x)",
                        threshold=VELOCITY_BURST_MULT,
                        observed=burst_result["observed"],
                    )
                )
                risk_factors.append(0.6)

            # 11. Cross-border concentration (new — FATF Recommendation 16).
            # If more than 30% of the customer's monthly transaction volume flows
            # to or from high-risk jurisdictions, the account warrants enhanced
            # due diligence regardless of individual transaction amounts.
            cross_border_result = await self._check_cross_border_concentration(customer_id)
            if cross_border_result["triggered"]:
                triggered_rules.append(
                    TriggeredRule(
                        rule="CROSS_BORDER_CONCENTRATION",
                        description=f"{cross_border_result['pct']:.0%} of monthly volume to/from high-risk jurisdictions (threshold: {CROSS_BORDER_PCT:.0%}). FATF Recommendation 16.",
                        threshold=CROSS_BORDER_PCT,
                        observed=cross_border_result["pct"],
                    )
                )
                risk_factors.append(0.65)

            # 12. Round-tripping detection (new — ROADMAP Phase 1).
            # Funds that depart and return to the same account within 30 days
            # via intermediaries are a layering indicator. This rule checks
            # whether the current inbound amount closely matches a recent outbound
            # amount from this customer — a simplified heuristic for the full pattern.
            round_trip = await self._check_round_tripping(customer_id, amount, direction)
            if round_trip["triggered"]:
                triggered_rules.append(
                    TriggeredRule(
                        rule="ROUND_TRIP_DETECTION",
                        description=f"Inbound amount NGN {amount:,.2f} closely matches outbound amount NGN {round_trip['matched_amount']:,.2f} within {ROUND_TRIP_WINDOW}-day window (potential layering).",
                    )
                )
                risk_factors.append(0.7)

            # 13. New account rapid activity (new — ROADMAP Phase 1).
            # High transaction volume within the first 30 days of account opening
            # is a placement risk indicator. Criminals often use newly opened
            # accounts to inject illicit funds before the monitoring system builds
            # a behavioural baseline for the account.
            new_acct_result = await self._check_new_account_activity(customer_id)
            if new_acct_result["triggered"]:
                triggered_rules.append(
                    TriggeredRule(
                        rule="NEW_ACCOUNT_RAPID_ACTIVITY",
                        description=f"New account: {new_acct_result['txn_count']} transactions or NGN {new_acct_result['total_amount']:,.2f} total within first {NEW_ACCOUNT_WINDOW} days (thresholds: {NEW_ACCOUNT_TXN_LIMIT} txns or NGN {NEW_ACCOUNT_AMT_LIMIT:,.2f}).",
                        threshold=float(NEW_ACCOUNT_TXN_LIMIT),
                        observed=float(new_acct_result["txn_count"]),
                    )
                )
                risk_factors.append(0.55)

            # 14. Counterparty risk scoring (new — ROADMAP Phase 1).
            # If the counterparty name on this transaction has previously been flagged
            # by another agent (e.g., appeared in sanctions matches or alerts), the
            # risk of this transaction is elevated regardless of its own characteristics.
            counterparty_name = transaction.get("counterparty_name", "")
            if counterparty_name:
                cp_result = await self._check_counterparty_risk(counterparty_name)
                if cp_result["triggered"]:
                    triggered_rules.append(
                        TriggeredRule(
                            rule="COUNTERPARTY_RISK",
                            description=f"Counterparty '{counterparty_name}' has been flagged by prior agent screening ({cp_result['reason']}).",
                        )
                    )
                    risk_factors.append(0.65)

            # 15. Time-of-day anomaly (new — ROADMAP Phase 1).
            # Transactions at unusual hours (2am-5am WAT) outside the customer's
            # established pattern are a behavioural anomaly. Cross-border layering
            # often occurs in off-hours to exploit reduced monitoring intensity.
            tod_result = self._check_time_of_day_anomaly(timestamp_str)
            if tod_result["triggered"]:
                triggered_rules.append(
                    TriggeredRule(
                        rule="TIME_OF_DAY_ANOMALY",
                        description=f"Transaction at {tod_result['hour']:02d}:00 WAT — outside standard business hours. Statistical anomaly vs. 90-day customer pattern.",
                    )
                )
                risk_factors.append(0.25)

        # 7. Round amount detection
        # Large round-number transactions (multiples of NGN 500K) are a
        # behavioural indicator of structured criminal payments. Legitimate
        # commercial payments rarely land on exact round figures at this scale.
        if self._is_round_amount(amount):
            triggered_rules.append(
                TriggeredRule(
                    rule="ROUND_AMOUNT",
                    description=f"Round amount transaction: NGN {amount:,.2f}",
                    observed=amount,
                )
            )
            risk_factors.append(0.25)

        # 8. High-risk geography check
        # FATF identifies these jurisdictions as high-risk due to strategic
        # deficiencies in their AML/CFT frameworks or active sanctions.
        # The HIGH_RISK_GEOS list is defined at module level for performance
        # and updated when FATF/CBN guidance changes.
        if any(code in (geo_location or "").upper() for code in HIGH_RISK_GEOS):
            triggered_rules.append(
                TriggeredRule(
                    rule="HIGH_RISK_GEOGRAPHY",
                    description=f"Transaction involves high-risk or sanctioned jurisdiction: {geo_location}",
                )
            )
            risk_factors.append(0.7)

        # 9. International wire threshold
        # Cross-border wires above NGN 1M require enhanced due diligence per
        # CBN forex regulations. The lower threshold (NGN 1M vs NGN 10M for
        # domestic transfers) reflects the additional risk of cross-border
        # fund flows that are harder to trace and recover.
        if txn_type == "international_wire" and amount >= 1_000_000:
            triggered_rules.append(
                TriggeredRule(
                    rule="INTERNATIONAL_WIRE",
                    description=f"International wire of NGN {amount:,.2f}: enhanced due diligence required",
                    observed=amount,
                )
            )
            risk_factors.append(0.4)

        # Calculate composite risk score from all triggered rules
        risk_score = self._compute_risk_score(risk_factors, amount)

        # A transaction is flagged if any rule fired OR the composite score
        # reaches the 0.5 threshold. This dual condition ensures that a single
        # high-confidence rule is sufficient to flag without requiring multiple
        # rules to combine.
        flagged = len(triggered_rules) > 0 or risk_score >= 0.5

        # Confidence starts at 0.6 (base) and increases with each additional
        # triggered rule (more evidence = higher certainty). Capped at 0.95
        # to preserve human reviewability of high-confidence cases.
        confidence = min(0.95, 0.6 + (len(triggered_rules) * 0.05))
        status = "flagged" if flagged else "cleared"

        # Persist the screening result back to the transaction record
        await update_transaction_status(self.db, txn_id, status, risk_score)

        # MANDATORY: Log to audit trail BEFORE returning.
        # CBN requires real-time audit logging of all screening decisions.
        await log_agent_decision(
            db=self.db,
            agent_name=self.name,
            entity_type="transaction",
            entity_id=txn_id,
            decision=status,
            confidence=confidence,
            details={
                "triggered_rules": [r.model_dump() for r in triggered_rules],
                "risk_score": risk_score,
                "amount": amount,
                "currency": currency,
                "transaction_type": txn_type,
                "channel": channel,
            },
            risk_score=risk_score,
        )

        return TransactionMonitorResult(
            transaction_id=txn_id,
            customer_id=customer_id,
            risk_score=round(risk_score, 4),
            confidence=round(confidence, 4),
            flagged=flagged,
            triggered_rules=triggered_rules,
            status=status,
            audit_logged=True,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _get_recent_transactions(self, customer_id: str, hours: int) -> list[dict]:
        """Return transactions within the velocity window (default 24h).

        Fetches the last 7 days from the DB and filters in Python to avoid
        a complex SQL time comparison that would be DB-specific. The 7-day
        window covers even the longest configurable velocity window with margin.
        """
        all_txns = await get_customer_transactions(self.db, customer_id, days=7)
        cutoff = datetime.now(WAT) - timedelta(hours=hours)
        recent = []
        for t in all_txns:
            try:
                ts = datetime.fromisoformat(t.get("timestamp", ""))
                # Normalise timezone-naive timestamps to WAT before comparison
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=WAT)
                if ts >= cutoff:
                    recent.append(t)
            except (ValueError, TypeError):
                # Skip unparseable timestamps rather than crashing the pipeline
                pass
        return recent

    def _detect_structuring(self, recent_txns: list[dict], threshold: float) -> int:
        """Count cash transactions just below the reporting threshold.

        Structuring (smurfing) is deliberately keeping cash deposits below
        a reporting threshold to avoid detection. FATF defines the typical
        structuring band as 80-99% of the threshold; we use 90% (configurable
        via STRUCTURING_THRESHOLD_PCT) to reduce false positives.
        """
        lower = threshold * STRUCTURING_PCT
        count = sum(
            1
            for t in recent_txns
            if lower <= float(t.get("amount", 0)) < threshold
            and t.get("transaction_type") in ("cash_deposit", "cash_withdrawal")
        )
        return count

    async def check_dormant_reactivation(self, customer_id: str, transaction: dict) -> dict:
        """Detect dormant account reactivation per CBN AML/CFT Guidelines Section 4.

        CBN defines dormancy as no debit or credit transactions for 180 days (6 months).
        This method:
        1. Fetches all transactions for the customer over the past 2 years.
        2. Finds the most recent transaction before the current one.
        3. If the gap exceeds DORMANT_THRESHOLD_DAYS, the rule triggers.
        4. Updates the customer record with is_dormant=0 and last_transaction_at on trigger,
           because the current transaction represents a reactivation event.

        Reactivation with immediate high-value amounts (>NGN 1M) is classified
        as 'high' severity; gradual reactivation (smaller amounts) is 'medium'.
        This is more accurate than the previous 90-day heuristic because it uses
        the actual last transaction date rather than a fixed window comparison.
        """
        # Fetch 2 years of history to reliably find the previous transaction timestamp
        all_txns = await get_customer_transactions(self.db, customer_id, days=730)
        now = datetime.now(WAT)

        # Filter out the current transaction itself (not yet committed to DB at this point)
        current_txn_id = transaction.get("id", "")
        prior_txns = [t for t in all_txns if t.get("id") != current_txn_id]

        if not prior_txns:
            # No prior transactions — this is the customer's very first transaction.
            # No dormancy to detect; will be caught by NEW_ACCOUNT_RAPID_ACTIVITY instead.
            return {"rule": "DORMANT_REACTIVATION", "triggered": False}

        # Find the most recent prior transaction timestamp
        last_ts = None
        for t in prior_txns:
            ts_str = t.get("timestamp", "")
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=WAT)
                    if last_ts is None or ts > last_ts:
                        last_ts = ts
                except (ValueError, TypeError):
                    pass

        if last_ts is None:
            return {"rule": "DORMANT_REACTIVATION", "triggered": False}

        days_inactive = (now - last_ts).days

        # Update the customer's last_transaction_at and dormancy state.
        # This keeps the dormancy fields accurate for continuous monitoring queries.
        await update_customer(self.db, customer_id, {
            "last_transaction_at": now.isoformat(),
            "is_dormant": 0,  # Account is reactivating — no longer dormant
        })

        if days_inactive >= DORMANT_THRESHOLD_DAYS:
            return {
                "rule": "DORMANT_REACTIVATION",
                "triggered": True,
                "days_inactive": days_inactive,
                "severity": DORMANT_SEVERITY,
                "description": f"Account reactivated after {days_inactive} days of inactivity",
            }
        return {"rule": "DORMANT_REACTIVATION", "triggered": False, "days_inactive": days_inactive}

    async def _check_velocity_burst(self, customer_id: str, current_24h_count: int) -> dict:
        """Detect a sudden spike in transaction frequency vs. 90-day baseline.

        Algorithm:
        1. Fetch 90 days of transaction history to establish the average daily rate.
        2. Compare today's count to the average.
        3. If today's count exceeds VELOCITY_BURST_MULTIPLIER * average, flag.

        A burst of 3x or more above baseline in 24h is statistically anomalous
        for legitimate accounts and consistent with rapid layering patterns where
        large amounts are split into many small transactions in a short window.
        """
        # Get 90-day history to compute the daily average
        txns_90d = await get_customer_transactions(self.db, customer_id, days=90)
        if len(txns_90d) < 5:
            # Insufficient history for meaningful baseline comparison.
            # New accounts are handled by the NEW_ACCOUNT_RAPID_ACTIVITY rule.
            return {"triggered": False}

        # Daily average over the 90-day window (excluding today to avoid circularity)
        cutoff_today = datetime.now(WAT) - timedelta(hours=VELOCITY_WINDOW)
        older = [
            t for t in txns_90d
            if self._parse_ts(t.get("timestamp", "")) < cutoff_today
        ]
        if not older:
            return {"triggered": False}

        avg_daily = len(older) / 89.0  # 89 days (90 minus current day)
        if avg_daily < 0.1:
            # Very low baseline — even 1 transaction today is a "spike" but not suspicious
            return {"triggered": False}

        burst_ratio = current_24h_count / avg_daily
        if burst_ratio >= VELOCITY_BURST_MULT:
            return {"triggered": True, "observed": round(burst_ratio, 2)}
        return {"triggered": False, "observed": round(burst_ratio, 2)}

    async def _check_cross_border_concentration(self, customer_id: str) -> dict:
        """Check if cross-border transactions to high-risk jurisdictions exceed 30% of monthly volume.

        FATF Recommendation 16 requires enhanced due diligence for customers with
        concentrated cross-border exposure to high-risk jurisdictions. A 30%
        threshold allows legitimate trade finance activity while flagging
        systematic routing through sanctioned or weak-governance countries.
        """
        # 30-day lookback for monthly concentration calculation
        txns_30d = await get_customer_transactions(self.db, customer_id, days=30)
        if not txns_30d:
            return {"triggered": False}

        total_amount = sum(float(t.get("amount", 0)) for t in txns_30d)
        if total_amount == 0:
            return {"triggered": False}

        # Sum amounts for transactions to/from FATF/CBN high-risk jurisdictions
        high_risk_amount = sum(
            float(t.get("amount", 0))
            for t in txns_30d
            if any(code in (t.get("geo_location") or "").upper() for code in HIGH_RISK_GEOS)
        )

        concentration = high_risk_amount / total_amount
        if concentration >= CROSS_BORDER_PCT:
            return {"triggered": True, "pct": concentration, "high_risk_amount": high_risk_amount}
        return {"triggered": False, "pct": concentration}

    async def _check_round_tripping(self, customer_id: str, amount: float, direction: str) -> dict:
        """Detect potential round-tripping: funds leaving and returning via intermediaries.

        Round-tripping is a layering technique where funds are sent out and
        return to the same account (often via shell companies or multiple hops)
        to simulate legitimate business transactions and obscure the audit trail.

        Simplified heuristic: if this is an inbound transaction, check whether a
        similar outbound amount occurred within ROUND_TRIP_WINDOW days. A match
        within 10% tolerance suggests a round-trip pattern.

        Note: Full round-trip detection requires network analysis across multiple
        accounts, which is handled by the PatternAnalyzerAgent (Agent 4).
        This rule catches the simple same-account case.
        """
        if direction != "inbound":
            # Round-trip only detectable on the return leg (inbound transaction)
            return {"triggered": False}

        # Look for outbound transactions of similar amount within the round-trip window
        txns = await get_customer_transactions(self.db, customer_id, days=ROUND_TRIP_WINDOW)
        tolerance = 0.10  # 10% tolerance to account for fees and FX slippage

        for t in txns:
            if t.get("direction") == "outbound":
                prior_amount = float(t.get("amount", 0))
                if prior_amount > 0 and abs(amount - prior_amount) / prior_amount <= tolerance:
                    # Amounts are within tolerance — potential round-trip
                    return {
                        "triggered": True,
                        "matched_amount": prior_amount,
                        "tolerance_pct": tolerance,
                    }
        return {"triggered": False}

    async def _check_new_account_activity(self, customer_id: str) -> dict:
        """Flag unusually high activity on newly opened accounts.

        New accounts (< 30 days old) with >10 transactions or >NGN 5M total
        volume are flagged. Criminal ML operations often use freshly opened
        accounts to place funds before the monitoring system develops a
        behavioural baseline, so the first 30 days require heightened scrutiny.

        Data source: customer creation timestamp from the customers table.
        """
        customer = await get_customer(self.db, customer_id)
        if not customer:
            return {"triggered": False}

        created_at_str = customer.get("created_at", "")
        if not created_at_str:
            return {"triggered": False}

        try:
            created_at = datetime.fromisoformat(created_at_str)
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=WAT)
        except (ValueError, TypeError):
            return {"triggered": False}

        account_age_days = (datetime.now(WAT) - created_at).days
        if account_age_days > NEW_ACCOUNT_WINDOW:
            # Account is older than the observation window — rule does not apply
            return {"triggered": False}

        # Check transaction volume within the account's lifetime so far
        txns = await get_customer_transactions(self.db, customer_id, days=NEW_ACCOUNT_WINDOW + 1)
        txn_count = len(txns)
        total_amount = sum(float(t.get("amount", 0)) for t in txns)

        if txn_count > NEW_ACCOUNT_TXN_LIMIT or total_amount > NEW_ACCOUNT_AMT_LIMIT:
            return {
                "triggered": True,
                "account_age_days": account_age_days,
                "txn_count": txn_count,
                "total_amount": total_amount,
            }
        return {"triggered": False, "txn_count": txn_count, "total_amount": total_amount}

    async def _check_counterparty_risk(self, counterparty_name: str) -> dict:
        """Check if this transaction's counterparty has been flagged in prior screening.

        If a counterparty name appears in the sanctions_matches table (any action),
        the current transaction is elevated because the counterparty is a known
        risk entity. This propagates risk signals from the sanctions screener
        into the transaction monitor without requiring a full re-screening.

        The check uses a case-insensitive LIKE match to handle minor name variations
        in the counterparty field (e.g., 'ABC Ltd' vs 'A.B.C. Limited').
        """
        try:
            async with self.db.execute(
                "SELECT COUNT(*) as c FROM sanctions_matches WHERE LOWER(matched_entity) LIKE LOWER(?)",
                (f"%{counterparty_name}%",),
            ) as cur:
                row = await cur.fetchone()
                match_count = row["c"] if row else 0

            if match_count > 0:
                return {
                    "triggered": True,
                    "reason": f"{match_count} prior sanctions match(es) for counterparty name",
                }
        except Exception:
            # DB errors must not crash the screening pipeline
            pass
        return {"triggered": False}

    def _check_time_of_day_anomaly(self, timestamp_str: str) -> dict:
        """Flag transactions during off-hours (02:00-05:00 WAT).

        Off-hours transactions (2am to 5am Nigerian time) are statistically
        rare for legitimate retail and commercial banking and correlate with
        automated laundering scripts, account takeover attacks, and cross-border
        layering designed to exploit reduced monitoring during Nigerian night hours.

        This is a simplified implementation. A full statistical anomaly detector
        would compare each transaction hour against the customer's personal 90-day
        distribution (implemented in PatternAnalyzerAgent). This rule catches the
        most obvious cases without requiring historical distribution analysis.
        """
        try:
            ts = datetime.fromisoformat(timestamp_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=WAT)
            hour = ts.hour
            # 02:00 to 05:00 WAT is the highest-risk window for automated ML activity
            if 2 <= hour <= 5:
                return {"triggered": True, "hour": hour}
        except (ValueError, TypeError):
            pass
        return {"triggered": False}

    def _parse_ts(self, ts_str: str) -> datetime:
        """Parse an ISO timestamp string to a timezone-aware datetime.

        Falls back to now() if parsing fails rather than raising — this
        ensures the pipeline never crashes on malformed timestamps.
        """
        try:
            ts = datetime.fromisoformat(ts_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=WAT)
            return ts
        except (ValueError, TypeError):
            return datetime.now(WAT)

    def _is_round_amount(self, amount: float) -> bool:
        """Return True if the amount is a large round number (multiple of NGN 500K).

        The NGN 500K minimum filters out ordinary round-number payments
        (e.g., NGN 50,000 service fees). Only large round amounts are
        meaningful as ML indicators.
        """
        return amount >= 500_000 and amount % 500_000 == 0

    def _compute_risk_score(self, risk_factors: list[float], amount: float) -> float:
        """Compute a composite risk score from individual rule scores and amount.

        Algorithm:
        1. If no rules fired, return a baseline score based on amount alone.
           Large amounts have inherent risk even without specific rule triggers.
        2. If rules fired, combine scores using geometric decay:
           - The highest score dominates (primary signal).
           - Each additional factor contributes at half the weight of the previous.
           This prevents score inflation when many weak rules fire simultaneously.
        3. Apply an amount multiplier for very large transactions:
           - ≥ NGN 50M: ×1.3 (near materiality threshold)
           - ≥ NGN 10M: ×1.15 (above transfer threshold)
        4. Cap at 1.0.

        The geometric decay (0.5^i) design reflects the principle that the
        first rule is the strongest signal; additional rules provide
        corroborating evidence at diminishing marginal value.
        """
        if not risk_factors:
            # Low base risk from amount alone — no rules triggered
            if amount >= 50_000_000:
                return 0.45
            elif amount >= 10_000_000:
                return 0.25
            elif amount >= 1_000_000:
                return 0.1
            return 0.05

        # Combine risk factors: max score plus geometric contributions of others
        sorted_factors = sorted(risk_factors, reverse=True)
        score = sorted_factors[0]
        for i, f in enumerate(sorted_factors[1:], 1):
            # Geometric decay: each additional factor contributes half as much
            score += f * (0.5 ** i)

        # Apply amount multiplier for materially large transactions
        if amount >= 50_000_000:
            score *= 1.3
        elif amount >= 10_000_000:
            score *= 1.15

        return min(1.0, score)
