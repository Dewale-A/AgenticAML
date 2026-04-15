"""
Audit trail helpers for AgenticAML governance.
Every agent decision MUST be logged via these helpers before returning.
The audit_trail table is append-only (immutable log).
"""

import json
from typing import Any, Dict, Optional

import aiosqlite

from src.database import log_audit, new_id, now_wat


async def log_agent_decision(
    db: aiosqlite.Connection,
    agent_name: str,
    entity_type: str,
    entity_id: str,
    decision: str,
    confidence: Optional[float],
    details: Optional[Dict[str, Any]] = None,
    risk_score: Optional[float] = None,
):
    """Log an agent decision to the immutable audit trail."""
    metadata = {
        "agent": agent_name,
        "decision": decision,
        "confidence": confidence,
        "risk_score": risk_score,
    }
    if details:
        metadata.update(details)

    await log_audit(
        db=db,
        entity_type=entity_type,
        entity_id=entity_id,
        event_type="agent_decision",
        actor=agent_name,
        description=f"{agent_name} decision: {decision}",
        after_state=metadata,
        metadata=metadata,
    )


async def log_governance_decision(
    db: aiosqlite.Connection,
    gate: str,
    entity_type: str,
    entity_id: str,
    passed: bool,
    reason: str,
    requires_human: bool = False,
    action_taken: Optional[str] = None,
):
    """Log a governance gate evaluation."""
    metadata = {
        "gate": gate,
        "passed": passed,
        "reason": reason,
        "requires_human": requires_human,
        "action_taken": action_taken,
    }
    await log_audit(
        db=db,
        entity_type=entity_type,
        entity_id=entity_id,
        event_type="governance_check",
        actor="governance_engine",
        description=f"Governance gate '{gate}': {'PASSED' if passed else 'FAILED'} - {reason}",
        metadata=metadata,
    )


async def log_human_decision(
    db: aiosqlite.Connection,
    entity_type: str,
    entity_id: str,
    event_type: str,
    actor: str,
    decision: str,
    rationale: str,
    before_state: Optional[Dict] = None,
    after_state: Optional[Dict] = None,
):
    """Log a human review/approval decision."""
    await log_audit(
        db=db,
        entity_type=entity_type,
        entity_id=entity_id,
        event_type=event_type,
        actor=actor,
        description=f"Human decision by {actor}: {decision} - {rationale}",
        before_state=before_state,
        after_state=after_state,
        metadata={"decision": decision, "rationale": rationale},
    )


async def log_sanctions_screening(
    db: aiosqlite.Connection,
    entity_id: str,
    name_screened: str,
    lists_checked: list,
    match_count: int,
    recommendation: str,
):
    """Log sanctions screening result (required regardless of outcome)."""
    await log_audit(
        db=db,
        entity_type="transaction",
        entity_id=entity_id,
        event_type="sanctions_screening",
        actor="sanctions_screener_agent",
        description=f"Sanctions screening for '{name_screened}': {match_count} match(es), recommendation={recommendation}",
        metadata={
            "lists_checked": lists_checked,
            "match_count": match_count,
            "recommendation": recommendation,
            "name_screened": name_screened,
        },
    )


async def log_sar_lifecycle(
    db: aiosqlite.Connection,
    sar_id: str,
    event: str,
    actor: str,
    details: Dict[str, Any],
):
    """Log SAR lifecycle events (draft, approve, reject, file)."""
    await log_audit(
        db=db,
        entity_type="sar",
        entity_id=sar_id,
        event_type=f"sar_{event}",
        actor=actor,
        description=f"SAR {event} by {actor}",
        metadata=details,
    )


async def log_case_lifecycle(
    db: aiosqlite.Connection,
    case_id: str,
    event: str,
    actor: str,
    details: Dict[str, Any],
):
    """Log case lifecycle events."""
    await log_audit(
        db=db,
        entity_type="case",
        entity_id=case_id,
        event_type=f"case_{event}",
        actor=actor,
        description=f"Case {event} by {actor}",
        metadata=details,
    )
