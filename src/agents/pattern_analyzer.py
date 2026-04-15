"""
Agent 4: Pattern Analyzer
Uses LLM reasoning (when available) or rule-based logic to detect complex
money laundering patterns. Covers behavioral anomalies, network analysis,
and typology matching.

In demo mode (no OPENAI_API_KEY): uses rule-based pattern detection only.
With OPENAI_API_KEY: augments rule-based with LLM narrative analysis.
"""

from __future__ import annotations

import os
import json
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import aiosqlite

from src.database import get_customer, get_customer_transactions, list_alerts, now_wat
from src.governance.audit import log_agent_decision
from src.models import PatternAnalyzerResult, PatternMatch

WAT = timezone(timedelta(hours=1))

OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")


class PatternAnalyzerAgent:
    name = "pattern_analyzer_agent"

    def __init__(self, db: aiosqlite.Connection):
        self.db = db
        self._llm = None
        if OPENAI_KEY:
            try:
                from langchain_openai import ChatOpenAI
                self._llm = ChatOpenAI(model="gpt-4o", temperature=0, api_key=OPENAI_KEY)
            except Exception:
                self._llm = None

    async def analyze(
        self,
        customer_id: str,
        transaction_id: Optional[str] = None,
        alert_summaries: Optional[List[Dict]] = None,
    ) -> PatternAnalyzerResult:
        """
        Analyze transaction patterns for a customer.
        Logs reasoning chain to audit trail before returning.
        """
        customer = await get_customer(self.db, customer_id)
        transactions = await get_customer_transactions(self.db, customer_id, days=90)
        alerts = await list_alerts(self.db, customer_id=customer_id, limit=50)

        patterns: List[PatternMatch] = []

        # Rule-based pattern detection (always runs)
        patterns += self._detect_structuring_pattern(transactions)
        patterns += self._detect_rapid_movement(transactions)
        patterns += self._detect_geographic_anomaly(transactions)
        patterns += self._detect_time_anomaly(transactions)
        patterns += self._detect_circular_transactions(transactions)
        patterns += self._detect_round_amount_pattern(transactions)
        patterns += self._detect_layering(transactions)

        if customer:
            patterns += self._detect_pep_patterns(customer, transactions)

        # LLM augmentation if available
        llm_evidence = ""
        if self._llm and (transactions or alerts):
            llm_evidence = await self._llm_analyze(customer, transactions, alerts, patterns)

        # Overall risk assessment
        overall_risk = self._assess_overall_risk(patterns, customer, transactions)
        recommended_actions = self._recommend_actions(overall_risk, patterns)

        supporting_evidence = self._build_evidence_summary(transactions, alerts, patterns, llm_evidence)

        # MANDATORY: Log reasoning chain to audit trail before returning
        await log_agent_decision(
            db=self.db,
            agent_name=self.name,
            entity_type="customer",
            entity_id=customer_id,
            decision=overall_risk,
            confidence=self._compute_confidence(patterns, transactions),
            details={
                "patterns_detected": [p.model_dump() for p in patterns],
                "overall_risk": overall_risk,
                "recommended_actions": recommended_actions,
                "transaction_count_analyzed": len(transactions),
                "llm_augmented": bool(llm_evidence),
            },
        )

        return PatternAnalyzerResult(
            customer_id=customer_id,
            overall_risk=overall_risk,
            patterns_detected=patterns,
            recommended_actions=recommended_actions,
            supporting_evidence=supporting_evidence,
            audit_logged=True,
        )

    # ------------------------------------------------------------------
    # Rule-based pattern detectors
    # ------------------------------------------------------------------

    def _detect_structuring_pattern(self, txns: List[Dict]) -> List[PatternMatch]:
        """Detect smurfing: multiple transactions just below NGN 5M threshold."""
        threshold = 5_000_000
        lower = threshold * 0.9
        hits = [
            t for t in txns
            if lower <= float(t.get("amount", 0)) < threshold
            and t.get("transaction_type") in ("cash_deposit", "cash_withdrawal")
        ]
        if len(hits) >= 3:
            return [
                PatternMatch(
                    pattern_name="STRUCTURING",
                    description=f"{len(hits)} cash transactions just below NGN 5M threshold detected across {self._date_range(hits)}",
                    confidence=min(0.95, 0.5 + len(hits) * 0.1),
                    typology="structuring_smurfing",
                    evidence=[
                        f"Transaction {t['id'][:8]}: NGN {float(t['amount']):,.2f} on {t.get('timestamp', '')[:10]}"
                        for t in hits[:5]
                    ],
                )
            ]
        return []

    def _detect_rapid_movement(self, txns: List[Dict]) -> List[PatternMatch]:
        """Detect rapid fund movement: large inflows quickly followed by outflows."""
        if len(txns) < 4:
            return []

        sorted_txns = sorted(txns, key=lambda t: t.get("timestamp", ""))
        inflows = [t for t in sorted_txns if t.get("direction") == "inbound" and float(t.get("amount", 0)) >= 1_000_000]
        outflows = [t for t in sorted_txns if t.get("direction") == "outbound" and float(t.get("amount", 0)) >= 1_000_000]

        if not inflows or not outflows:
            return []

        # Check for rapid sequences within 48 hours
        rapid_sequences = []
        for inflow in inflows:
            in_ts = self._parse_ts(inflow.get("timestamp", ""))
            for outflow in outflows:
                out_ts = self._parse_ts(outflow.get("timestamp", ""))
                diff_hours = abs((out_ts - in_ts).total_seconds()) / 3600
                if 0 < diff_hours <= 48:
                    rapid_sequences.append((inflow, outflow, diff_hours))

        if len(rapid_sequences) >= 2:
            total_moved = sum(float(p[1].get("amount", 0)) for p in rapid_sequences)
            return [
                PatternMatch(
                    pattern_name="RAPID_FUND_MOVEMENT",
                    description=f"Funds rapidly moved outbound within 48h of receipt ({len(rapid_sequences)} sequences, total NGN {total_moved:,.2f})",
                    confidence=0.75,
                    typology="layering",
                    evidence=[
                        f"Inflow NGN {float(p[0].get('amount',0)):,.2f} -> Outflow NGN {float(p[1].get('amount',0)):,.2f} within {p[2]:.1f}h"
                        for p in rapid_sequences[:3]
                    ],
                )
            ]
        return []

    def _detect_geographic_anomaly(self, txns: List[Dict]) -> List[PatternMatch]:
        """Detect geographic anomalies: transactions from multiple distant locations."""
        locations = [t.get("geo_location", "") for t in txns if t.get("geo_location")]
        if len(set(locations)) >= 5:
            high_risk_locs = [loc for loc in locations if any(
                code in loc.upper() for code in ["IR", "KP", "SY", "CU", "SD"]
            )]
            if high_risk_locs:
                return [
                    PatternMatch(
                        pattern_name="HIGH_RISK_GEOGRAPHY",
                        description=f"Transactions from {len(set(locations))} different locations including high-risk jurisdictions: {', '.join(set(high_risk_locs))}",
                        confidence=0.8,
                        typology="geographic_anomaly",
                        evidence=[f"Location: {loc}" for loc in list(set(high_risk_locs))[:5]],
                    )
                ]
            return [
                PatternMatch(
                    pattern_name="GEOGRAPHIC_DISPERSION",
                    description=f"Transactions from {len(set(locations))} different locations: {', '.join(list(set(locations))[:5])}",
                    confidence=0.5,
                    typology="geographic_anomaly",
                    evidence=[f"Location: {loc}" for loc in list(set(locations))[:5]],
                )
            ]
        return []

    def _detect_time_anomaly(self, txns: List[Dict]) -> List[PatternMatch]:
        """Detect unusual transaction times (midnight to 5am WAT)."""
        unusual = []
        for t in txns:
            try:
                ts = datetime.fromisoformat(t.get("timestamp", ""))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=WAT)
                if 0 <= ts.hour < 5:
                    unusual.append(t)
            except (ValueError, TypeError):
                pass
        if len(unusual) >= 5:
            return [
                PatternMatch(
                    pattern_name="UNUSUAL_TRANSACTION_TIMES",
                    description=f"{len(unusual)} transactions between midnight and 5am WAT",
                    confidence=0.55,
                    typology="behavioral_anomaly",
                    evidence=[
                        f"NGN {float(t.get('amount',0)):,.2f} at {t.get('timestamp','')[:16]}"
                        for t in unusual[:5]
                    ],
                )
            ]
        return []

    def _detect_circular_transactions(self, txns: List[Dict]) -> List[PatternMatch]:
        """Detect circular fund flows: money sent out and returned from same counterparty."""
        counterparties: Dict[str, Dict] = {}
        for t in txns:
            cp = t.get("counterparty_account", "") or t.get("counterparty_name", "")
            if not cp:
                continue
            if cp not in counterparties:
                counterparties[cp] = {"inbound": 0.0, "outbound": 0.0}
            direction = t.get("direction", "")
            amount = float(t.get("amount", 0))
            if direction == "inbound":
                counterparties[cp]["inbound"] += amount
            elif direction == "outbound":
                counterparties[cp]["outbound"] += amount

        circular = [
            cp for cp, flows in counterparties.items()
            if flows["inbound"] > 500_000 and flows["outbound"] > 500_000
            and min(flows["inbound"], flows["outbound"]) / max(flows["inbound"], flows["outbound"]) >= 0.7
        ]

        if circular:
            return [
                PatternMatch(
                    pattern_name="CIRCULAR_TRANSACTIONS",
                    description=f"Circular fund flows detected with {len(circular)} counterpart(ies): funds sent out and returned",
                    confidence=0.7,
                    typology="layering_circular",
                    evidence=[f"Counterparty: {cp[:30]}" for cp in circular[:5]],
                )
            ]
        return []

    def _detect_round_amount_pattern(self, txns: List[Dict]) -> List[PatternMatch]:
        """Detect pattern of repeated round-number transactions (classic ML indicator)."""
        round_txns = [
            t for t in txns
            if float(t.get("amount", 0)) >= 1_000_000
            and float(t.get("amount", 0)) % 1_000_000 == 0
        ]
        if len(round_txns) >= 5:
            return [
                PatternMatch(
                    pattern_name="ROUND_AMOUNT_PATTERN",
                    description=f"{len(round_txns)} round-number transactions (multiples of NGN 1M) in 90 days",
                    confidence=0.6,
                    typology="structuring",
                    evidence=[
                        f"NGN {float(t.get('amount',0)):,.2f} via {t.get('channel','')}"
                        for t in round_txns[:5]
                    ],
                )
            ]
        return []

    def _detect_layering(self, txns: List[Dict]) -> List[PatternMatch]:
        """Detect layering: many small transactions through different channels."""
        if len(txns) < 10:
            return []
        channels = [t.get("channel", "") for t in txns]
        channel_variety = len(set(channels))
        total_amount = sum(float(t.get("amount", 0)) for t in txns)
        avg_amount = total_amount / len(txns)

        if channel_variety >= 4 and avg_amount < 2_000_000 and len(txns) >= 15:
            return [
                PatternMatch(
                    pattern_name="LAYERING_MULTI_CHANNEL",
                    description=f"Layering pattern: {len(txns)} transactions across {channel_variety} different channels, avg NGN {avg_amount:,.2f}",
                    confidence=0.65,
                    typology="layering",
                    evidence=[f"Channel: {ch}" for ch in list(set(channels))],
                )
            ]
        return []

    def _detect_pep_patterns(self, customer: Dict, txns: List[Dict]) -> List[PatternMatch]:
        """Detect PEP-related corruption patterns."""
        if not customer.get("pep_status"):
            return []

        large_round_txns = [
            t for t in txns
            if float(t.get("amount", 0)) >= 10_000_000
            and float(t.get("amount", 0)) % 5_000_000 == 0
        ]

        if large_round_txns:
            return [
                PatternMatch(
                    pattern_name="PEP_LARGE_ROUND_TRANSACTIONS",
                    description=f"Politically exposed person with {len(large_round_txns)} large round-figure transactions (potential corruption/bribery pattern)",
                    confidence=0.72,
                    typology="pep_corruption",
                    evidence=[
                        f"NGN {float(t.get('amount',0)):,.2f} on {t.get('timestamp','')[:10]}"
                        for t in large_round_txns[:5]
                    ],
                )
            ]
        return []

    # ------------------------------------------------------------------
    # LLM augmentation
    # ------------------------------------------------------------------

    async def _llm_analyze(
        self,
        customer: Optional[Dict],
        txns: List[Dict],
        alerts: List[Dict],
        rule_patterns: List[PatternMatch],
    ) -> str:
        """Call LLM to augment rule-based analysis with narrative reasoning."""
        if not self._llm:
            return ""

        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            system = """You are an expert AML compliance analyst at a Nigerian bank.
Analyze the provided transaction data and identify money laundering patterns.
Focus on: structuring, layering, integration, trade-based ML, PEP corruption.
Be concise. Output only the key findings and reasoning chain for the audit log."""

            txn_summary = json.dumps([
                {
                    "id": t["id"][:8],
                    "amount_ngn": float(t.get("amount", 0)),
                    "type": t.get("transaction_type"),
                    "channel": t.get("channel"),
                    "direction": t.get("direction"),
                    "geo": t.get("geo_location"),
                    "date": t.get("timestamp", "")[:10],
                }
                for t in txns[:30]
            ], indent=2)

            rule_findings = [f"{p.pattern_name}: {p.description}" for p in rule_patterns]

            human = f"""Customer risk tier: {customer.get('risk_tier', 'unknown') if customer else 'unknown'}
PEP status: {bool(customer.get('pep_status')) if customer else False}
Rule-based findings: {rule_findings}
Recent transactions (last 30 shown):
{txn_summary}

Provide your AML analysis reasoning (max 200 words):"""

            messages = [SystemMessage(content=system), HumanMessage(content=human)]
            response = await self._llm.ainvoke(messages)
            return str(response.content)
        except Exception as e:
            return f"LLM analysis unavailable: {str(e)}"

    # ------------------------------------------------------------------
    # Scoring and helpers
    # ------------------------------------------------------------------

    def _assess_overall_risk(
        self, patterns: List[PatternMatch], customer: Optional[Dict], txns: List[Dict]
    ) -> str:
        if not patterns and not txns:
            return "low"

        max_confidence = max((p.confidence for p in patterns), default=0.0)
        high_risk_typologies = {"pep_corruption", "layering", "structuring_smurfing", "layering_circular"}
        has_high_risk_typology = any(p.typology in high_risk_typologies for p in patterns)

        if len(patterns) >= 4 or (has_high_risk_typology and max_confidence >= 0.8):
            return "critical"
        elif len(patterns) >= 3 or (has_high_risk_typology and max_confidence >= 0.65):
            return "high"
        elif len(patterns) >= 1 or max_confidence >= 0.5:
            return "medium"
        return "low"

    def _recommend_actions(self, risk_level: str, patterns: List[PatternMatch]) -> List[str]:
        actions = []
        if risk_level == "critical":
            actions += [
                "Escalate immediately to Compliance Officer",
                "Prepare SAR/STR for NFIU filing",
                "Consider account restriction pending investigation",
                "Conduct enhanced due diligence",
            ]
        elif risk_level == "high":
            actions += [
                "Escalate to Senior Analyst for review",
                "Collect additional documentation from customer",
                "Monitor account closely for 30 days",
            ]
        elif risk_level == "medium":
            actions += [
                "Flag for analyst review",
                "Enhanced transaction monitoring for 14 days",
            ]
        else:
            actions.append("Continue standard monitoring")

        typologies = {p.typology for p in patterns}
        if "structuring_smurfing" in typologies:
            actions.append("Investigate linked accounts for coordinated structuring")
        if "layering" in typologies:
            actions.append("Trace fund flows to identify ultimate beneficiary")
        if "pep_corruption" in typologies:
            actions.append("Request source of funds declaration from PEP customer")
        return actions

    def _build_evidence_summary(
        self,
        txns: List[Dict],
        alerts: List[Dict],
        patterns: List[PatternMatch],
        llm_evidence: str,
    ) -> str:
        lines = [
            f"Transactions analyzed: {len(txns)} (90-day window)",
            f"Alerts reviewed: {len(alerts)}",
            f"Patterns detected: {len(patterns)}",
        ]
        for p in patterns:
            lines.append(f"  [{p.typology}] {p.pattern_name} (confidence: {p.confidence:.2f})")
        if llm_evidence:
            lines.append(f"LLM analysis: {llm_evidence[:300]}")
        return "\n".join(lines)

    def _compute_confidence(self, patterns: List[PatternMatch], txns: List[Dict]) -> float:
        if not txns:
            return 0.5
        if not patterns:
            return 0.85  # High confidence in clean result
        return min(0.95, max(p.confidence for p in patterns))

    def _parse_ts(self, ts_str: str) -> datetime:
        try:
            ts = datetime.fromisoformat(ts_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=WAT)
            return ts
        except (ValueError, TypeError):
            return datetime.now(WAT)

    def _date_range(self, txns: List[Dict]) -> str:
        dates = sorted(t.get("timestamp", "")[:10] for t in txns if t.get("timestamp"))
        if not dates:
            return "unknown date range"
        return f"{dates[0]} to {dates[-1]}"
