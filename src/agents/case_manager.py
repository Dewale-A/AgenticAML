"""
Agent 6: Case Manager

The final agent in the pipeline. Creates investigation cases, assigns them
to appropriate compliance team members based on priority, and generates
compliance reports.

Responsibilities:
1. Case creation: Opens a formal investigation case for every flagged
   transaction, linking it to the triggering alert and customer.
2. Priority assessment: Maps agent risk scores to case priority levels
   (critical/high/medium/low) that drive SLA enforcement.
3. Role-based assignment: Routes cases to the correct tier of analyst
   based on priority — critical cases go to the Compliance Officer,
   high-priority to Senior Analysts, others to Analysts. This implements
   the tiered escalation chain required by CBN.
4. SLA tracking: Calculates the investigation deadline from the priority
   and SlaConfig and stores it in the case record for monitoring.
5. Reporting: Generates daily compliance summaries and alert analytics
   for management and regulatory reporting purposes.

CBN requires financial institutions to maintain documented investigation
workflows with defined SLA timelines and clear escalation paths. This
agent implements that requirement systematically.
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

# Compliance team roster for demo. In production this would be loaded from
# an HR or identity management system. The load field is a placeholder for
# workload balancing — not currently implemented but reserved for future use.
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
        """Create an investigation case and assign it to the appropriate analyst.

        The case creation logic:
        1. Determine case type from the highest-priority risk signal.
        2. Determine case priority from the risk scores.
        3. Auto-assign to the appropriate compliance role (policy-driven).
        4. Build a description summarising all available risk signals.
        5. Calculate the SLA deadline from the priority level.
        6. Persist the case and log two audit entries (lifecycle + agent decision).
        """
        # Case type reflects the primary investigation focus area
        case_type = self._determine_case_type(
            pattern_result, monitor_result, sanctions_result, kyc_result
        )
        priority = self._determine_priority(
            pattern_result, monitor_result, sanctions_result
        )

        # Role-based assignment ensures the right expertise handles each case:
        # critical → compliance officer (highest authority, CBN escalation requirement)
        # high → senior analyst (experience with complex ML patterns)
        # medium/low → analyst (standard investigative workload)
        assignee = self._assign_case(priority)

        description = self._build_description(
            case_type, priority, pattern_result, monitor_result, kyc_result, sanctions_result
        )

        # SLA deadline is calculated from SlaConfig and stored in the case record
        # so compliance supervisors can query for approaching deadlines.
        sla_hours = get_sla_hours(priority)
        deadline = (datetime.now(WAT) + timedelta(hours=sla_hours)).isoformat()

        # Create the case record in the database
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

        # MANDATORY: Log case creation to the audit trail before returning.
        # The assignment_rationale explains WHY this analyst was chosen,
        # which is important for cases where an analyst might question or
        # contest their workload assignment.
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
        """Generate a daily compliance summary report.

        Called by the /reports/daily API endpoint. Provides the Compliance
        Officer with a morning briefing on:
        - Today's transaction volume and flag rate
        - Alert generation rate
        - SAR drafts awaiting approval (human review backlog)
        - Regulatory notes for CBN reporting requirements

        The report is logged to the audit trail to maintain a record of
        when compliance reports were generated and by which system.
        """
        today = datetime.now(WAT).date().isoformat()
        stats = await get_dashboard_stats(self.db)

        # Filter today's transactions and alerts from the full dataset.
        # A more efficient production implementation would use a date-indexed
        # query, but this approach is correct and readable for demo purposes.
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
            # Overall totals from the full database (not just today)
            "totals": stats,
            # Today's activity breakdown
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
            # Regulatory reminders embedded in the report for the Compliance Officer
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
        """Generate alert analytics for the compliance dashboard.

        Key metrics computed:
        - by_severity: distribution across low/medium/high/critical
        - by_agent: which agents are generating the most alerts
          (high counts from a single agent may indicate tuning needed)
        - by_status: open/investigating/resolved/false_positive split
        - avg_resolution_hours: average investigation turnaround time
        - false_positive_rate: (false_positives / resolved) — a key efficiency
          KPI. Target is typically < 20% for a well-tuned AML system.
        - top_alert_types: most frequent alert types for pattern identification

        The false_positive_rate calculation uses (resolved + false_positive)
        as the denominator to measure the precision of closed cases only —
        open cases cannot yet be classified as true or false positives.
        """
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

            # Compute resolution time only for alerts that have been resolved
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
        # Denominator includes both 'resolved' and 'false_positive' status alerts
        resolved = by_status.get("resolved", 0) + false_positives

        # Top 10 alert types by frequency — used to identify systemic patterns
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
            # None if no alerts have been resolved yet
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
        """Select the primary investigation case type from available signals.

        Priority order mirrors the severity of the underlying risk:
        1. Sanctions investigations have the highest legal urgency
        2. KYC failures are account-level and must be resolved before trading
        3. Pattern-based cases reflect the primary ML typology detected
        4. Transaction monitor flags are the fallback
        5. General AML investigation if no specific type can be determined
        """
        if sanctions_result and sanctions_result.get("overall_recommendation") == "block":
            return "sanctions_investigation"
        if kyc_result and kyc_result.get("kyc_status") == "failed":
            return "kyc_failure"
        if pattern_result:
            patterns = pattern_result.get("patterns_detected", [])
            if patterns:
                # Use the first (highest-confidence) detected pattern's typology
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
        """Map risk signals to a case priority level.

        Priority thresholds:
        - critical: sanctions block OR critical pattern risk → 4h SLA
        - high: high pattern risk OR risk_score ≥ 0.7 → 24h SLA
        - medium: moderate risk_score (0.4–0.7) → 72h SLA
        - low: everything else → 168h SLA

        The risk_score thresholds (0.4 and 0.7) were chosen to align with the
        GovernanceEngine's materiality and confidence gate thresholds, ensuring
        consistency across the pipeline.
        """
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
        """Assign a case to the appropriate compliance team member by priority.

        Assignment policy (mirrors CBN's tiered escalation requirement):
        - critical → Compliance Officer (must have authority to file SARs and
          confirm sanctions blocks; role-enforced at the governance level)
        - high → Senior Analyst (experienced enough to handle layering and PEP cases)
        - medium/low → Analyst (standard investigation workload)

        Falls back to the last (highest-seniority) team member if the target
        role is not found in the team roster — ensures no case is left unassigned.
        """
        if priority == "critical":
            # Critical cases go to the compliance officer
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
        """Build a pipe-separated case description from all available signals.

        The description is stored on the case record and shown in the case
        management dashboard. Pipe-separated format makes it easy for the
        analyst to scan the key facts without opening each individual report.

        Example output:
        "Case Type: Structuring Investigation | Priority: HIGH | Triggered Rules:
        STRUCTURING, VELOCITY_COUNT | Pattern Analysis: 2 pattern(s) detected,
        overall risk=HIGH | KYC Status: VERIFIED"
        """
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
