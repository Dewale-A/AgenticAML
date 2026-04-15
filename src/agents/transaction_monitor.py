"""
Agent 1: Transaction Monitor

The first agent in the 6-stage AML pipeline. Applies rule-based threshold
monitoring to individual transactions in real time.

CBN requires real-time transaction monitoring for all Tier-3 accounts and
for any transaction above the cash reporting threshold (NGN 5M). This agent
fulfils that requirement by checking each transaction against configurable
rules before it is processed.

Detection rules implemented:
  1. CASH_THRESHOLD        — cash txns ≥ NGN 5M (CBN Currency Transaction Report trigger)
  2. TRANSFER_THRESHOLD    — transfers ≥ NGN 10M (enhanced monitoring trigger)
  3. VELOCITY_COUNT        — >10 transactions in 24h window (layering indicator)
  4. VELOCITY_AMOUNT       — >NGN 20M cumulative in 24h (large-value velocity)
  5. STRUCTURING           — multiple cash txns just below the cash threshold (smurfing)
  6. DORMANT_ACCOUNT       — sudden activity after 90+ days dormancy
  7. ROUND_AMOUNT          — large round-number transactions (classic ML indicator)
  8. HIGH_RISK_GEOGRAPHY   — transactions involving FATF high-risk jurisdictions
  9. INTERNATIONAL_WIRE    — large cross-border wires requiring enhanced due diligence
"""

from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import aiosqlite

from src.database import (
    get_customer,
    get_customer_transactions,
    update_transaction_status,
    log_audit,
    now_wat,
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


class TransactionMonitorAgent:
    name = "transaction_monitor_agent"

    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def screen(self, transaction: Dict[str, Any]) -> TransactionMonitorResult:
        """Screen a single transaction against all configured AML rules.

        This is the primary screening method, called for every transaction
        in the pipeline. It runs all rule checks, computes a composite risk
        score, updates the transaction status in the DB, and logs to the
        audit trail before returning.

        Returns a TransactionMonitorResult with:
        - risk_score: 0.0–1.0 composite risk score
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

        triggered_rules: List[TriggeredRule] = []
        # risk_factors are individual rule scores combined by _compute_risk_score()
        risk_factors: List[float] = []

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

        # 3–5. Velocity and structuring checks require transaction history
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

            # 6. Dormant account detection
            # Accounts with no activity for 90+ days that suddenly receive large
            # deposits are a known indicator of account takeover or money mule
            # activity. The agent checks for a gap of at least 90 days before
            # the recent activity burst.
            dormant = await self._is_dormant_account(customer_id, recent_txns)
            if dormant:
                triggered_rules.append(
                    TriggeredRule(
                        rule="DORMANT_ACCOUNT",
                        description="Sudden activity on previously dormant account (no transactions in 90+ days)",
                    )
                )
                risk_factors.append(0.6)

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
        # deficiencies in their AML/CFT frameworks or active sanctions:
        # IR=Iran, KP=North Korea, SY=Syria, CU=Cuba, SD=Sudan, YE=Yemen,
        # LY=Libya, MM=Myanmar.
        high_risk_geos = ["IR", "KP", "SY", "CU", "SD", "YE", "LY", "MM"]
        if any(code in (geo_location or "").upper() for code in high_risk_geos):
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

    async def _get_recent_transactions(self, customer_id: str, hours: int) -> List[Dict]:
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

    def _detect_structuring(self, recent_txns: List[Dict], threshold: float) -> int:
        """Count cash transactions just below the reporting threshold.

        Structuring (smurfing) is deliberately keeping cash deposits below
        a reporting threshold to avoid detection. FATF defines the typical
        structuring band as 80–99% of the threshold; we use 90% (configurable
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

    async def _is_dormant_account(self, customer_id: str, recent_txns: List[Dict]) -> bool:
        """Detect if an account was dormant for 90+ days before recent activity.

        Logic:
        1. If there are recent transactions (last 7 days), fetch 6-month history.
        2. Check if there were zero transactions in the 90-day window (7–97 days ago).
        3. If no activity in that window, the account was dormant before the burst.

        The 97-day outer bound (90 + 7) accounts for the 7-day 'recent' window
        without creating a gap that would miss the dormancy.
        """
        if recent_txns:
            # Has recent activity: check if there was nothing in the 90 days before that
            all_txns = await get_customer_transactions(self.db, customer_id, days=180)
            # Filter to older than 7 days
            cutoff_recent = datetime.now(WAT) - timedelta(days=7)
            cutoff_dormant = datetime.now(WAT) - timedelta(days=97)
            older_txns = [
                t for t in all_txns
                if t.get("timestamp")
                and self._parse_ts(t["timestamp"]) < cutoff_recent
                and self._parse_ts(t["timestamp"]) > cutoff_dormant
            ]
            # Dormant if zero transactions in the 90-day look-back window
            # (but there were some even older transactions, confirming it's
            # a real account, not a new one)
            if len(older_txns) == 0 and len(all_txns) > len(recent_txns):
                return True
        return False

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

    def _compute_risk_score(self, risk_factors: List[float], amount: float) -> float:
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
