# AgenticAML

**AI-Powered AML Compliance for Nigerian Financial Institutions**

AgenticAML is a production-grade, multi-agent Anti-Money Laundering (AML) compliance system built to meet the CBN Baseline Standards for Automated AML Solutions (Circular BSD/DIR/PUB/LAB/019/002, March 10, 2026). It automates the full AML compliance lifecycle: transaction screening, KYC verification, sanctions screening, pattern detection, SAR generation, and case management, with governance controls enforced at every stage.

**Port:** 8003

---

## Architecture

### 6-Agent Pipeline

```
Transaction Data
      |
      v
[1. Transaction Monitor]  <-- Rule-based threshold, velocity, structuring, geo checks
      |
      v
[2. KYC Verifier]         <-- BVN/NIN validation, PEP detection, risk tier assignment
      |
      v
[3. Sanctions Screener]   <-- OFAC, UN, CBN domestic lists, fuzzy name matching
      |
      v
[4. Pattern Analyzer]     <-- LLM + rule-based: behavioral anomalies, layering, smurfing
      |
      v
[5. SAR Generator]        <-- Draft SAR/STR in NFIU format (mandatory human approval)
      |
      v
[6. Case Manager]         <-- Case creation, assignment, SLA tracking, regulatory reports
      |
      v
  Governance Engine       <-- Inline at every stage: confidence gate, materiality gate,
                              sanctions block, human-in-the-loop, audit trail
```

Every decision made by any agent is logged to an **immutable audit trail** before the result is returned. The governance engine runs between each stage, not just at the end.

### Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend | Python 3.12, FastAPI |
| Database | SQLite (demo), PostgreSQL (production) |
| Agent Framework | LangChain |
| LLM | OpenAI GPT-4o (optional, falls back to rule-based) |
| Containerization | Docker, Docker Compose |
| CI/CD | GitHub Actions |
| Testing | pytest, pytest-asyncio |

---

## Quick Start

### 1. Clone and configure

```bash
git clone <repository-url>
cd AgenticAML
cp .env.example .env
```

Edit `.env` and set your values. At minimum:

```env
DB_PATH=/app/data/aml.db
INSTITUTION_NAME=Your Bank Name
INSTITUTION_CODE=YOURCODE001
# Optional: enables LLM-powered pattern analysis
OPENAI_API_KEY=sk-...
```

### 2. Run with Docker Compose

```bash
docker compose up --build
```

The API will be available at `http://localhost:8003`.

On first start, if the database is empty, the system automatically seeds 20 customers, 200 transactions, and pre-processed alerts, SARs, and cases for demonstration.

### 3. Run locally (development)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

mkdir -p data
export DB_PATH=./data/aml.db
export SEED_ON_START=true

uvicorn src.main:app --host 0.0.0.0 --port 8003 --reload
```

### 4. Health check

```bash
curl http://localhost:8003/health
```

---

## API Reference

### System

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check and system status |

### Transactions

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/transactions/screen` | Screen a single transaction through the full 6-agent pipeline |
| POST | `/transactions/batch` | Screen a batch of transactions |
| GET | `/transactions` | List transactions with optional filters |
| GET | `/transactions/{id}` | Get transaction details with alerts |

**Example: Screen a transaction**

```bash
curl -X POST http://localhost:8003/transactions/screen \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": "CUST001",
    "amount": 12000000,
    "currency": "NGN",
    "transaction_type": "transfer",
    "channel": "internet_banking",
    "direction": "outbound",
    "geo_location": "Lagos, NG",
    "timestamp": "2026-04-15T10:30:00+01:00"
  }'
```

### Customers

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/customers` | List all customers |
| GET | `/customers/{id}` | Customer profile with risk history |
| POST | `/customers/{id}/kyc` | Trigger KYC verification |
| PUT | `/customers/{id}/risk-tier` | Update risk tier (requires human approval) |

### Alerts

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/alerts` | List alerts (filter by status, severity, agent) |
| GET | `/alerts/{id}` | Alert details with linked transactions |
| PUT | `/alerts/{id}/assign` | Assign alert to analyst |
| PUT | `/alerts/{id}/resolve` | Resolve alert with rationale |

### Sanctions

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/sanctions/screen?name=...` | Screen a name against all lists |
| GET | `/sanctions/matches` | List all sanctions matches |
| POST | `/sanctions/matches/{id}/review` | Human review of a sanctions match |

### SARs (Suspicious Activity Reports)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/sars` | List SARs (filter by status, priority) |
| GET | `/sars/{id}` | SAR details |
| POST | `/sars/{id}/approve` | **Mandatory human approval** before filing |
| POST | `/sars/{id}/reject` | Reject SAR draft with rationale |
| POST | `/sars/{id}/file` | File SAR with NFIU (post-approval only) |

### Cases

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/cases` | List investigation cases |
| GET | `/cases/{id}` | Case details with full history |
| PUT | `/cases/{id}/status` | Update case status |
| PUT | `/cases/{id}/assign` | Assign case to team member |

### Governance

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/governance/dashboard` | Governance metrics and statistics |
| GET | `/governance/audit-trail` | Full audit trail with filters |
| GET | `/governance/audit-trail/{entity_id}` | Audit trail for a specific entity |
| GET | `/governance/model-validation` | Model validation history |
| POST | `/governance/model-validation` | Record a new model validation (CBN annual requirement) |

### Reports

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/reports/daily` | Daily compliance summary |
| GET | `/reports/weekly` | Weekly compliance report |
| GET | `/reports/str-summary` | STR/SAR filing summary |
| GET | `/reports/alert-analytics` | Alert volume, types, and resolution analytics |

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_PATH` | `/app/data/aml.db` | SQLite database path |
| `SEED_ON_START` | `true` | Auto-seed demo data if DB is empty |
| `OPENAI_API_KEY` | _(empty)_ | OpenAI API key (falls back to rule-based if not set) |
| `CASH_THRESHOLD` | `5000000` | NGN cash reporting threshold |
| `TRANSFER_THRESHOLD` | `10000000` | NGN transfer reporting threshold |
| `MATERIALITY_THRESHOLD` | `50000000` | NGN materiality threshold for enhanced review |
| `VELOCITY_WINDOW_HOURS` | `24` | Velocity check window in hours |
| `VELOCITY_MAX_TRANSACTIONS` | `10` | Max transactions in velocity window |
| `VELOCITY_MAX_AMOUNT` | `20000000` | Max amount in velocity window (NGN) |
| `STRUCTURING_THRESHOLD_PCT` | `0.9` | Structuring detection: % of cash threshold |
| `CONFIDENCE_GATE_THRESHOLD` | `0.7` | Min confidence before human escalation |
| `AUTO_BLOCK_SANCTIONS` | `true` | Auto-block confirmed sanctions matches (CBN mandate) |
| `INSTITUTION_NAME` | `Demo Bank Nigeria Ltd` | Reporting institution name |
| `INSTITUTION_CODE` | `DEMOBANK001` | Reporting institution code |
| `PORT` | `8003` | API server port |

---

## Testing

```bash
pip install -r requirements.txt

# Run all tests
pytest tests/ --asyncio-mode=auto -v

# Run with coverage
pytest tests/ --asyncio-mode=auto --cov=src --cov-report=term-missing -v

# Run specific test modules
pytest tests/test_agents.py --asyncio-mode=auto -v
pytest tests/test_governance.py --asyncio-mode=auto -v
pytest tests/test_api.py --asyncio-mode=auto -v
pytest tests/test_database.py --asyncio-mode=auto -v
```

Tests run in **rule-based mode** (no OpenAI API key required). Each test module uses a separate isolated SQLite database that is created fresh and cleaned up after the test session.

---

## CBN Compliance Mapping

The following table maps CBN Circular BSD/DIR/PUB/LAB/019/002 requirements to AgenticAML features:

| CBN Requirement | AgenticAML Implementation |
|----------------|--------------------------|
| **Automated transaction monitoring with configurable thresholds** | Agent 1 (Transaction Monitor): configurable NGN thresholds via environment variables; covers cash, wire, velocity, structuring, dormant accounts |
| **KYC identity verification with BVN/NIN validation** | Agent 2 (KYC Verifier): BVN/NIN format validation, completeness scoring, risk tier assignment; production integrates with NIBSS and NIMC APIs |
| **Sanctions screening against OFAC, UN, and domestic lists** | Agent 3 (Sanctions Screener): fuzzy name matching across OFAC SDN, UN Consolidated, CBN domestic lists, PEP database, adverse media indicators |
| **Confirmed sanctions matches MUST block transactions** | Governance Engine: `sanctions_block` gate auto-blocks any `exact` or `strong` match; `AUTO_BLOCK_SANCTIONS=true` enforces this unconditionally |
| **Human-in-the-loop for SAR filing decisions** | Agent 5 (SAR Generator): always produces `status=draft`; SAR cannot be filed without explicit human approval via `POST /sars/{id}/approve` |
| **Mandatory SAR filing within 24 hours (NFIU requirement)** | SLA tracking in Case Manager; `str_filing_deadline_hours=24` in `SlaConfig`; filing deadline alerts in governance dashboard |
| **Annual model validation (accuracy, drift, bias, fairness)** | `POST /governance/model-validation` records validation results; `model_validations` table stores history; CBN-required fields tracked |
| **Immutable audit trail for all decisions** | `audit_trail` table is append-only; every agent calls `log_agent_decision()` before returning; governance engine calls `log_governance_decision()` at every gate |
| **Explainability of AI/ML decisions** | Pattern Analyzer logs full reasoning chain to audit trail; all triggered rules stored with threshold and observed values |
| **Segregation of duties** | Case Manager enforces role-based case closure; `high_risk_case_close_roles` restricts who can close critical cases |
| **Escalation chains with SLA tracking** | Risk-tiered SLAs (critical: 4h, high: 24h, medium: 72h, low: 168h); case manager assigns by role and priority |
| **STR/CTR regulatory report generation** | Reports endpoints generate NFIU-format summaries; `GET /reports/str-summary` provides filing status |
| **PEP detection and enhanced due diligence** | KYC Verifier checks name for PEP keywords and existing PEP flag; PEP customers auto-elevated to high/very_high risk tier |
| **Cross-channel transaction aggregation** | Transaction Monitor aggregates across all channels per customer in the velocity window |
| **Structuring/smurfing detection** | Transaction Monitor detects multiple transactions just below threshold; Pattern Analyzer cross-references for confirmed structuring patterns |
| **Configurable risk thresholds via administration** | All thresholds configurable via environment variables without code changes; documented in `.env.example` |
| **False positive rate tracking** | Alert Analytics endpoint reports false positive rates; `model_validations` tracks bias and fairness metrics |

### Risk Tier Thresholds (CBN-Aligned)

| Tier | Amount Range | Required Action |
|------|-------------|----------------|
| Low | Below NGN 1M | Automated processing, logged |
| Medium | NGN 1M to 5M | Enhanced monitoring, analyst review if flagged |
| High | NGN 5M to 50M | Senior analyst review required |
| Critical | Above NGN 50M or sanctions match | Compliance officer + mandatory SAR assessment |

---

## Governance Controls

The governance engine enforces the following controls between every agent stage:

| Control | Gate Name | Description |
|---------|-----------|-------------|
| Confidence Gate | `confidence_gate` | Agent outputs below 0.7 confidence escalate to human review |
| Materiality Gate | `materiality_gate` | Transactions above NGN 50M require additional human review |
| Sanctions Block | `sanctions_block` | Confirmed sanctions matches auto-block (CBN mandate, no override) |
| Human-in-the-Loop | `human_in_the_loop` | SAR filing always requires human approval |
| KYC Escalation | `kyc_escalation` | Failed/incomplete KYC escalates to compliance officer |
| Escalation Chain | `escalation_chain` | Critical/high risk patterns escalate by role |

---

## Demo Data

On first startup (when the database is empty), the system seeds:

- **20 customers**: Mix of individuals and corporates, various risk tiers, some with PEP status, some with incomplete KYC. Nigerian names and addresses.
- **200 transactions**: Various types (transfer, cash deposit, cash withdrawal, international wire, mobile money), channels, and amounts. Includes suspicious patterns: structuring, rapid fund movement, high-risk geography, dormant account activity.
- **Sanctions lists**: ~50 simulated entries across OFAC SDN, UN Consolidated, and CBN domestic watchlist, with near-matches for fuzzy matching demonstration.
- **Pre-processed alerts and cases**: 5-10 processed transactions showing the full pipeline, at least one SAR in draft status awaiting human approval, at least one active investigation case.

---

## Project Structure

```
AgenticAML/
  src/
    main.py                   # FastAPI app, all routes, pipeline orchestration
    database.py               # SQLite/PostgreSQL CRUD operations, schema
    models.py                 # Pydantic models for all entities
    agents/
      transaction_monitor.py  # Agent 1: Rule-based transaction screening
      kyc_verifier.py         # Agent 2: BVN/NIN validation, PEP detection
      sanctions_screener.py   # Agent 3: Multi-list sanctions screening
      pattern_analyzer.py     # Agent 4: LLM + rule-based pattern detection
      sar_generator.py        # Agent 5: NFIU-format SAR drafting
      case_manager.py         # Agent 6: Case routing, SLA tracking, reports
    governance/
      engine.py               # Governance gate evaluation (runs between every stage)
      rules.py                # Configurable thresholds and role definitions
      audit.py                # Immutable audit trail logging helpers
    data/
      seed.py                 # Demo data seeding
      sanctions_lists.py      # Simulated OFAC, UN, and CBN sanctions data
      sample_transactions.py  # Realistic transaction generator
  tests/
    test_agents.py            # All 6 agents with realistic sample data
    test_governance.py        # Governance engine, rules, audit trail
    test_api.py               # All FastAPI endpoints
    test_database.py          # Database CRUD operations
  Dockerfile
  docker-compose.yml
  requirements.txt
  .env.example
  .github/workflows/ci.yml
  SPEC.md
```

---

## Regulatory Context

AgenticAML is designed for Nigerian-jurisdiction use under:

- **CBN AML/CFT/CPF Guidelines** (Central Bank of Nigeria)
- **Money Laundering (Prevention and Prohibition) Act 2022**
- **CBN Circular BSD/DIR/PUB/LAB/019/002** (March 10, 2026): Baseline Standards for Automated AML Solutions
- **FATF Recommendations** (Financial Action Task Force)
- **NFIU Reporting Requirements** (Nigeria Financial Intelligence Unit): 24-hour STR filing deadline

All amounts are in **Nigerian Naira (NGN)**. All timestamps are in **West Africa Time (WAT, UTC+1)**.

> This system is designed as a compliance tool that assists human compliance officers. All high-risk decisions require human review. SAR filing always requires human approval. No transaction is blocked without a logged, auditable reason.
