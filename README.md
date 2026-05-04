# AgenticAML (Sentinel)

**Full Customer Lifecycle AML Platform for Nigerian Financial Institutions**

AgenticAML is a governance-first, multi-agent AML system built to meet the [CBN Baseline Standards for Automated AML Solutions](https://www.cbn.gov.ng/Out/2026/CCD/CBN%20issues%20Baseline%20Standards%20for%20Automated%20Anti-Money%20Laundering%20Solution.pdf) (Circular BSD/DIR/PUB/LAB/019/002, March 10, 2026). Seven AI agents work together to screen new customers, monitor transactions, verify identities, detect patterns, draft SARs, and manage cases, with a governance engine enforcing 11 compliance controls at every stage.

**Live demo:** [sentinel.veristack.ca](https://sentinel.veristack.ca)

![Dashboard](docs/screenshots/dashboard.png)

## Why This Exists

On March 10, 2026, the Central Bank of Nigeria issued a directive requiring ALL regulated financial institutions to deploy automated AML systems. Banks have 18 months. Fintechs have 24 months. Every institution must submit an implementation roadmap by June 10, 2026.

Most existing AML solutions (Oracle FCCM, NICE Actimize, SAS AML) cost $500K to $2M+ to implement. AgenticAML provides the same capabilities at a fraction of the cost, purpose-built for the Nigerian regulatory context with governance embedded from the ground up.

## Architecture

![Architecture](docs/architecture.svg)

## Three-Layer Verification Framework

AgenticAML uses a three-layer verification architecture. Each layer operates independently and the system degrades gracefully when upstream layers are unavailable.

| Layer | What It Covers | Status |
|-------|---------------|--------|
| **Layer 3** | Watchlist Screening (OFAC, UN, PEP, Adverse Media) + Continuous Monitoring + Customer Pre-Screening | **Live** |
| **Layer 2** | KYC Identity Verification via YouVerify API (BVN, NIN, Address, CAC) | Hooks ready, activates with API key |
| **Layer 1** | Biometric Verification (fingerprint, liveness, document OCR) | Future, client-specific |

## The 7-Agent Pipeline

```
NEW CUSTOMER                           EXISTING CUSTOMER
     |                                        |
     v                                        |
[0. Onboarding Screener]                      |
     |                                        |
  Clear? ──yes──> Onboard ────────────────────+
     |                                        |
  Sanctions? ──> AUTO-BLOCK                   |
     |                                        |
  PEP/Adverse? ──> C-Suite Escalation         |
                                              v
                                    [1. Transaction Monitor]
                                              |
                                    [2. KYC Verifier]
                                              |
                                    [3. Watchlist Screener]
                                              |
                                    [4. Pattern Analyzer]
                                              |
                                    [5. SAR Generator]
                                              |
                                    [6. Case Manager]
                                              |
                                     Governance Engine
                                     (inline at EVERY stage)
```

### Agent 0: Onboarding Screener
Screens new customers against all watchlists before account activation. Clean customers are onboarded normally. Sanctions matches are auto-blocked (CBN mandate). PEP or adverse media matches escalate to C-suite or Head of Compliance for documented approval before the customer can transact.

### Agent 1: Transaction Monitor
Rule-based threshold screening with 8 detection parameters: cash/transfer thresholds, velocity burst detection, structuring, dormant account reactivation (6+ months inactive), round-tripping, cross-border concentration, new account rapid activity, and time-of-day anomalies. All thresholds are configurable via environment variables.

### Agent 2: KYC Verifier
Identity verification with BVN/NIN validation, customer data completeness checks, PEP status assessment, and risk tier assignment. Built with a provider abstraction layer: when YouVerify API is configured (Layer 2), it calls real identity APIs. Otherwise, it runs rule-based completeness checks.

### Agent 3: Watchlist Screener
Multi-list screening against OFAC SDN, UN Consolidated Sanctions, Nigerian domestic watchlist, PEP database, internal watchlist, and adverse media indicators. Uses fuzzy name matching with configurable thresholds. Results are categorized as sanctions, PEP, or adverse media with distinct match types (exact, strong, partial, weak).

### Agent 4: Pattern Analyzer
LLM-powered behavioral analysis that detects complex patterns rule-based systems miss: sudden changes in transaction volume, geographic anomalies, circular transaction patterns (layering), smurfing/structuring, shell company indicators, and PEP-related corruption patterns. Falls back to rule-based detection if the LLM is unavailable.

### Agent 5: SAR Generator
Drafts Suspicious Activity Reports in NFIU format with structured subject information, suspicious activity narrative, transaction details, typology mapping, and evidence packaging. SAR filing always requires mandatory human approval (agents draft, humans approve).

### Agent 6: Case Manager
Routes cases, tracks investigations, manages compliance workflows, and generates regulatory reports. Features include auto-assignment by risk tier, load balancing across compliance teams, SLA tracking with breach alerts, and daily/weekly/monthly compliance summaries.

## Governance Engine: The Differentiator

The governance engine runs **between every agent stage** and enforces 11 control gates:

| Gate | What It Does |
|------|-------------|
| **Confidence Gate** | Routes uncertain AI outputs (below 0.7) to human review |
| **Materiality Gate** | Requires additional review for transactions above NGN 50M |
| **Sanctions Block** | Auto-blocks confirmed sanctions matches immediately |
| **Human-in-the-Loop** | SAR filing always requires human approval |
| **Executive Escalation** | PEP/adverse media customer onboarding escalates to C-suite/MLRO |
| **Risk-Tiered Escalation** | Routes critical/high risk to appropriate compliance tier |
| **Segregation of Duties** | Monitoring, investigation, and reporting handled by different roles |
| **Immutable Audit Trail** | Every decision (agent and human) logged |
| **Continuous Monitoring** | Periodic re-screening of all customers against updated lists |
| **Onboarding Gate** | New customers screened before any transactions |
| **Annual Model Validation** | AI model accuracy, drift, bias, and fairness tracking |

Every gate evaluation (pass or fail) is logged. A passed gate is as important as a failed one, because it proves the control was evaluated.

## Executive Escalation Workflow

When a new customer matches a PEP or adverse media list during onboarding:

1. Customer account is flagged as pending escalation
2. An escalation record is created with evidence summary, match details, and SLA timer (default 24 hours)
3. The escalation appears in the dashboard and Escalation Queue for C-suite/Head of Compliance
4. The approver must provide a documented rationale when approving or rejecting
5. Approved customers are onboarded at a high-risk tier with enhanced monitoring
6. Rejected customers are blocked with a full audit trail
7. All escalation decisions are immutably logged

## Continuous Monitoring

AgenticAML doesn't just screen once. The continuous monitoring engine:

- Re-screens all existing customers against updated watchlists on a configurable schedule
- Detects new matches when a previously clean customer appears on a newly updated list
- Triggers automated alerts and risk tier upgrades when customer profiles change
- Tracks list versions with checksums for delta detection
- Logs every monitoring run with entities screened, new matches found, and risk upgrades

## AI Model Governance (CBN Section 9)

| Dimension | How Measured |
|-----------|-------------|
| **Accuracy** | Agent predictions vs. confirmed investigation outcomes |
| **Model Drift** | Current performance vs. deployment baseline (15% threshold triggers fallback) |
| **Bias** | Alert distribution across customer demographics, geography, naming conventions |
| **Fairness** | Equal false positive/negative rates across customer segments |

**Key design principle:** The primary decision pipeline is rule-based and deterministic. The LLM (GPT-4o) augments analysis with narrative reasoning but never overrides rules. If the LLM goes down, the system keeps running with zero loss of core AML capability.

## CBN Compliance Coverage

AgenticAML covers **~95% (43 of 46)** CBN directive requirements. Full compliance matrix: [docs/cbn_compliance_matrix.md](docs/cbn_compliance_matrix.md)

| CBN Section | Coverage |
|-------------|----------|
| Customer Identification (KYC) | 75% (biometrics are hardware-dependent) |
| Know Your Business (KYB) | 50% (document management is a production feature) |
| Risk Assessment and Profiling | **100%** |
| Sanctions and PEP Screening | **100%** |
| Transaction Monitoring | **100%** |
| Investigation and Case Management | **100%** |
| Regulatory Reporting | **100%** |
| Audit and Governance | **100%** |
| AI/ML Requirements | **100%** |

## Screenshots

### Dashboard
Real-time compliance overview with risk distribution, alert types, pending escalations, continuous monitoring status, and customer onboarding stats.

![Dashboard](docs/screenshots/dashboard.png)

### Transactions
161 monitored transactions with color-coded risk scores, filterable by status, channel, and risk tier.

![Transactions](docs/screenshots/transactions.png)

### SARs (Human Review)
Mandatory human-in-the-loop for SAR filing. Agents draft, humans approve. Every decision logged with rationale.

![SARs](docs/screenshots/sars.png)

### Governance
Full audit trail, model validation history with accuracy/drift/bias/fairness scores, and governance control status.

![Governance](docs/screenshots/governance.png)

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend | Python 3.12, FastAPI |
| Database | SQLite (demo), PostgreSQL (production) |
| Agent Framework | LangChain |
| LLM | OpenAI GPT-4o (configurable, optional) |
| Frontend | Next.js 16, TypeScript, Tailwind CSS, Recharts |
| Containerization | Docker, Docker Compose |
| CI/CD | GitHub Actions |
| Testing | pytest (174 tests) |
| Code Quality | ruff, mypy, bandit, semgrep |

## Quick Start

### Prerequisites
- Python 3.12+
- Node.js 18+
- OpenAI API key (optional, for LLM-augmented analysis)

### Backend

```bash
git clone https://github.com/Dewale-A/AgenticAML.git
cd AgenticAML

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configure (optional)
cp .env.example .env
# Edit .env to add OPENAI_API_KEY for LLM features
# Add YOUVERIFY_API_KEY to enable Layer 2 identity verification

# Run (database auto-seeds on first start)
DB_PATH=./data/aml.db uvicorn src.main:app --port 8003
```

API docs at `http://localhost:8003/docs`

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Dashboard at `http://localhost:3000`

### Docker

```bash
docker compose up -d
```

## API Endpoints (52 total)

<details>
<summary>Click to expand full API reference</summary>

### Customer Onboarding (Agent 0)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/customers/onboarding` | Onboarding queue with screening status |
| POST | `/customers/onboard` | Screen and onboard a new customer |
| GET | `/customers/{id}/onboarding-status` | Onboarding status with linked escalations |
| POST | `/customers/{id}/onboarding/approve` | Approve escalated onboarding (C-suite/MLRO) |
| POST | `/customers/{id}/onboarding/reject` | Reject escalated onboarding |

### Core Pipeline
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/transactions/screen` | Screen a transaction through the full pipeline |
| POST | `/transactions/batch` | Batch screen multiple transactions |

### Transactions
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/transactions` | List transactions (filterable) |
| GET | `/transactions/{id}` | Transaction details with linked alerts |

### Customers
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/customers` | List all customers |
| GET | `/customers/{id}` | Customer profile with risk history |
| POST | `/customers/{id}/kyc` | Trigger KYC verification |
| PUT | `/customers/{id}/risk-tier` | Update risk tier (requires approval) |

### Alerts
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/alerts` | Alert queue (filterable) |
| GET | `/alerts/{id}` | Alert details |
| PUT | `/alerts/{id}/assign` | Assign alert to analyst |
| PUT | `/alerts/{id}/resolve` | Resolve alert (requires rationale) |

### Watchlist Screening
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/sanctions/screen` | Screen a name against all lists |
| GET | `/sanctions/matches` | List all matches (filterable by category) |
| POST | `/sanctions/matches/{id}/review` | Review a match (approve/dismiss) |

### Escalations
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/escalations` | List all escalations |
| GET | `/escalations/pending` | Pending escalations with SLA status |
| GET | `/escalations/{id}` | Escalation details with evidence |
| POST | `/escalations/{id}/approve` | Approve (requires rationale) |
| POST | `/escalations/{id}/reject` | Reject (requires rationale) |

### SARs
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/sars` | List all SARs |
| GET | `/sars/{id}` | SAR details |
| POST | `/sars/{id}/approve` | Approve SAR for filing (human decision) |
| POST | `/sars/{id}/reject` | Reject SAR draft (with rationale) |
| POST | `/sars/{id}/file` | File approved SAR with NFIU |

### Cases
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/cases` | List cases |
| GET | `/cases/{id}` | Case details with full history |
| PUT | `/cases/{id}/status` | Update case status |
| PUT | `/cases/{id}/assign` | Assign case |

### Continuous Monitoring
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/monitoring/run` | Trigger manual re-screening run |
| GET | `/monitoring/status` | Current monitoring status |
| GET | `/monitoring/runs` | Monitoring run history |
| GET | `/monitoring/runs/{id}` | Run details with audit trail |
| GET | `/screening-lists` | Screening list versions and checksums |
| POST | `/screening-lists/update` | Refresh all screening lists |

### Governance
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/governance/dashboard` | Governance stats, controls, metrics |
| GET | `/governance/audit-trail` | Full audit trail (filterable) |
| GET | `/governance/model-validation` | Model validation history |
| POST | `/governance/model-validation` | Record a model validation |

### Reporting
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/reports/daily` | Daily compliance summary |
| GET | `/reports/weekly` | Weekly compliance report |
| GET | `/reports/str-summary` | STR filing summary |
| GET | `/reports/alert-analytics` | Alert analytics |

</details>

## Seed Data

The system auto-seeds with realistic demo data on first run:

- **20 customers**: Mix of individuals and businesses, various risk tiers, some PEPs, some with incomplete KYC, dormant accounts. Nigerian names and context.
- **161 transactions**: Transfers, cash deposits/withdrawals, international wires, mobile money. Amounts from NGN 10K to NGN 100M. Includes suspicious patterns: structuring, rapid movement, geographic anomalies, dormant account reactivation.
- **9 alerts**: Generated by the agent pipeline, various severities and types.
- **3 SARs**: One pending approval (human review required), one approved and filed with NFIU, one rejected with rationale.
- **5 cases**: Active investigations at different stages.
- **3 escalations**: One pending (PEP match), one approved with rationale, one rejected.
- **3 monitoring runs**: Showing progression of continuous re-screening.
- **4 screening lists**: OFAC, UN, Nigerian domestic, internal PEP with version tracking.
- **Audit trail**: Full governance decision chain showing agent decisions, gate evaluations, and human actions.
- **Model validations**: Three AI models validated with accuracy, drift, bias, and fairness scores.

## Project Structure

```
AgenticAML/
  src/
    main.py                      FastAPI app, 52 endpoints
    database.py                  Database setup, all CRUD operations
    models.py                    Pydantic models
    agents/
      onboarding_screener.py     Agent 0: Pre-transaction customer screening
      transaction_monitor.py     Agent 1: 8-parameter threshold screening
      kyc_verifier.py            Agent 2: Identity verification (YouVerify ready)
      sanctions_screener.py      Agent 3: Multi-list watchlist screening
      pattern_analyzer.py        Agent 4: LLM-powered pattern detection
      sar_generator.py           Agent 5: SAR/STR drafting
      case_manager.py            Agent 6: Case management
    governance/
      engine.py                  Governance evaluation engine (11 gates)
      rules.py                   Configurable regulatory thresholds
      audit.py                   Immutable audit trail logging
      escalation.py              Executive escalation workflow
    monitoring/
      continuous_monitor.py      Scheduled customer re-screening
      list_manager.py            Screening list download and versioning
    data/
      seed.py                    Demo data generation
      sanctions_lists.py         Simulated sanctions databases
      sample_transactions.py     Transaction generator
  frontend/
    src/
      app/                       Next.js App Router
      components/
        Dashboard.tsx            Overview with escalation/monitoring widgets
        CustomerOnboarding.tsx   Agent 0 UI: screening form, queue, SLA
        Transactions.tsx         Transaction monitoring
        Alerts.tsx               Alert queue and management
        WatchlistScreening.tsx   Sanctions/PEP/Adverse Media screening
        SARs.tsx                 Human-in-the-loop SAR approval
        EscalationPanel.tsx      C-Suite/MLRO approval panel
        Cases.tsx                Investigation management
        Governance.tsx           Audit trail and model validation
  scripts/
    review-pipeline.sh           Automated code quality review (ruff, mypy, bandit, semgrep, hey)
  tests/                         174 pytest tests
  docs/
    architecture.svg             System architecture diagram
    cbn_compliance_matrix.md     CBN requirement mapping (~95% coverage)
    ROADMAP.md                   Enhancement roadmap
```

## Code Quality Pipeline

Every build is reviewed with enterprise-grade static analysis:

```bash
# Standard review (lint + type check + security + tests)
./scripts/review-pipeline.sh

# Auto-fix safe lint issues
./scripts/review-pipeline.sh --fix

# Full review including concurrent load tests (requires running server)
./scripts/review-pipeline.sh --load-test
```

Tools: ruff (async/security rules), mypy (type checking), bandit (security scanning), semgrep (pattern analysis), hey (HTTP load testing).

## Production Considerations

For production deployment at a financial institution:

1. **Database**: Migrate from SQLite to PostgreSQL with connection pooling
2. **Authentication**: Add RBAC (analyst, senior analyst, compliance officer, MLRO roles)
3. **Identity Verification**: Set YOUVERIFY_API_KEY to activate Layer 2 (BVN/NIN/PEP)
4. **Biometrics**: Integrate with biometric SDK for Layer 1 (Smile Identity, Veriff)
5. **CORS**: Lock down allowed origins (currently wildcard for development)
6. **Encryption**: TLS for all API communication, encryption at rest for PII
7. **Monitoring**: Structured logging, Prometheus metrics, Grafana dashboards
8. **High Availability**: Multi-instance deployment behind a load balancer
9. **Data Retention**: 5-year minimum for audit trail records (NFIU requirement)

## Regulatory References

- [CBN Baseline Standards for Automated AML Solutions](https://www.cbn.gov.ng/Out/2026/CCD/CBN%20issues%20Baseline%20Standards%20for%20Automated%20Anti-Money%20Laundering%20Solution.pdf) (March 2026)
- Money Laundering (Prevention and Prohibition) Act 2022
- FATF Recommendations (40 Recommendations)
- CBN AML/CFT/CPF Guidelines
- NFIU STR Filing Requirements

## License

This project is licensed under the [Business Source License 1.1](LICENSE).

**Free for:** evaluation, testing, academic research, personal use, and contributing improvements.

**Commercial use** (production deployment for revenue-generating activities) requires a commercial license from VeriStack. Contact aderonmu.ad@gmail.com for licensing inquiries.

The licensed work converts to Apache License 2.0 on April 27, 2030.

---

**Built by [VeriStack](https://veristack.ca)** | Innovate Boldly, Scale Securely.
