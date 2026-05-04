// Main dashboard tab - KPI stats, charts, recent alerts, regulatory compliance.
// v2 additions: Pending Escalations widget, Continuous Monitoring widget, Customer Onboarding widget.
'use client'
import { useEffect, useState } from 'react'
import { ArrowLeftRight, Bell, FileText, Briefcase, TrendingUp, CheckCircle, AlertTriangle, UserPlus, RefreshCw, Activity, Clock } from 'lucide-react'
import { StatCard } from './ui/Card'
import Card from './ui/Card'
import RiskDistribution from './charts/RiskDistribution'
import AlertTrend from './charts/AlertTrend'
import { SeverityBadge, StatusBadge, Badge } from './ui/Badge'
import { CustomerMap, getCustomerMap, formatCustomer } from '@/lib/customerLookup'

// Fetch helper - uses the Next.js API proxy to avoid CORS
async function fetchAPI(path: string, query?: string) {
  const params = new URLSearchParams({ path })
  if (query) params.set('query', query)
  const res = await fetch(`/api/proxy?${params}`)
  if (!res.ok) throw new Error(`API error ${res.status}`)
  return res.json()
}

// Format NGN currency
function formatNGN(amount: number) {
  return new Intl.NumberFormat('en-NG', { style: 'currency', currency: 'NGN', maximumFractionDigits: 0 }).format(amount)
}

// Format date in WAT (UTC+1)
function formatWAT(isoDate: string) {
  return new Date(isoDate).toLocaleString('en-NG', { timeZone: 'Africa/Lagos', dateStyle: 'short', timeStyle: 'short' })
}

interface Stats {
  total_transactions: number
  flagged_transactions: number
  open_alerts: number
  pending_sars: number
  open_cases: number
  avg_confidence: number
}

// Escalation summary fetched separately for the dashboard widget
interface EscalationSummary {
  pending: number
  pep: number
  adverse_media: number
  sla_breached: number
}

// Continuous monitoring status for the monitoring widget
interface MonitoringStatus {
  last_run?: string
  customers_screened?: number
  new_matches?: number
  risk_upgrades?: number
  status?: string
}

// Onboarding summary for the onboarding widget
interface OnboardingSummary {
  pending: number
  approved_today: number
  blocked_today: number
}

export default function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [transactions, setTransactions] = useState<any[]>([])
  const [alerts, setAlerts] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [customerMap, setCustomerMap] = useState<CustomerMap>({})
  // v2 widget state - fetched in parallel with existing data, failures degrade gracefully
  const [escalationSummary, setEscalationSummary] = useState<EscalationSummary | null>(null)
  const [monitoringStatus, setMonitoringStatus] = useState<MonitoringStatus | null>(null)
  const [onboardingSummary, setOnboardingSummary] = useState<OnboardingSummary | null>(null)
  const [monitoringRunning, setMonitoringRunning] = useState(false)

  useEffect(() => {
    async function load() {
      try {
        setLoading(true)
        const [txRes, alertRes, statsRes] = await Promise.all([
          fetchAPI('/transactions', 'limit=500'),
          fetchAPI('/alerts'),
          fetchAPI('/api/stats'),
        ])
        getCustomerMap().then(setCustomerMap)

        const txList = txRes.transactions || txRes || []
        const alertList = alertRes.alerts || alertRes || []
        const apiStats = statsRes.stats || {}

        setTransactions(txList)
        setAlerts(alertList)

        // Use /api/stats for accurate counts (not paginated transaction list)
        setStats({
          total_transactions: apiStats.total_transactions ?? txList.length,
          flagged_transactions: apiStats.flagged_transactions ?? 0,
          open_alerts: apiStats.open_alerts ?? 0,
          pending_sars: apiStats.pending_sar_approvals ?? 0,
          open_cases: apiStats.open_cases ?? 0,
          avg_confidence: apiStats.avg_confidence ?? 0,
        })

      } catch (e: any) {
        setError(e.message)
      } finally {
        setLoading(false)
      }
    }
    load()

    // Fetch v2 widget data in parallel - failures are non-fatal (widgets show N/A gracefully)
    async function loadWidgetData() {
      // Escalation summary
      fetchAPI('/escalations/pending')
        .then(res => {
          const list = res.escalations || res || []
          const now = Date.now()
          setEscalationSummary({
            pending: list.length,
            pep: list.filter((e: any) => e.escalation_reason?.includes('pep')).length,
            adverse_media: list.filter((e: any) => e.escalation_reason?.includes('adverse')).length,
            // SLA breached = expires_at is in the past
            sla_breached: list.filter((e: any) => e.expires_at && new Date(e.expires_at).getTime() < now).length,
          })
        })
        .catch(() => {
          // Backend may not have escalations endpoint yet; show zeros
          setEscalationSummary({ pending: 0, pep: 0, adverse_media: 0, sla_breached: 0 })
        })

      // Monitoring status
      fetchAPI('/monitoring/status')
        .then(res => setMonitoringStatus(res.status || res))
        .catch(() => setMonitoringStatus({}))

      // Onboarding summary from stats or onboarding endpoint
      fetchAPI('/customers/onboarding/summary')
        .then(res => setOnboardingSummary(res.summary || res))
        .catch(() => setOnboardingSummary({ pending: 0, approved_today: 0, blocked_today: 0 }))
    }
    loadWidgetData()
  }, [])

  // Trigger manual monitoring run - called from the Continuous Monitoring widget.
  // Uses a direct fetch POST because Dashboard's fetchAPI helper is GET-only.
  async function triggerMonitoringRun() {
    setMonitoringRunning(true)
    try {
      await fetch(`/api/proxy?path=${encodeURIComponent('/monitoring/run')}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      })
      // Refresh status after triggering
      const res = await fetchAPI('/monitoring/status')
      setMonitoringStatus(res.status || res)
    } catch {
      // Non-fatal: monitoring may not be configured yet
    } finally {
      setMonitoringRunning(false)
    }
  }

  // Build risk distribution data from transactions
  const riskDist = (() => {
    const tiers: Record<string, number> = { low: 0, medium: 0, high: 0, critical: 0 }
    transactions.forEach(t => {
      const score = t.risk_score || 0
      if (score >= 0.8) tiers.critical++
      else if (score >= 0.6) tiers.high++
      else if (score >= 0.4) tiers.medium++
      else tiers.low++
    })
    return Object.entries(tiers).map(([tier, count]) => ({ tier, count }))
  })()

  // Build alert type distribution
  const alertTypeDist = (() => {
    const types: Record<string, number> = {}
    alerts.forEach(a => {
      const t = a.alert_type || a.type || 'unknown'
      types[t] = (types[t] || 0) + 1
    })
    return Object.entries(types).map(([type, count]) => ({ type, count }))
  })()

  const recentAlerts = alerts.slice(0, 5)

  if (loading) return (
    <div className="flex items-center justify-center h-64 text-slate-400">
      <div className="text-center">
        <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
        <p>Loading dashboard data...</p>
      </div>
    </div>
  )

  if (error) return (
    <div className="bg-red-900/20 border border-red-800 rounded-xl p-6 text-red-400">
      <p className="font-medium">Failed to load dashboard</p>
      <p className="text-sm mt-1 text-red-500">{error}</p>
      <p className="text-sm mt-2 text-slate-500">Ensure the backend is running at the configured API_URL.</p>
    </div>
  )

  return (
    <div className="space-y-6">
      {/* KPI Stats Row */}
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-4">
        <StatCard
          label="Total Transactions"
          value={stats?.total_transactions ?? '-'}
          icon={<ArrowLeftRight className="w-4 h-4" />}
        />
        <StatCard
          label="Flagged"
          value={stats?.flagged_transactions ?? '-'}
          icon={<AlertTriangle className="w-4 h-4 text-amber-400" />}
        />
        <StatCard
          label="Open Alerts"
          value={stats?.open_alerts ?? '-'}
          icon={<Bell className="w-4 h-4 text-red-400" />}
        />
        <StatCard
          label="Pending SARs"
          value={stats?.pending_sars ?? '-'}
          icon={<FileText className="w-4 h-4 text-blue-400" />}
        />
        <StatCard
          label="Open Cases"
          value={stats?.open_cases ?? '-'}
          icon={<Briefcase className="w-4 h-4 text-purple-400" />}
        />
        <StatCard
          label="Avg Confidence"
          value={stats ? `${(stats.avg_confidence * 100).toFixed(1)}%` : '-'}
          icon={<TrendingUp className="w-4 h-4 text-emerald-400" />}
        />
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <Card title="Risk Distribution" subtitle="Transactions by risk tier">
          <RiskDistribution data={riskDist} />
        </Card>
        <Card title="Alert Types" subtitle="Count of alerts by typology">
          <AlertTrend data={alertTypeDist} />
        </Card>
      </div>

      {/* v2 Widgets row: Pending Escalations | Continuous Monitoring | Customer Onboarding */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Pending Escalations widget - red SLA breach indicator */}
        <Card title="Pending Escalations" subtitle="Require C-suite or MLRO decision">
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-3xl font-bold text-white">{escalationSummary?.pending ?? '-'}</span>
              {/* Red badge when any escalation has breached SLA */}
              {escalationSummary && escalationSummary.sla_breached > 0 && (
                <span className="flex items-center gap-1 bg-red-900/40 border border-red-700/50 text-red-400 text-xs px-2 py-1 rounded-full">
                  <AlertTriangle className="w-3 h-3" /> {escalationSummary.sla_breached} SLA breached
                </span>
              )}
            </div>
            <div className="space-y-1.5">
              <div className="flex justify-between text-xs">
                <span className="text-orange-400">PEP matches</span>
                <span className="text-slate-300">{escalationSummary?.pep ?? '-'}</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-yellow-400">Adverse Media</span>
                <span className="text-slate-300">{escalationSummary?.adverse_media ?? '-'}</span>
              </div>
            </div>
            {escalationSummary && escalationSummary.sla_breached > 0 && (
              <p className="text-red-400 text-xs">Immediate action required on overdue escalations.</p>
            )}
          </div>
        </Card>

        {/* Continuous Monitoring widget - shows last run stats and Run Now button */}
        <Card
          title="Continuous Monitoring"
          subtitle="Periodic re-screening of all customers"
          headerRight={
            <button
              onClick={triggerMonitoringRun}
              disabled={monitoringRunning}
              className="flex items-center gap-1.5 text-xs text-blue-400 hover:text-blue-300 disabled:opacity-50 transition-colors"
            >
              {monitoringRunning ? (
                <div className="w-3 h-3 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
              ) : (
                <RefreshCw className="w-3 h-3" />
              )}
              Run Now
            </button>
          }
        >
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <Activity className="w-4 h-4 text-blue-400" />
              <Badge variant={monitoringStatus?.status === 'running' ? 'info' : monitoringStatus?.status === 'failed' ? 'danger' : 'success'}>
                {monitoringStatus?.status?.toUpperCase() || 'IDLE'}
              </Badge>
            </div>
            <div className="space-y-1.5">
              <div className="flex justify-between text-xs">
                <span className="text-slate-500">Last run</span>
                <span className="text-slate-300">
                  {monitoringStatus?.last_run ? formatWAT(monitoringStatus.last_run) : 'Never'}
                </span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-slate-500">Customers screened</span>
                <span className="text-slate-300">{monitoringStatus?.customers_screened ?? '-'}</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-slate-500">New matches</span>
                <span className={`${(monitoringStatus?.new_matches ?? 0) > 0 ? 'text-amber-400' : 'text-slate-300'}`}>
                  {monitoringStatus?.new_matches ?? '-'}
                </span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-slate-500">Risk upgrades</span>
                <span className={`${(monitoringStatus?.risk_upgrades ?? 0) > 0 ? 'text-red-400' : 'text-slate-300'}`}>
                  {monitoringStatus?.risk_upgrades ?? '-'}
                </span>
              </div>
            </div>
          </div>
        </Card>

        {/* Customer Onboarding widget - pending, approved today, blocked today */}
        <Card title="Customer Onboarding" subtitle="Pre-screening pipeline status">
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <UserPlus className="w-4 h-4 text-blue-400" />
              <span className="text-3xl font-bold text-white">{onboardingSummary?.pending ?? '-'}</span>
              <span className="text-slate-500 text-xs">pending</span>
            </div>
            <div className="space-y-1.5">
              <div className="flex justify-between text-xs">
                <span className="text-emerald-400">Approved today</span>
                <span className="text-slate-300">{onboardingSummary?.approved_today ?? '-'}</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-red-400">Blocked today</span>
                <span className="text-slate-300">{onboardingSummary?.blocked_today ?? '-'}</span>
              </div>
            </div>
            {onboardingSummary && onboardingSummary.pending > 0 && (
              <div className="flex items-center gap-1.5 text-xs text-orange-400">
                <Clock className="w-3 h-3" />
                {onboardingSummary.pending} awaiting decision
              </div>
            )}
          </div>
        </Card>
      </div>

      {/* Bottom row: Recent alerts + Regulatory compliance */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        {/* Recent alerts */}
        <div className="xl:col-span-2">
          <Card title="Recent Alerts" subtitle="Latest 5 alerts requiring attention">
            {recentAlerts.length === 0 ? (
              <p className="text-slate-500 text-sm">No alerts found.</p>
            ) : (
              <div className="space-y-3">
                {recentAlerts.map((alert: any) => (
                  <div key={alert.alert_id || alert.id} className="flex items-center justify-between p-3 bg-slate-700/40 rounded-lg">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <SeverityBadge severity={alert.severity} />
                        <span className="text-slate-400 text-xs truncate">{alert.alert_type || alert.type}</span>
                      </div>
                      <p className="text-slate-300 text-sm truncate">{formatCustomer(alert.customer_id, customerMap) || 'Unknown customer'}</p>
                      <p className="text-slate-500 text-xs">{alert.created_at ? formatWAT(alert.created_at) : 'N/A'}</p>
                    </div>
                    <StatusBadge status={alert.status} />
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>

        {/* Regulatory compliance panel */}
        <Card title="Regulatory Alignment" subtitle="Compliance framework status">
          <div className="space-y-4">
            {[
              { name: 'FATF Recommendations', status: 'compliant', desc: 'Risk-based approach active' },
              { name: 'CBN AML/CFT Guidelines', status: 'compliant', desc: 'AI model validated annually' },
              { name: 'NFIU Reporting', status: 'compliant', desc: 'SAR filing pipeline active' },
              { name: 'Human Oversight', status: 'compliant', desc: 'All SARs require human approval' },
            ].map(item => (
              <div key={item.name} className="flex items-start gap-3">
                <CheckCircle className="w-5 h-5 text-emerald-400 flex-shrink-0 mt-0.5" />
                <div>
                  <p className="text-slate-200 text-sm font-medium">{item.name}</p>
                  <p className="text-slate-500 text-xs">{item.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  )
}
