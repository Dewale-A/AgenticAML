"""
Demo data seeder for AgenticAML.
Creates 20 realistic Nigerian customers, 200 transactions,
pre-processed alerts, a draft SAR, and active investigation cases.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from src.data.sample_transactions import generate_transactions_for_customer
from src.database import (
    create_alert,
    create_case,
    create_customer,
    create_model_validation,
    create_sanctions_match,
    create_sar,
    create_transaction,
    get_db,
    init_db,
    log_audit,
    new_id,
    update_customer,
    upsert_screening_list,
)

# West Africa Time (UTC+1) — all timestamps stored in WAT per CBN reporting standards
WAT = timezone(timedelta(hours=1))


# ---------------------------------------------------------------------------
# Seed customers (20 realistic Nigerian profiles)
# ---------------------------------------------------------------------------

# Each customer represents a distinct AML risk scenario used to exercise
# different detection rules and agent pipelines during demo and testing.
# Risk tiers follow CBN Risk-Based Supervision framework (low/medium/high/very_high).
SEED_CUSTOMERS = [
    # Low-risk individuals — standard verified retail customers with no red flags
    {
        "id": "cust_001",
        "name": "Adaeze Okonkwo",
        "bvn": "22345678901",  # Bank Verification Number — CBN mandatory unique identifier
        "nin": "12345678901",  # National Identification Number — NIMC-issued, required for KYC
        "date_of_birth": "1990-04-15",
        "phone": "+2348012345678",
        "address": "14 Ozumba Mbadiwe Avenue, Victoria Island, Lagos",
        "account_type": "individual",
        "risk_tier": "low",
        "kyc_status": "verified",  # Full BVN + NIN + address verification complete
        "pep_status": 0,  # 0 = not a Politically Exposed Person
    },
    {
        "id": "cust_002",
        "name": "Emeka Nwosu",
        "bvn": "22345678902",
        "nin": "12345678902",
        "date_of_birth": "1985-09-22",
        "phone": "+2348023456789",
        "address": "7 Allen Avenue, Ikeja, Lagos",
        "account_type": "individual",
        "risk_tier": "low",
        "kyc_status": "verified",
        "pep_status": 0,
    },
    {
        "id": "cust_003",
        "name": "Ngozi Adeyemi",
        "bvn": "22345678903",
        "nin": "12345678903",
        "date_of_birth": "1992-12-01",
        "phone": "+2348034567890",
        "address": "23 Wuse Zone 5, Abuja FCT",
        "account_type": "individual",
        "risk_tier": "low",
        "kyc_status": "verified",
        "pep_status": 0,
    },
    # Medium-risk individuals — elevated activity or geography warrants closer monitoring
    {
        "id": "cust_004",
        "name": "Babatunde Fashola",
        "bvn": "22345678904",
        "nin": "12345678904",
        "date_of_birth": "1978-03-30",
        "phone": "+2348045678901",
        "address": "5 Bourdillon Road, Ikoyi, Lagos",  # High-value Ikoyi address — medium risk
        "account_type": "individual",
        "risk_tier": "medium",
        "kyc_status": "verified",
        "pep_status": 0,
    },
    {
        "id": "cust_005",
        "name": "Chinelo Okafor",
        "bvn": "22345678905",
        "nin": "12345678905",
        "date_of_birth": "1988-07-11",
        "phone": "+2348056789012",
        "address": "18 Trans Amadi Industrial Layout, Port Harcourt",  # Oil-sector geography — medium risk
        "account_type": "individual",
        "risk_tier": "medium",
        "kyc_status": "verified",
        "pep_status": 0,
    },
    # Structuring pattern customer — designed to trigger STRUCTURING detection rule
    # Deposits multiple amounts just below the NGN 5M Currency Transaction Report (CTR) threshold
    # CBN/NFIU require CTRs for cash transactions >= NGN 5M (MLPPA 2022, Section 10)
    {
        "id": "cust_006",
        "name": "Tunde Bakare",
        "bvn": "22345678906",
        "nin": "12345678906",
        "date_of_birth": "1982-06-25",
        "phone": "+2348067890123",
        "address": "32 Obafemi Awolowo Way, Ikeja, Lagos",
        "account_type": "individual",
        "risk_tier": "high",
        "kyc_status": "verified",
        "pep_status": 0,
    },
    # Rapid fund movement customer — designed to trigger LAYERING detection
    # Receives large international wire then disperses across multiple accounts within 48h
    {
        "id": "cust_007",
        "name": "Oluwaseun Adebayo",
        "bvn": "22345678907",
        "nin": "12345678907",
        "date_of_birth": "1987-01-18",
        "phone": "+2348078901234",
        "address": "11 Alausa, Ikeja, Lagos",
        "account_type": "individual",
        "risk_tier": "high",
        "kyc_status": "verified",
        "pep_status": 0,
    },
    # PEP customer — Politically Exposed Person (active Senator on Finance Committee)
    # FATF Recommendation 12 requires Enhanced Due Diligence (EDD) for all PEPs.
    # CBN BSD/DIR/PUB/LAB/019/002 mandates automated PEP screening at onboarding and transaction level.
    {
        "id": "cust_008",
        "name": "Senator Adewale Ogundimu",
        "bvn": "22345678908",
        "nin": "12345678908",
        "date_of_birth": "1962-08-20",
        "phone": "+2348089012345",
        "address": "National Assembly Quarters, Asokoro, Abuja",
        "account_type": "individual",
        "risk_tier": "very_high",  # PEPs are automatically elevated to very_high risk
        "kyc_status": "verified",
        "pep_status": 1,  # 1 = confirmed PEP — triggers EDD and heightened transaction scrutiny
    },
    # Incomplete KYC customer — missing NIN, DOB, and address
    # CBN KYC Regulations require all three for full account verification.
    # Account should be restricted or flagged pending documentation completion.
    {
        "id": "cust_009",
        "name": "Abiodun Salami",
        "bvn": "22345678909",
        "nin": None,           # Missing NIN — KYC gap
        "date_of_birth": None, # Missing DOB — KYC gap
        "phone": "+2348090123456",
        "address": None,       # Missing address — KYC gap
        "account_type": "individual",
        "risk_tier": "medium",
        "kyc_status": "incomplete",  # Triggers KYC_INCOMPLETE alert in kyc_verifier_agent
        "pep_status": 0,
    },
    # Dormant account customer — long period of inactivity followed by large transaction
    # CBN guidelines flag dormant-to-active transitions as AML red flags
    {
        "id": "cust_010",
        "name": "Fatima Musa Bello",
        "bvn": "22345678910",
        "nin": "12345678910",
        "date_of_birth": "1975-11-05",
        "phone": "+2348001234567",
        "address": "44 Sultan Road, Kano",
        "account_type": "individual",
        "risk_tier": "low",
        "kyc_status": "verified",
        "pep_status": 0,
    },
    # Corporate accounts — BVN/NIN not applicable; corporate KYC uses RC number and CAC docs
    {
        "id": "cust_011",
        "name": "Eko Logistics and Trading Ltd",
        "bvn": "22345678911",
        "nin": None,           # NIN not applicable for corporate entities
        "date_of_birth": None, # DOB not applicable for corporate entities
        "phone": "+2348112345678",
        "address": "16 Creek Road, Apapa, Lagos",  # Port/logistics zone — watch for TBML
        "account_type": "corporate",
        "risk_tier": "medium",
        "kyc_status": "verified",
        "pep_status": 0,
    },
    {
        "id": "cust_012",
        "name": "Abuja Capital Investments Ltd",
        "bvn": "22345678912",
        "nin": None,
        "date_of_birth": None,
        "phone": "+2348123456789",
        "address": "Plot 1234 Central Business District, Abuja",
        "account_type": "corporate",
        "risk_tier": "high",  # Investment firm — higher risk for round-amount layering
        "kyc_status": "verified",
        "pep_status": 0,
    },
    # Round amounts pattern — exact multiples of 5M/10M/15M/20M signal possible layering
    # FATF Typology: round-number transfers are a recognised indicator of ML placement/layering
    {
        "id": "cust_013",
        "name": "Musa Ibrahim Tanko",
        "bvn": "22345678913",
        "nin": "12345678913",
        "date_of_birth": "1975-12-30",
        "phone": "+2348134567890",
        "address": "7 Maiduguri Road, Kano",
        "account_type": "individual",
        "risk_tier": "high",
        "kyc_status": "verified",
        "pep_status": 0,
    },
    # High-risk geography customer — initiates transactions to FATF/OFAC sanctioned jurisdictions
    # CBN requires enhanced monitoring for transactions to/from high-risk countries (Iran, North Korea, Sudan)
    {
        "id": "cust_014",
        "name": "Usman Garba Musa",
        "bvn": "22345678914",
        "nin": "12345678914",
        "date_of_birth": "1968-03-08",
        "phone": "+2348145678901",
        "address": "23 Ahmadu Bello Way, Kaduna",
        "account_type": "individual",
        "risk_tier": "high",
        "kyc_status": "verified",
        "pep_status": 0,
    },
    # Sanctions near-match — name identical to NFIU/NDLEA domestic watchlist entry
    # Used to demonstrate fuzzy matching and auto-block logic in sanctions_screener_agent.
    # CBN mandates immediate blocking and STR filing for confirmed sanctions matches.
    {
        "id": "cust_015",
        "name": "Chukwuemeka Eze",
        "bvn": "22345678915",
        "nin": "12345678915",
        "date_of_birth": "1979-11-03",
        "phone": "+2348156789012",
        "address": "88 New Market Road, Onitsha, Anambra",
        "account_type": "individual",
        "risk_tier": "very_high",  # Pre-elevated due to name match with domestic watchlist
        "kyc_status": "verified",
        "pep_status": 0,
    },
    # Additional normal customers — provide baseline clean-account comparison data
    {
        "id": "cust_016",
        "name": "Oluwakemi Adesanya",
        "bvn": "22345678916",
        "nin": "12345678916",
        "date_of_birth": "1995-02-28",
        "phone": "+2348167890123",
        "address": "15 Lekki Phase 1, Lagos",
        "account_type": "individual",
        "risk_tier": "low",
        "kyc_status": "verified",
        "pep_status": 0,
    },
    {
        "id": "cust_017",
        "name": "Ifeanyi Obi",
        "bvn": "22345678917",
        "nin": "12345678917",
        "date_of_birth": "1991-08-14",
        "phone": "+2348178901234",
        "address": "3 GRA Phase 2, Port Harcourt, Rivers",
        "account_type": "individual",
        "risk_tier": "low",
        "kyc_status": "verified",
        "pep_status": 0,
    },
    {
        "id": "cust_018",
        "name": "Amaka Chidinma Eze",
        "bvn": "22345678918",
        "nin": "12345678918",
        "date_of_birth": "1989-05-20",
        "phone": "+2348189012345",
        "address": "41 Independence Layout, Enugu",
        "account_type": "individual",
        "risk_tier": "low",
        "kyc_status": "verified",
        "pep_status": 0,
    },
    {
        "id": "cust_019",
        "name": "Northern Trade & Commerce Ltd",
        "bvn": "22345678919",
        "nin": None,
        "date_of_birth": None,
        "phone": "+2348190123456",
        "address": "12 Kasuwan Kurmi, Kano",
        "account_type": "corporate",
        "risk_tier": "medium",
        "kyc_status": "verified",
        "pep_status": 0,
    },
    {
        "id": "cust_020",
        "name": "Bello Rabiu",
        "bvn": "22345678920",
        "nin": "12345678920",
        "date_of_birth": "1982-03-10",
        "phone": "+2348101234567",
        "address": "25 Emir Palace Road, Kano",
        "account_type": "individual",
        "risk_tier": "high",
        "kyc_status": "verified",
        "pep_status": 1,  # Near-match to PEP database entry — demonstrates fuzzy PEP screening
    },
]

# Maps customer IDs to suspicious transaction pattern types.
# The generator uses this to inject realistic AML red-flag transactions
# alongside normal ones, so each high-risk customer has representative typology data.
SUSPICIOUS_PATTERNS = {
    "cust_006": "structuring",      # Sub-threshold cash deposits (smurfing)
    "cust_007": "rapid_movement",   # Inflow → quick dispersal (layering)
    "cust_008": "pep",              # Large round inflows from contractors (PEP corruption)
    "cust_010": "dormant",          # Dormant account sudden reactivation
    "cust_012": "round_amounts",    # Exact round-number transfers (layering indicator)
    "cust_013": "round_amounts",    # Same pattern, different customer profile
    "cust_014": "high_risk_geo",    # Wire to sanctioned jurisdiction (Iran/DPRK/Sudan)
    "cust_015": "structuring",      # Structuring + sanctions match combination
    "cust_020": "pep",              # PEP near-match scenario
}


async def seed_database():
    """Seed the database with demo data."""
    print("Initializing database...")
    await init_db()

    async with get_db() as db:
        print("Seeding customers...")
        created_customers = []
        for cdata in SEED_CUSTOMERS:
            try:
                customer = await create_customer(db, cdata)
                created_customers.append(customer)
                print(f"  Created customer: {customer['name']} ({customer['id']})")
            except Exception as e:
                # Customer already exists (re-seed scenario) — fetch the existing record
                # rather than failing, so the rest of the seed can reference it
                print(f"  Skip existing customer {cdata['id']}: {e}")
                from src.database import get_customer
                existing = await get_customer(db, cdata["id"])
                if existing:
                    created_customers.append(existing)

        print("\nSeeding transactions (~200)...")
        all_transactions = []
        # Per-customer transaction counts are weighted to give suspicious customers
        # enough data points for pattern detection algorithms to fire confidently
        txn_counts = {
            "cust_006": 15,  # Structuring (many txns needed to show velocity)
            "cust_007": 12,  # Rapid movement (inflow + multiple outflows)
            "cust_008": 10,  # PEP (large round inflows)
            "cust_010": 5,   # Dormant (minimal history + 1 large reactivation txn)
            "cust_012": 12,  # Round amounts (needs several examples)
            "cust_013": 10,  # Round amounts
            "cust_014": 8,   # High-risk geo
            "cust_015": 12,  # Structuring (near-match)
            "cust_020": 8,   # PEP near-match
        }
        default_txn_count = 8  # Clean customers get 8 normal transactions each

        for customer in created_customers:
            cid = customer["id"]
            count = txn_counts.get(cid, default_txn_count)
            pattern = SUSPICIOUS_PATTERNS.get(cid)  # None for normal customers

            txns = generate_transactions_for_customer(customer, total_count=count, suspicious_type=pattern)
            for txn_data in txns:
                txn_data["id"] = new_id()  # Assign UUID before DB insert
                try:
                    txn = await create_transaction(db, txn_data)
                    all_transactions.append(txn)
                except Exception as e:
                    print(f"  Error creating transaction: {e}")

        print(f"  Created {len(all_transactions)} transactions")

        # Seed downstream pipeline outputs so the demo UI shows a fully processed state
        print("\nSeeding pre-processed alerts...")
        await seed_alerts(db, created_customers, all_transactions)

        print("\nSeeding sanctions matches...")
        await seed_sanctions_matches(db, created_customers, all_transactions)

        print("\nSeeding SARs...")
        await seed_sars(db)

        print("\nSeeding cases...")
        await seed_cases(db)

        # Audit trail demonstrates the immutable decision chain required by
        # CBN BSD/DIR/PUB/LAB/019/002 — every agent action and human decision is logged
        print("\nSeeding governance audit trail...")
        await seed_audit_trail(db)

        # CBN requires annual independent model validation for all AI-assisted AML systems
        print("\nSeeding model validation records...")
        await seed_model_validations(db)

        # Dormant account flags: marks qualifying customers with is_dormant=1 per CBN 180-day threshold
        print("\nSeeding dormant account flags...")
        await seed_dormant_accounts(db)

        # Onboarding escalations: PEP pending approval, adverse media reviewed, sanctions blocked
        print("\nSeeding onboarding escalations...")
        await seed_onboarding_escalations(db)

        # Monitoring run history and screening list metadata for the Monitoring tab
        print("\nSeeding monitoring runs and screening lists...")
        await seed_monitoring_runs(db)

        print("\nDatabase seeding complete!")


async def seed_alerts(db, customers: list[dict], transactions: list[dict]):
    """Create pre-processed alerts showing the full pipeline."""
    now = datetime.now(WAT)

    alerts_data = [
        # High-severity structuring alert for cust_006
        # Represents the output of transaction_monitor_agent after detecting
        # multiple sub-threshold cash deposits (smurfing pattern)
        {
            "id": "alert_001",
            # Link to the first available transaction for this customer
            "transaction_id": next((t["id"] for t in transactions if t["customer_id"] == "cust_006"), None),
            "customer_id": "cust_006",
            "agent_source": "transaction_monitor_agent",
            "alert_type": "STRUCTURING",
            "severity": "high",
            "description": "Customer 'Tunde Bakare' detected with 7 cash deposits of NGN 4.4M-4.95M within 21 days, all just below the NGN 5M reporting threshold. Classic structuring/smurfing pattern.",
            "confidence": 0.87,
            "status": "investigating",
            "assigned_to": "Ngozi Adeyemi",
        },
        # Critical alert for PEP customer cust_008
        # FATF Recommendation 12: all PEP transactions must be subject to enhanced scrutiny.
        # Round inflows from government contractors during budget appropriation period
        # are a textbook PEP corruption indicator.
        {
            "id": "alert_002",
            "transaction_id": next((t["id"] for t in transactions if t["customer_id"] == "cust_008"), None),
            "customer_id": "cust_008",
            "agent_source": "pattern_analyzer_agent",
            "alert_type": "PEP_LARGE_ROUND_TRANSACTIONS",
            "severity": "critical",
            "description": "Senator Adewale Ogundimu (PEP) received NGN 50M, 25M, and 100M from government contractors within 60 days. Possible PEP corruption/bribery pattern per FATF Recommendation 12.",
            "confidence": 0.91,
            "status": "open",
            "assigned_to": "Chinelo Okafor",
        },
        # Rapid fund movement alert for cust_007
        # Classic ML layering: funds arrive from offshore then are dispersed quickly
        # to obscure the audit trail — triggers RAPID_FUND_MOVEMENT rule
        {
            "id": "alert_003",
            "transaction_id": next((t["id"] for t in transactions if t["customer_id"] == "cust_007"), None),
            "customer_id": "cust_007",
            "agent_source": "pattern_analyzer_agent",
            "alert_type": "RAPID_FUND_MOVEMENT",
            "severity": "high",
            "description": "Oluwaseun Adebayo received NGN 15M international wire from Dubai then dispersed funds across 5 accounts within 36 hours. Classic layering typology.",
            "confidence": 0.83,
            "status": "investigating",
            "assigned_to": "Babatunde Fashola",
        },
        # Sanctions alert for cust_015
        # Name match against NFIU domestic watchlist (NDLEA drug-trafficking entry).
        # CBN mandate: transactions for sanctioned names must be BLOCKED immediately;
        # STR must be filed with NFIU within 24 hours of detection.
        {
            "id": "alert_004",
            "transaction_id": next((t["id"] for t in transactions if t["customer_id"] == "cust_015"), None),
            "customer_id": "cust_015",
            "agent_source": "sanctions_screener_agent",
            "alert_type": "SANCTIONS_MATCH",
            "severity": "critical",
            "description": "Customer 'Chukwuemeka Eze' name matches NFIU domestic watchlist entry (NDLEA - drug trafficking). Match score: 0.97. Transaction BLOCKED per CBN mandate.",
            "confidence": 0.97,
            "status": "open",
            "assigned_to": "Chinelo Okafor",
        },
        # KYC incomplete alert for cust_009
        # CBN KYC Regulations (2023 revised) require NIN, DOB, and address for
        # Tier 2/3 accounts. Missing fields trigger account restriction pending remediation.
        {
            "id": "alert_005",
            "customer_id": "cust_009",
            "transaction_id": next((t["id"] for t in transactions if t["customer_id"] == "cust_009"), None),
            "agent_source": "kyc_verifier_agent",
            "alert_type": "KYC_INCOMPLETE",
            "severity": "medium",
            "description": "Customer 'Abiodun Salami' has incomplete KYC: missing NIN, date of birth, and address. Account flagged pending documentation completion.",
            "confidence": 0.95,
            "status": "open",
            "assigned_to": "Adaeze Okonkwo",
        },
        # High-risk geography alert for cust_014
        # Wire to Tehran (Iran) — OFAC/UN sanctioned jurisdiction.
        # CBN requires Enhanced Due Diligence and mandatory STR for transactions
        # involving FATF high-risk or OFAC-sanctioned countries.
        {
            "id": "alert_006",
            "transaction_id": next((t["id"] for t in transactions if t["customer_id"] == "cust_014"), None),
            "customer_id": "cust_014",
            "agent_source": "transaction_monitor_agent",
            "alert_type": "HIGH_RISK_GEOGRAPHY",
            "severity": "high",
            "description": "Usman Garba Musa initiated international wire of NGN 8.5M to Tehran, Iran - a sanctioned jurisdiction. Enhanced due diligence required.",
            "confidence": 0.92,
            "status": "investigating",
            "assigned_to": "Babatunde Fashola",
        },
        # Resolved (false positive) alert — demonstrates the full alert lifecycle
        # including human review, investigation, and closure with documented rationale.
        # Audit trail for this case shows how false positives are recorded per CBN requirements.
        {
            "id": "alert_007",
            "transaction_id": next((t["id"] for t in transactions if t["customer_id"] == "cust_001"), None),
            "customer_id": "cust_001",
            "agent_source": "transaction_monitor_agent",
            "alert_type": "VELOCITY_COUNT",
            "severity": "low",
            "description": "Adaeze Okonkwo: 11 transactions in 24h window. Investigation confirmed legitimate salary payments and vendor settlements.",
            "confidence": 0.65,
            "status": "resolved",
            "assigned_to": "Emeka Nwosu",
            "resolved_at": (now - timedelta(days=2)).isoformat(),
        },
        # Round amounts alert for cust_013
        # Exact round-figure transfers are a recognised layering indicator in FATF Typologies.
        # The pattern (5M → 10M → 15M → 20M) suggests deliberate structuring of outflows.
        {
            "id": "alert_008",
            "transaction_id": next((t["id"] for t in transactions if t["customer_id"] == "cust_013"), None),
            "customer_id": "cust_013",
            "agent_source": "pattern_analyzer_agent",
            "alert_type": "ROUND_AMOUNT_PATTERN",
            "severity": "medium",
            "description": "Musa Ibrahim Tanko: 6 transfers of exact NGN round-figure amounts (5M, 10M, 15M, 20M pattern) over 45 days. Possible layering indicator.",
            "confidence": 0.72,
            "status": "open",
            "assigned_to": "Adaeze Okonkwo",
        },
    ]

    for adata in alerts_data:
        try:
            alert = await create_alert(db, adata)
            print(f"  Created alert: {alert['alert_type']} for {alert['customer_id']}")
        except Exception as e:
            print(f"  Skip existing alert {adata['id']}: {e}")


async def seed_sanctions_matches(db, customers: list[dict], transactions: list[dict]):
    """Create sanctions match records."""
    # Grab the first transaction for each customer we need to link matches to
    txn_cust015 = next((t["id"] for t in transactions if t["customer_id"] == "cust_015"), None)
    txn_cust020 = next((t["id"] for t in transactions if t["customer_id"] == "cust_020"), None)

    matches_data = [
        # High-score match for cust_015 (Chukwuemeka Eze) against NFIU domestic list
        # Score 0.97 is above the auto-block threshold — transaction is blocked immediately
        # per CBN BSD/DIR/PUB/LAB/019/002 sanctions screening requirements
        {
            "id": "smatch_001",
            "customer_id": "cust_015",
            "transaction_id": txn_cust015,
            "list_name": "NIGERIAN_DOMESTIC",
            "matched_entity": "Chukwuemeka Eze",
            "match_type": "strong",    # Fuzzy score >= 0.90 → classified as strong match
            "match_score": 0.97,
            "action_taken": "block",   # Auto-blocked: strong sanctions match
            "reviewed_by": None,       # Pending mandatory human review
        },
        # PEP match for cust_020 (Bello Rabiu) — exact name match in PEP database
        # PEP matches trigger Enhanced Due Diligence review, not automatic blocking,
        # because PEP status alone is not grounds for refusal under CBN rules
        {
            "id": "smatch_002",
            "customer_id": "cust_020",
            "transaction_id": txn_cust020,
            "list_name": "PEP_DATABASE",
            "matched_entity": "Bello Rabiu",
            "match_type": "exact",
            "match_score": 0.99,
            "action_taken": "review",  # EDD required; account not blocked outright
            "reviewed_by": None,
        },
        # PEP match for cust_008 (Senator) — already reviewed by compliance officer
        # No linked transaction: match was triggered at onboarding/periodic screening
        {
            "id": "smatch_003",
            "customer_id": "cust_008",
            "transaction_id": None,  # Periodic screening, not transaction-linked
            "list_name": "PEP_DATABASE",
            "matched_entity": "Senator Adewale Ogundimu",
            "match_type": "exact",
            "match_score": 1.0,        # Perfect match — same name in PEP registry
            "action_taken": "review",
            "reviewed_by": "Chinelo Okafor",  # Human review completed
        },
        # Partial match (false positive scenario) for cust_002 against OFAC SDN
        # Score 0.58 is below the auto-block threshold; sent to human review for disposition.
        # Demonstrates the 3-tier match handling: block (>0.85) / review (0.50-0.85) / clear (<0.50)
        {
            "id": "smatch_004",
            "customer_id": "cust_002",
            "transaction_id": None,
            "list_name": "OFAC_SDN",
            "matched_entity": "Hassan Ibrahim Musa",
            "match_type": "weak",      # Low confidence — likely false positive
            "match_score": 0.58,
            "action_taken": "review",
            "reviewed_by": "Adaeze Okonkwo",  # Reviewed and dismissed as false positive
        },
    ]

    for mdata in matches_data:
        try:
            match = await create_sanctions_match(db, mdata)
            print(f"  Created sanctions match: {match['match_type']} - {match['matched_entity']}")
        except Exception as e:
            print(f"  Skip existing match {mdata['id']}: {e}")


async def seed_sars(db):
    """Create pre-seeded SARs including one in draft status awaiting human approval."""
    now = datetime.now(WAT)

    sars_data = [
        # Draft SAR awaiting human approval (most important demo scenario)
        # This is the primary "human in the loop" showcase:
        # - AI agent drafted the SAR narrative from transaction and pattern data
        # - Governance engine enforced mandatory human approval before filing
        # - NFIU requires STR filing within 24 hours of detection (MLPPA 2022, Section 6)
        {
            "id": "sar_001",
            "alert_id": "alert_002",   # Linked to the PEP alert
            "customer_id": "cust_008",
            "draft_narrative": """SUSPICIOUS TRANSACTION REPORT (STR) - DRAFT
Reporting Institution: Demo Bank Nigeria Ltd (DEMOBANK001)
Report Date: """ + now.strftime("%Y-%m-%d") + """
Reporting Officer: Chief Compliance Officer
Filing Deadline: 24 hours from initial detection (NFIU requirement)

SECTION 1: SUBJECT INFORMATION
Name: Senator Adewale Ogundimu
Customer ID: cust_008
BVN: 22345678908
NIN: 12345678908
Risk Tier: VERY_HIGH
PEP Status: Yes (Active Senator, Lagos State - Senate Finance Committee)
Account Type: Individual
Address: National Assembly Quarters, Asokoro, Abuja
Phone: +2348089012345

SECTION 2: SUSPICIOUS ACTIVITY DESCRIPTION
Typology: PEP Corruption/Bribery Pattern
Total Amount at Risk: NGN 175,000,000

The account of Senator Adewale Ogundimu, a Politically Exposed Person
serving on the Senate Finance Committee, received three large round-figure
transactions totalling NGN 175,000,000 from entities identified as
government contractors over a period of 60 days.

SECTION 3: REASON FOR SUSPICION
- PEP status: Active senator with budget oversight responsibilities
- Three round-figure inflows: NGN 50,000,000, NGN 25,000,000, NGN 100,000,000
- All from entities described as "Government Contractor"
- Timing correlates with Senate budget appropriation period
- Pattern consistent with FATF Recommendation 12 (PEP) risk indicators
- Pattern matches: PEP_LARGE_ROUND_TRANSACTIONS (confidence: 0.91)

SECTION 4: TRANSACTION DETAILS
See attached transaction history in evidence package.

SECTION 5: SUPPORTING EVIDENCE
Transactions analyzed: 10 (90-day window)
Alerts reviewed: 1
Patterns detected: 1 (PEP_LARGE_ROUND_TRANSACTIONS, confidence 0.91)

SECTION 6: REPORTING INSTITUTION DECLARATION
This report has been drafted by the AgenticAML system. MANDATORY human
approval is required before submission to the NFIU.

NOTE: DRAFT - Human Approval Required Before Filing with NFIU""",
            "typology": "pep_corruption",
            "priority": "critical",
            "status": "draft",         # Blocked at governance gate — awaiting human sign-off
            "drafted_by": "sar_generator_agent",
        },
        # Approved and filed SAR — shows the complete lifecycle from draft → filed
        # NFIU reference number is the confirmation of successful STR submission
        {
            "id": "sar_002",
            "alert_id": "alert_001",
            "customer_id": "cust_006",
            "draft_narrative": "Draft SAR for Tunde Bakare structuring case - see final narrative.",
            "final_narrative": """SUSPICIOUS TRANSACTION REPORT (STR) - FILED
Reporting Institution: Demo Bank Nigeria Ltd (DEMOBANK001)
Report Date: """ + (now - timedelta(days=10)).strftime("%Y-%m-%d") + """
NFIU Reference: NFIU-2026-0042-NG

SECTION 1: SUBJECT
Name: Tunde Bakare | BVN: 22345678906 | Risk: HIGH

SECTION 2: ACTIVITY
7 cash deposits ranging NGN 4.4M-4.95M over 21 days.
Classic structuring pattern to evade the NGN 5M CTR threshold.

SECTION 3: REASON FOR SUSPICION
Multiple threshold-just-below deposits over 21 days.
STRUCTURING rule triggered. Confidence: 87%.

FILED with NFIU on """ + (now - timedelta(days=8)).strftime("%Y-%m-%d") + """.""",
            "typology": "structuring_smurfing",
            "priority": "urgent",
            "status": "filed",         # Successfully submitted to NFIU
            "drafted_by": "sar_generator_agent",
            "approved_by": "Chinelo Okafor",
            "approval_rationale": "Evidence clearly supports structuring typology. Pattern is unambiguous. Approved for immediate NFIU filing.",
            "filed_at": (now - timedelta(days=8)).isoformat(),
            "nfiu_reference": "NFIU-2026-0042-NG",  # Official NFIU acknowledgement reference
        },
        # Rejected SAR — shows that human review can dismiss agent-generated reports
        # when investigation reveals a legitimate business explanation (false positive)
        {
            "id": "sar_003",
            "alert_id": "alert_007",
            "customer_id": "cust_001",
            "draft_narrative": "Draft SAR for velocity alert - customer Adaeze Okonkwo.",
            "typology": "suspicious_activity",
            "priority": "routine",
            "status": "rejected",      # Human determined this was not suspicious activity
            "drafted_by": "sar_generator_agent",
            "approved_by": "Ngozi Adeyemi",
            "approval_rationale": "Investigation confirmed legitimate activity: salary disbursements and vendor payments for small business operations. No AML indicators. SAR rejected.",
        },
    ]

    for sdata in sars_data:
        try:
            sar = await create_sar(db, sdata)
            print(f"  Created SAR: {sar['typology']} - status={sar['status']}")
        except Exception as e:
            print(f"  Skip existing SAR {sdata['id']}: {e}")


async def seed_cases(db):
    """Create pre-seeded investigation cases."""
    now = datetime.now(WAT)

    cases_data = [
        # Active critical investigation (PEP) — linked to alert_002 and sar_001
        # Assigned to a named compliance officer; demonstrates workload management
        {
            "id": "case_001",
            "alert_id": "alert_002",
            "customer_id": "cust_008",
            "case_type": "pep_investigation",
            "priority": "critical",
            "status": "investigating",
            "assigned_to": "Chinelo Okafor",
            "description": "Case Type: PEP Investigation | Priority: CRITICAL | Pattern Analysis: 1 pattern detected, overall risk=CRITICAL | Sanctions: 1 match, recommendation=REVIEW",
        },
        # Active high-priority investigation (structuring)
        # Status 'investigating' means an analyst has taken ownership and is working it
        {
            "id": "case_002",
            "alert_id": "alert_001",
            "customer_id": "cust_006",
            "case_type": "structuring_investigation",
            "priority": "high",
            "status": "investigating",
            "assigned_to": "Ngozi Adeyemi",
            "description": "Case Type: Structuring Investigation | Priority: HIGH | Triggered Rules: STRUCTURING, VELOCITY_COUNT | Pattern Analysis: 2 patterns detected, overall risk=HIGH",
        },
        # Pending review — rapid movement case awaiting senior sign-off before escalation
        {
            "id": "case_003",
            "alert_id": "alert_003",
            "customer_id": "cust_007",
            "case_type": "layering_investigation",
            "priority": "high",
            "status": "pending_review",  # Analyst has assessed; waiting for supervisor approval
            "assigned_to": "Babatunde Fashola",
            "description": "Case Type: Layering Investigation | Priority: HIGH | Pattern Analysis: RAPID_FUND_MOVEMENT detected, confidence 0.83",
        },
        # Open sanctions case — sanctions block already applied; case needs human review
        # CBN requires documented human disposition for all sanctions matches
        {
            "id": "case_004",
            "alert_id": "alert_004",
            "customer_id": "cust_015",
            "case_type": "sanctions_investigation",
            "priority": "critical",
            "status": "open",
            "assigned_to": "Chinelo Okafor",
            "description": "Case Type: Sanctions Investigation | Priority: CRITICAL | Sanctions: 1 match (strong, score=0.97), recommendation=BLOCK",
        },
        # Closed case (resolved) — demonstrates full lifecycle ending in closure
        # Resolution statement is required before closing any case per governance rules
        {
            "id": "case_005",
            "alert_id": "alert_007",
            "customer_id": "cust_001",
            "case_type": "transaction_monitoring_alert",
            "priority": "low",
            "status": "closed",
            "assigned_to": "Emeka Nwosu",
            "description": "Case Type: Transaction Monitoring Alert | Priority: LOW | Triggered Rules: VELOCITY_COUNT",
            "resolution": "FALSE POSITIVE: Customer confirmed legitimate activity. Salary disbursements and vendor payments verified. Case closed.",
            "closed_at": (now - timedelta(days=2)).isoformat(),
        },
    ]

    for cdata in cases_data:
        try:
            case = await create_case(db, cdata)
            print(f"  Created case: {case['case_type']} - {case['priority']} - {case['status']}")
        except Exception as e:
            print(f"  Skip existing case {cdata['id']}: {e}")


async def seed_audit_trail(db):
    """Create sample audit trail entries showing the complete decision chain."""
    now = datetime.now(WAT)
    # Each entry represents a step in the 6-agent pipeline for the structuring case (alert_001 / sar_002).
    # The complete chain demonstrates the immutable audit trail required by
    # CBN BSD/DIR/PUB/LAB/019/002: every automated and human decision must be logged with actor,
    # timestamp, and outcome so regulators can reconstruct the full decision history.
    entries = [
        # Step 1: Transaction Monitor flags the transaction as suspicious
        {
            "entity_type": "transaction",
            "entity_id": "alert_001",
            "event_type": "agent_decision",
            "actor": "transaction_monitor_agent",
            "description": "transaction_monitor_agent decision: flagged",
            "metadata": '{"agent": "transaction_monitor_agent", "decision": "flagged", "confidence": 0.87, "risk_score": 0.82}',
        },
        # Step 2: Governance engine evaluates the confidence gate
        # Confidence 0.87 exceeds the 0.70 minimum threshold — pipeline continues
        {
            "entity_type": "transaction",
            "entity_id": "alert_001",
            "event_type": "governance_check",
            "actor": "governance_engine",
            "description": "Governance gate 'confidence_gate': PASSED - Confidence 0.87 meets threshold 0.70",
            "metadata": '{"gate": "confidence_gate", "passed": true, "requires_human": false}',
        },
        # Step 3: KYC Verifier confirms the customer's identity and risk tier
        {
            "entity_type": "customer",
            "entity_id": "cust_006",
            "event_type": "agent_decision",
            "actor": "kyc_verifier_agent",
            "description": "kyc_verifier_agent decision: verified",
            "metadata": '{"agent": "kyc_verifier_agent", "decision": "verified", "confidence": 0.9, "risk_tier": "high"}',
        },
        # Step 4: Sanctions screener checks Tunde Bakare against all 4 lists — no match found
        # All 4 mandatory lists are checked: OFAC SDN, UN Consolidated, Nigerian Domestic, PEP DB
        {
            "entity_type": "transaction",
            "entity_id": "alert_001",
            "event_type": "sanctions_screening",
            "actor": "sanctions_screener_agent",
            "description": "Sanctions screening for 'Tunde Bakare': 0 match(es), recommendation=clear",
            "metadata": '{"lists_checked": ["OFAC_SDN", "UN_CONSOLIDATED", "NIGERIAN_DOMESTIC", "PEP_DATABASE"], "match_count": 0, "recommendation": "clear"}',
        },
        # Step 5: Pattern analyzer confirms the structuring pattern across transaction history
        {
            "entity_type": "customer",
            "entity_id": "cust_006",
            "event_type": "agent_decision",
            "actor": "pattern_analyzer_agent",
            "description": "pattern_analyzer_agent decision: high",
            "metadata": '{"agent": "pattern_analyzer_agent", "decision": "high", "confidence": 0.87, "patterns_detected": 2}',
        },
        # Step 6: SAR generator drafts the report — but cannot file it automatically
        {
            "entity_type": "sar",
            "entity_id": "sar_001",
            "event_type": "sar_drafted",
            "actor": "sar_generator_agent",
            "description": "SAR drafted by sar_generator_agent",
            "metadata": '{"typology": "pep_corruption", "priority": "critical", "requires_human_approval": true}',
        },
        # Step 7: Governance engine enforces the mandatory human-in-the-loop gate for SAR filing.
        # CBN BSD/DIR/PUB/LAB/019/002 explicitly prohibits autonomous AI filing of STRs —
        # a human compliance officer must review and approve every report before NFIU submission.
        {
            "entity_type": "sar",
            "entity_id": "sar_001",
            "event_type": "governance_check",
            "actor": "governance_engine",
            "description": "Governance gate 'human_in_the_loop': PASSED - SAR filing ALWAYS requires mandatory human approval per CBN mandate",
            "metadata": '{"gate": "human_in_the_loop", "passed": true, "requires_human": true, "action_taken": "await_human_approval"}',
        },
        # Step 8: Human compliance officer approves sar_002 (structuring case — separate from sar_001)
        {
            "entity_type": "sar",
            "entity_id": "sar_002",
            "event_type": "sar_approved",
            "actor": "Chinelo Okafor",
            "description": "Human decision by Chinelo Okafor: approved - Evidence clearly supports structuring typology.",
            "metadata": '{"decision": "approved", "rationale": "Evidence clearly supports structuring typology. Pattern is unambiguous. Approved for immediate NFIU filing."}',
        },
        # Step 9: SAR filed with NFIU; reference number confirms receipt
        {
            "entity_type": "sar",
            "entity_id": "sar_002",
            "event_type": "sar_filed",
            "actor": "Chinelo Okafor",
            "description": "SAR filed with NFIU. Reference: NFIU-2026-0042-NG",
            "metadata": '{"nfiu_reference": "NFIU-2026-0042-NG", "filed_at": "' + (now - timedelta(days=8)).isoformat() + '"}',
        },
        # Step 10: Case manager creates and assigns an investigation case
        # Priority-based auto-assignment routes critical cases to senior compliance officers
        {
            "entity_type": "case",
            "entity_id": "case_001",
            "event_type": "case_created",
            "actor": "case_manager_agent",
            "description": "Case created and assigned by case_manager_agent",
            "metadata": '{"priority": "critical", "assigned_to": "Chinelo Okafor", "case_type": "pep_investigation", "assignment_rationale": "Auto-assigned to compliance_officer based on priority=critical"}',
        },
    ]

    for entry in entries:
        try:
            await log_audit(
                db=db,
                entity_type=entry["entity_type"],
                entity_id=entry["entity_id"],
                event_type=entry["event_type"],
                actor=entry["actor"],
                description=entry["description"],
                metadata=None,  # Metadata string stored in description for simplicity in demo
            )
        except Exception:
            pass  # Skip if duplicate — idempotent seeding

    print(f"  Created {len(entries)} audit trail entries")


async def seed_model_validations(db):
    """Create CBN-mandated model validation records."""
    now = datetime.now(WAT)

    # CBN BSD/DIR/PUB/LAB/019/002 requires that all AI/ML models used in AML systems
    # undergo annual independent validation covering accuracy, drift, bias, and fairness.
    # These records must be retained and made available to CBN examiners on request.
    validations = [
        {
            "model_name": "transaction_monitor",
            "validation_type": "annual_cbn_validation",
            "accuracy": 0.923,        # 92.3% accuracy on labelled historical SAR/non-SAR dataset
            "drift_score": 0.041,     # Low drift — model behaviour is stable over time
            "bias_score": 0.028,      # Minimal demographic bias across customer segments
            "fairness_score": 0.961,  # High fairness — no significant differential impact by geography/ethnicity
            "human_reviewer": "Dr. Amina Suleiman (Independent Validator)",
            "findings": "Model performing within acceptable parameters. Alert fatigue rate at 12%. Recommend threshold recalibration for mobile_money channel. No significant demographic bias detected across customer segments. Approved for continued deployment.",
        },
        {
            "model_name": "pattern_analyzer",
            "validation_type": "annual_cbn_validation",
            "accuracy": 0.881,
            "drift_score": 0.067,     # Elevated drift — new mobile money patterns emerged in Q4 2025
            "bias_score": 0.034,
            "fairness_score": 0.944,
            "human_reviewer": "Dr. Amina Suleiman (Independent Validator)",
            "findings": "LLM pattern analyzer shows 88.1% accuracy on historical SAR cases. Slight drift detected in Q4 2025 due to new mobile money patterns. Bias assessment: no significant geographic or demographic bias. Recommend quarterly model refresh. Conditionally approved pending recalibration.",
        },
        {
            "model_name": "sanctions_screener",
            "validation_type": "annual_cbn_validation",
            "accuracy": 0.967,        # Highest accuracy — rule-based fuzzy matching is more deterministic
            "drift_score": 0.019,     # Very low drift — list-matching logic is stable
            "bias_score": 0.012,
            "fairness_score": 0.988,
            "human_reviewer": "Dr. Amina Suleiman (Independent Validator)",
            "findings": "Fuzzy matching algorithm shows 96.7% accuracy. False positive rate at 3.1% (within acceptable range). No bias detected. List coverage comprehensive: OFAC, UN, domestic, PEP. Approved.",
        },
    ]

    for vdata in validations:
        try:
            val = await create_model_validation(db, vdata)
            print(f"  Created model validation: {val['model_name']}")
        except Exception as e:
            print(f"  Error creating validation: {e}")


async def seed_dormant_accounts(db):
    """Mark dormant customers with is_dormant=1 and last_transaction_at timestamps.

    Two customers are seeded as dormant (inactive for 180+ days per CBN threshold):
    - cust_010 is already partially dormant in the main seed data (minimal txns).
      Here we ensure the dormancy flag is set and a reactivation alert exists.
    - cust_004 is updated to simulate sudden reactivation after a year of inactivity,
      which triggers the DORMANT_REACTIVATION rule in TransactionMonitorAgent.

    CBN AML/CFT Guidelines Section 4 defines dormancy as 180 days without customer-
    initiated transactions. Enhanced monitoring applies to reactivated dormant accounts.
    """
    now = datetime.now(WAT)

    # Mark cust_010 (existing dormant scenario) with dormancy flags
    try:
        dormant_since = (now - timedelta(days=210)).isoformat()
        last_txn = (now - timedelta(days=210)).isoformat()
        await update_customer(db, "cust_010", {
            "is_dormant": 1,
            "dormant_since": dormant_since,
            "last_transaction_at": last_txn,
        })
        print("  Updated cust_010: marked dormant (210 days inactive)")
    except Exception as e:
        print(f"  Error updating cust_010 dormancy: {e}")

    # Create a dormant reactivation alert for cust_010 to show in the alerts tab
    try:
        await create_alert(db, {
            "id": "alert_dormant_001",
            "customer_id": "cust_010",
            "transaction_id": None,
            "agent_source": "transaction_monitor_agent",
            "alert_type": "DORMANT_REACTIVATION",
            "severity": "high",
            "description": (
                "Dormant account reactivation detected: 'Kola Adeyinka' (cust_010) "
                "had no activity for 210 days (exceeds 180-day CBN dormancy threshold). "
                "Sudden inbound transfer of NGN 12,500,000 received. "
                "Enhanced monitoring and enhanced due diligence required per CBN AML/CFT Section 4."
            ),
            "confidence": 0.91,
            "status": "open",
        })
        print("  Created dormant reactivation alert for cust_010")
    except Exception:
        pass  # Alert may already exist

    # Log dormancy detection to audit trail
    try:
        await log_audit(
            db=db,
            entity_type="customer",
            entity_id="cust_010",
            event_type="dormancy_detected",
            actor="transaction_monitor_agent",
            description=(
                "Customer 'Kola Adeyinka' account flagged as dormant: 210 days since last "
                "customer-initiated transaction. CBN AML/CFT Guidelines Section 4 threshold "
                "(180 days) exceeded. Account status updated to is_dormant=1."
            ),
            metadata={"days_inactive": 210, "cbn_threshold_days": 180},
        )
    except Exception:
        pass


async def seed_onboarding_escalations(db):
    """Seed onboarding scenarios: approved, pending review, PEP escalation, blocked.

    Demonstrates the full Agent 0 decision tree for the onboarding screener.
    These records show compliance teams the four possible onboarding outcomes
    and provide realistic data for the Onboarding tab in the dashboard.
    """
    now = datetime.now(WAT)

    escalations = [
        # PEP onboarding pending MLRO approval (FATF Recommendation 12).
        # A state governor's chief of staff applied for a corporate account —
        # PEP detection triggers mandatory C-suite/MLRO review before activation.
        {
            "id": "esc_001",
            "entity_type": "customer_onboarding",
            "entity_id": "cust_008",  # Babatunde Fashola — existing PEP seed customer
            "escalation_reason": (
                "PEP match detected during onboarding screening: Customer name "
                "'Babatunde Fashola' matched against internal PEP database with strong "
                "match (score 0.91). FATF Recommendation 12 requires enhanced due diligence "
                "and C-suite/MLRO approval before account activation."
            ),
            "required_approver_role": "mlro",
            "sla_hours": 4,  # Critical PEP escalations: 4-hour SLA
            "current_status": "pending",
            "decision_rationale": None,
            "assigned_to": None,
            "match_evidence": (
                '{"list_name": "internal_pep", "matched_entity": "Babatunde Fashola", '
                '"match_type": "strong", "match_score": 0.91, "match_category": "pep"}'
            ),
        },
        # Adverse media escalation pending compliance officer review.
        # Customer linked to an ongoing EFCC investigation per adverse media screening.
        {
            "id": "esc_002",
            "entity_type": "customer_onboarding",
            "entity_id": "cust_020",  # Near-PEP match scenario
            "escalation_reason": (
                "Adverse media match at onboarding: Customer name closely matches "
                "an entity referenced in EFCC enforcement proceedings (partial match, "
                "score 0.73). Head of Compliance review required per CBN AML/CFT "
                "Guidelines Section 3.2 (adverse media screening)."
            ),
            "required_approver_role": "compliance_officer",
            "sla_hours": 24,
            "current_status": "approved",
            "decision_rationale": (
                "Enhanced due diligence completed. EFCC reference is for a different entity "
                "with similar name — false positive confirmed. Customer passed identity "
                "verification (BVN/NIN match). Account approved with enhanced monitoring "
                "for 90 days per policy. Approved: Chinelo Okafor (MLRO), 2026-04-15."
            ),
            "assigned_to": "Chinelo Okafor",
            "match_evidence": (
                '{"list_name": "nigerian_domestic", "matched_entity": "Emmanuel Okafor", '
                '"match_type": "partial", "match_score": 0.73, "match_category": "adverse_media"}'
            ),
        },
        # Rejected onboarding: confirmed sanctions match.
        # Name matched OFAC SDN list with exact score — account registration blocked per CBN mandate.
        {
            "id": "esc_003",
            "entity_type": "customer_onboarding",
            "entity_id": "cust_019",  # Existing blocked/sanctions scenario
            "escalation_reason": (
                "Confirmed sanctions match at onboarding: Customer name matched "
                "OFAC SDN list with exact match (score 0.98). Account registration "
                "BLOCKED per CBN AML/CFT mandate. Senior compliance officer review required "
                "for any exception consideration (none expected)."
            ),
            "required_approver_role": "compliance_officer",
            "sla_hours": 4,
            "current_status": "rejected",
            "decision_rationale": (
                "Confirmed OFAC sanctions match with score 0.98. No grounds for exception. "
                "Account registration permanently rejected. NFIU notified. "
                "Rejected: Ngozi Adeyemi (Senior Analyst), 2026-04-10."
            ),
            "assigned_to": "Ngozi Adeyemi",
            "match_evidence": (
                '{"list_name": "ofac_sdn", "matched_entity": "Ibrahim Al-Zubayr", '
                '"match_type": "exact", "match_score": 0.98, "match_category": "sanctions"}'
            ),
        },
    ]

    for esc_data in escalations:
        try:
            # Compute expires_at based on sla_hours (same as create_escalation in database.py)
            expires_at = (now + timedelta(hours=esc_data["sla_hours"])).isoformat()

            await db.execute(
                """INSERT OR IGNORE INTO escalations
                   (id, entity_type, entity_id, escalation_reason,
                    required_approver_role, sla_hours, current_status,
                    decision_rationale, assigned_to, match_evidence,
                    expires_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    esc_data["id"],
                    esc_data["entity_type"],
                    esc_data["entity_id"],
                    esc_data["escalation_reason"],
                    esc_data["required_approver_role"],
                    esc_data["sla_hours"],
                    esc_data["current_status"],
                    esc_data.get("decision_rationale"),
                    esc_data.get("assigned_to"),
                    esc_data.get("match_evidence"),
                    expires_at,
                    now.isoformat(),
                ),
            )
            await db.commit()
            print(f"  Created escalation: {esc_data['id']} ({esc_data['current_status']})")
        except Exception as e:
            print(f"  Error creating escalation {esc_data['id']}: {e}")

    # Log audit entries for the escalations
    audit_entries = [
        {
            "entity_type": "escalation",
            "entity_id": "esc_001",
            "event_type": "escalation_created",
            "actor": "onboarding_screener_agent",
            "description": "PEP onboarding escalation created. MLRO approval required (FATF R.12).",
        },
        {
            "entity_type": "escalation",
            "entity_id": "esc_002",
            "event_type": "escalation_approved",
            "actor": "Chinelo Okafor",
            "description": "Adverse media escalation approved after enhanced due diligence. False positive confirmed.",
        },
        {
            "entity_type": "escalation",
            "entity_id": "esc_003",
            "event_type": "escalation_rejected",
            "actor": "Ngozi Adeyemi",
            "description": "Sanctions match escalation rejected. Account registration blocked. NFIU notified.",
        },
    ]
    for entry in audit_entries:
        try:
            await log_audit(
                db=db,
                entity_type=entry["entity_type"],
                entity_id=entry["entity_id"],
                event_type=entry["event_type"],
                actor=entry["actor"],
                description=entry["description"],
                metadata=None,
            )
        except Exception:
            pass
    print(f"  Created {len(escalations)} onboarding escalations")


async def seed_monitoring_runs(db):
    """Seed monitoring run history and screening list records.

    Creates 3 completed monitoring runs showing realistic execution history.
    Also seeds the screening_lists table with current list metadata so the
    Monitoring tab shows list freshness information immediately on first load.

    CBN requires documented evidence of periodic re-screening cadence.
    These records satisfy that requirement by showing when monitoring last ran
    and what it found.
    """
    now = datetime.now(WAT)

    # Seed screening list metadata (checksums simulate what ListManager would compute)
    screening_lists = [
        {
            "list_name": "ofac_sdn",
            "version": "2026-04-28",
            "last_updated": (now - timedelta(days=6)).isoformat(),
            "entry_count": 18,
            "source_url": "https://www.treasury.gov/ofac/downloads/sdn.csv",
            "checksum": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
        },
        {
            "list_name": "un_consolidated",
            "version": "2026-04-25",
            "last_updated": (now - timedelta(days=9)).isoformat(),
            "entry_count": 14,
            "source_url": "https://scsanctions.un.org/resources/xml/en/consolidated.xml",
            "checksum": "b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3",
        },
        {
            "list_name": "nigerian_domestic",
            "version": "2026-05-01",
            "last_updated": (now - timedelta(days=3)).isoformat(),
            "entry_count": 12,
            "source_url": "internal://cbn-nfiu-watchlist",
            "checksum": "c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4",
        },
        {
            "list_name": "internal_pep",
            "version": "2026-05-01",
            "last_updated": (now - timedelta(days=3)).isoformat(),
            "entry_count": 8,
            "source_url": "internal://pep-database",
            "checksum": "d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5",
        },
    ]

    for sl_data in screening_lists:
        try:
            await upsert_screening_list(db, sl_data)
            print(f"  Seeded screening list: {sl_data['list_name']} ({sl_data['entry_count']} entries)")
        except Exception as e:
            print(f"  Error seeding screening list {sl_data['list_name']}: {e}")

    # Seed monitoring run history: 3 completed runs
    monitoring_runs = [
        # Run 3 weeks ago — baseline run, no new matches
        {
            "id": "run_001",
            "run_type": "scheduled",
            "started_at": (now - timedelta(days=21)).isoformat(),
            "completed_at": (now - timedelta(days=21, hours=-0.5)).isoformat(),
            "status": "completed",
            "customers_screened": 20,
            "new_matches": 0,
            "risk_upgrades": 0,
            "metadata": '{"trigger": "weekly_schedule", "list_versions": {"ofac_sdn": "2026-04-14"}}',
        },
        # Run 14 days ago — detected 1 new PEP match, upgraded 1 risk tier
        {
            "id": "run_002",
            "run_type": "scheduled",
            "started_at": (now - timedelta(days=14)).isoformat(),
            "completed_at": (now - timedelta(days=14, hours=-0.4)).isoformat(),
            "status": "completed",
            "customers_screened": 20,
            "new_matches": 1,
            "risk_upgrades": 1,
            "metadata": '{"trigger": "weekly_schedule", "note": "cust_020 newly matched against internal_pep list"}',
        },
        # Run 7 days ago — detected 2 new matches (list was updated with new entries)
        {
            "id": "run_003",
            "run_type": "list_update",
            "started_at": (now - timedelta(days=7)).isoformat(),
            "completed_at": (now - timedelta(days=7, hours=-0.6)).isoformat(),
            "status": "completed",
            "customers_screened": 20,
            "new_matches": 2,
            "risk_upgrades": 1,
            "metadata": '{"trigger": "list_update", "updated_list": "nigerian_domestic", "note": "2 customers matched new NFIU entries"}',
        },
    ]

    for run_data in monitoring_runs:
        try:
            await db.execute(
                """INSERT OR IGNORE INTO monitoring_runs
                   (id, run_type, started_at, completed_at, status,
                    customers_screened, new_matches, risk_upgrades, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_data["id"],
                    run_data["run_type"],
                    run_data["started_at"],
                    run_data.get("completed_at"),
                    run_data["status"],
                    run_data.get("customers_screened", 0),
                    run_data.get("new_matches", 0),
                    run_data.get("risk_upgrades", 0),
                    run_data.get("metadata"),
                ),
            )
            await db.commit()
            print(f"  Created monitoring run: {run_data['id']} ({run_data['new_matches']} new matches)")
        except Exception as e:
            print(f"  Error creating monitoring run {run_data['id']}: {e}")

    # Audit entries for the significant monitoring run (run_002 found a PEP match)
    try:
        await log_audit(
            db=db,
            entity_type="monitoring_run",
            entity_id="run_002",
            event_type="monitoring_run_completed",
            actor="continuous_monitor",
            description=(
                "Monitoring run 'scheduled' completed: 20 customers screened, "
                "1 new match found (cust_020 matched internal_pep), 1 risk tier upgraded."
            ),
            metadata={
                "run_type": "scheduled",
                "customers_screened": 20,
                "new_matches": 1,
                "risk_upgrades": 1,
            },
        )
        await log_audit(
            db=db,
            entity_type="monitoring_run",
            entity_id="run_003",
            event_type="monitoring_run_completed",
            actor="continuous_monitor",
            description=(
                "Monitoring run 'list_update' completed: 20 customers screened, "
                "2 new matches found (new NFIU entries added), 1 risk tier upgraded."
            ),
            metadata={
                "run_type": "list_update",
                "customers_screened": 20,
                "new_matches": 2,
                "risk_upgrades": 1,
            },
        )
    except Exception:
        pass

    print(f"  Created {len(monitoring_runs)} monitoring runs, {len(screening_lists)} screening list records")


if __name__ == "__main__":
    asyncio.run(seed_database())
