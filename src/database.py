"""
Database setup and CRUD operations for AgenticAML.

This module is the single source of truth for all database interactions.
SQLite is used for portability in the demo; the schema is designed to be
PostgreSQL-compatible for production promotion (TEXT PKs, explicit FK
declarations, no SQLite-specific syntax).

DB path defaults to /app/data/aml.db and is overridable via DB_PATH env var
so the same image can be run with an external volume or a test database.
"""

import os
import json
import uuid
import asyncio
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any

import aiosqlite

# West Africa Time (UTC+1) — all timestamps stored and returned in WAT to
# comply with CBN's requirement that audit records reflect local Nigerian time.
WAT = timezone(timedelta(hours=1))

# DB path is read once at module load. Callers can override via env var
# without code changes, which is important for test isolation.
DB_PATH = os.getenv("DB_PATH", "/app/data/aml.db")


def now_wat() -> str:
    """Return current timestamp in WAT ISO format.

    WAT is used consistently across all records so that audit logs, timestamps,
    and SLA calculations are aligned to Nigerian business time without
    timezone ambiguity.
    """
    return datetime.now(WAT).isoformat()


def new_id() -> str:
    """Generate a random UUID string for use as a primary key.

    UUID4 (random) is preferred over sequential IDs to avoid enumeration
    attacks and to allow distributed insertion without coordination.
    """
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

# The schema is defined as a single SQL string and executed via executescript
# so the entire DDL runs in one database round-trip. Using IF NOT EXISTS on
# every table makes this idempotent — safe to call on every startup.
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS customers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    -- BVN (Bank Verification Number): CBN-mandated 11-digit customer ID
    -- issued by the Nigeria Inter-Bank Settlement System (NIBSS).
    bvn TEXT,
    -- NIN (National Identity Number): NIMC-issued 11-digit national ID.
    -- CBN requires both BVN and NIN for Tier-3 accounts.
    nin TEXT,
    date_of_birth TEXT,
    phone TEXT,
    address TEXT,
    -- individual | corporate — determines which KYC fields are mandatory
    account_type TEXT DEFAULT 'individual',
    -- low | medium | high | very_high — drives monitoring intensity and SLA
    risk_tier TEXT DEFAULT 'low',
    -- pending | verified | incomplete | failed | requires_update
    kyc_status TEXT DEFAULT 'pending',
    -- 1 = Politically Exposed Person. PEPs require enhanced due diligence
    -- per FATF Recommendation 12 and CBN AML/CFT guidelines.
    pep_status INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS transactions (
    id TEXT PRIMARY KEY,
    customer_id TEXT REFERENCES customers(id),
    counterparty_name TEXT,
    counterparty_account TEXT,
    amount REAL NOT NULL,
    -- NGN is the default; USD and other currencies are stored as-is
    -- and converted to NGN equivalent for threshold comparisons.
    currency TEXT DEFAULT 'NGN',
    -- transfer | cash_deposit | cash_withdrawal | international_wire |
    -- mobile_money | pos_payment
    transaction_type TEXT,
    -- branch | mobile_app | internet_banking | atm | pos | ussd
    channel TEXT,
    -- inbound | outbound — used for velocity and layering pattern detection
    direction TEXT,
    -- ISO country code or city/country string; used for high-risk geo checks
    geo_location TEXT,
    timestamp TEXT NOT NULL,
    -- pending | cleared | flagged — updated by TransactionMonitorAgent
    status TEXT DEFAULT 'pending',
    -- 0.0–1.0 composite risk score assigned by TransactionMonitorAgent
    risk_score REAL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS alerts (
    id TEXT PRIMARY KEY,
    transaction_id TEXT REFERENCES transactions(id),
    customer_id TEXT REFERENCES customers(id),
    -- Which agent raised this alert (e.g., transaction_monitor_agent)
    agent_source TEXT NOT NULL,
    -- Machine-readable type (e.g., STRUCTURING, VELOCITY_COUNT)
    alert_type TEXT NOT NULL,
    -- low | medium | high | critical
    severity TEXT DEFAULT 'medium',
    description TEXT,
    -- Agent's self-reported confidence in this alert (0.0–1.0).
    -- Used by GovernanceEngine confidence gate.
    confidence REAL,
    -- open | investigating | resolved | false_positive
    status TEXT DEFAULT 'open',
    -- Name of the compliance analyst currently owning this alert
    assigned_to TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    -- Populated when status moves to resolved or false_positive
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS sanctions_matches (
    id TEXT PRIMARY KEY,
    customer_id TEXT REFERENCES customers(id),
    transaction_id TEXT REFERENCES transactions(id),
    -- Which list triggered the match (OFAC_SDN, UN_CONSOLIDATED, etc.)
    list_name TEXT NOT NULL,
    matched_entity TEXT,
    -- exact | strong | partial | weak — determines automatic action
    match_type TEXT,
    -- 0.0–1.0 fuzzy similarity score
    match_score REAL,
    -- block | review | dismissed — action taken post-screening
    action_taken TEXT,
    -- Compliance officer who reviewed this match (mandatory for blocks)
    reviewed_by TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sars (
    id TEXT PRIMARY KEY,
    alert_id TEXT REFERENCES alerts(id),
    customer_id TEXT REFERENCES customers(id),
    -- AI-generated draft narrative awaiting human review
    draft_narrative TEXT,
    -- Human-edited final narrative submitted to NFIU
    final_narrative TEXT,
    -- AML typology (e.g., structuring_smurfing, pep_corruption, layering)
    typology TEXT,
    -- routine | urgent | critical — drives NFIU filing priority
    priority TEXT DEFAULT 'routine',
    -- draft | pending_approval | approved | rejected | filed
    -- Governance: SAR can only be filed after human approval (CBN mandate)
    status TEXT DEFAULT 'draft',
    -- Always set to sar_generator_agent; used for audit trail traceability
    drafted_by TEXT DEFAULT 'sar_generator_agent',
    -- Compliance officer who approved this SAR for filing
    approved_by TEXT,
    approval_rationale TEXT,
    -- Timestamp when SAR was filed with NFIU
    filed_at TEXT,
    -- NFIU-assigned reference number for cross-referencing with regulator
    nfiu_reference TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cases (
    id TEXT PRIMARY KEY,
    alert_id TEXT REFERENCES alerts(id),
    customer_id TEXT REFERENCES customers(id),
    -- Workflow-level type (e.g., sanctions_investigation, kyc_failure)
    case_type TEXT,
    -- critical | high | medium | low — maps to SLA hours in GovernanceRules
    priority TEXT DEFAULT 'medium',
    -- open | investigating | pending_review | closed
    status TEXT DEFAULT 'open',
    -- Compliance team member responsible for this investigation
    assigned_to TEXT,
    description TEXT,
    -- Free-text resolution recorded when case is closed
    resolution TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    closed_at TEXT
);

CREATE TABLE IF NOT EXISTS audit_trail (
    id TEXT PRIMARY KEY,
    -- Entity class this event belongs to (transaction, customer, sar, case…)
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    -- Structured event type (agent_decision, governance_check, sar_approved…)
    event_type TEXT NOT NULL,
    -- Either an agent name (e.g., transaction_monitor_agent) or a human name
    actor TEXT NOT NULL,
    description TEXT,
    -- JSON snapshot of the entity state BEFORE the change (for reversibility audit)
    before_state TEXT,
    -- JSON snapshot AFTER the change
    after_state TEXT,
    -- Any additional structured metadata (e.g., confidence, rule names)
    metadata TEXT,
    -- Stored in WAT for regulatory alignment. This table is append-only —
    -- rows are never updated or deleted (CBN immutable log requirement).
    timestamp TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS model_validations (
    id TEXT PRIMARY KEY,
    model_name TEXT NOT NULL,
    -- annual_cbn_validation | quarterly_review | ad_hoc
    -- CBN mandates annual independent validation of all AML models.
    validation_type TEXT,
    -- Accuracy of the model on held-out historical SAR/alert data
    accuracy REAL,
    -- Measure of model drift since last validation (lower is better)
    drift_score REAL,
    -- Demographic bias score (lower means less bias)
    bias_score REAL,
    -- Fairness score across customer segments (higher is better)
    fairness_score REAL,
    -- Independent human reviewer (cannot be the model's own developer)
    human_reviewer TEXT,
    -- Free-text findings from the independent validation
    findings TEXT,
    validated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

@asynccontextmanager
async def get_db():
    """Yield a database connection with WAL mode and foreign-key enforcement.

    WAL (Write-Ahead Logging) is enabled so concurrent reads don't block
    writes — important when multiple agents and API handlers share the DB.

    Foreign keys are ON to catch referential integrity bugs during development;
    in production this prevents orphaned alerts and sanctions matches.
    """
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = await aiosqlite.connect(DB_PATH)
    # aiosqlite.Row gives dict-like access by column name, which is safer than
    # positional indexing when schema columns are reordered.
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
    finally:
        await db.close()


async def init_db():
    """Initialize the database schema (idempotent — safe to call every startup).

    Uses executescript so all DDL statements run as a single transaction,
    preventing partial schema states if the process is interrupted.
    """
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.executescript(SCHEMA_SQL)
        await db.commit()


# ---------------------------------------------------------------------------
# Audit Trail
# ---------------------------------------------------------------------------

async def log_audit(
    db: aiosqlite.Connection,
    entity_type: str,
    entity_id: str,
    event_type: str,
    actor: str,
    description: str,
    before_state: Optional[Dict] = None,
    after_state: Optional[Dict] = None,
    metadata: Optional[Dict] = None,
):
    """Append an immutable audit log entry.

    Every agent decision and every human action MUST flow through this
    function before the handler returns. The audit_trail table is the
    primary evidence layer for CBN regulatory examinations.

    JSON serialization of before/after states preserves a point-in-time
    snapshot even if the parent record is later updated.
    """
    await db.execute(
        """INSERT INTO audit_trail
           (id, entity_type, entity_id, event_type, actor, description,
            before_state, after_state, metadata, timestamp)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            new_id(),
            entity_type,
            entity_id,
            event_type,
            actor,
            description,
            json.dumps(before_state) if before_state else None,
            json.dumps(after_state) if after_state else None,
            json.dumps(metadata) if metadata else None,
            now_wat(),
        ),
    )
    await db.commit()


async def get_audit_trail(
    db: aiosqlite.Connection,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict]:
    """Retrieve audit entries in descending timestamp order.

    Optional filters let callers fetch the complete history for a specific
    entity (e.g., all events for SAR sar_001) or a class of entities
    (e.g., all governance_check events for report generation).

    The dynamic WHERE clause is built by appending conditions only when
    filters are provided, rather than using a fixed query with NULL checks,
    to keep the query plan efficient.
    """
    conditions = []
    params: List[Any] = []
    if entity_type:
        conditions.append("entity_type = ?")
        params.append(entity_type)
    if entity_id:
        conditions.append("entity_id = ?")
        params.append(entity_id)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params += [limit, offset]
    async with db.execute(
        f"SELECT * FROM audit_trail {where} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
        params,
    ) as cursor:
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------

async def create_customer(db: aiosqlite.Connection, data: Dict) -> Dict:
    """Insert a new customer row and return the full created record.

    The caller may supply an explicit `id` (e.g., seed data with stable IDs)
    or let new_id() generate one. Both timestamps are set to the same WAT
    instant so the initial record is consistent.
    """
    cid = data.get("id") or new_id()
    ts = now_wat()
    await db.execute(
        """INSERT INTO customers
           (id, name, bvn, nin, date_of_birth, phone, address, account_type,
            risk_tier, kyc_status, pep_status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            cid,
            data["name"],
            data.get("bvn"),
            data.get("nin"),
            data.get("date_of_birth"),
            data.get("phone"),
            data.get("address"),
            data.get("account_type", "individual"),
            data.get("risk_tier", "low"),
            data.get("kyc_status", "pending"),
            int(data.get("pep_status", 0)),
            ts,
            ts,
        ),
    )
    await db.commit()
    return await get_customer(db, cid)


async def get_customer(db: aiosqlite.Connection, customer_id: str) -> Optional[Dict]:
    """Fetch a single customer by primary key. Returns None if not found."""
    async with db.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def list_customers(db: aiosqlite.Connection, limit: int = 100, offset: int = 0) -> List[Dict]:
    """Return all customers ordered by creation date (newest first).

    Ordered by created_at DESC so the most recently onboarded customers
    appear first, which is the natural browsing order for compliance dashboards.
    """
    async with db.execute(
        "SELECT * FROM customers ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset)
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def update_customer(db: aiosqlite.Connection, customer_id: str, updates: Dict) -> Optional[Dict]:
    """Apply a partial update to a customer record.

    updated_at is always refreshed on every write so the record shows when
    it was last modified. The caller only needs to pass the fields to change;
    unspecified fields are untouched (partial update pattern).
    """
    updates["updated_at"] = now_wat()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [customer_id]
    await db.execute(f"UPDATE customers SET {set_clause} WHERE id = ?", values)
    await db.commit()
    return await get_customer(db, customer_id)


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

async def create_transaction(db: aiosqlite.Connection, data: Dict) -> Dict:
    """Insert a transaction row.

    The `timestamp` field represents the business event time (when the
    transaction occurred). `created_at` is the system ingestion time.
    They may differ when transactions are ingested in batch.
    """
    tid = data.get("id") or new_id()
    ts = now_wat()
    await db.execute(
        """INSERT INTO transactions
           (id, customer_id, counterparty_name, counterparty_account, amount,
            currency, transaction_type, channel, direction, geo_location,
            timestamp, status, risk_score, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            tid,
            data.get("customer_id"),
            data.get("counterparty_name"),
            data.get("counterparty_account"),
            data["amount"],
            data.get("currency", "NGN"),
            data.get("transaction_type"),
            data.get("channel"),
            data.get("direction"),
            data.get("geo_location"),
            data.get("timestamp", ts),
            data.get("status", "pending"),
            data.get("risk_score"),
            ts,
        ),
    )
    await db.commit()
    return await get_transaction(db, tid)


async def get_transaction(db: aiosqlite.Connection, transaction_id: str) -> Optional[Dict]:
    """Fetch a single transaction by primary key."""
    async with db.execute("SELECT * FROM transactions WHERE id = ?", (transaction_id,)) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def list_transactions(
    db: aiosqlite.Connection,
    customer_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict]:
    """Return transactions with optional customer and status filters.

    Ordered by timestamp DESC so the most recent transaction appears first,
    which is the natural order for compliance review workflows.
    """
    conditions = []
    params: List[Any] = []
    if customer_id:
        conditions.append("customer_id = ?")
        params.append(customer_id)
    if status:
        conditions.append("status = ?")
        params.append(status)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params += [limit, offset]
    async with db.execute(
        f"SELECT * FROM transactions {where} ORDER BY timestamp DESC LIMIT ? OFFSET ?", params
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def update_transaction_status(
    db: aiosqlite.Connection, transaction_id: str, status: str, risk_score: Optional[float] = None
) -> Optional[Dict]:
    """Update a transaction's screening status and optionally its risk score.

    Called by TransactionMonitorAgent after scoring. The risk_score is stored
    alongside the status so downstream queries can filter by risk level
    without re-running the scoring pipeline.
    """
    if risk_score is not None:
        await db.execute(
            "UPDATE transactions SET status = ?, risk_score = ? WHERE id = ?",
            (status, risk_score, transaction_id),
        )
    else:
        await db.execute("UPDATE transactions SET status = ? WHERE id = ?", (status, transaction_id))
    await db.commit()
    return await get_transaction(db, transaction_id)


async def get_customer_transactions(
    db: aiosqlite.Connection, customer_id: str, days: int = 90
) -> List[Dict]:
    """Return all transactions for a customer within a lookback window.

    The 90-day default covers the FATF-recommended behavioural analysis
    window for transaction pattern detection. Extended windows (e.g., 180
    days for dormant account checks) can be requested by passing a larger
    `days` value.
    """
    cutoff = (datetime.now(WAT) - timedelta(days=days)).isoformat()
    async with db.execute(
        "SELECT * FROM transactions WHERE customer_id = ? AND timestamp >= ? ORDER BY timestamp DESC",
        (customer_id, cutoff),
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

async def create_alert(db: aiosqlite.Connection, data: Dict) -> Dict:
    """Insert an alert raised by an agent.

    agent_source and alert_type are non-nullable because every alert must be
    attributable to a specific agent and a machine-readable type for
    analytics (false positive rates by agent, alert volume by type).
    """
    aid = data.get("id") or new_id()
    ts = now_wat()
    await db.execute(
        """INSERT INTO alerts
           (id, transaction_id, customer_id, agent_source, alert_type,
            severity, description, confidence, status, assigned_to, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            aid,
            data.get("transaction_id"),
            data.get("customer_id"),
            data["agent_source"],
            data["alert_type"],
            data.get("severity", "medium"),
            data.get("description"),
            data.get("confidence"),
            data.get("status", "open"),
            data.get("assigned_to"),
            ts,
        ),
    )
    await db.commit()
    return await get_alert(db, aid)


async def get_alert(db: aiosqlite.Connection, alert_id: str) -> Optional[Dict]:
    """Fetch a single alert by primary key."""
    async with db.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def list_alerts(
    db: aiosqlite.Connection,
    status: Optional[str] = None,
    severity: Optional[str] = None,
    agent_source: Optional[str] = None,
    customer_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict]:
    """Return alerts with multi-dimensional filters.

    The agent_source filter allows per-agent false positive analysis
    (e.g., 'show me only alerts from sanctions_screener_agent').
    """
    conditions = []
    params: List[Any] = []
    if status:
        conditions.append("status = ?")
        params.append(status)
    if severity:
        conditions.append("severity = ?")
        params.append(severity)
    if agent_source:
        conditions.append("agent_source = ?")
        params.append(agent_source)
    if customer_id:
        conditions.append("customer_id = ?")
        params.append(customer_id)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params += [limit, offset]
    async with db.execute(
        f"SELECT * FROM alerts {where} ORDER BY created_at DESC LIMIT ? OFFSET ?", params
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def update_alert(db: aiosqlite.Connection, alert_id: str, updates: Dict) -> Optional[Dict]:
    """Apply a partial update to an alert (e.g., change status, assign analyst)."""
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [alert_id]
    await db.execute(f"UPDATE alerts SET {set_clause} WHERE id = ?", values)
    await db.commit()
    return await get_alert(db, alert_id)


# ---------------------------------------------------------------------------
# Sanctions Matches
# ---------------------------------------------------------------------------

async def create_sanctions_match(db: aiosqlite.Connection, data: Dict) -> Dict:
    """Persist a sanctions screening hit to the database.

    Every match — including weak ones that result in 'review' rather than
    'block' — is stored. CBN requires financial institutions to maintain
    evidence of all screening activity, not just confirmed hits.
    """
    mid = data.get("id") or new_id()
    ts = now_wat()
    await db.execute(
        """INSERT INTO sanctions_matches
           (id, customer_id, transaction_id, list_name, matched_entity,
            match_type, match_score, action_taken, reviewed_by, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            mid,
            data.get("customer_id"),
            data.get("transaction_id"),
            data["list_name"],
            data.get("matched_entity"),
            data.get("match_type"),
            data.get("match_score"),
            data.get("action_taken"),
            data.get("reviewed_by"),
            ts,
        ),
    )
    await db.commit()
    return await get_sanctions_match(db, mid)


async def get_sanctions_match(db: aiosqlite.Connection, match_id: str) -> Optional[Dict]:
    """Fetch a single sanctions match record."""
    async with db.execute("SELECT * FROM sanctions_matches WHERE id = ?", (match_id,)) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def list_sanctions_matches(
    db: aiosqlite.Connection,
    customer_id: Optional[str] = None,
    action_taken: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict]:
    """Return sanctions matches. Filter by customer or action (block/review/dismissed)."""
    conditions = []
    params: List[Any] = []
    if customer_id:
        conditions.append("customer_id = ?")
        params.append(customer_id)
    if action_taken:
        conditions.append("action_taken = ?")
        params.append(action_taken)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params += [limit, offset]
    async with db.execute(
        f"SELECT * FROM sanctions_matches {where} ORDER BY created_at DESC LIMIT ? OFFSET ?", params
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def update_sanctions_match(db: aiosqlite.Connection, match_id: str, updates: Dict) -> Optional[Dict]:
    """Update a sanctions match record (e.g., record reviewer, change action)."""
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [match_id]
    await db.execute(f"UPDATE sanctions_matches SET {set_clause} WHERE id = ?", values)
    await db.commit()
    return await get_sanctions_match(db, match_id)


# ---------------------------------------------------------------------------
# SARs
# ---------------------------------------------------------------------------

async def create_sar(db: aiosqlite.Connection, data: Dict) -> Dict:
    """Insert a Suspicious Activity Report draft.

    SARs are always created in 'draft' status. The governance engine and
    API layer enforce that a human approval step must occur before the
    status can advance to 'filed'. This is a hard CBN/NFIU requirement.
    """
    sid = data.get("id") or new_id()
    ts = now_wat()
    await db.execute(
        """INSERT INTO sars
           (id, alert_id, customer_id, draft_narrative, final_narrative,
            typology, priority, status, drafted_by, approved_by,
            approval_rationale, filed_at, nfiu_reference, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            sid,
            data.get("alert_id"),
            data.get("customer_id"),
            data.get("draft_narrative"),
            data.get("final_narrative"),
            data.get("typology"),
            data.get("priority", "routine"),
            data.get("status", "draft"),
            data.get("drafted_by", "sar_generator_agent"),
            data.get("approved_by"),
            data.get("approval_rationale"),
            data.get("filed_at"),
            data.get("nfiu_reference"),
            ts,
            ts,
        ),
    )
    await db.commit()
    return await get_sar(db, sid)


async def get_sar(db: aiosqlite.Connection, sar_id: str) -> Optional[Dict]:
    """Fetch a single SAR by primary key."""
    async with db.execute("SELECT * FROM sars WHERE id = ?", (sar_id,)) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def list_sars(
    db: aiosqlite.Connection,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    customer_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict]:
    """Return SARs. Filtering by status='draft' shows pending human approvals."""
    conditions = []
    params: List[Any] = []
    if status:
        conditions.append("status = ?")
        params.append(status)
    if priority:
        conditions.append("priority = ?")
        params.append(priority)
    if customer_id:
        conditions.append("customer_id = ?")
        params.append(customer_id)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params += [limit, offset]
    async with db.execute(
        f"SELECT * FROM sars {where} ORDER BY created_at DESC LIMIT ? OFFSET ?", params
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def update_sar(db: aiosqlite.Connection, sar_id: str, updates: Dict) -> Optional[Dict]:
    """Apply a partial update to a SAR (e.g., status change, approval recording).

    updated_at is refreshed on every write so the SAR lifecycle timeline
    is accurate in the audit trail.
    """
    updates["updated_at"] = now_wat()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [sar_id]
    await db.execute(f"UPDATE sars SET {set_clause} WHERE id = ?", values)
    await db.commit()
    return await get_sar(db, sar_id)


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------

async def create_case(db: aiosqlite.Connection, data: Dict) -> Dict:
    """Create an investigation case and return it.

    Cases are the top-level workflow unit that compliance analysts work through.
    They are linked to alerts and may have one or more SARs generated during
    the investigation lifecycle.
    """
    cid = data.get("id") or new_id()
    ts = now_wat()
    await db.execute(
        """INSERT INTO cases
           (id, alert_id, customer_id, case_type, priority, status,
            assigned_to, description, resolution, created_at, updated_at, closed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            cid,
            data.get("alert_id"),
            data.get("customer_id"),
            data.get("case_type"),
            data.get("priority", "medium"),
            data.get("status", "open"),
            data.get("assigned_to"),
            data.get("description"),
            data.get("resolution"),
            ts,
            ts,
            data.get("closed_at"),
        ),
    )
    await db.commit()
    return await get_case(db, cid)


async def get_case(db: aiosqlite.Connection, case_id: str) -> Optional[Dict]:
    """Fetch a single case by primary key."""
    async with db.execute("SELECT * FROM cases WHERE id = ?", (case_id,)) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def list_cases(
    db: aiosqlite.Connection,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    assigned_to: Optional[str] = None,
    customer_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict]:
    """Return cases with workload-management filters.

    The assigned_to filter supports per-analyst workload views.
    The priority filter lets managers surface critical cases quickly.
    """
    conditions = []
    params: List[Any] = []
    if status:
        conditions.append("status = ?")
        params.append(status)
    if priority:
        conditions.append("priority = ?")
        params.append(priority)
    if assigned_to:
        conditions.append("assigned_to = ?")
        params.append(assigned_to)
    if customer_id:
        conditions.append("customer_id = ?")
        params.append(customer_id)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params += [limit, offset]
    async with db.execute(
        f"SELECT * FROM cases {where} ORDER BY created_at DESC LIMIT ? OFFSET ?", params
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def update_case(db: aiosqlite.Connection, case_id: str, updates: Dict) -> Optional[Dict]:
    """Apply a partial update to a case.

    updated_at is always refreshed so the case timeline is accurate for
    SLA tracking — supervisors can see how long a case has been idle.
    """
    updates["updated_at"] = now_wat()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [case_id]
    await db.execute(f"UPDATE cases SET {set_clause} WHERE id = ?", values)
    await db.commit()
    return await get_case(db, case_id)


# ---------------------------------------------------------------------------
# Model Validations
# ---------------------------------------------------------------------------

async def create_model_validation(db: aiosqlite.Connection, data: Dict) -> Dict:
    """Record a model validation result.

    CBN BSD/DIR/PUB/LAB/019/002 mandates annual independent validation of
    all AI/ML models used in AML compliance. This table stores each
    validation event so the regulator can inspect the history on examination.

    Metrics stored (accuracy, drift_score, bias_score, fairness_score) align
    with the CBN's Model Risk Management guidelines and FATF's requirements
    for AI-based financial crime detection systems.
    """
    vid = data.get("id") or new_id()
    ts = now_wat()
    await db.execute(
        """INSERT INTO model_validations
           (id, model_name, validation_type, accuracy, drift_score, bias_score,
            fairness_score, human_reviewer, findings, validated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            vid,
            data["model_name"],
            data.get("validation_type"),
            data.get("accuracy"),
            data.get("drift_score"),
            data.get("bias_score"),
            data.get("fairness_score"),
            data.get("human_reviewer"),
            data.get("findings"),
            ts,
        ),
    )
    await db.commit()
    async with db.execute("SELECT * FROM model_validations WHERE id = ?", (vid,)) as cur:
        row = await cur.fetchone()
    return dict(row)


async def list_model_validations(
    db: aiosqlite.Connection, model_name: Optional[str] = None, limit: int = 50
) -> List[Dict]:
    """Return model validation history, newest first.

    Filtering by model_name allows examiners to review the full validation
    history for a specific model (e.g., the sanctions screener's fuzzy
    matching algorithm).
    """
    if model_name:
        async with db.execute(
            "SELECT * FROM model_validations WHERE model_name = ? ORDER BY validated_at DESC LIMIT ?",
            (model_name, limit),
        ) as cur:
            rows = await cur.fetchall()
    else:
        async with db.execute(
            "SELECT * FROM model_validations ORDER BY validated_at DESC LIMIT ?", (limit,)
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Dashboard stats helpers
# ---------------------------------------------------------------------------

async def get_dashboard_stats(db: aiosqlite.Connection) -> Dict:
    """Aggregate key compliance metrics for the governance dashboard.

    Each stat is fetched with its own query rather than a single complex
    JOIN to keep each query simple and independently fast. The function
    is called by the governance dashboard and daily report endpoints.

    Counts returned:
    - total/flagged transactions: transaction processing volume and flag rate
    - open/total alerts: triage queue health
    - pending_sar_approvals: human review backlog (compliance officer workload)
    - filed_sars: evidence of regulatory filing activity
    - open_cases: active investigation load
    - sanctions_blocks: number of transactions auto-blocked per CBN mandate
    - total/high_risk customers: customer base risk profile
    """
    stats: Dict[str, Any] = {}

    async with db.execute("SELECT COUNT(*) as c FROM transactions") as cur:
        row = await cur.fetchone()
        stats["total_transactions"] = row["c"]

    async with db.execute("SELECT COUNT(*) as c FROM transactions WHERE status = 'flagged'") as cur:
        row = await cur.fetchone()
        stats["flagged_transactions"] = row["c"]

    async with db.execute("SELECT COUNT(*) as c FROM alerts WHERE status = 'open'") as cur:
        row = await cur.fetchone()
        stats["open_alerts"] = row["c"]

    async with db.execute("SELECT COUNT(*) as c FROM alerts") as cur:
        row = await cur.fetchone()
        stats["total_alerts"] = row["c"]

    async with db.execute("SELECT COUNT(*) as c FROM sars WHERE status = 'draft'") as cur:
        row = await cur.fetchone()
        stats["pending_sar_approvals"] = row["c"]

    async with db.execute("SELECT COUNT(*) as c FROM sars WHERE status = 'filed'") as cur:
        row = await cur.fetchone()
        stats["filed_sars"] = row["c"]

    async with db.execute(
        "SELECT COUNT(*) as c FROM cases WHERE status IN ('open', 'investigating')"
    ) as cur:
        row = await cur.fetchone()
        stats["open_cases"] = row["c"]

    async with db.execute(
        "SELECT AVG(confidence) as avg_conf FROM alerts WHERE confidence IS NOT NULL"
    ) as cur:
        row = await cur.fetchone()
        stats["avg_confidence"] = round(row["avg_conf"] or 0.0, 4)

    async with db.execute(
        "SELECT COUNT(*) as c FROM sanctions_matches WHERE action_taken = 'block'"
    ) as cur:
        row = await cur.fetchone()
        stats["sanctions_blocks"] = row["c"]

    async with db.execute("SELECT COUNT(*) as c FROM customers") as cur:
        row = await cur.fetchone()
        stats["total_customers"] = row["c"]

    # High-risk customers (high + very_high) are tracked separately because
    # they require enhanced due diligence and have stricter monitoring thresholds.
    async with db.execute(
        "SELECT COUNT(*) as c FROM customers WHERE risk_tier IN ('high', 'very_high')"
    ) as cur:
        row = await cur.fetchone()
        stats["high_risk_customers"] = row["c"]

    return stats
