"""
Agent 5: SAR Generator

Drafts Suspicious Activity Reports (SAR/STR) in NFIU-compliant format.

GOVERNANCE CONSTRAINT: This agent ONLY creates DRAFT reports. It CANNOT
file a report with the NFIU. Every SAR created by this agent is in
'draft' status and requires human approval before its status can be
advanced to 'approved' or 'filed'. This is enforced by:
1. Always setting status='draft' in the created SAR record.
2. The governance engine's human_in_the_loop gate (runs after this agent).
3. The API layer rejecting /sars/{id}/file requests unless status='approved'.

Two narrative generation modes:
- LLM-based (OPENAI_API_KEY set): GPT-4o generates a professional NFIU-format
  narrative using all available evidence context. Falls back to rule-based
  if the API call fails.
- Rule-based (always available): Structured template-based narrative using
  the agent outputs passed as context. Produces consistent, machine-readable
  SAR sections that an analyst can review and enhance.

NFIU Filing Deadline: The Money Laundering (Prevention and Prohibition) Act
2022 requires filing within 24 hours of the initial determination of suspicion.
This agent includes the deadline notice in every SAR draft.
"""

from __future__ import annotations

import json
import os

import aiosqlite

from src.database import (
    create_sar,
    get_alert,
    get_customer,
    get_transaction,
    list_alerts,
    now_wat,
)
from src.governance.audit import log_agent_decision, log_sar_lifecycle
from src.models import SarGeneratorResult

OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")
# Institution details are injected via environment variables so the same
# codebase can be deployed at different institutions without code changes.
INSTITUTION_NAME = os.getenv("INSTITUTION_NAME", "Demo Bank Nigeria Ltd")
INSTITUTION_CODE = os.getenv("INSTITUTION_CODE", "DEMOBANK001")
REPORTING_OFFICER = os.getenv("REPORTING_OFFICER", "Chief Compliance Officer")


class SarGeneratorAgent:
    name = "sar_generator_agent"

    def __init__(self, db: aiosqlite.Connection):
        self.db = db
        # LLM initialised once per agent instance (see PatternAnalyzerAgent comment)
        self._llm = None
        if OPENAI_KEY:
            try:
                from langchain_openai import ChatOpenAI
                # temperature=0.1 gives slight variation to avoid repetitive
                # boilerplate while staying factual — appropriate for compliance reports.
                self._llm = ChatOpenAI(model="gpt-4o", temperature=0.1, api_key=OPENAI_KEY)
            except Exception:
                self._llm = None

    async def generate(
        self,
        customer_id: str,
        alert_id: str | None = None,
        transaction_id: str | None = None,
        pattern_result: dict | None = None,
        monitor_result: dict | None = None,
        kyc_result: dict | None = None,
        sanctions_result: dict | None = None,
    ) -> SarGeneratorResult:
        """Generate a draft SAR/STR and persist it for mandatory human review.

        Generation steps:
        1. Collect all available context (customer, alert, transaction, prior results).
        2. Determine the AML typology from the strongest available signal.
        3. Determine filing priority from risk level and transaction amount.
        4. Generate a narrative (LLM or rule-based template).
        5. Persist the draft SAR with status='draft'.
        6. Log two audit entries: the SAR lifecycle event and the agent decision.
        7. Return the result with requires_human_approval=True.

        The function ALWAYS returns requires_human_approval=True. There is no
        code path that creates a SAR in 'approved' or 'filed' status from this agent.
        """
        # Collect full context for narrative generation
        customer = await get_customer(self.db, customer_id)
        alert = await get_alert(self.db, alert_id) if alert_id else None
        transaction = await get_transaction(self.db, transaction_id) if transaction_id else None
        # Include recent alerts for context about ongoing suspicious activity
        recent_alerts = await list_alerts(self.db, customer_id=customer_id, limit=10)

        # Determine typology from the highest-confidence signal available
        typology = self._determine_typology(
            pattern_result, monitor_result, sanctions_result, customer
        )

        # Priority drives NFIU filing urgency (critical → immediate action)
        priority = self._determine_priority(
            pattern_result, monitor_result, sanctions_result, transaction
        )

        # Generate narrative using LLM if available, otherwise use template
        if self._llm:
            narrative = await self._llm_narrative(
                customer, transaction, alert, recent_alerts,
                pattern_result, monitor_result, kyc_result, sanctions_result, typology
            )
        else:
            narrative = self._rule_based_narrative(
                customer, transaction, alert, recent_alerts,
                pattern_result, monitor_result, kyc_result, sanctions_result, typology
            )

        # Persist the draft SAR. Status is always 'draft' — never 'approved'.
        sar_data = {
            "alert_id": alert_id,
            "customer_id": customer_id,
            "draft_narrative": narrative,
            "typology": typology,
            "priority": priority,
            "status": "draft",
            "drafted_by": self.name,
        }
        sar = await create_sar(self.db, sar_data)

        # MANDATORY: Log SAR draft to the audit trail before returning.
        # log_sar_lifecycle records the creation event with requires_human_approval=True
        # so the audit trail explicitly shows that the human approval requirement
        # was communicated at the time of drafting.
        await log_sar_lifecycle(
            db=self.db,
            sar_id=sar["id"],
            event="drafted",
            actor=self.name,
            details={
                "customer_id": customer_id,
                "typology": typology,
                "priority": priority,
                "requires_human_approval": True,
                "alert_id": alert_id,
                "transaction_id": transaction_id,
            },
        )

        # Second audit entry captures the agent decision with governance note
        await log_agent_decision(
            db=self.db,
            agent_name=self.name,
            entity_type="sar",
            entity_id=sar["id"],
            decision="drafted_pending_approval",
            confidence=0.85,
            details={
                "typology": typology,
                "priority": priority,
                "requires_human_approval": True,
                "governance_note": "SAR filing requires mandatory human approval per CBN mandate",
            },
        )

        return SarGeneratorResult(
            sar_id=sar["id"],
            customer_id=customer_id,
            alert_id=alert_id,
            draft_narrative=narrative,
            typology=typology,
            priority=priority,
            status="draft",
            requires_human_approval=True,
            audit_logged=True,
        )

    # ------------------------------------------------------------------
    # Narrative generation
    # ------------------------------------------------------------------

    def _rule_based_narrative(
        self,
        customer: dict | None,
        transaction: dict | None,
        alert: dict | None,
        recent_alerts: list[dict],
        pattern_result: dict | None,
        monitor_result: dict | None,
        kyc_result: dict | None,
        sanctions_result: dict | None,
        typology: str,
    ) -> str:
        """Generate a structured NFIU-format SAR narrative without an LLM.

        The template follows the NFIU STR format with six mandatory sections:
        1. Subject Information — customer identity details
        2. Suspicious Activity Description — typology and transaction details
        3. Reason for Suspicion — triggered rules and patterns
        4. Transaction Details — full transaction record
        5. Supporting Evidence — pattern analysis summary
        6. Declaration — institution and human approval notice

        The human approval notice in Section 6 is not just boilerplate —
        it serves as a reminder embedded in the document itself that this
        draft cannot be submitted to NFIU without officer approval.
        """
        cname = customer.get("name", "Unknown Customer") if customer else "Unknown Customer"
        # Truncate customer ID to 8 chars for readability in the SAR narrative
        cid = customer.get("id", "")[:8] if customer else ""
        bvn = customer.get("bvn", "N/A") if customer else "N/A"
        nin = customer.get("nin", "N/A") if customer else "N/A"
        risk_tier = customer.get("risk_tier", "unknown") if customer else "unknown"
        pep = "Yes" if (customer and customer.get("pep_status")) else "No"

        amount_str = ""
        if transaction:
            amount_str = f"NGN {float(transaction.get('amount', 0)):,.2f}"

        # Format the list of triggered rules for Section 3
        triggered = ""
        if monitor_result and monitor_result.get("triggered_rules"):
            rules = monitor_result["triggered_rules"]
            triggered = "; ".join(
                r.get("rule", "") if isinstance(r, dict) else str(r)
                for r in rules[:5]
            )

        # Format the list of detected patterns for Section 3
        patterns = ""
        if pattern_result and pattern_result.get("patterns_detected"):
            pats = pattern_result["patterns_detected"]
            patterns = "; ".join(
                p.get("pattern_name", "") if isinstance(p, dict) else str(p)
                for p in pats[:5]
            )

        narrative = f"""SUSPICIOUS TRANSACTION REPORT (STR) - DRAFT
Reporting Institution: {INSTITUTION_NAME} ({INSTITUTION_CODE})
Report Date: {now_wat()[:10]}
Reporting Officer: {REPORTING_OFFICER}
Filing Deadline: 24 hours from initial detection (NFIU requirement)

SECTION 1: SUBJECT INFORMATION
Name: {cname}
Customer ID: {cid}
BVN: {bvn}
NIN: {nin}
Risk Tier: {risk_tier.upper()}
PEP Status: {pep}
Account Type: {customer.get('account_type', 'N/A') if customer else 'N/A'}
Address: {customer.get('address', 'N/A') if customer else 'N/A'}
Phone: {customer.get('phone', 'N/A') if customer else 'N/A'}

SECTION 2: SUSPICIOUS ACTIVITY DESCRIPTION
Typology: {typology.replace('_', ' ').title()}
{f'Transaction Amount: {amount_str}' if amount_str else ''}
{f'Transaction Type: {transaction.get("transaction_type", "N/A")}' if transaction else ''}
{f'Channel: {transaction.get("channel", "N/A")}' if transaction else ''}
{f'Counterparty: {transaction.get("counterparty_name", "N/A")}' if transaction else ''}
{f'Geo Location: {transaction.get("geo_location", "N/A")}' if transaction else ''}

SECTION 3: REASON FOR SUSPICION
The subject's transactions have been flagged by the AgenticAML system for the following reasons:
- Triggered Rules: {triggered or 'N/A'}
- Patterns Detected: {patterns or 'N/A'}
- Alert Count (90 days): {len(recent_alerts)}
- Overall Risk Assessment: {pattern_result.get('overall_risk', 'N/A').upper() if pattern_result else 'N/A'}

SECTION 4: TRANSACTION DETAILS
{self._format_transaction_section(transaction)}

SECTION 5: SUPPORTING EVIDENCE
{pattern_result.get('supporting_evidence', 'See attached transaction history.') if pattern_result else 'See attached transaction history.'}

SECTION 6: REPORTING INSTITUTION DECLARATION
This report has been prepared by the AgenticAML automated compliance system.
The draft requires review and approval by an authorised compliance officer
before submission to the NFIU.

NOTE: This is a DRAFT report. Human approval is MANDATORY before filing.
DO NOT submit to NFIU without authorised officer approval and signature.
"""
        return narrative.strip()

    def _format_transaction_section(self, txn: dict | None) -> str:
        """Format the transaction details block for the SAR narrative."""
        if not txn:
            return "No single transaction: see customer alert history."
        return (
            f"  Transaction ID: {txn.get('id', 'N/A')}\n"
            f"  Amount: NGN {float(txn.get('amount', 0)):,.2f}\n"
            f"  Date: {txn.get('timestamp', 'N/A')[:19]}\n"
            f"  Type: {txn.get('transaction_type', 'N/A')}\n"
            f"  Channel: {txn.get('channel', 'N/A')}\n"
            f"  Direction: {txn.get('direction', 'N/A')}\n"
            f"  Counterparty: {txn.get('counterparty_name', 'N/A')}\n"
            f"  Counterparty Account: {txn.get('counterparty_account', 'N/A')}\n"
            f"  Status: {txn.get('status', 'N/A')}"
        )

    async def _llm_narrative(
        self,
        customer: dict | None,
        transaction: dict | None,
        alert: dict | None,
        recent_alerts: list[dict],
        pattern_result: dict | None,
        monitor_result: dict | None,
        kyc_result: dict | None,
        sanctions_result: dict | None,
        typology: str,
    ) -> str:
        """Generate a professional SAR narrative using GPT-4o.

        The LLM is given a structured JSON context containing all available
        evidence. The system prompt constrains it to factual, professional
        language in the NFIU STR format. Falls back to the rule-based
        narrative if the API call fails — the pipeline must always produce a SAR.
        """
        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            system = """You are a senior AML compliance officer at a Nigerian commercial bank.
Draft a professional Suspicious Transaction Report (STR) in NFIU format.
Be factual, precise, and professional. Include all relevant sections.
Use Nigerian banking terminology. Amounts in NGN.
Mark clearly as DRAFT requiring human approval."""

            # Strip timestamps from customer context to reduce token usage
            # while preserving all operationally relevant fields
            context = {
                "customer": {k: v for k, v in (customer or {}).items() if k not in ["created_at", "updated_at"]},
                "transaction": transaction,
                "typology": typology,
                "alert_count": len(recent_alerts),
                "patterns": pattern_result.get("patterns_detected", []) if pattern_result else [],
                "triggered_rules": monitor_result.get("triggered_rules", []) if monitor_result else [],
                "kyc_status": kyc_result.get("kyc_status") if kyc_result else None,
                "sanctions": sanctions_result.get("matches", []) if sanctions_result else [],
            }

            human = f"""Generate a complete NFIU STR in the following context:
{json.dumps(context, indent=2, default=str)}

Institution: {INSTITUTION_NAME} ({INSTITUTION_CODE})
Report Date: {now_wat()[:10]}

Include: Subject Info, Suspicious Activity Description, Reason for Suspicion,
Transaction Details, Evidence Summary, Declaration.
Mark as DRAFT - Human Approval Required."""

            messages = [SystemMessage(content=system), HumanMessage(content=human)]
            response = await self._llm.ainvoke(messages)
            return str(response.content)
        except Exception:
            # Fall back to rule-based narrative — LLM failure must not prevent
            # SAR generation, as the 24h NFIU deadline cannot be missed.
            return self._rule_based_narrative(
                customer, transaction, alert, recent_alerts,
                pattern_result, monitor_result, kyc_result, sanctions_result, typology
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _determine_typology(
        self,
        pattern_result: dict | None,
        monitor_result: dict | None,
        sanctions_result: dict | None,
        customer: dict | None,
    ) -> str:
        """Select the primary AML typology for the SAR from the available signals.

        Priority order:
        1. Sanctions-related (most severe — legal obligation to report)
        2. Pattern-based typology with highest confidence (most specific)
        3. Rule-based typology from the transaction monitor
        4. PEP-related if customer is a PEP
        5. Generic 'suspicious_activity' as last resort

        The typology drives NFIU categorisation and affects how the SAR
        is handled by the receiving unit.
        """
        if sanctions_result and sanctions_result.get("overall_recommendation") == "block":
            return "sanctions_related"
        if pattern_result:
            patterns = pattern_result.get("patterns_detected", [])
            if patterns:
                # Return the typology of the highest-confidence pattern
                sorted_pats = sorted(
                    patterns,
                    key=lambda p: p.get("confidence", 0) if isinstance(p, dict) else p.confidence,
                    reverse=True,
                )
                p = sorted_pats[0]
                return p.get("typology", "unknown") if isinstance(p, dict) else p.typology
        if monitor_result:
            rules = monitor_result.get("triggered_rules", [])
            rule_names = [r.get("rule", "") if isinstance(r, dict) else str(r) for r in rules]
            if "STRUCTURING" in rule_names:
                return "structuring_smurfing"
            if "HIGH_RISK_GEOGRAPHY" in rule_names:
                return "cross_border_suspicious"
        if customer and customer.get("pep_status"):
            return "pep_related"
        return "suspicious_activity"

    def _determine_priority(
        self,
        pattern_result: dict | None,
        monitor_result: dict | None,
        sanctions_result: dict | None,
        transaction: dict | None,
    ) -> str:
        """Determine the SAR filing priority from the available risk signals.

        Priority mapping:
        - critical: sanctions block OR critical pattern risk
          → immediate escalation, same-day NFIU notification required
        - urgent: very large transaction (≥NGN 50M) OR high pattern risk
          OR high transaction risk score (≥0.7)
          → file within 24h (NFIU STR deadline)
        - routine: all other cases
          → normal 24h filing process

        The NGN 50M threshold for 'urgent' aligns with the materiality_threshold
        in ThresholdConfig — transactions above this amount are always treated
        as high-priority for regulatory purposes.
        """
        if sanctions_result and sanctions_result.get("overall_recommendation") == "block":
            return "critical"
        if pattern_result and pattern_result.get("overall_risk") == "critical":
            return "critical"
        if transaction and float(transaction.get("amount", 0)) >= 50_000_000:
            return "urgent"
        if pattern_result and pattern_result.get("overall_risk") == "high":
            return "urgent"
        if monitor_result and float(monitor_result.get("risk_score", 0)) >= 0.7:
            return "urgent"
        return "routine"
