"""
Agent 5: SAR Generator
Drafts Suspicious Activity Reports (SAR/STR) in NFIU format.
GOVERNANCE: SAR filing ALWAYS requires human approval. Never auto-file.
"""

from __future__ import annotations

import os
import json
from typing import Any, Dict, List, Optional

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
INSTITUTION_NAME = os.getenv("INSTITUTION_NAME", "Demo Bank Nigeria Ltd")
INSTITUTION_CODE = os.getenv("INSTITUTION_CODE", "DEMOBANK001")
REPORTING_OFFICER = os.getenv("REPORTING_OFFICER", "Chief Compliance Officer")


class SarGeneratorAgent:
    name = "sar_generator_agent"

    def __init__(self, db: aiosqlite.Connection):
        self.db = db
        self._llm = None
        if OPENAI_KEY:
            try:
                from langchain_openai import ChatOpenAI
                self._llm = ChatOpenAI(model="gpt-4o", temperature=0.1, api_key=OPENAI_KEY)
            except Exception:
                self._llm = None

    async def generate(
        self,
        customer_id: str,
        alert_id: Optional[str] = None,
        transaction_id: Optional[str] = None,
        pattern_result: Optional[Dict] = None,
        monitor_result: Optional[Dict] = None,
        kyc_result: Optional[Dict] = None,
        sanctions_result: Optional[Dict] = None,
    ) -> SarGeneratorResult:
        """
        Generate a draft SAR/STR. Returns draft for mandatory human approval.
        Logs to audit trail before returning.
        """
        # Collect context
        customer = await get_customer(self.db, customer_id)
        alert = await get_alert(self.db, alert_id) if alert_id else None
        transaction = await get_transaction(self.db, transaction_id) if transaction_id else None
        recent_alerts = await list_alerts(self.db, customer_id=customer_id, limit=10)

        # Determine typology
        typology = self._determine_typology(
            pattern_result, monitor_result, sanctions_result, customer
        )

        # Determine priority
        priority = self._determine_priority(
            pattern_result, monitor_result, sanctions_result, transaction
        )

        # Generate narrative
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

        # Persist draft SAR (status=draft, awaiting human approval)
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

        # MANDATORY: Log SAR draft to audit trail before returning
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
        customer: Optional[Dict],
        transaction: Optional[Dict],
        alert: Optional[Dict],
        recent_alerts: List[Dict],
        pattern_result: Optional[Dict],
        monitor_result: Optional[Dict],
        kyc_result: Optional[Dict],
        sanctions_result: Optional[Dict],
        typology: str,
    ) -> str:
        """Generate structured SAR narrative without LLM."""
        cname = customer.get("name", "Unknown Customer") if customer else "Unknown Customer"
        cid = customer.get("id", "")[:8] if customer else ""
        bvn = customer.get("bvn", "N/A") if customer else "N/A"
        nin = customer.get("nin", "N/A") if customer else "N/A"
        risk_tier = customer.get("risk_tier", "unknown") if customer else "unknown"
        pep = "Yes" if (customer and customer.get("pep_status")) else "No"

        amount_str = ""
        if transaction:
            amount_str = f"NGN {float(transaction.get('amount', 0)):,.2f}"

        triggered = ""
        if monitor_result and monitor_result.get("triggered_rules"):
            rules = monitor_result["triggered_rules"]
            triggered = "; ".join(
                r.get("rule", "") if isinstance(r, dict) else str(r)
                for r in rules[:5]
            )

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

    def _format_transaction_section(self, txn: Optional[Dict]) -> str:
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
        customer: Optional[Dict],
        transaction: Optional[Dict],
        alert: Optional[Dict],
        recent_alerts: List[Dict],
        pattern_result: Optional[Dict],
        monitor_result: Optional[Dict],
        kyc_result: Optional[Dict],
        sanctions_result: Optional[Dict],
        typology: str,
    ) -> str:
        """Generate professional SAR narrative using LLM."""
        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            system = """You are a senior AML compliance officer at a Nigerian commercial bank.
Draft a professional Suspicious Transaction Report (STR) in NFIU format.
Be factual, precise, and professional. Include all relevant sections.
Use Nigerian banking terminology. Amounts in NGN.
Mark clearly as DRAFT requiring human approval."""

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
            return self._rule_based_narrative(
                customer, transaction, alert, recent_alerts,
                pattern_result, monitor_result, kyc_result, sanctions_result, typology
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _determine_typology(
        self,
        pattern_result: Optional[Dict],
        monitor_result: Optional[Dict],
        sanctions_result: Optional[Dict],
        customer: Optional[Dict],
    ) -> str:
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
        pattern_result: Optional[Dict],
        monitor_result: Optional[Dict],
        sanctions_result: Optional[Dict],
        transaction: Optional[Dict],
    ) -> str:
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
