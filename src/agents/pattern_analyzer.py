"""
Agent 4: Pattern Analyzer

Analyses customer transaction history to detect complex money laundering
patterns that rule-based threshold checks cannot catch on a single transaction.

This agent runs a 90-day lookback (the FATF-recommended behavioural window)
and applies multiple pattern detectors simultaneously to build a multi-signal
risk picture.

Two operating modes:
- Rule-based (always active): deterministic pattern detectors for known
  FATF/GIABA ML typologies. Runs in milliseconds with no external dependencies.
- LLM-augmented (when OPENAI_API_KEY is set): GPT-4o provides narrative
  reasoning and can surface emerging patterns not yet in the rule set.
  The LLM reasoning chain is logged to the audit trail for explainability.

FATF typologies covered:
  structuring_smurfing    — multiple cash txns just below reporting threshold
  layering                — rapid multi-channel fund movement to obscure origin
  layering_circular       — funds sent out and returned from same counterparty
  geographic_anomaly      — transactions from high-risk or unusual jurisdictions
  behavioral_anomaly      — unusual transaction times or patterns
  structuring             — round-amount pattern at NGN 1M+ scale
  pep_corruption          — PEP + large round-figure inflows from contractors

The overall_risk output drives downstream SAR generation:
  critical → mandatory SAR assessment (CBN mandates immediate action)
  high     → senior analyst review required
  medium   → enhanced monitoring
  low      → standard monitoring
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import aiosqlite

from src.database import get_customer, get_customer_transactions, list_alerts
from src.governance.audit import log_agent_decision
from src.models import PatternAnalyzerResult, PatternMatch

WAT = timezone(timedelta(hours=1))

# Optional LLM augmentation. Loaded at __init__ time so the agent can fall
# back gracefully to rule-based analysis if the API key is absent or if
# the langchain import fails (e.g., missing package in deployment).
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")


class PatternAnalyzerAgent:
    name = "pattern_analyzer_agent"

    def __init__(self, db: aiosqlite.Connection):
        self.db = db
        # LLM is initialised once per agent instance (not per analysis call)
        # to avoid repeated API client setup overhead in the hot path.
        self._llm = None
        if OPENAI_KEY:
            try:
                from langchain_openai import ChatOpenAI
                # temperature=0 ensures deterministic, fact-focused analysis
                # rather than creative generation — appropriate for compliance.
                self._llm = ChatOpenAI(model="gpt-4o", temperature=0, api_key=OPENAI_KEY)
            except Exception:
                # If LangChain is not installed or the key is invalid,
                # fall back to rule-based only without crashing.
                self._llm = None

    async def analyze(
        self,
        customer_id: str,
        transaction_id: str | None = None,
        alert_summaries: list[dict] | None = None,
    ) -> PatternAnalyzerResult:
        """Analyse transaction patterns for a customer over a 90-day window.

        Analysis steps:
        1. Fetch the customer profile, 90 days of transactions, and existing alerts.
        2. Run all rule-based pattern detectors (always executed).
        3. Optionally augment with LLM narrative analysis if API key is set.
        4. Assess overall risk level from detected patterns.
        5. Generate recommended actions for the compliance analyst.
        6. Build a supporting evidence summary.
        7. Log the reasoning chain to the audit trail before returning.
        """
        customer = await get_customer(self.db, customer_id)
        # 90-day window is the standard FATF behavioural analysis period
        transactions = await get_customer_transactions(self.db, customer_id, days=90)
        alerts = await list_alerts(self.db, customer_id=customer_id, limit=50)

        patterns: list[PatternMatch] = []

        # Rule-based pattern detection always runs — provides a deterministic
        # baseline that works in all environments and produces auditable results.
        patterns += self._detect_structuring_pattern(transactions)
        patterns += self._detect_rapid_movement(transactions)
        patterns += self._detect_geographic_anomaly(transactions)
        patterns += self._detect_time_anomaly(transactions)
        patterns += self._detect_circular_transactions(transactions)
        patterns += self._detect_round_amount_pattern(transactions)
        patterns += self._detect_layering(transactions)

        # PEP-specific pattern detection — only triggered if customer is a PEP.
        # PEPs have a higher baseline for what constitutes suspicious activity;
        # even legal government contractor payments may warrant SAR consideration.
        if customer:
            patterns += self._detect_pep_patterns(customer, transactions)

        # LLM augmentation: adds narrative context and may catch patterns
        # that the rule set hasn't explicitly enumerated. The LLM output is
        # incorporated into the evidence summary, not used to modify the
        # detected patterns list (rule-based findings are the primary signal).
        llm_evidence = ""
        if self._llm and (transactions or alerts):
            llm_evidence = await self._llm_analyze(customer, transactions, alerts, patterns)

        # Overall risk is the worst-case across all detected patterns
        overall_risk = self._assess_overall_risk(patterns, customer, transactions)
        recommended_actions = self._recommend_actions(overall_risk, patterns)
        supporting_evidence = self._build_evidence_summary(transactions, alerts, patterns, llm_evidence)

        # MANDATORY: Log the reasoning chain to the audit trail before returning.
        # The patterns_detected, overall_risk, and recommended_actions are all
        # logged so the compliance decision chain is fully reconstructable.
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

    def _detect_structuring_pattern(self, txns: list[dict]) -> list[PatternMatch]:
        """Detect smurfing: multiple cash transactions just below the NGN 5M threshold.

        Three or more qualifying transactions is the minimum to distinguish
        a pattern from coincidence. The 90%-of-threshold band (NGN 4.5M-4.99M)
        aligns with FATF's definition of structuring behaviour.

        Confidence scales with the number of hits: more transactions in the
        structuring band = higher certainty that the behaviour is intentional.
        """
        threshold = 5_000_000
        lower = threshold * 0.9  # NGN 4.5M lower bound
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

    def _detect_rapid_movement(self, txns: list[dict]) -> list[PatternMatch]:
        """Detect rapid fund movement: large inflows quickly followed by outflows.

        Classic layering indicator: funds arrive (placement) and are quickly
        dispersed (layering) to obscure the origin. The 48-hour window is
        used because legitimate business disbursements rarely happen within
        hours of receipt at the NGN 1M+ scale.

        Two or more rapid sequences is the trigger threshold to avoid false
        positives from legitimate same-day settlement patterns.
        """
        if len(txns) < 4:
            return []

        sorted_txns = sorted(txns, key=lambda t: t.get("timestamp", ""))
        # Only consider substantial movements (≥NGN 1M) to filter out noise
        inflows = [t for t in sorted_txns if t.get("direction") == "inbound" and float(t.get("amount", 0)) >= 1_000_000]
        outflows = [t for t in sorted_txns if t.get("direction") == "outbound" and float(t.get("amount", 0)) >= 1_000_000]

        if not inflows or not outflows:
            return []

        # Find inflow→outflow pairs within 48 hours
        rapid_sequences = []
        for inflow in inflows:
            in_ts = self._parse_ts(inflow.get("timestamp", ""))
            for outflow in outflows:
                out_ts = self._parse_ts(outflow.get("timestamp", ""))
                diff_hours = abs((out_ts - in_ts).total_seconds()) / 3600
                # 0 < diff_hours ≤ 48: outflow after inflow within 48 hours
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

    def _detect_geographic_anomaly(self, txns: list[dict]) -> list[PatternMatch]:
        """Detect geographic anomalies: transactions from many different locations.

        Five or more distinct locations is suspicious for a retail Nigerian
        customer (legitimate business accounts are expected to have higher
        geographic dispersion). High-risk jurisdictions in the mix elevate
        the confidence score significantly.

        High-risk codes: IR=Iran, KP=North Korea, SY=Syria, CU=Cuba, SD=Sudan
        (FATF high-risk/under increased monitoring jurisdictions).
        """
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

    def _detect_time_anomaly(self, txns: list[dict]) -> list[PatternMatch]:
        """Detect unusual transaction times: midnight to 5am WAT.

        Five or more transactions in the 00:00-05:00 WAT window is anomalous
        for a retail customer. Automated ML layering operations and overseas
        principals directing money mules often transact during Nigerian
        nighttime when human oversight is reduced.

        The 5-transaction minimum avoids flagging occasional legitimate
        late-night or early-morning transactions (e.g., travel, emergencies).
        """
        unusual = []
        for t in txns:
            try:
                ts = datetime.fromisoformat(t.get("timestamp", ""))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=WAT)
                # 00:00 to 05:00 WAT is the suspicious window
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

    def _detect_circular_transactions(self, txns: list[dict]) -> list[PatternMatch]:
        """Detect circular fund flows: money sent out and returned from same counterparty.

        Circular transactions obscure the origin of funds by creating a
        paper trail of apparent 'activity' between two parties who are
        actually just cycling the same funds. The 0.7 ratio threshold means
        inflows and outflows with the same counterparty are within 30% of
        each other — indicating the same money is going back and forth.

        Minimum NGN 500K per direction filters out routine small-value
        reciprocal payments (e.g., splitting bills, petty cash).
        """
        counterparties: dict[str, dict] = {}
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
            # Ratio ≥ 0.7 means the smaller amount is at least 70% of the larger
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

    def _detect_round_amount_pattern(self, txns: list[dict]) -> list[PatternMatch]:
        """Detect a pattern of repeated round-number transactions (classic ML indicator).

        Five or more transactions that are exact multiples of NGN 1M strongly
        suggests deliberate structuring — legitimate commercial payments rarely
        land on exactly round figures at this scale. This complements the
        single-transaction ROUND_AMOUNT rule in the transaction monitor.
        """
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

    def _detect_layering(self, txns: list[dict]) -> list[PatternMatch]:
        """Detect layering: many small transactions through many different channels.

        Layering through channel diversity (4+ different payment channels)
        with low average transaction amounts (below NGN 2M) and high
        frequency (15+ transactions) is a known ML indicator. The pattern
        suggests deliberately routing funds through multiple channels to
        complicate tracing.

        The thresholds (4 channels, NGN 2M avg, 15 transactions) are calibrated
        to avoid flagging legitimate SMEs who naturally use multiple channels.
        """
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

    def _detect_pep_patterns(self, customer: dict, txns: list[dict]) -> list[PatternMatch]:
        """Detect PEP-related corruption patterns: large round-figure inflows from contractors.

        A PEP receiving multiple large round-figure transfers from entities
        described as 'government contractors' is a classic bribery/corruption
        indicator per FATF Recommendation 12. The pattern is defined as:
        - Customer is a PEP (pep_status=1)
        - One or more inflows ≥ NGN 10M that are exact multiples of NGN 5M
          (round figures at this scale are unusual for legitimate business)
        """
        if not customer.get("pep_status"):
            return []

        # Look for large round figures: multiples of NGN 5M, at least NGN 10M
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
        customer: dict | None,
        txns: list[dict],
        alerts: list[dict],
        rule_patterns: list[PatternMatch],
    ) -> str:
        """Call GPT-4o to augment rule-based analysis with narrative reasoning.

        The LLM is given the rule-based findings as context so it can focus
        on patterns not yet captured by the rules rather than repeating them.
        The prompt limits the response to 200 words to keep the output
        focused and audit-trail friendly (verbose LLM outputs are harder
        to review for compliance examiners).

        Only the last 30 transactions are included in the prompt to stay
        within practical context limits and to focus the LLM on recent behaviour.
        """
        if not self._llm:
            return ""

        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            system = """You are an expert AML compliance analyst at a Nigerian bank.
Analyze the provided transaction data and identify money laundering patterns.
Focus on: structuring, layering, integration, trade-based ML, PEP corruption.
Be concise. Output only the key findings and reasoning chain for the audit log."""

            # Summarise transactions to reduce token usage while preserving
            # the key fields needed for pattern analysis
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
                for t in txns[:30]  # Cap at 30 to control token usage
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
            # LLM failure should never crash the pipeline — fall back gracefully
            return f"LLM analysis unavailable: {e!s}"

    # ------------------------------------------------------------------
    # Scoring and helpers
    # ------------------------------------------------------------------

    def _assess_overall_risk(
        self, patterns: list[PatternMatch], customer: dict | None, txns: list[dict]
    ) -> str:
        """Determine the overall risk level from the detected pattern set.

        Risk escalation logic:
        - critical: 4+ patterns detected, OR a high-risk typology with 80%+ confidence
          (either condition is sufficient for mandatory CBN escalation)
        - high: 3+ patterns, OR a high-risk typology at 65%+ confidence
        - medium: at least 1 pattern, OR max confidence ≥ 0.5
        - low: no patterns and no transactions to analyse

        High-risk typologies are those that directly correspond to FATF priority
        typologies for Nigerian financial institutions: structuring, layering,
        and PEP corruption.
        """
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

    def _recommend_actions(self, risk_level: str, patterns: list[PatternMatch]) -> list[str]:
        """Generate recommended actions for the compliance analyst.

        Actions are tiered by risk level (mandatory escalation actions first)
        and then supplemented with typology-specific investigative steps.
        These recommendations are included in the case description and SAR
        supporting evidence to guide the analyst's investigation.
        """
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

        # Typology-specific investigative steps
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
        txns: list[dict],
        alerts: list[dict],
        patterns: list[PatternMatch],
        llm_evidence: str,
    ) -> str:
        """Build a human-readable evidence summary for the SAR supporting evidence section.

        The summary is structured to be easily read by a compliance analyst
        reviewing the SAR draft: transaction scope first, then patterns,
        then optional LLM analysis truncated to 300 characters to avoid
        overwhelming the SAR narrative with LLM verbosity.
        """
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

    def _compute_confidence(self, patterns: list[PatternMatch], txns: list[dict]) -> float:
        """Compute the overall confidence of the pattern analysis result.

        No transactions: 0.5 (uncertain — no data to analyse).
        No patterns: 0.85 (high confidence in a clean result — we searched
        comprehensively and found nothing).
        Patterns detected: confidence equals the highest individual pattern
        confidence (the strongest signal sets the overall certainty).
        """
        if not txns:
            return 0.5
        if not patterns:
            return 0.85  # High confidence in clean result
        return min(0.95, max(p.confidence for p in patterns))

    def _parse_ts(self, ts_str: str) -> datetime:
        """Parse an ISO timestamp, defaulting to now() on failure."""
        try:
            ts = datetime.fromisoformat(ts_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=WAT)
            return ts
        except (ValueError, TypeError):
            return datetime.now(WAT)

    def _date_range(self, txns: list[dict]) -> str:
        """Return a human-readable date range string for a list of transactions.

        Used in pattern descriptions so analysts can quickly see the temporal
        span of detected activity without querying the database.
        """
        dates = sorted(t.get("timestamp", "")[:10] for t in txns if t.get("timestamp"))
        if not dates:
            return "unknown date range"
        return f"{dates[0]} to {dates[-1]}"
