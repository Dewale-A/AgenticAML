"""
Agent 6: Case Manager
Routes cases, tracks investigations, manages compliance workflows,
and generates regulatory reports. Enforces SLA and escalation chains.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import aiosqlite

from src.database import (
    create_case,
    get_alert,
    get_customer,
    list_alerts,
    list_cases,
    list_sars,
    list_transactions,
    get_dashboard_stats,
    now_wat,
)
from src.governance.audit import log_agent_decision, log_case_lifecycle
from src.governance.rules import get_sla_hours
from src.models import CaseManagerResult

WAT = timezone(timedelta(hours=1))

# Compliance team roster (demo)
COMPLIANCE_TEAM = [
    {"id": "analyst_1", "name": "Adaeze Okonkwo", "role": "analyst", "load": 0},
    {"id": "analyst_2", "name": "Emeka Nwosu", "role": "analyst", "load": 0},
    {"id": "senior_1", "name": "Ngozi Adeyemi", "role": "senior_analyst", "load": 0},
    {"id": "senior_2", "name": "Babatunde Fashola", "role": "senior_analyst", "load": 0},
    {"id": "officer_1", "name": "Chinelo Okafor", "role": "compliance_officer", "load": 0},
]


class CaseManagerAgent:
    name = "case_manager_agent"

    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def create_and_assign(
        self,
        customer_id: str,
        alert_id: Optional[str] = None,
        pattern_result: Optional[Dict] = None,
        monitor_result: Optional[Dict] = None,
        kyc_result: Optional[Dict] = None,
        sanctions_result: Optional[Dict] = None,
        sar_result: Optional[Dict] = None,
    ) -> CaseManagerResult:
        """
        Create a case and assign to the appropriate compliance team member.
        Logs to audit trail before returning.
        """
        # Determine case type and priority
        case_type = self._determine_case_type(
            pattern_result, monitor_result, sanctions_result, kyc_result
        )
        priority = self._determine_priority(
            pattern_result, monitor_result, sanctions_result
        )

        # Auto-assign based on priority and role
        assignee = self._assign_case(priority)

        # Build case description
        description = self._build_description(
            case_type, priority, pattern_result, monitor_result, kyc_result, sanctions_result
        )

        # Calculate SLA deadline
        sla_hours = get_sla_hours(priority)
        deadline = (datetime.now(WAT) + timedelta(hours=sla_hours)).isoformat()

        # Create case in DB
        case_data = {
            "alert_id": alert_id,
            "customer_id": customer_id,
            "case_type": case_type,
            "priority": priority,
            "status": "open",
            "assigned_to": assignee["name"],
            "description": description,
        }
        case = await create_case(self.db, case_data)

        # MANDATORY: Log case creation to audit trail before returning
        await log_case_lifecycle(
            db=self.db,
            case_id=case["id"],
            event="created",
            actor=self.name,
            details={
                "case_type": case_type,
                "priority": priority,
                "assigned_to": assignee["name"],
                "assigned_role": assignee["role"],
                "sla_deadline": deadline,
                "alert_id": alert_id,
                "customer_id": customer_id,
                "assignment_rationale": f"Auto-assigned to {assignee['role']} based on priority={priority}",
            },
        )

        await log_agent_decision(
            db=self.db,
            agent_name=self.name,
            entity_type="case",
            entity_id=case["id"],
            decision="created_and_assigned",
            confidence=0.9,
            details={
                "case_type": case_type,
                "priority": priority,
                "assigned_to": assignee["name"],
                "sla_deadline": deadline,
            },
        )

        return CaseManagerResult(
            case_id=case["id"],
            alert_id=alert_id,
            customer_id=customer_id,
            case_type=case_type,
            priority=priority,
            assigned_to=assignee["name"],
            status="open",
            sla_deadline=deadline,
            audit_logged=True,
        )

    async def generate_daily_report(self) -> Dict[str, Any]:
        """Generate daily compliance summary report."""
        today = datetime.now(WAT).date().isoformat()
        stats = await get_dashboard_stats(self.db)

        txns_today = await list_transactions(self.db, limit=1000)
        today_txns = [t for t in txns_today if t.get("timestamp", "")[:10] == today]

        alerts_today = await list_alerts(self.db, limit=1000)
        today_alerts = [a for a in alerts_today if a.get("created_at", "")[:10] == today]

        sars_today = await list_sars(self.db, limit=100)
        today_sars = [s for s in sars_today if s.get("created_at", "")[:10] == today]

        report = {
            "report_type": "daily_compliance_summary",
            "report_date": today,
            "generated_at": now_wat(),
            "generated_by": self.name,
            "institution": os.getenv("INSTITUTION_NAME", "Demo Bank Nigeria Ltd"),
            "totals": stats,
            "today": {
                "transactions": len(today_txns),
                "flagged": sum(1 for t in today_txns if t.get("status") == "flagged"),
                "alerts_generated": len(today_alerts),
                "sars_drafted": len(today_sars),
            },
            "high_risk_summary": {
                "open_critical_cases": 0,
                "pending_sar_approvals": stats.get("pending_sar_approvals", 0),
                "sanctions_blocks": stats.get("sanctions_blocks", 0),
            },
            "regulatory_notes": [
                "All STR filings must be submitted to NFIU within 24 hours of detection.",
                "High-risk cases require senior compliance officer review.",
                "Sanctions blocks have been logged for CBN reporting.",
            ],
        }

        await log_agent_decision(
            db=self.db,
            agent_name=self.name,
            entity_type="report",
            entity_id=today,
            decision="daily_report_generated",
            confidence=1.0,
            details={"report_date": today},
        )

        return report

    async def generate_alert_analytics(self) -> Dict[str, Any]:
        """Generate alert analytics for compliance dashboard."""
        alerts = await list_alerts(self.db, limit=1000)

        by_severity: Dict[str, int] = {}
        by_agent: Dict[str, int] = {}
        by_status: Dict[str, int] = {}
        by_type: Dict[str, int] = {}
        resolution_hours: List[float] = []

        for a in alerts:
            sev = a.get("severity", "unknown")
            by_severity[sev] = by_severity.get(sev, 0) + 1

            agent = a.get("agent_source", "unknown")
            by_agent[agent] = by_agent.get(agent, 0) + 1

            status = a.get("status", "unknown")
            by_status[status] = by_status.get(status, 0) + 1

            atype = a.get("alert_type", "unknown")
            by_type[atype] = by_type.get(atype, 0) + 1

            if a.get("resolved_at") and a.get("created_at"):
                try:
                    created = datetime.fromisoformat(a["created_at"])
                    resolved = datetime.fromisoformat(a["resolved_at"])
                    hours = (resolved - created).total_seconds() / 3600
                    resolution_hours.append(hours)
                except (ValueError, TypeError):
                    pass

        total = len(alerts)
        false_positives = by_status.get("false_positive", 0)
        resolved = by_status.get("resolved", 0) + false_positives

        top_types = sorted(by_type.items(), key=lambda x: x[1], reverse=True)[:10]

        return {
            "total_alerts": total,
            "by_severity": by_severity,
            "by_agent": by_agent,
            "by_status": by_status,
            "avg_resolution_hours": (
                round(sum(resolution_hours) / len(resolution_hours), 2)
                if resolution_hours
                else None
            ),
            "false_positive_rate": (
                round(false_positives / resolved, 4) if resolved > 0 else None
            ),
            "top_alert_types": [{"type": t, "count": c} for t, c in top_types],
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _determine_case_type(
        self,
        pattern_result: Optional[Dict],
        monitor_result: Optional[Dict],
        sanctions_result: Optional[Dict],
        kyc_result: Optional[Dict],
    ) -> str:
        if sanctions_result and sanctions_result.get("overall_recommendation") == "block":
            return "sanctions_investigation"
        if kyc_result and kyc_result.get("kyc_status") == "failed":
            return "kyc_failure"
        if pattern_result:
            patterns = pattern_result.get("patterns_detected", [])
            if patterns:
                p = patterns[0]
                typology = p.get("typology", "") if isinstance(p, dict) else getattr(p, "typology", "")
                if "structuring" in typology:
                    return "structuring_investigation"
                if "layering" in typology:
                    return "layering_investigation"
                if "pep" in typology:
                    return "pep_investigation"
        if monitor_result and monitor_result.get("flagged"):
            return "transaction_monitoring_alert"
        return "general_aml_investigation"

    def _determine_priority(
        self,
        pattern_result: Optional[Dict],
        monitor_result: Optional[Dict],
        sanctions_result: Optional[Dict],
    ) -> str:
        if sanctions_result and sanctions_result.get("overall_recommendation") == "block":
            return "critical"
        if pattern_result and pattern_result.get("overall_risk") in ("critical",):
            return "critical"
        if pattern_result and pattern_result.get("overall_risk") == "high":
            return "high"
        if monitor_result and float(monitor_result.get("risk_score", 0)) >= 0.7:
            return "high"
        if monitor_result and float(monitor_result.get("risk_score", 0)) >= 0.4:
            return "medium"
        return "low"

    def _assign_case(self, priority: str) -> Dict[str, str]:
        """Assign case to appropriate team member based on priority."""
        if priority == "critical":
            # Critical cases go to compliance officer
            return next(
                (m for m in COMPLIANCE_TEAM if m["role"] == "compliance_officer"),
                COMPLIANCE_TEAM[-1],
            )
        elif priority == "high":
            # High priority to senior analysts
            senior = [m for m in COMPLIANCE_TEAM if m["role"] == "senior_analyst"]
            return senior[0] if senior else COMPLIANCE_TEAM[0]
        else:
            # Medium/low to analysts
            analysts = [m for m in COMPLIANCE_TEAM if m["role"] == "analyst"]
            return analysts[0] if analysts else COMPLIANCE_TEAM[0]

    def _build_description(
        self,
        case_type: str,
        priority: str,
        pattern_result: Optional[Dict],
        monitor_result: Optional[Dict],
        kyc_result: Optional[Dict],
        sanctions_result: Optional[Dict],
    ) -> str:
        parts = [f"Case Type: {case_type.replace('_', ' ').title()}"]
        parts.append(f"Priority: {priority.upper()}")

        if monitor_result:
            rules = monitor_result.get("triggered_rules", [])
            if rules:
                rule_names = [r.get("rule", "") if isinstance(r, dict) else str(r) for r in rules[:3]]
                parts.append(f"Triggered Rules: {', '.join(rule_names)}")

        if pattern_result:
            risk = pattern_result.get("overall_risk", "")
            pcount = len(pattern_result.get("patterns_detected", []))
            if risk:
                parts.append(f"Pattern Analysis: {pcount} pattern(s) detected, overall risk={risk.upper()}")

        if kyc_result:
            parts.append(f"KYC Status: {kyc_result.get('kyc_status', 'unknown').upper()}")

        if sanctions_result:
            rec = sanctions_result.get("overall_recommendation", "clear")
            mcount = len(sanctions_result.get("matches", []))
            parts.append(f"Sanctions: {mcount} match(es), recommendation={rec.upper()}")

        return " | ".join(parts)
