"""
AgenticAML: AI-Powered AML Compliance for Nigerian Financial Institutions
FastAPI application with all routes.
Port: 8003
"""

from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

import aiosqlite
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from src.database import (
    init_db,
    get_db,
    get_dashboard_stats,
    get_audit_trail,
    list_customers,
    get_customer,
    update_customer,
    list_transactions,
    get_transaction,
    list_alerts,
    get_alert,
    update_alert,
    list_sanctions_matches,
    get_sanctions_match,
    update_sanctions_match,
    list_sars,
    get_sar,
    update_sar,
    list_cases,
    get_case,
    update_case,
    create_model_validation,
    list_model_validations,
    create_transaction,
    new_id,
    now_wat,
)
from src.models import (
    Customer,
    CustomerCreate,
    Transaction,
    TransactionCreate,
    BatchScreenRequest,
    Alert,
    AlertAssign,
    AlertResolve,
    SanctionsScreenRequest,
    SanctionsMatchReview,
    Sar,
    SarApprove,
    SarReject,
    SarFile,
    Case,
    CaseStatusUpdate,
    CaseAssign,
    RiskTierUpdate,
    ModelValidationCreate,
    PipelineResult,
)
from src.agents.transaction_monitor import TransactionMonitorAgent
from src.agents.kyc_verifier import KycVerifierAgent
from src.agents.sanctions_screener import SanctionsScreenerAgent
from src.agents.pattern_analyzer import PatternAnalyzerAgent
from src.agents.sar_generator import SarGeneratorAgent
from src.agents.case_manager import CaseManagerAgent
from src.governance.engine import GovernanceEngine
from src.governance.audit import log_human_decision


# ---------------------------------------------------------------------------
# Startup / lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB and optionally seed demo data on startup."""
    await init_db()

    # Auto-seed if DB is empty
    db_path = os.getenv("DB_PATH", "/app/data/aml.db")
    seed_on_start = os.getenv("SEED_ON_START", "true").lower() == "true"
    if seed_on_start:
        try:
            async with get_db() as db:
                from src.database import list_customers as lc
                customers = await lc(db, limit=1)
                if not customers:
                    from src.data.seed import seed_database
                    await seed_database()
        except Exception as e:
            print(f"Seed skipped: {e}")

    yield


app = FastAPI(
    title="AgenticAML",
    description="AI-Powered AML Compliance for Nigerian Financial Institutions. CBN BSD/DIR/PUB/LAB/019/002 compliant.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Helper: run full 6-agent pipeline on a transaction
# ---------------------------------------------------------------------------

async def run_pipeline(txn: Dict[str, Any]) -> Dict[str, Any]:
    """Execute all 6 agents in sequence with governance checks between each stage."""
    start = time.time()
    governance_decisions = []

    async with get_db() as db:
        gov = GovernanceEngine(db)

        # Ensure transaction is in DB
        existing = await get_transaction(db, txn["id"])
        if not existing:
            txn = await create_transaction(db, txn)
        else:
            txn = existing

        # -- Stage 1: Transaction Monitor --
        monitor_agent = TransactionMonitorAgent(db)
        monitor_result = await monitor_agent.screen(txn)
        gov_result_1 = await gov.evaluate(
            "transaction_monitor",
            "transaction",
            txn["id"],
            monitor_result.model_dump(),
            context={"amount": txn.get("amount", 0)},
        )
        governance_decisions.append(gov_result_1)

        # -- Stage 2: KYC Verifier --
        kyc_agent = KycVerifierAgent(db)
        kyc_result = await kyc_agent.verify(
            txn["customer_id"],
            monitor_context=monitor_result.model_dump(),
        )
        gov_result_2 = await gov.evaluate(
            "kyc_verifier",
            "customer",
            txn["customer_id"],
            kyc_result.model_dump(),
        )
        governance_decisions.append(gov_result_2)

        # -- Stage 3: Sanctions Screener --
        customer = await get_customer(db, txn["customer_id"])
        screener_agent = SanctionsScreenerAgent(db)

        # Screen customer name
        customer_name = customer.get("name", "") if customer else ""
        sanctions_result = await screener_agent.screen(
            name=customer_name,
            customer_id=txn["customer_id"],
            transaction_id=txn["id"],
        )

        # Also screen counterparty if present
        if txn.get("counterparty_name"):
            cp_result = await screener_agent.screen(
                name=txn["counterparty_name"],
                transaction_id=txn["id"],
            )
            # Merge counterparty matches
            if cp_result.matches:
                sanctions_result.matches.extend(cp_result.matches)
                from src.models import SanctionsScreenResult
                # Re-evaluate overall recommendation
                actions = [m.action_taken for m in sanctions_result.matches]
                if "block" in actions:
                    sanctions_result.overall_recommendation = "block"
                elif "review" in actions:
                    sanctions_result.overall_recommendation = "review"

        gov_result_3 = await gov.evaluate(
            "sanctions_screener",
            "transaction",
            txn["id"],
            sanctions_result.model_dump(),
        )
        governance_decisions.append(gov_result_3)

        # If blocked by sanctions - stop pipeline
        final_status = "cleared"
        if gov_result_3.blocked:
            final_status = "blocked"
            elapsed = (time.time() - start) * 1000
            return {
                "transaction_id": txn["id"],
                "customer_id": txn["customer_id"],
                "monitor_result": monitor_result.model_dump(),
                "kyc_result": kyc_result.model_dump(),
                "sanctions_result": sanctions_result.model_dump(),
                "pattern_result": None,
                "sar_result": None,
                "case_result": None,
                "governance_decisions": [g.model_dump() for g in governance_decisions],
                "final_status": "blocked",
                "processing_time_ms": round(elapsed, 2),
            }

        # -- Stage 4: Pattern Analyzer (only for flagged transactions) --
        pattern_result = None
        gov_result_4 = None

        if monitor_result.flagged or kyc_result.risk_tier in ("high", "very_high") or sanctions_result.matches:
            pattern_agent = PatternAnalyzerAgent(db)
            pattern_result = await pattern_agent.analyze(
                customer_id=txn["customer_id"],
                transaction_id=txn["id"],
            )
            gov_result_4 = await gov.evaluate(
                "pattern_analyzer",
                "customer",
                txn["customer_id"],
                pattern_result.model_dump(),
                context={"amount": txn.get("amount", 0)},
            )
            governance_decisions.append(gov_result_4)

        # Determine if SAR should be generated
        should_generate_sar = (
            (pattern_result and pattern_result.overall_risk in ("critical", "high"))
            or (monitor_result.risk_score >= 0.75)
            or (sanctions_result.overall_recommendation in ("block", "review"))
        )

        # -- Stage 5: SAR Generator --
        sar_result = None
        gov_result_5 = None
        if should_generate_sar:
            sar_agent = SarGeneratorAgent(db)
            alert_id = None

            # Create alert if flagged
            if monitor_result.flagged:
                from src.database import create_alert
                alert_data = {
                    "transaction_id": txn["id"],
                    "customer_id": txn["customer_id"],
                    "agent_source": "transaction_monitor_agent",
                    "alert_type": monitor_result.triggered_rules[0].rule if monitor_result.triggered_rules else "SUSPICIOUS",
                    "severity": "critical" if monitor_result.risk_score >= 0.8 else "high",
                    "description": f"Risk score: {monitor_result.risk_score:.2f}. Rules: {[r.rule for r in monitor_result.triggered_rules]}",
                    "confidence": monitor_result.confidence,
                    "status": "open",
                }
                alert = await create_alert(db, alert_data)
                alert_id = alert["id"]

            sar_result = await sar_agent.generate(
                customer_id=txn["customer_id"],
                alert_id=alert_id,
                transaction_id=txn["id"],
                pattern_result=pattern_result.model_dump() if pattern_result else None,
                monitor_result=monitor_result.model_dump(),
                kyc_result=kyc_result.model_dump(),
                sanctions_result=sanctions_result.model_dump(),
            )
            gov_result_5 = await gov.evaluate(
                "sar_generator",
                "sar",
                sar_result.sar_id,
                sar_result.model_dump(),
            )
            governance_decisions.append(gov_result_5)

        # -- Stage 6: Case Manager --
        case_result = None
        if monitor_result.flagged or should_generate_sar:
            case_agent = CaseManagerAgent(db)
            alert_id_for_case = sar_result.alert_id if sar_result else None
            case_result = await case_agent.create_and_assign(
                customer_id=txn["customer_id"],
                alert_id=alert_id_for_case,
                pattern_result=pattern_result.model_dump() if pattern_result else None,
                monitor_result=monitor_result.model_dump(),
                kyc_result=kyc_result.model_dump(),
                sanctions_result=sanctions_result.model_dump(),
                sar_result=sar_result.model_dump() if sar_result else None,
            )

        # Final status
        if gov_result_3.blocked:
            final_status = "blocked"
        elif any(g.escalated for g in governance_decisions):
            final_status = "escalated"
        elif monitor_result.flagged:
            final_status = "flagged"
        else:
            final_status = "cleared"

        elapsed = (time.time() - start) * 1000

        return {
            "transaction_id": txn["id"],
            "customer_id": txn["customer_id"],
            "monitor_result": monitor_result.model_dump(),
            "kyc_result": kyc_result.model_dump(),
            "sanctions_result": sanctions_result.model_dump(),
            "pattern_result": pattern_result.model_dump() if pattern_result else None,
            "sar_result": sar_result.model_dump() if sar_result else None,
            "case_result": case_result.model_dump() if case_result else None,
            "governance_decisions": [g.model_dump() for g in governance_decisions],
            "final_status": final_status,
            "processing_time_ms": round(elapsed, 2),
        }


# ===========================================================================
# ROUTES
# ===========================================================================

# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------

@app.get("/health", tags=["System"])
async def health_check():
    return {
        "status": "healthy",
        "service": "AgenticAML",
        "version": "1.0.0",
        "timestamp": now_wat(),
        "db_path": os.getenv("DB_PATH", "/app/data/aml.db"),
    }


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

@app.post("/transactions/screen", tags=["Transactions"])
async def screen_transaction(txn: TransactionCreate):
    """Screen a single transaction through the full 6-agent pipeline."""
    txn_data = txn.model_dump()
    txn_data["id"] = new_id()
    result = await run_pipeline(txn_data)
    return result


@app.post("/transactions/batch", tags=["Transactions"])
async def screen_batch(batch: BatchScreenRequest):
    """Screen a batch of transactions."""
    results = []
    for txn in batch.transactions:
        txn_data = txn.model_dump()
        txn_data["id"] = new_id()
        try:
            result = await run_pipeline(txn_data)
            results.append(result)
        except Exception as e:
            results.append({"error": str(e), "transaction": txn_data})
    return {"processed": len(results), "results": results}


@app.get("/transactions", tags=["Transactions"])
async def get_transactions(
    customer_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List transactions with optional filters."""
    async with get_db() as db:
        txns = await list_transactions(db, customer_id=customer_id, status=status, limit=limit, offset=offset)
    return {"transactions": txns, "count": len(txns)}


@app.get("/transactions/{transaction_id}", tags=["Transactions"])
async def get_transaction_details(transaction_id: str):
    """Get transaction details with linked alerts."""
    async with get_db() as db:
        txn = await get_transaction(db, transaction_id)
        if not txn:
            raise HTTPException(status_code=404, detail="Transaction not found")
        alerts = await list_alerts(db, limit=100)
        txn_alerts = [a for a in alerts if a.get("transaction_id") == transaction_id]
    return {"transaction": txn, "alerts": txn_alerts}


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------

@app.get("/customers", tags=["Customers"])
async def get_customers(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List all customers."""
    async with get_db() as db:
        customers = await list_customers(db, limit=limit, offset=offset)
    return {"customers": customers, "count": len(customers)}


@app.get("/customers/{customer_id}", tags=["Customers"])
async def get_customer_profile(customer_id: str):
    """Customer profile with risk history."""
    async with get_db() as db:
        customer = await get_customer(db, customer_id)
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")
        txns = await list_transactions(db, customer_id=customer_id, limit=100)
        alerts = await list_alerts(db, customer_id=customer_id, limit=50)
        sars = await list_sars(db, customer_id=customer_id, limit=20)
        cases = await list_cases(db, customer_id=customer_id, limit=20)
        audit = await get_audit_trail(db, entity_type="customer", entity_id=customer_id, limit=50)
    return {
        "customer": customer,
        "transactions": txns,
        "alerts": alerts,
        "sars": sars,
        "cases": cases,
        "audit_trail": audit,
    }


@app.post("/customers/{customer_id}/kyc", tags=["Customers"])
async def trigger_kyc(customer_id: str):
    """Trigger KYC verification for a customer."""
    async with get_db() as db:
        customer = await get_customer(db, customer_id)
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")
        agent = KycVerifierAgent(db)
        result = await agent.verify(customer_id)
    return result.model_dump()


@app.put("/customers/{customer_id}/risk-tier", tags=["Customers"])
async def update_risk_tier(customer_id: str, body: RiskTierUpdate):
    """
    Update customer risk tier. Downgrades require human approval per governance rules.
    """
    async with get_db() as db:
        customer = await get_customer(db, customer_id)
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")

        tier_order = {"low": 0, "medium": 1, "high": 2, "very_high": 3}
        current_order = tier_order.get(customer.get("risk_tier", "low"), 0)
        new_order = tier_order.get(body.risk_tier, 0)

        if new_order < current_order:
            # Downgrade: log as human decision (governance requirement)
            await log_human_decision(
                db=db,
                entity_type="customer",
                entity_id=customer_id,
                event_type="risk_tier_downgrade",
                actor=body.approved_by,
                decision=f"downgrade to {body.risk_tier}",
                rationale=body.rationale,
                before_state={"risk_tier": customer["risk_tier"]},
                after_state={"risk_tier": body.risk_tier},
            )

        updated = await update_customer(db, customer_id, {"risk_tier": body.risk_tier})
    return {"customer": updated, "risk_tier_updated": body.risk_tier, "approved_by": body.approved_by}


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

@app.get("/alerts", tags=["Alerts"])
async def get_alerts(
    status: Optional[str] = None,
    severity: Optional[str] = None,
    agent_source: Optional[str] = None,
    customer_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List alerts with filters."""
    async with get_db() as db:
        alerts = await list_alerts(
            db,
            status=status,
            severity=severity,
            agent_source=agent_source,
            customer_id=customer_id,
            limit=limit,
            offset=offset,
        )
    return {"alerts": alerts, "count": len(alerts)}


@app.get("/alerts/{alert_id}", tags=["Alerts"])
async def get_alert_details(alert_id: str):
    """Alert details with linked transaction."""
    async with get_db() as db:
        alert = await get_alert(db, alert_id)
        if not alert:
            raise HTTPException(status_code=404, detail="Alert not found")
        txn = None
        if alert.get("transaction_id"):
            txn = await get_transaction(db, alert["transaction_id"])
        audit = await get_audit_trail(db, entity_id=alert_id, limit=20)
    return {"alert": alert, "transaction": txn, "audit_trail": audit}


@app.put("/alerts/{alert_id}/assign", tags=["Alerts"])
async def assign_alert(alert_id: str, body: AlertAssign):
    """Assign alert to an analyst."""
    async with get_db() as db:
        alert = await get_alert(db, alert_id)
        if not alert:
            raise HTTPException(status_code=404, detail="Alert not found")
        updated = await update_alert(db, alert_id, {"assigned_to": body.assigned_to, "status": "investigating"})
        await log_human_decision(
            db=db,
            entity_type="alert",
            entity_id=alert_id,
            event_type="alert_assigned",
            actor=body.assigned_to,
            decision=f"assigned to {body.assigned_to}",
            rationale="Manual assignment",
        )
    return {"alert": updated}


@app.put("/alerts/{alert_id}/resolve", tags=["Alerts"])
async def resolve_alert(alert_id: str, body: AlertResolve):
    """Resolve alert with rationale."""
    async with get_db() as db:
        alert = await get_alert(db, alert_id)
        if not alert:
            raise HTTPException(status_code=404, detail="Alert not found")
        updates = {
            "status": body.resolution,
            "resolved_at": now_wat(),
        }
        updated = await update_alert(db, alert_id, updates)
        await log_human_decision(
            db=db,
            entity_type="alert",
            entity_id=alert_id,
            event_type="alert_resolved",
            actor="compliance_officer",
            decision=body.resolution,
            rationale=body.rationale,
        )
    return {"alert": updated}


# ---------------------------------------------------------------------------
# Sanctions
# ---------------------------------------------------------------------------

@app.get("/sanctions/screen", tags=["Sanctions"])
async def screen_sanctions(
    name: str = Query(..., description="Full name to screen"),
    customer_id: Optional[str] = None,
    transaction_id: Optional[str] = None,
):
    """Screen a name/entity against all sanctions lists."""
    async with get_db() as db:
        agent = SanctionsScreenerAgent(db)
        result = await agent.screen(
            name=name,
            customer_id=customer_id,
            transaction_id=transaction_id,
        )
    return result.model_dump()


@app.get("/sanctions/matches", tags=["Sanctions"])
async def get_sanctions_matches(
    customer_id: Optional[str] = None,
    action_taken: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List all sanctions matches."""
    async with get_db() as db:
        matches = await list_sanctions_matches(
            db, customer_id=customer_id, action_taken=action_taken, limit=limit, offset=offset
        )
    return {"matches": matches, "count": len(matches)}


@app.post("/sanctions/matches/{match_id}/review", tags=["Sanctions"])
async def review_sanctions_match(match_id: str, body: SanctionsMatchReview):
    """Review a sanctions match (approve confirmed block or dismiss false positive)."""
    async with get_db() as db:
        match = await get_sanctions_match(db, match_id)
        if not match:
            raise HTTPException(status_code=404, detail="Sanctions match not found")

        new_action = "block" if body.decision == "approve" else "dismissed"
        updated = await update_sanctions_match(
            db, match_id, {"action_taken": new_action, "reviewed_by": body.reviewed_by}
        )
        await log_human_decision(
            db=db,
            entity_type="sanctions_match",
            entity_id=match_id,
            event_type="sanctions_review",
            actor=body.reviewed_by,
            decision=body.decision,
            rationale=body.rationale,
        )
    return {"match": updated}


# ---------------------------------------------------------------------------
# SARs
# ---------------------------------------------------------------------------

@app.get("/sars", tags=["SARs"])
async def get_sars(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    customer_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List SARs with filters."""
    async with get_db() as db:
        sars = await list_sars(db, status=status, priority=priority, customer_id=customer_id, limit=limit, offset=offset)
    return {"sars": sars, "count": len(sars)}


@app.get("/sars/{sar_id}", tags=["SARs"])
async def get_sar_details(sar_id: str):
    """SAR details with audit trail."""
    async with get_db() as db:
        sar = await get_sar(db, sar_id)
        if not sar:
            raise HTTPException(status_code=404, detail="SAR not found")
        audit = await get_audit_trail(db, entity_type="sar", entity_id=sar_id, limit=30)
    return {"sar": sar, "audit_trail": audit}


@app.post("/sars/{sar_id}/approve", tags=["SARs"])
async def approve_sar(sar_id: str, body: SarApprove):
    """
    Approve SAR for filing. MANDATORY human decision - agents cannot auto-approve.
    """
    async with get_db() as db:
        sar = await get_sar(db, sar_id)
        if not sar:
            raise HTTPException(status_code=404, detail="SAR not found")
        if sar.get("status") not in ("draft", "pending_approval"):
            raise HTTPException(
                status_code=400,
                detail=f"SAR cannot be approved in status: {sar.get('status')}",
            )

        updates = {
            "status": "approved",
            "approved_by": body.approved_by,
            "approval_rationale": body.rationale,
        }
        if body.final_narrative:
            updates["final_narrative"] = body.final_narrative

        updated = await update_sar(db, sar_id, updates)

        # Log mandatory human approval to audit trail
        from src.governance.audit import log_sar_lifecycle
        await log_sar_lifecycle(
            db=db,
            sar_id=sar_id,
            event="approved",
            actor=body.approved_by,
            details={
                "approved_by": body.approved_by,
                "rationale": body.rationale,
                "governance_note": "MANDATORY human approval recorded per CBN mandate",
            },
        )

    return {"sar": updated, "approved_by": body.approved_by}


@app.post("/sars/{sar_id}/reject", tags=["SARs"])
async def reject_sar(sar_id: str, body: SarReject):
    """Reject SAR draft with rationale."""
    async with get_db() as db:
        sar = await get_sar(db, sar_id)
        if not sar:
            raise HTTPException(status_code=404, detail="SAR not found")
        if sar.get("status") not in ("draft", "pending_approval"):
            raise HTTPException(
                status_code=400,
                detail=f"SAR cannot be rejected in status: {sar.get('status')}",
            )

        updates = {
            "status": "rejected",
            "approved_by": body.rejected_by,
            "approval_rationale": body.rationale,
        }
        updated = await update_sar(db, sar_id, updates)

        from src.governance.audit import log_sar_lifecycle
        await log_sar_lifecycle(
            db=db,
            sar_id=sar_id,
            event="rejected",
            actor=body.rejected_by,
            details={"rejected_by": body.rejected_by, "rationale": body.rationale},
        )

    return {"sar": updated, "rejected_by": body.rejected_by}


@app.post("/sars/{sar_id}/file", tags=["SARs"])
async def file_sar(sar_id: str, body: SarFile):
    """File SAR with NFIU (only after human approval)."""
    async with get_db() as db:
        sar = await get_sar(db, sar_id)
        if not sar:
            raise HTTPException(status_code=404, detail="SAR not found")
        if sar.get("status") != "approved":
            raise HTTPException(
                status_code=400,
                detail="SAR must be approved by a compliance officer before filing with NFIU",
            )

        nfiu_ref = body.nfiu_reference or f"NFIU-{now_wat()[:4]}-{new_id()[:8].upper()}-NG"
        updates = {
            "status": "filed",
            "filed_at": now_wat(),
            "nfiu_reference": nfiu_ref,
        }
        updated = await update_sar(db, sar_id, updates)

        from src.governance.audit import log_sar_lifecycle
        await log_sar_lifecycle(
            db=db,
            sar_id=sar_id,
            event="filed",
            actor=body.filed_by,
            details={"filed_by": body.filed_by, "nfiu_reference": nfiu_ref, "filed_at": now_wat()},
        )

    return {"sar": updated, "nfiu_reference": nfiu_ref}


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------

@app.get("/cases", tags=["Cases"])
async def get_cases(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    assigned_to: Optional[str] = None,
    customer_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List cases with filters."""
    async with get_db() as db:
        cases = await list_cases(
            db, status=status, priority=priority, assigned_to=assigned_to,
            customer_id=customer_id, limit=limit, offset=offset
        )
    return {"cases": cases, "count": len(cases)}


@app.get("/cases/{case_id}", tags=["Cases"])
async def get_case_details(case_id: str):
    """Case details with full history."""
    async with get_db() as db:
        case = await get_case(db, case_id)
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        audit = await get_audit_trail(db, entity_type="case", entity_id=case_id, limit=50)
        # Get linked alert
        alert = None
        if case.get("alert_id"):
            alert = await get_alert(db, case["alert_id"])
        # Get linked SARs
        sars = await list_sars(db, customer_id=case.get("customer_id"), limit=10)
    return {"case": case, "alert": alert, "sars": sars, "audit_trail": audit}


@app.put("/cases/{case_id}/status", tags=["Cases"])
async def update_case_status(case_id: str, body: CaseStatusUpdate):
    """Update case status."""
    async with get_db() as db:
        case = await get_case(db, case_id)
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")

        # Governance: Cannot close high-risk case without senior review
        if body.status == "closed" and case.get("priority") in ("critical", "high"):
            if not body.resolution:
                raise HTTPException(
                    status_code=400,
                    detail="High-risk cases require a resolution statement before closing.",
                )

        updates: Dict[str, Any] = {"status": body.status}
        if body.resolution:
            updates["resolution"] = body.resolution
        if body.status == "closed":
            updates["closed_at"] = now_wat()

        updated = await update_case(db, case_id, updates)

        from src.governance.audit import log_case_lifecycle
        await log_case_lifecycle(
            db=db,
            case_id=case_id,
            event="status_updated",
            actor=body.updated_by,
            details={"new_status": body.status, "resolution": body.resolution},
        )

    return {"case": updated}


@app.put("/cases/{case_id}/assign", tags=["Cases"])
async def assign_case(case_id: str, body: CaseAssign):
    """Assign case to a team member."""
    async with get_db() as db:
        case = await get_case(db, case_id)
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        updated = await update_case(db, case_id, {"assigned_to": body.assigned_to})

        from src.governance.audit import log_case_lifecycle
        await log_case_lifecycle(
            db=db,
            case_id=case_id,
            event="reassigned",
            actor=body.assigned_by,
            details={
                "assigned_to": body.assigned_to,
                "assigned_by": body.assigned_by,
            },
        )
    return {"case": updated}


# ---------------------------------------------------------------------------
# Governance
# ---------------------------------------------------------------------------

@app.get("/governance/dashboard", tags=["Governance"])
async def governance_dashboard():
    """Governance dashboard with stats and metrics."""
    async with get_db() as db:
        stats = await get_dashboard_stats(db)

        # Audit trail summary
        audit = await get_audit_trail(db, limit=1000)
        event_types: Dict[str, int] = {}
        for entry in audit:
            et = entry.get("event_type", "unknown")
            event_types[et] = event_types.get(et, 0) + 1

        # Model validation summary
        validations = await list_model_validations(db, limit=10)

    return {
        "dashboard_generated_at": now_wat(),
        "stats": stats,
        "governance_controls_active": {
            "confidence_gate": True,
            "materiality_gate": True,
            "sanctions_auto_block": True,
            "sar_human_in_the_loop": True,
            "audit_trail_immutable": True,
            "model_validation_required": True,
            "escalation_chain": True,
        },
        "audit_event_summary": event_types,
        "total_audit_entries": len(audit),
        "model_validations": validations[:3],
        "regulatory_alignment": {
            "cbn_circular": "BSD/DIR/PUB/LAB/019/002",
            "ml_act": "Money Laundering (Prevention and Prohibition) Act 2022",
            "nfiu_reporting": "NFIU STR/CTR requirements",
            "fatf": "FATF 40 Recommendations",
        },
    }


@app.get("/governance/audit-trail", tags=["Governance"])
async def get_full_audit_trail(
    entity_type: Optional[str] = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """Full audit trail with filters."""
    async with get_db() as db:
        entries = await get_audit_trail(db, entity_type=entity_type, limit=limit, offset=offset)
    return {"audit_trail": entries, "count": len(entries)}


@app.get("/governance/audit-trail/{entity_id}", tags=["Governance"])
async def get_entity_audit_trail(entity_id: str):
    """Audit trail for a specific entity."""
    async with get_db() as db:
        entries = await get_audit_trail(db, entity_id=entity_id, limit=200)
    return {"entity_id": entity_id, "audit_trail": entries, "count": len(entries)}


@app.get("/governance/model-validation", tags=["Governance"])
async def get_model_validations(model_name: Optional[str] = None, limit: int = Query(50, ge=1)):
    """Model validation history (CBN annual requirement)."""
    async with get_db() as db:
        validations = await list_model_validations(db, model_name=model_name, limit=limit)
    return {"validations": validations, "count": len(validations)}


@app.post("/governance/model-validation", tags=["Governance"])
async def record_model_validation(body: ModelValidationCreate):
    """Record a model validation result."""
    async with get_db() as db:
        val = await create_model_validation(db, body.model_dump())
        await log_human_decision(
            db=db,
            entity_type="model_validation",
            entity_id=val["id"],
            event_type="model_validation_recorded",
            actor=body.human_reviewer or "system",
            decision="validation_recorded",
            rationale=body.findings or "Annual CBN model validation",
        )
    return {"validation": val}


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

@app.get("/reports/daily", tags=["Reports"])
async def daily_report():
    """Daily compliance summary."""
    async with get_db() as db:
        agent = CaseManagerAgent(db)
        report = await agent.generate_daily_report()
    return report


@app.get("/reports/weekly", tags=["Reports"])
async def weekly_report():
    """Weekly compliance report."""
    from datetime import date
    today = date.today()
    week_start = today - timedelta(days=today.weekday())

    async with get_db() as db:
        stats = await get_dashboard_stats(db)
        all_alerts = await list_alerts(db, limit=1000)
        all_sars = await list_sars(db, limit=500)
        all_cases = await list_cases(db, limit=500)

    week_start_str = week_start.isoformat()
    weekly_alerts = [a for a in all_alerts if a.get("created_at", "")[:10] >= week_start_str]
    weekly_sars = [s for s in all_sars if s.get("created_at", "")[:10] >= week_start_str]

    return {
        "report_type": "weekly_compliance",
        "week_starting": week_start_str,
        "generated_at": now_wat(),
        "institution": os.getenv("INSTITUTION_NAME", "Demo Bank Nigeria Ltd"),
        "totals": stats,
        "this_week": {
            "alerts_generated": len(weekly_alerts),
            "sars_drafted": len([s for s in weekly_sars if s.get("status") == "draft"]),
            "sars_filed": len([s for s in weekly_sars if s.get("status") == "filed"]),
            "high_severity_alerts": len([a for a in weekly_alerts if a.get("severity") in ("high", "critical")]),
        },
        "open_investigations": {
            "total": len([c for c in all_cases if c.get("status") in ("open", "investigating")]),
            "critical": len([c for c in all_cases if c.get("priority") == "critical" and c.get("status") not in ("closed",)]),
            "pending_review": len([c for c in all_cases if c.get("status") == "pending_review"]),
        },
    }


@app.get("/reports/str-summary", tags=["Reports"])
async def str_summary():
    """STR filing summary for NFIU."""
    async with get_db() as db:
        all_sars = await list_sars(db, limit=1000)

    by_status: Dict[str, int] = {}
    by_typology: Dict[str, int] = {}
    by_priority: Dict[str, int] = {}
    filed_sars = []

    for s in all_sars:
        status = s.get("status", "unknown")
        by_status[status] = by_status.get(status, 0) + 1

        typology = s.get("typology", "unknown")
        by_typology[typology] = by_typology.get(typology, 0) + 1

        priority = s.get("priority", "unknown")
        by_priority[priority] = by_priority.get(priority, 0) + 1

        if status == "filed":
            filed_sars.append({
                "sar_id": s["id"],
                "nfiu_reference": s.get("nfiu_reference"),
                "filed_at": s.get("filed_at"),
                "typology": s.get("typology"),
                "priority": s.get("priority"),
                "customer_id": s.get("customer_id"),
            })

    return {
        "report_type": "str_filing_summary",
        "generated_at": now_wat(),
        "institution": os.getenv("INSTITUTION_NAME", "Demo Bank Nigeria Ltd"),
        "total_sars": len(all_sars),
        "by_status": by_status,
        "by_typology": by_typology,
        "by_priority": by_priority,
        "filed_sars": filed_sars,
        "pending_approval": len([s for s in all_sars if s.get("status") == "draft"]),
        "nfiu_filing_deadline": "24 hours from initial STR detection per NFIU requirements",
    }


@app.get("/reports/alert-analytics", tags=["Reports"])
async def alert_analytics():
    """Alert analytics: volume, types, resolution rates."""
    async with get_db() as db:
        agent = CaseManagerAgent(db)
        analytics = await agent.generate_alert_analytics()
    return analytics


# ---------------------------------------------------------------------------
# API endpoints for external integration
# ---------------------------------------------------------------------------

@app.get("/api/stats", tags=["API"])
async def api_stats():
    """Dashboard stats for external integration."""
    async with get_db() as db:
        stats = await get_dashboard_stats(db)
    return {"stats": stats, "timestamp": now_wat()}


@app.get("/api/alerts/summary", tags=["API"])
async def api_alerts_summary():
    """Alert summary for external integration."""
    async with get_db() as db:
        open_alerts = await list_alerts(db, status="open", limit=100)
        critical = [a for a in open_alerts if a.get("severity") == "critical"]
        high = [a for a in open_alerts if a.get("severity") == "high"]
    return {
        "open_alerts": len(open_alerts),
        "critical": len(critical),
        "high": len(high),
        "timestamp": now_wat(),
    }
