# AgenticAML: AI-Powered AML Compliance for Nigerian Financial Institutions

## Product Overview

AgenticAML is a multi-agent AML compliance system built to meet the CBN Baseline Standards for Automated Anti-Money Laundering Solutions (Circular BSD/DIR/PUB/LAB/019/002, March 10, 2026). It automates transaction monitoring, KYC verification, sanctions screening, suspicious activity detection, SAR generation, case management, and regulatory reporting with governance controls embedded into every agent decision.

**Target users:** Nigerian deposit money banks, fintechs, payment service providers, mobile money operators, and international money transfer operators.

**Regulatory alignment:** CBN AML/CFT/CPF guidelines, Money Laundering (Prevention and Prohibition) Act 2022, FATF Recommendations, NFIU reporting requirements.

---

## Architecture

### Tech Stack
- **Backend:** Python 3.12, FastAPI
- **Database:** SQLite (demo), PostgreSQL (production)
- **Agent Framework:** LangChain
- **LLM:** OpenAI GPT-4o (configurable, supports Claude)
- **Frontend:** Next.js + Tailwind CSS (dashboard)
- **Containerization:** Docker + Docker Compose
- **CI/CD:** GitHub Actions
- **Testing:** pytest

### 6-Agent Pipeline

```
Transaction Data  -->  [1. Transaction Monitor]  -->  [2. KYC Verifier]
                                |                            |
                                v                            v
                       [3. Sanctions Screener]  -->  [4. Pattern Analyzer]
                                                            |
                                                            v
                                                   [5. SAR Generator]
                                                            |
                                                            v
                                                   [6. Case Manager]
                                                            |
                                                   Governance Engine
                                                   (inline at every stage)
```

---

## Agent Specifications

### Agent 1: Transaction Monitor
**Purpose:** Ingest and screen transactions against rule-based thresholds in real time.

**Inputs:**
- Transaction feed (JSON): sender, receiver, amount, currency, channel, timestamp, geo_location
- Customer risk profile

**Processing:**
- Threshold monitoring (transactions above configurable limits: NGN 5M cash, NGN 10M transfer)
- Velocity checks (frequency of transactions in time window)
- Structuring detection (multiple transactions just below threshold)
- Cross-channel aggregation (same customer, different channels)
- Round amount detection
- Dormant account activity detection

**Outputs:**
- Risk score (0.0 to 1.0)
- List of triggered rules with descriptions
- Flagged or cleared status
- Confidence score

**Governance:**
- Every screening decision logged with rule, threshold, and result
- Configurable thresholds via environment variables
- Audit trail entry per transaction

### Agent 2: KYC Verifier
**Purpose:** Verify customer identity against national databases and assess KYC completeness.

**Inputs:**
- Customer record: name, BVN, NIN, date_of_birth, address, phone, account_type
- Transaction context from Agent 1

**Processing:**
- BVN/NIN validation (simulated API call for demo, real integration for production)
- Customer data completeness check (missing fields flagged)
- Risk profile assessment (individual vs corporate, domestic vs international)
- PEP status check
- Customer risk tier assignment (low, medium, high, very_high)

**Outputs:**
- KYC status: verified, incomplete, failed, requires_update
- Risk tier assignment
- Missing documentation list
- Verification confidence score

**Governance:**
- Identity verification decisions logged with data sources checked
- Failed verifications automatically escalate to compliance officer
- Customer risk tier changes require human approval for downgrades

### Agent 3: Sanctions Screener
**Purpose:** Screen customers and counterparties against sanctions lists, PEP databases, and adverse media.

**Inputs:**
- Customer/counterparty names from transaction
- Entity details (aliases, date of birth, nationality, address)

**Processing:**
- Screen against:
  - OFAC SDN List (simulated)
  - UN Consolidated Sanctions List (simulated)
  - Nigerian domestic sanctions/watchlist
  - PEP database
  - Internal watchlist
  - Adverse media indicators
- Fuzzy name matching (handling transliteration, aliases, partial matches)
- Match scoring (exact, strong, partial, weak)

**Outputs:**
- Match results per list with match type and score
- Recommended action: clear, review, block
- Matched entity details for investigation

**Governance:**
- **Confirmed sanctions matches MUST block transactions** (CBN mandate)
- All screening results logged regardless of outcome
- False positive rate tracked for model improvement
- Human review required for "strong" and "partial" matches
- "Block" actions require senior compliance officer confirmation

### Agent 4: Pattern Analyzer
**Purpose:** Use LLM reasoning to detect complex patterns that rule-based systems miss.

**Inputs:**
- Transaction history for flagged customers (last 90 days)
- Alert history from Agents 1-3
- Customer profile and risk tier

**Processing:**
- Behavioral anomaly detection:
  - Sudden changes in transaction volume or frequency
  - Geographic anomalies (transactions from unusual locations)
  - Time-of-day anomalies
  - New counterparty patterns
- Network analysis:
  - Connected accounts (shared addresses, phones, beneficiaries)
  - Circular transaction patterns (layering detection)
  - Rapid fund movement through multiple accounts
- Typology matching:
  - Trade-based money laundering indicators
  - Smurfing/structuring patterns
  - Shell company indicators
  - PEP-related corruption patterns

**Outputs:**
- Identified patterns with descriptions
- Typology classification
- Overall risk assessment (low, medium, high, critical)
- Recommended investigation actions
- Supporting evidence summary

**Governance:**
- LLM reasoning chain logged (explainability)
- Pattern confidence scores with evidence citations
- High-risk patterns automatically escalate to Agent 5
- Annual model validation required (CBN mandate): accuracy, drift, bias, fairness
- Human review mandatory for "critical" risk assessments

### Agent 5: SAR Generator
**Purpose:** Draft Suspicious Activity Reports from flagged transactions and investigations.

**Inputs:**
- Flagged transaction details
- Alert summaries from Agents 1-4
- Customer profile
- Investigation notes (if any)

**Processing:**
- Generate structured SAR/STR matching NFIU format:
  - Subject information (name, ID, account details)
  - Suspicious activity description (narrative)
  - Transaction details (dates, amounts, counterparties)
  - Reason for suspicion (mapped to typologies)
  - Supporting evidence summary
  - Reporting institution details
- Risk categorization of the report
- Priority assignment (routine, urgent, critical)

**Outputs:**
- Draft SAR/STR document (structured JSON + narrative text)
- Filing priority recommendation
- Evidence package (linked transactions, alerts, patterns)

**Governance:**
- **SAR filing decisions require MANDATORY human approval** (agents draft, humans approve)
- Draft SAR and final SAR both logged
- Filing deadline tracking (24 hours for STR per NFIU requirements)
- Reviewer must provide rationale for approve/modify/reject
- Complete audit trail from initial alert to filed report

### Agent 6: Case Manager
**Purpose:** Route cases, track investigations, manage compliance workflows, and generate regulatory reports.

**Inputs:**
- Alerts and escalations from all agents
- SAR filing status
- Investigation assignments and updates

**Processing:**
- Case creation and assignment:
  - Auto-assign by risk tier and case type
  - Load balancing across compliance team
  - Priority queue management
- Investigation workflow:
  - Status tracking (open, investigating, pending_review, closed)
  - Evidence collection and documentation
  - Deadline monitoring (SLA tracking)
- Regulatory reporting:
  - STR/CTR report generation for NFIU
  - Compliance dashboard metrics
  - Periodic summary reports (daily, weekly, monthly)
- Trend analysis:
  - Alert volume trends
  - False positive rates
  - Resolution time tracking
  - Typology distribution

**Outputs:**
- Case status and assignments
- Regulatory reports (STR, CTR, periodic summaries)
- Compliance dashboard data
- Alert and case analytics

**Governance:**
- Case assignments logged with rationale
- Escalation chains enforced (cannot close high-risk case without senior review)
- Regulatory report filing tracked with confirmation
- SLA breach alerts
- Complete investigation history preserved

---

## Governance Engine (Inline at Every Stage)

The governance engine evaluates every agent decision and enforces controls. It operates between every agent stage.

### Controls

| Control | Description | When Applied |
|---------|------------|-------------|
| **Confidence Gate** | Decisions below confidence threshold escalate to human review | Every agent output |
| **Materiality Gate** | Transactions above materiality thresholds require additional review | Transaction Monitor, Pattern Analyzer |
| **Sanctions Block** | Confirmed sanctions matches automatically blocked | Sanctions Screener |
| **Human-in-the-Loop** | Mandatory human approval for SAR filing, high-risk decisions | SAR Generator, Case Manager |
| **Segregation of Duties** | Monitoring, investigation, and reporting handled by different roles | Case Manager |
| **Model Validation** | AI/ML model accuracy, drift, and bias tracked | Pattern Analyzer (CBN annual requirement) |
| **Audit Trail** | Every decision (agent and human) logged immutably | All agents |
| **Escalation Chain** | Risk-tiered escalation with SLA tracking | All agents |

### Risk Tiers

| Tier | Transaction Threshold | Required Action |
|------|----------------------|-----------------|
| **Low** | Below NGN 1M | Automated processing, logged |
| **Medium** | NGN 1M to NGN 5M | Enhanced monitoring, analyst review if flagged |
| **High** | NGN 5M to NGN 50M | Senior analyst review required |
| **Critical** | Above NGN 50M or sanctions match | Compliance officer + mandatory SAR assessment |

---

## Data Model

```sql
-- Customers
CREATE TABLE customers (
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

-- Transactions
CREATE TABLE transactions (
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

-- Alerts
CREATE TABLE alerts (
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

-- Sanctions Matches
CREATE TABLE sanctions_matches (
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

-- SARs (Suspicious Activity Reports)
CREATE TABLE sars (
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

-- Cases
CREATE TABLE cases (
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

-- Audit Trail (immutable log)
CREATE TABLE audit_trail (
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

-- Model Validation Log (CBN annual requirement)
CREATE TABLE model_validations (
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
```

---

## API Endpoints

```
# System
GET    /health                          Health check

# Transactions
POST   /transactions/screen             Screen a single transaction (full pipeline)
POST   /transactions/batch              Screen a batch of transactions
GET    /transactions                     List transactions (with filters)
GET    /transactions/{id}               Get transaction details with alerts

# Customers
GET    /customers                        List customers
GET    /customers/{id}                  Customer profile with risk history
POST   /customers/{id}/kyc              Trigger KYC verification
PUT    /customers/{id}/risk-tier        Update customer risk tier (requires approval)

# Alerts
GET    /alerts                           List alerts (with filters: status, severity, agent)
GET    /alerts/{id}                     Alert details with linked transactions
PUT    /alerts/{id}/assign              Assign alert to analyst
PUT    /alerts/{id}/resolve             Resolve alert (requires rationale)

# Sanctions
GET    /sanctions/screen                 Screen a name/entity against all lists
GET    /sanctions/matches                List all matches (with filters)
POST   /sanctions/matches/{id}/review   Review a sanctions match (approve/dismiss)

# SARs
GET    /sars                             List SARs (with filters)
GET    /sars/{id}                       SAR details
POST   /sars/{id}/approve               Approve SAR for filing (human decision, mandatory)
POST   /sars/{id}/reject                Reject SAR draft (with rationale)
POST   /sars/{id}/file                  File SAR with NFIU (post-approval)

# Cases
GET    /cases                            List cases
GET    /cases/{id}                      Case details with full history
PUT    /cases/{id}/status               Update case status
PUT    /cases/{id}/assign               Assign case

# Governance
GET    /governance/dashboard             Governance dashboard (stats, metrics)
GET    /governance/audit-trail           Full audit trail (with filters)
GET    /governance/audit-trail/{entity}  Audit trail for specific entity
GET    /governance/model-validation      Model validation history
POST   /governance/model-validation      Record a model validation

# Reporting
GET    /reports/daily                    Daily compliance summary
GET    /reports/weekly                   Weekly compliance report
GET    /reports/str-summary              STR filing summary
GET    /reports/alert-analytics          Alert analytics (volume, types, resolution)

# API (JSON for external integration)
GET    /api/stats                        Dashboard stats for integration
GET    /api/alerts/summary               Alert summary for integration
```

---

## File Structure

```
AgenticAML/
  src/
    __init__.py
    main.py                   # FastAPI app, routes, startup
    database.py               # SQLite/PostgreSQL setup, all CRUD
    models.py                 # Pydantic models
    agents/
      __init__.py
      transaction_monitor.py  # Agent 1: Rule-based screening
      kyc_verifier.py        # Agent 2: Identity verification
      sanctions_screener.py  # Agent 3: Sanctions/PEP screening
      pattern_analyzer.py    # Agent 4: LLM pattern detection
      sar_generator.py       # Agent 5: SAR drafting
      case_manager.py        # Agent 6: Case management
    governance/
      __init__.py
      engine.py              # Governance evaluation engine
      rules.py               # Configurable governance rules
      audit.py               # Audit trail logging
    data/
      __init__.py
      seed.py                # Demo data seeding
      sanctions_lists.py     # Simulated sanctions data
      sample_transactions.py # Sample transaction generator
  tests/
    __init__.py
    test_agents.py
    test_governance.py
    test_api.py
    test_database.py
  docs/
    architecture.svg         # System architecture diagram
    cbn_compliance_matrix.md # CBN requirement to feature mapping
  Dockerfile
  docker-compose.yml
  requirements.txt
  .env.example
  .github/
    workflows/
      ci.yml
  README.md
  SPEC.md
```

---

## Seed Data (Demo)

Generate realistic demo data for showcase:

### Customers (20 sample)
- Mix of individuals and businesses
- Various risk tiers (low, medium, high)
- Some with PEP status
- Some with incomplete KYC
- Nigerian names and addresses

### Transactions (200 sample)
- Variety of transaction types (transfer, cash_deposit, cash_withdrawal, international_wire, mobile_money)
- Various channels (branch, mobile_app, internet_banking, atm, pos)
- Range of amounts (NGN 10,000 to NGN 100,000,000)
- Include suspicious patterns:
  - Structuring (multiple transactions just below NGN 5M)
  - Rapid fund movement
  - Unusual geographic patterns
  - Dormant account sudden activity
  - Round amount transfers to high-risk jurisdictions

### Sanctions Lists (simulated)
- 50 sample entries across OFAC, UN, and domestic lists
- Include some near-matches to customer names (for fuzzy matching demo)

### Pre-Seeded Alerts and Cases
- 5-10 pre-processed transactions showing the full pipeline
- At least one SAR in draft status (awaiting human approval)
- At least one active investigation case
- Governance audit trail entries showing the complete decision chain

---

## Docker Configuration

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8003
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8003"]
```

```yaml
# docker-compose.yml
services:
  api:
    build: .
    ports:
      - "8003:8003"
    volumes:
      - aml_data:/app/data
    env_file:
      - .env
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8003/health')"]
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  aml_data:
    driver: local
```

---

## Requirements

```
fastapi==0.115.0
uvicorn[standard]==0.34.0
pydantic>=2.0
aiosqlite==0.21.0
python-dotenv==1.0.1
langchain>=0.3.0
langchain-openai>=0.3.0
python-multipart==0.0.18
httpx==0.28.1
```

---

## Important Build Notes

1. Database path: `/app/data/aml.db` (NOT inside src/). Volume mounts to `/app/data/` only.
2. All TemplateResponse calls: `templates.TemplateResponse(request=request, name="template.html", context=ctx)` (Starlette 1.0 compatibility)
3. No em dashes anywhere. Use commas, periods, colons instead.
4. All dates in WAT (West Africa Time, UTC+1) for Nigerian context.
5. Currency: Nigerian Naira (NGN) throughout.
6. Every agent must log to the audit trail before returning results.
7. The governance engine runs between every agent stage.
8. SAR approval is ALWAYS human-in-the-loop (never auto-approve).
9. Sanctions blocks are automatic (CBN mandate).
10. Port 8003 (different from FinanceRAG 8001, InvoiceIntelligence 8081, Nexus 8002).
11. OpenAI API key from OPENAI_API_KEY env var. If not set, agents should use rule-based logic only (no LLM calls) for demo mode.
