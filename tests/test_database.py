"""
Tests for database CRUD operations and audit trail.
"""

import os
import pytest
import asyncio
import tempfile

os.environ["DB_PATH"] = "/tmp/test_aml.db"
os.environ["SEED_ON_START"] = "false"

from src.database import (
    init_db,
    get_db,
    create_customer,
    get_customer,
    update_customer,
    list_customers,
    create_transaction,
    get_transaction,
    list_transactions,
    create_alert,
    get_alert,
    update_alert,
    list_alerts,
    create_sar,
    get_sar,
    update_sar,
    list_sars,
    create_case,
    get_case,
    update_case,
    log_audit,
    get_audit_trail,
    get_dashboard_stats,
    new_id,
    now_wat,
)


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session", autouse=True)
async def setup_db():
    """Initialize test database."""
    import aiosqlite
    # Remove old test db
    try:
        os.remove("/tmp/test_aml.db")
    except FileNotFoundError:
        pass
    await init_db()
    yield
    try:
        os.remove("/tmp/test_aml.db")
    except FileNotFoundError:
        pass


@pytest.fixture
async def db():
    async with await get_db() as conn:
        yield conn


# ---------------------------------------------------------------------------
# Customer CRUD
# ---------------------------------------------------------------------------

class TestCustomerCRUD:
    @pytest.mark.asyncio
    async def test_create_customer(self, db):
        cdata = {
            "id": "test_cust_001",
            "name": "Adaeze Okonkwo",
            "bvn": "22345678901",
            "nin": "12345678901",
            "date_of_birth": "1990-04-15",
            "phone": "+2348012345678",
            "address": "14 Ozumba Mbadiwe, Lagos",
            "account_type": "individual",
            "risk_tier": "low",
            "kyc_status": "pending",
        }
        customer = await create_customer(db, cdata)
        assert customer["id"] == "test_cust_001"
        assert customer["name"] == "Adaeze Okonkwo"
        assert customer["risk_tier"] == "low"
        assert customer["kyc_status"] == "pending"

    @pytest.mark.asyncio
    async def test_get_customer(self, db):
        customer = await get_customer(db, "test_cust_001")
        assert customer is not None
        assert customer["name"] == "Adaeze Okonkwo"

    @pytest.mark.asyncio
    async def test_get_nonexistent_customer(self, db):
        customer = await get_customer(db, "nonexistent")
        assert customer is None

    @pytest.mark.asyncio
    async def test_update_customer(self, db):
        updated = await update_customer(db, "test_cust_001", {"risk_tier": "medium", "kyc_status": "verified"})
        assert updated["risk_tier"] == "medium"
        assert updated["kyc_status"] == "verified"

    @pytest.mark.asyncio
    async def test_list_customers(self, db):
        # Create another customer
        await create_customer(db, {
            "id": "test_cust_002",
            "name": "Emeka Nwosu",
            "bvn": "22345678902",
        })
        customers = await list_customers(db, limit=10)
        assert len(customers) >= 2


# ---------------------------------------------------------------------------
# Transaction CRUD
# ---------------------------------------------------------------------------

class TestTransactionCRUD:
    @pytest.mark.asyncio
    async def test_create_transaction(self, db):
        txn_data = {
            "id": "test_txn_001",
            "customer_id": "test_cust_001",
            "counterparty_name": "Test Counterparty",
            "amount": 5000000.0,
            "currency": "NGN",
            "transaction_type": "transfer",
            "channel": "mobile_app",
            "direction": "outbound",
            "geo_location": "Lagos, NG",
            "timestamp": now_wat(),
            "status": "pending",
        }
        txn = await create_transaction(db, txn_data)
        assert txn["id"] == "test_txn_001"
        assert txn["amount"] == 5000000.0
        assert txn["currency"] == "NGN"

    @pytest.mark.asyncio
    async def test_get_transaction(self, db):
        txn = await get_transaction(db, "test_txn_001")
        assert txn is not None
        assert txn["customer_id"] == "test_cust_001"

    @pytest.mark.asyncio
    async def test_list_transactions_by_customer(self, db):
        txns = await list_transactions(db, customer_id="test_cust_001")
        assert len(txns) >= 1
        assert all(t["customer_id"] == "test_cust_001" for t in txns)


# ---------------------------------------------------------------------------
# Alert CRUD
# ---------------------------------------------------------------------------

class TestAlertCRUD:
    @pytest.mark.asyncio
    async def test_create_alert(self, db):
        alert_data = {
            "id": "test_alert_001",
            "transaction_id": "test_txn_001",
            "customer_id": "test_cust_001",
            "agent_source": "transaction_monitor_agent",
            "alert_type": "STRUCTURING",
            "severity": "high",
            "description": "Test structuring alert",
            "confidence": 0.87,
            "status": "open",
        }
        alert = await create_alert(db, alert_data)
        assert alert["id"] == "test_alert_001"
        assert alert["severity"] == "high"
        assert alert["status"] == "open"

    @pytest.mark.asyncio
    async def test_get_alert(self, db):
        alert = await get_alert(db, "test_alert_001")
        assert alert is not None
        assert alert["alert_type"] == "STRUCTURING"

    @pytest.mark.asyncio
    async def test_update_alert_status(self, db):
        updated = await update_alert(db, "test_alert_001", {"status": "resolved", "resolved_at": now_wat()})
        assert updated["status"] == "resolved"

    @pytest.mark.asyncio
    async def test_list_alerts_with_filters(self, db):
        # Reset status for filter test
        await update_alert(db, "test_alert_001", {"status": "open"})
        alerts = await list_alerts(db, status="open", severity="high")
        assert all(a["status"] == "open" for a in alerts)


# ---------------------------------------------------------------------------
# SAR CRUD
# ---------------------------------------------------------------------------

class TestSarCRUD:
    @pytest.mark.asyncio
    async def test_create_sar(self, db):
        sar_data = {
            "id": "test_sar_001",
            "customer_id": "test_cust_001",
            "draft_narrative": "Test SAR narrative",
            "typology": "structuring_smurfing",
            "priority": "urgent",
            "status": "draft",
            "drafted_by": "sar_generator_agent",
        }
        sar = await create_sar(db, sar_data)
        assert sar["id"] == "test_sar_001"
        assert sar["status"] == "draft"
        assert sar["drafted_by"] == "sar_generator_agent"

    @pytest.mark.asyncio
    async def test_sar_approval_workflow(self, db):
        # Approve SAR (human decision)
        updated = await update_sar(db, "test_sar_001", {
            "status": "approved",
            "approved_by": "compliance_officer",
            "approval_rationale": "Evidence sufficient",
        })
        assert updated["status"] == "approved"
        assert updated["approved_by"] == "compliance_officer"

    @pytest.mark.asyncio
    async def test_list_sars_by_status(self, db):
        sars = await list_sars(db, status="approved")
        assert all(s["status"] == "approved" for s in sars)


# ---------------------------------------------------------------------------
# Case CRUD
# ---------------------------------------------------------------------------

class TestCaseCRUD:
    @pytest.mark.asyncio
    async def test_create_case(self, db):
        case_data = {
            "id": "test_case_001",
            "customer_id": "test_cust_001",
            "case_type": "structuring_investigation",
            "priority": "high",
            "status": "open",
            "assigned_to": "Ngozi Adeyemi",
            "description": "Test investigation case",
        }
        case = await create_case(db, case_data)
        assert case["id"] == "test_case_001"
        assert case["priority"] == "high"
        assert case["assigned_to"] == "Ngozi Adeyemi"

    @pytest.mark.asyncio
    async def test_update_case_status(self, db):
        updated = await update_case(db, "test_case_001", {"status": "investigating"})
        assert updated["status"] == "investigating"


# ---------------------------------------------------------------------------
# Audit Trail
# ---------------------------------------------------------------------------

class TestAuditTrail:
    @pytest.mark.asyncio
    async def test_log_audit(self, db):
        await log_audit(
            db,
            entity_type="transaction",
            entity_id="test_txn_001",
            event_type="agent_decision",
            actor="transaction_monitor_agent",
            description="Test audit entry",
            metadata={"test": True},
        )

    @pytest.mark.asyncio
    async def test_get_audit_trail(self, db):
        entries = await get_audit_trail(db, entity_id="test_txn_001")
        assert len(entries) >= 1
        assert all(e["entity_id"] == "test_txn_001" for e in entries)

    @pytest.mark.asyncio
    async def test_audit_trail_immutability(self, db):
        """Audit trail should only append, never modify."""
        entries_before = await get_audit_trail(db, entity_id="test_txn_001")
        # Add another entry
        await log_audit(
            db, "transaction", "test_txn_001", "test_event", "test_actor", "Another entry"
        )
        entries_after = await get_audit_trail(db, entity_id="test_txn_001")
        assert len(entries_after) > len(entries_before)


# ---------------------------------------------------------------------------
# Dashboard stats
# ---------------------------------------------------------------------------

class TestDashboardStats:
    @pytest.mark.asyncio
    async def test_get_dashboard_stats(self, db):
        stats = await get_dashboard_stats(db)
        assert "total_transactions" in stats
        assert "open_alerts" in stats
        assert "total_customers" in stats
        assert "pending_sar_approvals" in stats
        assert stats["total_transactions"] >= 0
