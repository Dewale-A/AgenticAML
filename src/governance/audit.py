"""
Audit trail helpers for AgenticAML governance.

This module provides structured wrappers around the low-level log_audit()
database function. Each helper corresponds to a distinct type of compliance
event, ensuring that:

1. Every agent decision is attributed to a named agent with a confidence score.
2. Every governance gate evaluation is recorded with its pass/fail outcome.
3. Every human decision (approval, rejection, reassignment) is captured with
   the actor's identity and their stated rationale.
4. Sanctions screening is logged regardless of outcome — CBN requires evidence
   of screening activity even when no match is found.
5. SAR and case lifecycle events are individually tracked to support the
   NFIU's audit requirements for STR filing chains.

The audit_trail table is append-only. These helpers should never be called
to update or delete existing entries — only to append new ones.
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
    """Log an agent decision to the immutable audit trail.

    Called by every agent immediately before returning its result.
    The audit record is written BEFORE the function returns so that
    even if the caller crashes, the decision is persisted.

    The metadata dict combines the core decision fields with any
    additional details the agent passes (triggered rules, patterns, etc.)
    so the full reasoning context is captured in a single audit entry.
    """
    metadata = {
        "agent": agent_name,
        "decision": decision,
        "confidence": confidence,
        "risk_score": risk_score,
    }
    # Merge agent-specific details into metadata for a complete record
    if details:
        metadata.update(details)

    await log_audit(
        db=db,
        entity_type=entity_type,
        entity_id=entity_id,
        event_type="agent_decision",
        actor=agent_name,
        description=f"{agent_name} decision: {decision}",
        # after_state captures the agent's output — the 'state' of the entity
        # as assessed by the agent, even though the entity itself may not change.
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
    """Log a governance gate evaluation.

    Called by the GovernanceEngine for every gate check, pass or fail.
    Recording failed gates is as important as recording passed ones:
    a 'FAILED confidence_gate' entry is the evidence trail that a human
    review was triggered per governance policy.

    The description uses 'PASSED'/'FAILED' uppercase for easy grep-based
    extraction during regulatory examinations.
    """
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
    """Log a human review or approval decision.

    Used for any action taken by a human compliance officer or analyst:
    - SAR approval/rejection
    - Sanctions match review
    - Alert resolution
    - Risk tier downgrade
    - Case closure

    before_state and after_state capture the entity's state before and
    after the human intervention, providing a complete change record for
    CBN regulatory examinations.
    """
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
    """Log sanctions screening results (mandatory regardless of outcome).

    CBN and FATF require that financial institutions maintain evidence of
    screening activity for ALL customers and counterparties — not just those
    with matches. This function is called even for clean (no-match) results.

    lists_checked records which sanctions databases were consulted so the
    institution can demonstrate comprehensive screening coverage to examiners
    (OFAC, UN Consolidated, Nigerian domestic, PEP database, internal watchlist).
    """
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
    """Log SAR lifecycle events: drafted, approved, rejected, filed.

    The SAR lifecycle is a critical audit chain for NFIU compliance.
    Each transition must be individually logged with the actor's identity
    so that the full chain from AI draft → human review → NFIU submission
    is reconstructable during a regulatory examination.

    NFIU requires financial institutions to maintain SAR records for
    a minimum of 5 years with a complete decision audit trail.
    """
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
    """Log case lifecycle events: created, status_updated, reassigned, closed.

    Case lifecycle logging enables SLA compliance tracking (how long did
    the investigation take?) and supports CBN examination requests for
    specific investigation histories.
    """
    await log_audit(
        db=db,
        entity_type="case",
        entity_id=case_id,
        event_type=f"case_{event}",
        actor=actor,
        description=f"Case {event} by {actor}",
        metadata=details,
    )
