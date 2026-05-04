# AgenticAML (Sentinel) — Enhancement Roadmap v2

*Last updated: 2026-05-04*
*Source: Contact feedback session + data provider research*

---

## Overview

This roadmap transforms Sentinel from a transaction monitoring tool into a **full customer lifecycle AML platform** with a 3-layer verification framework, expanded screening pipeline, and executive escalation workflows.

All enhancements align with CBN Baseline Standards for Automated AML Solutions (March 2026).

---

## 1. Three-Layer Verification Framework

Sentinel's verification capabilities are organized into three layers. Each layer can be deployed independently, and the system degrades gracefully when upstream layers are unavailable.

### Layer 3: Watchlist Screening + Continuous Monitoring (NOW, no dependencies)

**Status:** Build immediately. No external API dependencies required.

**What it covers:**
- Sanctions screening against free, downloadable lists (OFAC SDN, UN Consolidated, Nigerian domestic)
- PEP screening against locally maintained database
- Adverse media indicator checks
- Continuous monitoring of customer risk profiles post-onboarding
- Periodic re-screening of all customers against updated lists
- Alert generation when a previously clean customer appears on a new list

**Data sources (all free, no API required):**
- OFAC SDN List: Bulk download (XML/CSV/JSON), no auth needed, updated several times per month
- UN Consolidated Sanctions List: Download (XML/PDF), available in 6 languages
- OpenSanctions: Open-source aggregator of 40+ global sanctions and PEP datasets. Pay-as-you-go API or self-hosted
- Nigerian domestic watchlist: Manually curated from CBN circulars and NFIU notices

**Continuous monitoring framework:**
- Scheduled re-screening job (configurable: daily, weekly, or on list update)
- Delta detection: compare current customer base against newly added list entries
- Risk score recalculation when customer profile changes or new transactions post
- Automated alerts for risk tier upgrades (e.g., customer newly matched to PEP list)
- Dashboard widget: "Continuous Monitoring Status" showing last run, entities screened, new matches

**New database tables:**
```sql
-- Continuous monitoring runs
CREATE TABLE monitoring_runs (
    id TEXT PRIMARY KEY,
    run_type TEXT NOT NULL,          -- 'scheduled', 'manual', 'list_update'
    started_at TEXT NOT NULL,
    completed_at TEXT,
    customers_screened INTEGER DEFAULT 0,
    new_matches INTEGER DEFAULT 0,
    risk_upgrades INTEGER DEFAULT 0,
    status TEXT DEFAULT 'running',   -- 'running', 'completed', 'failed'
    metadata TEXT                    -- JSON: list versions used, config snapshot
);

-- List version tracking
CREATE TABLE screening_lists (
    id TEXT PRIMARY KEY,
    list_name TEXT NOT NULL,         -- 'ofac_sdn', 'un_consolidated', 'nigerian_domestic', 'internal_pep'
    version TEXT,
    last_updated TEXT NOT NULL,
    entry_count INTEGER DEFAULT 0,
    source_url TEXT,
    checksum TEXT                    -- SHA-256 of list file for change detection
);
```

**New API endpoints:**
```
POST   /monitoring/run                   Trigger manual re-screening run
GET    /monitoring/runs                  List monitoring run history
GET    /monitoring/runs/{id}            Details of a specific run
GET    /monitoring/status                Current monitoring status and schedule
PUT    /monitoring/config                Update monitoring schedule/config
GET    /screening-lists                  List all screening lists with versions
POST   /screening-lists/update           Trigger list update (download latest)
```

### Layer 2: KYC Identity Verification via YouVerify (WHEN ACTIVATED)

**Status:** Build integration hooks now. Activate when YouVerify API access is provisioned.

**What it covers:**
- BVN (Bank Verification Number) validation via YouVerify API
- NIN (National Identification Number) validation
- Enhanced PEP screening with Nigerian-specific depth (state governors, LGA officials, military brass)
- Address verification
- Phone number verification
- Business registration verification (CAC)

**YouVerify API integration points:**
- PEP and Sanction Screening: `POST /v2/api/identity/ng/pep-sanction`
- BVN Verification: `POST /v2/api/identity/ng/bvn`
- NIN Verification: `POST /v2/api/identity/ng/nin`
- Address Verification: `POST /v2/api/identity/ng/address`
- Business (CAC) Lookup: `POST /v2/api/identity/ng/cac`

**Architecture changes:**
- KYC Verifier agent (Agent 2) gains a provider abstraction layer
- When YouVerify is configured (API key present), agent calls real API
- When YouVerify is unavailable, agent falls back to rule-based completeness checks (current behavior)
- All API responses cached locally for audit trail compliance
- Rate limiting: respect YouVerify API limits, queue excess requests

**Configuration:**
```env
YOUVERIFY_API_KEY=           # When set, enables Layer 2
YOUVERIFY_BASE_URL=https://api.youverify.co
YOUVERIFY_SANDBOX=true       # Use sandbox for testing
```

**New database table:**
```sql
-- External verification results (YouVerify and future providers)
CREATE TABLE identity_verifications (
    id TEXT PRIMARY KEY,
    customer_id TEXT REFERENCES customers(id),
    provider TEXT NOT NULL,           -- 'youverify', 'smile_id', etc.
    verification_type TEXT NOT NULL,  -- 'bvn', 'nin', 'pep', 'address', 'cac'
    request_payload TEXT,             -- JSON (sanitized, no raw PII)
    response_status TEXT,             -- 'verified', 'failed', 'partial', 'error'
    confidence_score REAL,
    raw_response TEXT,                -- Encrypted JSON
    verified_at TEXT DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT                   -- Re-verification needed after this date
);
```

### Layer 1: Biometric Verification (FUTURE, client-specific)

**Status:** Spec only. Implementation depends on client hardware and regulatory requirements.

**What it covers:**
- Fingerprint capture and matching (BVN-linked biometric database)
- Facial recognition / liveness detection
- Document OCR (passport, driver license, voter card, NIN slip)
- Photo matching (document photo vs. live capture)

**Why it is future:**
- Requires physical hardware (fingerprint scanners, cameras) at client sites
- SDK integration with biometric providers (e.g., Smile Identity, Veriff)
- Client-specific: not all institutions need this (e.g., digital-only banks may use selfie-based liveness instead of fingerprint)
- Regulatory requirement is at the institution level, not mandated for AML software

**Architecture placeholder:**
- `BiometricProvider` interface in Agent 2 (KYC Verifier)
- Provider implementations: `SmileIdentityProvider`, `VeriffProvider`, `ManualProvider`
- All biometric results feed into the same `identity_verifications` table

---

## 2. UI Rename: "Sanctions" Tab to "Watchlist Screening"

**Rationale:** The current "Sanctions" tab only implies sanctions list matching. In practice, it covers Sanctions, PEP, and Adverse Media screening. "Watchlist Screening" is the industry-standard term used by compliance officers and maps directly to CBN terminology.

**Changes required:**

### Frontend
- Rename Tab 4 from "Sanctions" to "Watchlist Screening" in `TabNav.tsx`
- Update `Sanctions.tsx` component to `WatchlistScreening.tsx`
- Add sub-categories within the tab:
  - **Sanctions Matches** (OFAC, UN, domestic)
  - **PEP Matches** (politically exposed persons)
  - **Adverse Media** (negative news, legal proceedings)
- Each sub-category gets a filter toggle and distinct badge color
- Sanctions matches: red badge
- PEP matches: orange badge
- Adverse media: yellow badge

### Backend
- Add `match_category` field to `sanctions_matches` table: `sanctions`, `pep`, `adverse_media`
- Update API response to include `match_category` in all screening results
- New filter parameter: `GET /sanctions/matches?category=pep`
- Rename API namespace consideration: keep `/sanctions/` for backward compatibility, add alias `/watchlist/` that routes to the same handlers

### Data Model Addition
```sql
ALTER TABLE sanctions_matches ADD COLUMN match_category TEXT DEFAULT 'sanctions';
-- Values: 'sanctions', 'pep', 'adverse_media'
```

---

## 3. Enhanced Transaction Monitoring Parameters

**Rationale:** The current Transaction Monitor agent checks thresholds, velocity, structuring, and round amounts. Contact feedback requests expanded parameters, especially dormant account detection.

### New Parameters for Agent 1 (Transaction Monitor)

| Parameter | Description | Threshold | CBN Ref |
|-----------|------------|-----------|---------|
| **Dormant account reactivation** | Account inactive for 6+ months suddenly transacting | Configurable (default: 180 days) | CBN AML/CFT Guidelines, Section 4 |
| **Velocity burst detection** | Sudden spike in transaction frequency vs. 90-day baseline | >3x baseline in 24hr window | Risk Assessment Section |
| **Cross-border concentration** | High percentage of transactions to/from high-risk jurisdictions | >30% of monthly volume | FATF Rec 16 |
| **Round-tripping detection** | Funds leaving and returning to same account via intermediaries | Pattern match within 30-day window | Transaction Monitoring Section |
| **Structuring (enhanced)** | Multiple transactions just below reporting threshold within 48hr | Aggregate exceeds threshold | Section 5 (CTR) |
| **New account rapid activity** | High transaction volume within first 30 days of account opening | >10 transactions or >NGN 5M in first 30 days | Risk Assessment Section |
| **Counterparty risk scoring** | Transactions with counterparties flagged by other agents | Any flagged counterparty | Sanctions Section |
| **Time-of-day anomaly** | Transactions outside customer's established pattern | Statistical deviation from 90-day pattern | Pattern Analysis |

### Dormant Account Detection (Priority)

**Definition:** An account with no debit or credit transactions for a configurable period (default: 180 days, per CBN guidelines on dormant accounts).

**Implementation:**
```python
# In transaction_monitor.py
def check_dormant_reactivation(self, customer_id: str, transaction: dict) -> dict:
    """
    Flag transactions on accounts that have been dormant.
    CBN considers an account dormant after 6 months of inactivity.
    Reactivation with immediate high-value transactions is a
    significant money laundering red flag.
    """
    last_activity = self.db.get_last_transaction_date(customer_id)
    if last_activity is None:
        return {"rule": "dormant_reactivation", "triggered": False}

    days_inactive = (now - last_activity).days
    if days_inactive >= self.config.dormant_threshold_days:
        return {
            "rule": "dormant_reactivation",
            "triggered": True,
            "severity": "high" if days_inactive > 365 else "medium",
            "days_inactive": days_inactive,
            "description": f"Account reactivated after {days_inactive} days of inactivity"
        }
    return {"rule": "dormant_reactivation", "triggered": False}
```

**Database changes:**
```sql
-- Track account activity windows for dormant detection
ALTER TABLE customers ADD COLUMN last_transaction_at TEXT;
ALTER TABLE customers ADD COLUMN is_dormant INTEGER DEFAULT 0;
ALTER TABLE customers ADD COLUMN dormant_since TEXT;
```

**Configuration:**
```env
DORMANT_THRESHOLD_DAYS=180      # CBN standard: 6 months
DORMANT_REACTIVATION_SEVERITY=high
NEW_ACCOUNT_WINDOW_DAYS=30
NEW_ACCOUNT_TXN_THRESHOLD=10
NEW_ACCOUNT_AMOUNT_THRESHOLD=5000000  # NGN 5M
```

---

## 4. Customer Onboarding Pipeline (New Customer Pre-Screening)

**Rationale:** Contact feedback: screen new customers against watchlists BEFORE they can transact. This is standard for any production AML platform and maps to CBN KYC requirements for customer acceptance.

### New Agent: Customer Onboarding Screener (Agent 0)

This agent sits BEFORE the existing 6-agent pipeline and acts as a gateway for new customer registration.

**Pipeline flow (updated):**

```
NEW CUSTOMER REGISTRATION
         |
         v
  [Agent 0: Onboarding Screener]
         |
    +---------+---------+
    |                   |
  CLEAR              MATCH FOUND
    |                   |
    v                   v
  Onboard         Match Category?
  Customer              |
    |            +------+------+
    |            |             |
    v         SANCTIONS     PEP/ADVERSE
  Enter        (Block)      MEDIA
  Normal          |             |
  Pipeline        v             v
    |          Reject +      Escalate to
    |          Audit Log     C-Suite /
    |                       Head of Compliance
    v                           |
  [Existing 6-Agent             v
   Transaction Pipeline]    APPROVE    REJECT
                              |          |
                              v          v
                          Onboard    Reject +
                          (High-Risk  Audit Log
                           Tier) +
                           Enhanced
                           Monitoring
```

**For existing customers:**
- Normal transaction monitoring pipeline (no change)
- Continuous monitoring (Layer 3) handles periodic re-screening

**Agent 0 Specification:**

**Purpose:** Screen new customers against all watchlists before account activation. Determine if customer can be onboarded, needs escalation, or must be rejected.

**Inputs:**
- Customer registration data: name, aliases, date_of_birth, nationality, BVN, NIN, address, account_type
- Registration source: branch, online, mobile, agent

**Processing:**
1. Screen customer name (and aliases) against all watchlists (Layer 3 lists)
2. If YouVerify is active (Layer 2), also run enhanced PEP/sanctions screening
3. Classify match result:
   - **No match:** Clear for onboarding, assign initial risk tier
   - **Sanctions match (confirmed/strong):** Block onboarding, generate alert, notify compliance
   - **PEP match:** Flag for C-suite/Head of Compliance approval before onboarding
   - **Adverse media match:** Flag for senior compliance review before onboarding
   - **Weak/partial match:** Flag for analyst review, can proceed with enhanced monitoring

**Outputs:**
- Onboarding decision: `approved`, `pending_review`, `pending_escalation`, `blocked`
- Risk tier assignment for approved customers
- Escalation record (if applicable) with required approver level
- Audit trail entry

**Governance controls:**
- Sanctions block is automatic and mandatory (CBN)
- PEP onboarding requires documented C-suite or Head of Compliance approval
- All onboarding decisions logged to audit trail regardless of outcome
- Cannot override a sanctions block without Head of Compliance + documented exception rationale

### Executive Escalation Workflow

**New table:**
```sql
CREATE TABLE escalations (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,       -- 'customer_onboarding', 'transaction', 'case'
    entity_id TEXT NOT NULL,         -- customer_id, transaction_id, or case_id
    escalation_reason TEXT NOT NULL, -- 'pep_match', 'adverse_media', 'high_risk_jurisdiction', etc.
    required_approver_role TEXT NOT NULL, -- 'head_of_compliance', 'c_suite', 'mlro', 'senior_analyst'
    current_status TEXT DEFAULT 'pending', -- 'pending', 'approved', 'rejected', 'expired'
    assigned_to TEXT,                -- Name/ID of the approver
    decision_rationale TEXT,         -- Required when approving or rejecting
    evidence_summary TEXT,           -- JSON: match details, screening results
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    decided_at TEXT,
    expires_at TEXT,                 -- Escalations must be resolved within SLA
    sla_hours INTEGER DEFAULT 24    -- Default: 24-hour resolution SLA
);
```

**New API endpoints:**
```
# Customer Onboarding
POST   /customers/onboard               Screen and onboard a new customer
GET    /customers/onboard/{id}/status   Check onboarding screening status
POST   /customers/onboard/{id}/approve  Approve escalated onboarding (C-suite/MLRO)
POST   /customers/onboard/{id}/reject   Reject escalated onboarding (with rationale)

# Escalations
GET    /escalations                      List all escalations (filterable by status, role)
GET    /escalations/{id}                Escalation details with evidence
POST   /escalations/{id}/approve        Approve (requires rationale)
POST   /escalations/{id}/reject         Reject (requires rationale)
GET    /escalations/pending             Pending escalations for current user's role
```

### UI Changes for Onboarding

**New Tab: "Customer Onboarding" (or add as sub-view under Customers)**
- Onboarding queue: list of customers pending screening or awaiting approval
- Status badges: Screening, Clear, Pending Approval, Blocked, Approved (High-Risk)
- Escalation panel: shows match details, evidence, approve/reject buttons with mandatory rationale
- SLA countdown timer on pending escalations

**Escalation Dashboard Widget (on main Dashboard):**
- "Pending Escalations" card showing count by type (PEP, Adverse Media, High-Risk)
- SLA breach indicator (red if any escalation past deadline)
- Quick-approve buttons for authorized users

---

## 5. Updated Architecture Diagram

The architecture diagram needs to reflect:
1. Agent 0 (Onboarding Screener) before the existing pipeline
2. Two pipeline paths: New Customer vs. Existing Customer
3. Executive escalation workflow
4. 3-layer verification framework visualization
5. Continuous monitoring loop
6. "Watchlist Screening" nomenclature (not "Sanctions")

---

## 6. Updated File Structure

```
AgenticAML/
  src/
    agents/
      onboarding_screener.py    # NEW: Agent 0 - Customer onboarding screening
      transaction_monitor.py    # UPDATED: Enhanced parameters (dormant, velocity, etc.)
      kyc_verifier.py           # UPDATED: Provider abstraction for YouVerify
      sanctions_screener.py     # UPDATED: Match categories, continuous monitoring
      pattern_analyzer.py       # No change
      sar_generator.py          # No change
      case_manager.py           # No change
    governance/
      engine.py                 # UPDATED: Onboarding gate, escalation routing
      rules.py                  # UPDATED: New thresholds
      audit.py                  # No change
      escalation.py             # NEW: Executive escalation workflow
    monitoring/
      __init__.py               # NEW
      continuous_monitor.py     # NEW: Scheduled re-screening engine
      list_manager.py           # NEW: Download and version screening lists
      scheduler.py              # NEW: Cron-like scheduling for monitoring runs
    providers/
      __init__.py               # NEW
      youverify.py              # NEW: YouVerify API client (Layer 2)
      biometric.py              # NEW: Biometric provider interface (Layer 1 stub)
    data/
      seed.py                   # UPDATED: New customer onboarding scenarios, dormant accounts
      sanctions_lists.py        # UPDATED: Match categories
  frontend/
    src/
      components/
        WatchlistScreening.tsx  # RENAMED from Sanctions.tsx
        CustomerOnboarding.tsx  # NEW: Onboarding queue and escalation UI
        EscalationPanel.tsx     # NEW: Approve/reject with rationale
        ContinuousMonitoring.tsx # NEW: Monitoring dashboard widget
```

---

## 7. Seed Data Updates

Add to the demo seed data:

### New Customer Onboarding Scenarios
- 3 clean customers (auto-approved, low/medium risk)
- 1 customer with PEP match (pending C-suite approval)
- 1 customer with sanctions match (auto-blocked)
- 1 customer with adverse media match (pending review)
- 1 customer approved by Head of Compliance with documented rationale

### Dormant Account Scenarios
- 2 customers with dormant accounts (inactive 8+ months)
- 1 dormant account with sudden high-value reactivation (flagged)
- 1 dormant account with gradual reactivation (lower risk)

### Escalation Records
- 2 pending escalations (one PEP, one adverse media)
- 1 approved escalation with rationale from Head of Compliance
- 1 rejected escalation with documented reason

### Continuous Monitoring History
- 3 completed monitoring runs showing progression
- 1 monitoring run that detected a new PEP match on an existing customer

---

## 8. Implementation Priority

### Phase 1: Quick Wins (This Sprint)
1. **Rename Sanctions tab to Watchlist Screening** (frontend only, 1-2 hours)
2. **Add `match_category` to sanctions_matches** (backend schema + API, 2-3 hours)
3. **Dormant account detection** in Transaction Monitor (backend, 3-4 hours)
4. **Enhanced transaction parameters** (velocity burst, new account rapid activity) (backend, 4-5 hours)

### Phase 2: Core Pipeline Enhancement (Next Sprint)
5. **Agent 0: Onboarding Screener** (new agent + API endpoints, 1-2 days)
6. **Executive escalation workflow** (database + API + governance engine update, 1 day)
7. **Customer Onboarding UI** (frontend tab/view, 1 day)
8. **Escalation panel UI** (approve/reject with rationale, half day)

### Phase 3: Continuous Monitoring (Following Sprint)
9. **Continuous monitoring engine** (scheduler + re-screening logic, 1-2 days)
10. **List management system** (download, version, delta detection, 1 day)
11. **Monitoring dashboard widgets** (frontend, half day)
12. **Updated seed data** for all new scenarios (half day)

### Phase 4: YouVerify Integration (When API Active)
13. **YouVerify API client** (provider abstraction, API calls, error handling, 1-2 days)
14. **KYC Verifier agent update** (swap in YouVerify when configured, 1 day)
15. **Enhanced PEP screening** with Nigerian-specific data, half day)

### Future: Layer 1 Biometric
16. **Biometric provider interface** (spec + stub implementation)
17. **Smile Identity or Veriff integration** (when client requires)

---

## 9. CBN Compliance Impact

These enhancements move Sentinel's CBN compliance from **90% to ~95%:**

| CBN Section | Before | After | Change |
|-------------|--------|-------|--------|
| Customer Identification (KYC) | 60% | 75% | +15% (YouVerify integration hooks, onboarding screening) |
| Know Your Business (KYB) | 38% | 50% | +12% (CAC verification via YouVerify) |
| Risk Assessment & Profiling | 100% | 100% | (maintained, enhanced parameters) |
| Sanctions & PEP Screening | 100% | 100% | (maintained, better categorization) |
| Transaction Monitoring | 100% | 100% | (maintained, expanded parameters) |
| Investigation & Case Management | 100% | 100% | (maintained, escalation workflow added) |
| Regulatory Reporting | 100% | 100% | (maintained) |
| Audit & Governance | 100% | 100% | (maintained, continuous monitoring audit) |
| AI/ML Requirements | 100% | 100% | (maintained) |

**Remaining gaps (5%):** Biometric verification hardware (Layer 1), full document management system, multi-language support.

---

## 10. Key Design Principles

1. **Graceful degradation:** Each layer works independently. If YouVerify is down, Layer 3 screening still runs. If biometrics are unavailable, KYC still works via document verification.

2. **Audit everything:** Every onboarding decision, escalation, approval, rejection, and monitoring run is logged to the immutable audit trail.

3. **Sanctions blocks are automatic:** CBN mandates immediate blocking of confirmed sanctions matches. No human can override without Head of Compliance approval and documented exception.

4. **PEP onboarding requires senior approval:** This is a regulatory requirement, not a suggestion. The system enforces it.

5. **Configurable thresholds:** All numeric thresholds (dormant days, velocity multipliers, amount limits) are environment-configurable, not hardcoded.

6. **Provider abstraction:** Identity verification, biometric checks, and screening data sources are all behind provider interfaces. Swapping YouVerify for Smile ID or adding ComplyAdvantage later requires only a new provider implementation, not agent rewrites.

---

*This roadmap is a living document. Update as contact feedback evolves and implementation progresses.*
