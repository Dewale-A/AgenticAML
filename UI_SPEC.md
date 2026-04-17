# AgenticAML Frontend Dashboard Specification

## Overview
A professional SaaS-style dashboard for the AgenticAML backend API. Built with Next.js + Tailwind CSS, deployed on Vercel. Connects to the FastAPI backend at the configured API URL.

## Tech Stack
- Next.js 14+ (App Router)
- Tailwind CSS
- TypeScript
- Recharts (for charts/visualizations)
- Lucide React (for icons)

## Design
- Dark theme (slate-900 background, slate-800 cards, slate-700 borders)
- Nigerian financial services context
- Professional, clean, governance-focused
- Mobile responsive
- VeriStack branding in footer: "Powered by VeriStack | veristack.ca"

## Pages/Tabs (Single Page Application with Tab Navigation)

### Tab 1: Dashboard (Default)
- **Stats row:** Total Transactions, Flagged, Open Alerts, Pending SARs, Open Cases, Avg Confidence
- **Risk distribution chart:** Donut chart showing transactions by risk tier (low/medium/high/critical)
- **Alert trend chart:** Bar chart showing alerts by type
- **Recent alerts list:** Last 5 alerts with severity badges
- **Regulatory alignment indicators:** FATF, CBN, NFIU compliance status

### Tab 2: Transactions
- **Transaction table:** Sortable, filterable list of all transactions
- Columns: ID, Customer, Amount (NGN), Type, Channel, Risk Score, Status, Timestamp
- Color-coded risk scores (green/yellow/orange/red)
- Click to expand: shows full transaction details + linked alerts
- Filter by: status, risk tier, channel, date range

### Tab 3: Alerts
- **Alert queue:** List of all alerts with severity badges
- Columns: Alert ID, Customer, Type, Severity, Agent Source, Status, Created
- Filter by: status (open/investigating/resolved), severity, agent source
- Click to expand: alert details, linked transaction, recommended action
- Action buttons: Assign, Investigate, Resolve (with rationale)

### Tab 4: Sanctions
- **Sanctions matches:** List of all matches with match type and score
- Columns: Customer, Matched Entity, List, Match Type, Score, Action, Reviewed By
- Match type badges: exact (red), strong (orange), partial (yellow), weak (gray)
- Action buttons: Block, Review, Dismiss

### Tab 5: SARs (Human Review)
- **SAR queue:** List of all SARs with status
- Columns: SAR ID, Customer, Typology, Priority, Status, Drafted By, Approved By
- Status flow: draft > approved > filed (or rejected)
- Click to expand: full SAR narrative, evidence summary
- **Approve/Reject buttons with mandatory rationale field**
- Filed SARs show NFIU reference number
- "HUMAN APPROVAL REQUIRED" banner on pending SARs

### Tab 6: Cases
- **Case management:** List of all cases
- Columns: Case ID, Customer, Type, Priority, Status, Assigned To, SLA
- Priority badges: critical (red), high (orange), medium (yellow), low (gray)
- SLA countdown (time remaining before SLA breach)
- Status flow: open > investigating > pending_review > closed

### Tab 7: Governance
- **Audit trail:** Searchable, filterable audit log
- Columns: Timestamp, Entity Type, Event Type, Actor, Description
- Filter by: entity type, event type, actor, date range
- **Model validation history:** Table of model validation records
- Shows: accuracy, drift, bias, fairness scores
- CBN compliance badge: "Annual Validation: Compliant"

## Navigation
- Sticky top nav bar with AgenticAML logo/name on left
- Tab buttons in the center
- "CBN Compliant" badge on the right
- Dark theme consistent throughout

## API Proxy
- Use Next.js API routes as proxy to backend
- Backend URL configurable via API_URL environment variable
- Default: http://localhost:8003

## File Structure
```
frontend/
  src/
    app/
      layout.tsx
      page.tsx
      globals.css
      api/
        proxy/
          route.ts
    components/
      Header.tsx
      TabNav.tsx
      Dashboard.tsx
      Transactions.tsx
      Alerts.tsx
      Sanctions.tsx
      SARs.tsx
      Cases.tsx
      Governance.tsx
      charts/
        RiskDistribution.tsx
        AlertTrend.tsx
      ui/
        Badge.tsx
        Card.tsx
        Table.tsx
        Modal.tsx
  package.json
  tailwind.config.ts
  tsconfig.json
  next.config.js
  .env.example
```

## Important Notes
- All amounts displayed in NGN (Nigerian Naira) with proper formatting
- Dates displayed in WAT (West Africa Time, UTC+1)
- The SARs tab must prominently show that human approval is mandatory (CBN requirement)
- Demo mode banner at top if DEMO_MODE env var is set
- Footer: "AgenticAML v1.0 | Governance-First AML Compliance | Powered by VeriStack"
- No em dashes in any text
