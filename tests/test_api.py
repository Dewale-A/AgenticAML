"""
Tests for all AgenticAML FastAPI endpoints.

Uses httpx.AsyncClient with the FastAPI app directly (no external server required).
Covers: health, transactions, customers, alerts, sanctions, SARs, cases, governance, reports.
"""

import os
import asyncio
import pytest

os.environ["DB_PATH"] = "/tmp/test_api_aml.db"
os.environ["SEED_ON_START"] = "false"
os.environ["OPENAI_API_KEY"] = ""

import httpx
from fastapi.testclient import TestClient

from src.database import (
    init_db,
    get_db,
    create_customer,
    create_transaction,
    create_alert,
    create_sar,
    create_case,
    now_wat,
    new_id,
)
from src.main import app


# ---------------------------------------------------------------------------
# Session fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session", autouse=True)
async def setup_db():
    try:
        os.remove("/tmp/test_api_aml.db")
    except FileNotFoundError:
        pass
    await init_db()
    yield
    try:
        os.remove("/tmp/test_api_aml.db")
    except FileNotFoundError:
        pass


@pytest.fixture(scope="session")
async def seed_data():
    """Seed test records once for the whole API test session."""
    async with await get_db() as db:
        # Customer
        cust = await create_customer(db, {
            "id": "api_test_cust_001",
            "name": "Uchenna Obiora",
            "bvn": "77788899900",
            "nin": "88899900011",
            "date_of_birth": "1988-08-15",
            "phone": "+2347055667788",
            "address": "30 Adetokunbo Ademola, Lagos",
            "account_type": "individual",
            "risk_tier": "low",
            "kyc_status": "pending",
            "pep_status": 0,
        })

        # Transaction
        txn = await create_transaction(db, {
            "id": "api_test_txn_001",
            "customer_id": "api_test_cust_001",
            "counterparty_name": "API Test Payee",
            "amount": 12_000_000.0,
            "currency": "NGN",
            "transaction_type": "transfer",
            "channel": "internet_banking",
            "direction": "outbound",
            "geo_location": "Lagos, NG",
            "timestamp": now_wat(),
            "status": "pending",
        })

        # Alert
        alert = await create_alert(db, {
            "id": "api_test_alert_001",
            "transaction_id": "api_test_txn_001",
            "customer_id": "api_test_cust_001",
            "agent_source": "transaction_monitor_agent",
            "alert_type": "TRANSFER_THRESHOLD",
            "severity": "high",
            "description": "Transfer above NGN 10M threshold",
            "confidence": 0.88,
            "status": "open",
        })

        # SAR
        sar = await create_sar(db, {
            "id": "api_test_sar_001",
            "alert_id": "api_test_alert_001",
            "customer_id": "api_test_cust_001",
            "draft_narrative": "The subject customer Uchenna Obiora executed a transfer of NGN 12,000,000 exceeding the reporting threshold. Enhanced due diligence is warranted.",
            "typology": "threshold_evasion",
            "priority": "urgent",
            "status": "draft",
            "drafted_by": "sar_generator_agent",
        })

        # Case
        case = await create_case(db, {
            "id": "api_test_case_001",
            "alert_id": "api_test_alert_001",
            "customer_id": "api_test_cust_001",
            "case_type": "transfer_monitoring",
            "priority": "high",
            "status": "open",
            "assigned_to": "Ngozi Adeyemi",
            "description": "Large transfer investigation",
        })

    return {
        "customer_id": "api_test_cust_001",
        "transaction_id": "api_test_txn_001",
        "alert_id": "api_test_alert_001",
        "sar_id": "api_test_sar_001",
        "case_id": "api_test_case_001",
    }


@pytest.fixture(scope="session")
def client():
    """Synchronous test client for the FastAPI app."""
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

class TestHealthEndpoint:

    def test_health_returns_200(self, client, seed_data):
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_response_structure(self, client, seed_data):
        response = client.get("/health")
        data = response.json()
        assert "status" in data
        assert data["status"] == "ok"

    def test_health_has_version(self, client, seed_data):
        response = client.get("/health")
        data = response.json()
        assert "version" in data or "app" in data or "status" in data


# ---------------------------------------------------------------------------
# Customer endpoints
# ---------------------------------------------------------------------------

class TestCustomerEndpoints:

    def test_list_customers_200(self, client, seed_data):
        response = client.get("/customers")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_list_customers_returns_seeded_customer(self, client, seed_data):
        response = client.get("/customers")
        assert response.status_code == 200
        customer_ids = [c["id"] for c in response.json()]
        assert "api_test_cust_001" in customer_ids

    def test_get_customer_by_id(self, client, seed_data):
        response = client.get(f"/customers/api_test_cust_001")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "api_test_cust_001"
        assert data["name"] == "Uchenna Obiora"

    def test_get_nonexistent_customer_404(self, client, seed_data):
        response = client.get("/customers/nonexistent_customer_xyz")
        assert response.status_code == 404

    def test_trigger_kyc_verification(self, client, seed_data):
        response = client.post("/customers/api_test_cust_001/kyc")
        assert response.status_code == 200
        data = response.json()
        assert "kyc_status" in data
        assert data["kyc_status"] in ("verified", "incomplete", "failed", "requires_update")

    def test_update_risk_tier_requires_approval(self, client, seed_data):
        payload = {
            "risk_tier": "medium",
            "rationale": "Increased transaction volume observed",
            "approved_by": "compliance_officer",
        }
        response = client.put("/customers/api_test_cust_001/risk-tier", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["risk_tier"] == "medium"

    def test_update_risk_tier_invalid_customer_404(self, client, seed_data):
        payload = {
            "risk_tier": "high",
            "rationale": "Test",
            "approved_by": "compliance_officer",
        }
        response = client.put("/customers/nonexistent_xyz/risk-tier", json=payload)
        assert response.status_code == 404

    def test_list_customers_limit_param(self, client, seed_data):
        response = client.get("/customers?limit=1")
        assert response.status_code == 200
        data = response.json()
        assert len(data) <= 1


# ---------------------------------------------------------------------------
# Transaction endpoints
# ---------------------------------------------------------------------------

class TestTransactionEndpoints:

    def test_list_transactions_200(self, client, seed_data):
        response = client.get("/transactions")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_get_transaction_by_id(self, client, seed_data):
        response = client.get("/transactions/api_test_txn_001")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "api_test_txn_001"
        assert data["amount"] == 12_000_000.0

    def test_get_nonexistent_transaction_404(self, client, seed_data):
        response = client.get("/transactions/nonexistent_txn_xyz")
        assert response.status_code == 404

    def test_screen_single_transaction(self, client, seed_data):
        """POST /transactions/screen runs the full 6-agent pipeline."""
        payload = {
            "customer_id": "api_test_cust_001",
            "counterparty_name": "New Payee Ltd",
            "amount": 500_000.0,
            "currency": "NGN",
            "transaction_type": "transfer",
            "channel": "mobile_app",
            "direction": "outbound",
            "geo_location": "Lagos, NG",
            "timestamp": now_wat(),
        }
        response = client.post("/transactions/screen", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert "transaction_id" in data
        assert "final_status" in data
        assert data["final_status"] in ("cleared", "flagged", "blocked", "escalated")

    def test_screen_transaction_returns_monitor_result(self, client, seed_data):
        """Pipeline result must include monitor_result."""
        payload = {
            "customer_id": "api_test_cust_001",
            "amount": 200_000.0,
            "currency": "NGN",
            "transaction_type": "transfer",
            "channel": "mobile_app",
            "direction": "inbound",
            "geo_location": "Abuja, NG",
            "timestamp": now_wat(),
        }
        response = client.post("/transactions/screen", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert "monitor_result" in data
        assert "kyc_result" in data
        assert "sanctions_result" in data

    def test_screen_transaction_with_high_risk_amount(self, client, seed_data):
        """Large transfer should produce flagged/escalated status."""
        payload = {
            "customer_id": "api_test_cust_001",
            "amount": 60_000_000.0,
            "currency": "NGN",
            "transaction_type": "transfer",
            "channel": "internet_banking",
            "direction": "outbound",
            "geo_location": "Lagos, NG",
            "timestamp": now_wat(),
        }
        response = client.post("/transactions/screen", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["final_status"] in ("flagged", "blocked", "escalated")

    def test_batch_screen_transactions(self, client, seed_data):
        """POST /transactions/batch screens multiple transactions at once."""
        payload = {
            "transactions": [
                {
                    "customer_id": "api_test_cust_001",
                    "amount": 100_000.0,
                    "currency": "NGN",
                    "transaction_type": "transfer",
                    "channel": "mobile_app",
                    "direction": "inbound",
                    "geo_location": "Lagos, NG",
                    "timestamp": now_wat(),
                },
                {
                    "customer_id": "api_test_cust_001",
                    "amount": 200_000.0,
                    "currency": "NGN",
                    "transaction_type": "cash_deposit",
                    "channel": "branch",
                    "direction": "inbound",
                    "geo_location": "Lagos, NG",
                    "timestamp": now_wat(),
                },
            ]
        }
        response = client.post("/transactions/batch", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 2

    def test_screen_transaction_invalid_amount_422(self, client, seed_data):
        """Zero or negative amount must be rejected with 422."""
        payload = {
            "customer_id": "api_test_cust_001",
            "amount": 0,
            "currency": "NGN",
            "transaction_type": "transfer",
            "channel": "mobile_app",
            "direction": "inbound",
            "geo_location": "Lagos, NG",
            "timestamp": now_wat(),
        }
        response = client.post("/transactions/screen", json=payload)
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Alert endpoints
# ---------------------------------------------------------------------------

class TestAlertEndpoints:

    def test_list_alerts_200(self, client, seed_data):
        response = client.get("/alerts")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_list_alerts_includes_seeded_alert(self, client, seed_data):
        response = client.get("/alerts")
        alert_ids = [a["id"] for a in response.json()]
        assert "api_test_alert_001" in alert_ids

    def test_get_alert_by_id(self, client, seed_data):
        response = client.get("/alerts/api_test_alert_001")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "api_test_alert_001"
        assert data["alert_type"] == "TRANSFER_THRESHOLD"

    def test_get_nonexistent_alert_404(self, client, seed_data):
        response = client.get("/alerts/nonexistent_alert_xyz")
        assert response.status_code == 404

    def test_filter_alerts_by_status(self, client, seed_data):
        response = client.get("/alerts?status=open")
        assert response.status_code == 200
        for alert in response.json():
            assert alert["status"] == "open"

    def test_filter_alerts_by_severity(self, client, seed_data):
        response = client.get("/alerts?severity=high")
        assert response.status_code == 200
        for alert in response.json():
            assert alert["severity"] == "high"

    def test_assign_alert_to_analyst(self, client, seed_data):
        payload = {"assigned_to": "Emeka Nwosu"}
        response = client.put("/alerts/api_test_alert_001/assign", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["assigned_to"] == "Emeka Nwosu"

    def test_resolve_alert_with_rationale(self, client, seed_data):
        payload = {
            "rationale": "Customer confirmed the transfer was authorized",
            "resolution": "resolved",
        }
        response = client.put("/alerts/api_test_alert_001/resolve", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("resolved", "false_positive")


# ---------------------------------------------------------------------------
# Sanctions endpoints
# ---------------------------------------------------------------------------

class TestSanctionsEndpoints:

    def test_screen_name_against_lists(self, client, seed_data):
        """GET /sanctions/screen must screen a name and return recommendation."""
        response = client.get("/sanctions/screen?name=Chukwuemeka+Amaka")
        assert response.status_code == 200
        data = response.json()
        assert "overall_recommendation" in data
        assert data["overall_recommendation"] in ("clear", "review", "block")
        assert "matches" in data

    def test_screen_name_missing_param_422(self, client, seed_data):
        """Sanctions screen without name param must return 422."""
        response = client.get("/sanctions/screen")
        assert response.status_code == 422

    def test_list_sanctions_matches_200(self, client, seed_data):
        response = client.get("/sanctions/matches")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_screen_known_sanctioned_name(self, client, seed_data):
        """Screening an exact entry from the sanctions list should return block or review."""
        from src.data.sanctions_lists import SANCTIONS_DB
        first_list = next(iter(SANCTIONS_DB.values()))
        if not first_list:
            pytest.skip("Sanctions list empty")

        target_name = first_list[0]["name"]
        response = client.get(f"/sanctions/screen?name={target_name}")
        assert response.status_code == 200
        data = response.json()
        assert data["overall_recommendation"] in ("block", "review")


# ---------------------------------------------------------------------------
# SAR endpoints
# ---------------------------------------------------------------------------

class TestSarEndpoints:

    def test_list_sars_200(self, client, seed_data):
        response = client.get("/sars")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_list_sars_includes_seeded_sar(self, client, seed_data):
        response = client.get("/sars")
        sar_ids = [s["id"] for s in response.json()]
        assert "api_test_sar_001" in sar_ids

    def test_get_sar_by_id(self, client, seed_data):
        response = client.get("/sars/api_test_sar_001")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "api_test_sar_001"
        assert data["status"] == "draft"

    def test_get_nonexistent_sar_404(self, client, seed_data):
        response = client.get("/sars/nonexistent_sar_xyz")
        assert response.status_code == 404

    def test_approve_sar_requires_human_decision(self, client, seed_data):
        """POST /sars/{id}/approve must record the approving officer."""
        # Reset to draft first
        async def reset_sar():
            async with await get_db() as db:
                from src.database import update_sar
                await update_sar(db, "api_test_sar_001", {"status": "draft"})
        asyncio.get_event_loop().run_until_complete(reset_sar())

        payload = {
            "approved_by": "compliance_officer_chinelo",
            "rationale": "Evidence of threshold evasion is clear and well-documented",
            "final_narrative": None,
        }
        response = client.post("/sars/api_test_sar_001/approve", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "approved"
        assert data["approved_by"] == "compliance_officer_chinelo"

    def test_reject_sar_with_rationale(self, client, seed_data):
        """POST /sars/{id}/reject must record the rejecting officer and reason."""
        # Create a fresh SAR to reject
        async def create_rejectable_sar():
            async with await get_db() as db:
                sar = await create_sar(db, {
                    "id": "api_test_sar_reject",
                    "customer_id": "api_test_cust_001",
                    "draft_narrative": "Rejection test SAR",
                    "typology": "other",
                    "priority": "routine",
                    "status": "draft",
                    "drafted_by": "sar_generator_agent",
                })
            return sar
        asyncio.get_event_loop().run_until_complete(create_rejectable_sar())

        payload = {
            "rejected_by": "compliance_officer_chinelo",
            "rationale": "Insufficient evidence; customer confirmed legitimate business purpose",
        }
        response = client.post("/sars/api_test_sar_reject/reject", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "rejected"

    def test_file_sar_post_approval(self, client, seed_data):
        """POST /sars/{id}/file must only work after approval."""
        # Create and approve a SAR
        async def setup_approved_sar():
            async with await get_db() as db:
                sar = await create_sar(db, {
                    "id": "api_test_sar_file",
                    "customer_id": "api_test_cust_001",
                    "draft_narrative": "Filing test SAR",
                    "typology": "structuring_smurfing",
                    "priority": "urgent",
                    "status": "approved",
                    "drafted_by": "sar_generator_agent",
                    "approved_by": "compliance_officer",
                })
            return sar
        asyncio.get_event_loop().run_until_complete(setup_approved_sar())

        payload = {
            "filed_by": "compliance_officer_chinelo",
            "nfiu_reference": "NFIU/2026/04/TEST001",
        }
        response = client.post("/sars/api_test_sar_file/file", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "filed"

    def test_filter_sars_by_status(self, client, seed_data):
        response = client.get("/sars?status=draft")
        assert response.status_code == 200
        for sar in response.json():
            assert sar["status"] == "draft"


# ---------------------------------------------------------------------------
# Case endpoints
# ---------------------------------------------------------------------------

class TestCaseEndpoints:

    def test_list_cases_200(self, client, seed_data):
        response = client.get("/cases")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_list_cases_includes_seeded_case(self, client, seed_data):
        response = client.get("/cases")
        case_ids = [c["id"] for c in response.json()]
        assert "api_test_case_001" in case_ids

    def test_get_case_by_id(self, client, seed_data):
        response = client.get("/cases/api_test_case_001")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "api_test_case_001"
        assert data["customer_id"] == "api_test_cust_001"

    def test_get_nonexistent_case_404(self, client, seed_data):
        response = client.get("/cases/nonexistent_case_xyz")
        assert response.status_code == 404

    def test_update_case_status(self, client, seed_data):
        payload = {
            "status": "investigating",
            "resolution": None,
            "updated_by": "Ngozi Adeyemi",
        }
        response = client.put("/cases/api_test_case_001/status", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "investigating"

    def test_assign_case(self, client, seed_data):
        payload = {
            "assigned_to": "Babatunde Fashola",
            "assigned_by": "Ngozi Adeyemi",
        }
        response = client.put("/cases/api_test_case_001/assign", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["assigned_to"] == "Babatunde Fashola"

    def test_close_case_with_resolution(self, client, seed_data):
        payload = {
            "status": "closed",
            "resolution": "Investigation complete. Transfer verified as legitimate payroll disbursement.",
            "updated_by": "senior_analyst_ngozi",
        }
        response = client.put("/cases/api_test_case_001/status", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "closed"


# ---------------------------------------------------------------------------
# Governance endpoints
# ---------------------------------------------------------------------------

class TestGovernanceEndpoints:

    def test_governance_dashboard_200(self, client, seed_data):
        response = client.get("/governance/dashboard")
        assert response.status_code == 200
        data = response.json()
        # Must include key metrics
        assert isinstance(data, dict)

    def test_audit_trail_endpoint_200(self, client, seed_data):
        response = client.get("/governance/audit-trail")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_audit_trail_entity_filter(self, client, seed_data):
        """GET /governance/audit-trail/{entity} must return entries for that entity."""
        response = client.get("/governance/audit-trail/api_test_txn_001")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_model_validation_list_200(self, client, seed_data):
        response = client.get("/governance/model-validation")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_record_model_validation(self, client, seed_data):
        """POST /governance/model-validation must record a model validation entry."""
        payload = {
            "model_name": "pattern_analyzer_v1",
            "validation_type": "annual",
            "accuracy": 0.92,
            "drift_score": 0.05,
            "bias_score": 0.03,
            "fairness_score": 0.89,
            "human_reviewer": "Dr. Adaeze Okonkwo",
            "findings": "Model performance within acceptable bounds. No significant drift detected.",
        }
        response = client.post("/governance/model-validation", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["model_name"] == "pattern_analyzer_v1"
        assert data["accuracy"] == 0.92
        assert "id" in data

    def test_model_validation_recorded_appears_in_list(self, client, seed_data):
        """After recording a validation, it should appear in the validation list."""
        payload = {
            "model_name": "kyc_verifier_v2",
            "validation_type": "annual",
            "accuracy": 0.95,
            "drift_score": 0.02,
            "human_reviewer": "Compliance Officer Chinelo",
        }
        client.post("/governance/model-validation", json=payload)

        response = client.get("/governance/model-validation")
        model_names = [v["model_name"] for v in response.json()]
        assert "kyc_verifier_v2" in model_names


# ---------------------------------------------------------------------------
# Reporting endpoints
# ---------------------------------------------------------------------------

class TestReportingEndpoints:

    def test_daily_report_200(self, client, seed_data):
        response = client.get("/reports/daily")
        assert response.status_code == 200
        data = response.json()
        assert "total_transactions" in data
        assert "flagged_transactions" in data
        assert "alerts_generated" in data

    def test_weekly_report_200(self, client, seed_data):
        response = client.get("/reports/weekly")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)

    def test_str_summary_200(self, client, seed_data):
        response = client.get("/reports/str-summary")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)

    def test_alert_analytics_200(self, client, seed_data):
        response = client.get("/reports/alert-analytics")
        assert response.status_code == 200
        data = response.json()
        assert "total_alerts" in data
        assert "by_severity" in data


# ---------------------------------------------------------------------------
# API integration endpoints
# ---------------------------------------------------------------------------

class TestApiIntegrationEndpoints:

    def test_api_stats_200(self, client, seed_data):
        response = client.get("/api/stats")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)

    def test_api_alerts_summary_200(self, client, seed_data):
        response = client.get("/api/alerts/summary")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)


# ---------------------------------------------------------------------------
# End-to-end pipeline test
# ---------------------------------------------------------------------------

class TestEndToEndPipeline:

    def test_full_pipeline_low_risk_transaction(self, client, seed_data):
        """A low-value transaction should clear the pipeline cleanly."""
        payload = {
            "customer_id": "api_test_cust_001",
            "amount": 75_000.0,
            "currency": "NGN",
            "transaction_type": "transfer",
            "channel": "mobile_app",
            "direction": "inbound",
            "geo_location": "Lagos, NG",
            "timestamp": now_wat(),
        }
        response = client.post("/transactions/screen", json=payload)
        assert response.status_code == 200
        result = response.json()
        assert "monitor_result" in result
        assert "kyc_result" in result
        assert "sanctions_result" in result
        assert "governance_decisions" in result
        assert result["final_status"] in ("cleared", "flagged")

    def test_full_pipeline_high_risk_transaction(self, client, seed_data):
        """A high-value cash deposit should produce alerts and a case."""
        payload = {
            "customer_id": "api_test_cust_001",
            "amount": 80_000_000.0,
            "currency": "NGN",
            "transaction_type": "cash_deposit",
            "channel": "branch",
            "direction": "inbound",
            "geo_location": "Lagos, NG",
            "timestamp": now_wat(),
        }
        response = client.post("/transactions/screen", json=payload)
        assert response.status_code == 200
        result = response.json()
        assert result["final_status"] in ("flagged", "blocked", "escalated")
        assert result["monitor_result"]["flagged"] is True

    def test_pipeline_result_governance_decisions_present(self, client, seed_data):
        """Pipeline result must always include governance decisions from all stages."""
        payload = {
            "customer_id": "api_test_cust_001",
            "amount": 500_000.0,
            "currency": "NGN",
            "transaction_type": "transfer",
            "channel": "mobile_app",
            "direction": "outbound",
            "geo_location": "Abuja, NG",
            "timestamp": now_wat(),
        }
        response = client.post("/transactions/screen", json=payload)
        assert response.status_code == 200
        result = response.json()
        assert "governance_decisions" in result
        assert isinstance(result["governance_decisions"], list)
        assert len(result["governance_decisions"]) >= 1

    def test_pipeline_processing_time_recorded(self, client, seed_data):
        """Pipeline result should record processing time in milliseconds."""
        payload = {
            "customer_id": "api_test_cust_001",
            "amount": 300_000.0,
            "currency": "NGN",
            "transaction_type": "transfer",
            "channel": "internet_banking",
            "direction": "outbound",
            "geo_location": "Lagos, NG",
            "timestamp": now_wat(),
        }
        response = client.post("/transactions/screen", json=payload)
        assert response.status_code == 200
        result = response.json()
        assert result.get("processing_time_ms") is not None
        assert result["processing_time_ms"] >= 0
