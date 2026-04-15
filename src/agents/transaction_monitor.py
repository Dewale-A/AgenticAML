"""
Agent 1: Transaction Monitor
Screens transactions against rule-based thresholds in real time.
Covers: threshold monitoring, velocity, structuring, round amounts, dormant accounts.
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

WAT = timezone(timedelta(hours=1))

CASH_THRESHOLD = RULES.thresholds.cash_threshold
TRANSFER_THRESHOLD = RULES.thresholds.transfer_threshold
VELOCITY_WINDOW = RULES.thresholds.velocity_window_hours
VELOCITY_MAX_TXN = RULES.thresholds.velocity_max_transactions
VELOCITY_MAX_AMT = RULES.thresholds.velocity_max_amount
STRUCTURING_PCT = RULES.thresholds.structuring_threshold_pct


class TransactionMonitorAgent:
    name = "transaction_monitor_agent"

    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def screen(self, transaction: Dict[str, Any]) -> TransactionMonitorResult:
        """
        Screen a single transaction. Logs to audit trail before returning.
        Returns TransactionMonitorResult with risk_score, triggered_rules, and status.
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
        risk_factors: List[float] = []

        # 1. Cash threshold check
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

        # 3. Velocity checks (last 24 hours)
        if customer_id:
            recent_txns = await self._get_recent_transactions(customer_id, VELOCITY_WINDOW)
            txn_count = len(recent_txns)
            total_recent_amt = sum(float(t.get("amount", 0)) for t in recent_txns)

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

            # 4. Structuring detection
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

            # 5. Dormant account detection
            dormant = await self._is_dormant_account(customer_id, recent_txns)
            if dormant:
                triggered_rules.append(
                    TriggeredRule(
                        rule="DORMANT_ACCOUNT",
                        description="Sudden activity on previously dormant account (no transactions in 90+ days)",
                    )
                )
                risk_factors.append(0.6)

        # 6. Round amount detection
        if self._is_round_amount(amount):
            triggered_rules.append(
                TriggeredRule(
                    rule="ROUND_AMOUNT",
                    description=f"Round amount transaction: NGN {amount:,.2f}",
                    observed=amount,
                )
            )
            risk_factors.append(0.25)

        # 7. High-risk geo location
        high_risk_geos = ["IR", "KP", "SY", "CU", "SD", "YE", "LY", "MM"]
        if any(code in (geo_location or "").upper() for code in high_risk_geos):
            triggered_rules.append(
                TriggeredRule(
                    rule="HIGH_RISK_GEOGRAPHY",
                    description=f"Transaction involves high-risk or sanctioned jurisdiction: {geo_location}",
                )
            )
            risk_factors.append(0.7)

        # 8. International wire above threshold
        if txn_type == "international_wire" and amount >= 1_000_000:
            triggered_rules.append(
                TriggeredRule(
                    rule="INTERNATIONAL_WIRE",
                    description=f"International wire of NGN {amount:,.2f}: enhanced due diligence required",
                    observed=amount,
                )
            )
            risk_factors.append(0.4)

        # Calculate composite risk score
        risk_score = self._compute_risk_score(risk_factors, amount)
        flagged = len(triggered_rules) > 0 or risk_score >= 0.5
        confidence = min(0.95, 0.6 + (len(triggered_rules) * 0.05))
        status = "flagged" if flagged else "cleared"

        # Update transaction status in DB
        await update_transaction_status(self.db, txn_id, status, risk_score)

        # MANDATORY: Log to audit trail before returning
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
        all_txns = await get_customer_transactions(self.db, customer_id, days=7)
        cutoff = datetime.now(WAT) - timedelta(hours=hours)
        recent = []
        for t in all_txns:
            try:
                ts = datetime.fromisoformat(t.get("timestamp", ""))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=WAT)
                if ts >= cutoff:
                    recent.append(t)
            except (ValueError, TypeError):
                pass
        return recent

    def _detect_structuring(self, recent_txns: List[Dict], threshold: float) -> int:
        """Count transactions just below the threshold (structuring/smurfing)."""
        lower = threshold * STRUCTURING_PCT
        count = sum(
            1
            for t in recent_txns
            if lower <= float(t.get("amount", 0)) < threshold
            and t.get("transaction_type") in ("cash_deposit", "cash_withdrawal")
        )
        return count

    async def _is_dormant_account(self, customer_id: str, recent_txns: List[Dict]) -> bool:
        """Detect if account was dormant (no transactions in 90 days) before recent activity."""
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
            if len(older_txns) == 0 and len(all_txns) > len(recent_txns):
                return True
        return False

    def _parse_ts(self, ts_str: str) -> datetime:
        try:
            ts = datetime.fromisoformat(ts_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=WAT)
            return ts
        except (ValueError, TypeError):
            return datetime.now(WAT)

    def _is_round_amount(self, amount: float) -> bool:
        """True if amount is a round number (no fractional NGN, divisible by 500000)."""
        return amount >= 500_000 and amount % 500_000 == 0

    def _compute_risk_score(self, risk_factors: List[float], amount: float) -> float:
        if not risk_factors:
            # Low base risk from amount alone
            if amount >= 50_000_000:
                return 0.45
            elif amount >= 10_000_000:
                return 0.25
            elif amount >= 1_000_000:
                return 0.1
            return 0.05

        # Combine risk factors: use max + partial contribution of others
        sorted_factors = sorted(risk_factors, reverse=True)
        score = sorted_factors[0]
        for i, f in enumerate(sorted_factors[1:], 1):
            score += f * (0.5 ** i)

        # Amount multiplier
        if amount >= 50_000_000:
            score *= 1.3
        elif amount >= 10_000_000:
            score *= 1.15

        return min(1.0, score)
