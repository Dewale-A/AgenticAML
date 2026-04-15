"""
Database setup and CRUD operations for AgenticAML.
Uses SQLite for demo (PostgreSQL-compatible schema for production).
DB path: /app/data/aml.db (configurable via DB_PATH env var).
"""

import os
import json
import uuid
import asyncio
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any

import aiosqlite

# West Africa Time (UTC+1)
WAT = timezone(timedelta(hours=1))

DB_PATH = os.getenv("DB_PATH", "/app/data/aml.db")


def now_wat() -> str:
    """Return current timestamp in WAT ISO format."""
    return datetime.now(WAT).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS customers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    bvn TEXT,
    nin TEXT,
    date_of_birth TEXT,
    phone TEXT,
    address TEXT,
    account_type TEXT DEFAULT 'individual',
    risk_tier TEXT DEFAULT 'low',
    kyc_status TEXT DEFAULT 'pending',
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
    currency TEXT DEFAULT 'NGN',
    transaction_type TEXT,
    channel TEXT,
    direction TEXT,
    geo_location TEXT,
    timestamp TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    risk_score REAL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS alerts (
    id TEXT PRIMARY KEY,
    transaction_id TEXT REFERENCES transactions(id),
    customer_id TEXT REFERENCES customers(id),
    agent_source TEXT NOT NULL,
    alert_type TEXT NOT NULL,
    severity TEXT DEFAULT 'medium',
    description TEXT,
    confidence REAL,
    status TEXT DEFAULT 'open',
    assigned_to TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS sanctions_matches (
    id TEXT PRIMARY KEY,
    customer_id TEXT REFERENCES customers(id),
    transaction_id TEXT REFERENCES transactions(id),
    list_name TEXT NOT NULL,
    matched_entity TEXT,
    match_type TEXT,
    match_score REAL,
    action_taken TEXT,
    reviewed_by TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sars (
    id TEXT PRIMARY KEY,
    alert_id TEXT REFERENCES alerts(id),
    customer_id TEXT REFERENCES customers(id),
    draft_narrative TEXT,
    final_narrative TEXT,
    typology TEXT,
    priority TEXT DEFAULT 'routine',
    status TEXT DEFAULT 'draft',
    drafted_by TEXT DEFAULT 'sar_generator_agent',
    approved_by TEXT,
    approval_rationale TEXT,
    filed_at TEXT,
    nfiu_reference TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cases (
    id TEXT PRIMARY KEY,
    alert_id TEXT REFERENCES alerts(id),
    customer_id TEXT REFERENCES customers(id),
    case_type TEXT,
    priority TEXT DEFAULT 'medium',
    status TEXT DEFAULT 'open',
    assigned_to TEXT,
    description TEXT,
    resolution TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    closed_at TEXT
);

CREATE TABLE IF NOT EXISTS audit_trail (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    description TEXT,
    before_state TEXT,
    after_state TEXT,
    metadata TEXT,
    timestamp TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS model_validations (
    id TEXT PRIMARY KEY,
    model_name TEXT NOT NULL,
    validation_type TEXT,
    accuracy REAL,
    drift_score REAL,
    bias_score REAL,
    fairness_score REAL,
    human_reviewer TEXT,
    findings TEXT,
    validated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

@asynccontextmanager
async def get_db():
    """Get a new database connection with row_factory set."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
    finally:
        await db.close()


async def init_db():
    """Initialize the database schema."""
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
    """Append an immutable audit log entry."""
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
    async with db.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def list_customers(db: aiosqlite.Connection, limit: int = 100, offset: int = 0) -> List[Dict]:
    async with db.execute(
        "SELECT * FROM customers ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset)
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def update_customer(db: aiosqlite.Connection, customer_id: str, updates: Dict) -> Optional[Dict]:
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
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [alert_id]
    await db.execute(f"UPDATE alerts SET {set_clause} WHERE id = ?", values)
    await db.commit()
    return await get_alert(db, alert_id)


# ---------------------------------------------------------------------------
# Sanctions Matches
# ---------------------------------------------------------------------------

async def create_sanctions_match(db: aiosqlite.Connection, data: Dict) -> Dict:
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
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [match_id]
    await db.execute(f"UPDATE sanctions_matches SET {set_clause} WHERE id = ?", values)
    await db.commit()
    return await get_sanctions_match(db, match_id)


# ---------------------------------------------------------------------------
# SARs
# ---------------------------------------------------------------------------

async def create_sar(db: aiosqlite.Connection, data: Dict) -> Dict:
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

    async with db.execute("SELECT COUNT(*) as c FROM cases WHERE status = 'open'") as cur:
        row = await cur.fetchone()
        stats["open_cases"] = row["c"]

    async with db.execute(
        "SELECT COUNT(*) as c FROM sanctions_matches WHERE action_taken = 'block'"
    ) as cur:
        row = await cur.fetchone()
        stats["sanctions_blocks"] = row["c"]

    async with db.execute("SELECT COUNT(*) as c FROM customers") as cur:
        row = await cur.fetchone()
        stats["total_customers"] = row["c"]

    async with db.execute(
        "SELECT COUNT(*) as c FROM customers WHERE risk_tier IN ('high', 'very_high')"
    ) as cur:
        row = await cur.fetchone()
        stats["high_risk_customers"] = row["c"]

    return stats
