// CustomerOnboarding tab - manages the pre-onboarding screening pipeline.
// New customers are screened against all watchlists before account activation (CBN KYC requirement).
// Shows onboarding queue, inline screening results, escalation panel, and SLA countdowns.
'use client'
import { useEffect, useState, useCallback } from 'react'
import { UserPlus, RefreshCw, Search, Clock, AlertTriangle, CheckCircle, XCircle, ChevronDown, ChevronUp } from 'lucide-react'
import Card from './ui/Card'
import { Table, Thead, Th, Tbody, Tr, Td } from './ui/Table'
import { Badge } from './ui/Badge'
import Modal from './ui/Modal'
import EscalationPanel from './EscalationPanel'

// Shared fetch helper - routes through Next.js proxy to avoid CORS
async function fetchAPI(path: string, body?: object, method = 'GET') {
  if (body !== undefined) {
    const res = await fetch(`/api/proxy?path=${encodeURIComponent(path)}`, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    return res.json()
  }
  const res = await fetch(`/api/proxy?path=${encodeURIComponent(path)}`)
  return res.json()
}

// Format dates in WAT (UTC+1 = Africa/Lagos) per project standard
function formatWAT(isoDate: string) {
  return new Date(isoDate).toLocaleString('en-NG', {
    timeZone: 'Africa/Lagos',
    dateStyle: 'short',
    timeStyle: 'short',
  })
}

// SLA countdown: returns remaining time string or "BREACHED" with urgency flag
function getSLAStatus(expiresAt: string | null): { label: string; breached: boolean } {
  if (!expiresAt) return { label: 'No SLA', breached: false }
  const ms = new Date(expiresAt).getTime() - Date.now()
  if (ms <= 0) return { label: 'BREACHED', breached: true }
  const hours = Math.floor(ms / 3600000)
  const mins = Math.floor((ms % 3600000) / 60000)
  if (hours > 0) return { label: `${hours}h ${mins}m`, breached: false }
  return { label: `${mins}m`, breached: mins < 30 }
}

// Onboarding status badge with color coding per spec:
// Screening=blue, Clear=green, Pending Approval=orange, Blocked=red, Approved High-Risk=yellow
function OnboardingStatusBadge({ status }: { status: string }) {
  const s = status?.toLowerCase()
  if (s === 'screening') {
    return (
      <span className="inline-flex items-center rounded-full border font-medium text-xs px-2 py-0.5 bg-blue-900/50 text-blue-400 border-blue-700/50">
        SCREENING
      </span>
    )
  }
  if (s === 'clear' || s === 'approved') {
    return (
      <span className="inline-flex items-center rounded-full border font-medium text-xs px-2 py-0.5 bg-emerald-900/50 text-emerald-400 border-emerald-700/50">
        CLEAR
      </span>
    )
  }
  if (s === 'pending_approval' || s === 'pending_escalation' || s === 'pending_review') {
    return (
      <span className="inline-flex items-center rounded-full border font-medium text-xs px-2 py-0.5 bg-orange-900/50 text-orange-400 border-orange-700/50">
        PENDING APPROVAL
      </span>
    )
  }
  if (s === 'blocked') {
    return (
      <span className="inline-flex items-center rounded-full border font-medium text-xs px-2 py-0.5 bg-red-900/50 text-red-400 border-red-700/50">
        BLOCKED
      </span>
    )
  }
  if (s === 'approved_high_risk') {
    return (
      <span className="inline-flex items-center rounded-full border font-medium text-xs px-2 py-0.5 bg-yellow-900/50 text-yellow-400 border-yellow-700/50">
        APPROVED (HIGH RISK)
      </span>
    )
  }
  return <Badge variant="ghost">{status?.toUpperCase() || 'UNKNOWN'}</Badge>
}

interface OnboardingRecord {
  id: string
  customer_id?: string
  name: string
  status: string
  screening_result?: string
  escalation_id?: string
  risk_tier?: string
  created_at: string
  expires_at?: string
}

// New customer form state
interface NewCustomerForm {
  name: string
  bvn: string
  nin: string
  date_of_birth: string
  phone: string
  address: string
  account_type: string
  nationality: string
}

const BLANK_FORM: NewCustomerForm = {
  name: '',
  bvn: '',
  nin: '',
  date_of_birth: '',
  phone: '',
  address: '',
  account_type: 'savings',
  nationality: 'Nigeria',
}

export default function CustomerOnboarding() {
  const [records, setRecords] = useState<OnboardingRecord[]>([])
  const [filtered, setFiltered] = useState<OnboardingRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  // Which queue record is expanded inline for escalation details
  const [expandedId, setExpandedId] = useState<string | null>(null)
  // New customer submission modal state
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState<NewCustomerForm>(BLANK_FORM)
  const [formLoading, setFormLoading] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [formResult, setFormResult] = useState<any | null>(null)

  const load = useCallback(function load() {
    setLoading(true)
    setError(null)
    // Fetch onboarding queue from backend
    fetchAPI('/customers/onboarding')
      .then(res => {
        const list: OnboardingRecord[] = res.records || res.onboarding || res || []
        setRecords(list)
        setFiltered(list)
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  // Filter queue by search and status
  useEffect(() => {
    let result = [...records]
    if (search) {
      const q = search.toLowerCase()
      result = result.filter(r =>
        r.name?.toLowerCase().includes(q) ||
        r.id?.toLowerCase().includes(q) ||
        r.customer_id?.toLowerCase().includes(q)
      )
    }
    if (statusFilter !== 'all') result = result.filter(r => r.status?.toLowerCase() === statusFilter)
    setFiltered(result)
  }, [records, search, statusFilter])

  async function submitNewCustomer(e: React.FormEvent) {
    e.preventDefault()
    // Validate required fields before hitting the API
    if (!form.name.trim()) {
      setFormError('Name is required.')
      return
    }
    setFormLoading(true)
    setFormError(null)
    setFormResult(null)
    try {
      const result = await fetchAPI('/customers/onboard', form, 'POST')
      setFormResult(result)
      // Refresh the queue so the new applicant appears immediately
      load()
    } catch (e: any) {
      setFormError(e.message || 'Submission failed.')
    } finally {
      setFormLoading(false)
    }
  }

  function closeForm() {
    setShowForm(false)
    setForm(BLANK_FORM)
    setFormError(null)
    setFormResult(null)
  }

  // Counts for header summary stats
  const pendingCount = records.filter(r => ['pending_approval', 'pending_escalation', 'pending_review', 'screening'].includes(r.status?.toLowerCase())).length
  const blockedCount = records.filter(r => r.status?.toLowerCase() === 'blocked').length

  if (loading) return (
    <div className="flex items-center justify-center h-64 text-slate-400">
      <div className="text-center">
        <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
        <p>Loading onboarding queue...</p>
      </div>
    </div>
  )

  if (error) return (
    <div className="bg-red-900/20 border border-red-800 rounded-xl p-6 text-red-400">
      <p className="font-medium">Failed to load onboarding queue</p>
      <p className="text-sm mt-1 text-red-500">{error}</p>
    </div>
  )

  return (
    <div className="space-y-4">
      {/* Summary banner - alerts compliance officers to pending escalations */}
      {pendingCount > 0 && (
        <div className="bg-orange-900/30 border border-orange-700/50 rounded-xl p-4 flex items-center gap-3">
          <AlertTriangle className="w-5 h-5 text-orange-400 flex-shrink-0" />
          <div>
            <p className="text-orange-300 font-semibold text-sm">ONBOARDING DECISIONS REQUIRED</p>
            <p className="text-orange-400/80 text-xs">
              {pendingCount} customer{pendingCount > 1 ? 's' : ''} pending review or approval.
              {blockedCount > 0 && ` ${blockedCount} blocked by sanctions match.`}
            </p>
          </div>
        </div>
      )}

      {/* Controls row */}
      <div className="flex flex-wrap gap-3 items-center">
        <div className="relative">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            type="text"
            placeholder="Search by name or ID..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="bg-[#111827] border border-[#1e293b] rounded-lg pl-9 pr-4 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500 w-64"
          />
        </div>
        <select
          value={statusFilter}
          onChange={e => setStatusFilter(e.target.value)}
          className="bg-[#111827] border border-[#1e293b] rounded-lg px-3 py-2 text-sm text-slate-300 focus:outline-none focus:border-blue-500"
        >
          <option value="all">All Statuses</option>
          <option value="screening">Screening</option>
          <option value="clear">Clear</option>
          <option value="pending_approval">Pending Approval</option>
          <option value="blocked">Blocked</option>
          <option value="approved_high_risk">Approved (High Risk)</option>
        </select>
        <button onClick={load} className="flex items-center gap-2 text-slate-400 hover:text-slate-200 text-sm">
          <RefreshCw className="w-4 h-4" /> Refresh
        </button>
        <span className="text-slate-500 text-sm">{filtered.length} records</span>
        {/* New customer button - opens the onboarding form */}
        <button
          onClick={() => setShowForm(true)}
          className="ml-auto flex items-center gap-2 bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
        >
          <UserPlus className="w-4 h-4" /> Onboard New Customer
        </button>
      </div>

      {/* Onboarding queue table */}
      <Card>
        <Table>
          <Thead>
            <tr>
              <Th>Name</Th>
              <Th>Status</Th>
              <Th>Risk Tier</Th>
              <Th>Screening Result</Th>
              <Th>Submitted (WAT)</Th>
              <Th>SLA</Th>
              <Th>{''}</Th>
            </tr>
          </Thead>
          <Tbody>
            {filtered.length === 0 ? (
              <Tr>
                <Td className="text-slate-500 text-center py-12">No onboarding records found.</Td>
              </Tr>
            ) : (
              filtered.map(record => {
                const sla = getSLAStatus(record.expires_at || null)
                const isExpanded = expandedId === record.id
                return (
                  <>
                    <Tr key={record.id}>
                      <Td>
                        <span className="text-slate-200 font-medium">{record.name}</span>
                        <p className="text-slate-500 text-xs font-mono mt-0.5">{record.id?.substring(0, 12)}</p>
                      </Td>
                      <Td><OnboardingStatusBadge status={record.status} /></Td>
                      <Td>
                        <Badge variant={
                          record.risk_tier === 'high' ? 'danger' :
                          record.risk_tier === 'medium' ? 'warning' :
                          record.risk_tier === 'low' ? 'success' : 'ghost'
                        }>
                          {record.risk_tier?.toUpperCase() || 'UNASSIGNED'}
                        </Badge>
                      </Td>
                      <Td>
                        <span className="text-slate-400 text-xs">{record.screening_result || 'Pending'}</span>
                      </Td>
                      <Td>
                        <span className="text-slate-400 text-xs">{record.created_at ? formatWAT(record.created_at) : 'N/A'}</span>
                      </Td>
                      <Td>
                        {/* SLA countdown - turns red when breached */}
                        {record.expires_at ? (
                          <span className={`flex items-center gap-1 text-xs font-mono ${sla.breached ? 'text-red-400' : 'text-slate-400'}`}>
                            <Clock className="w-3 h-3" />
                            {sla.label}
                          </span>
                        ) : (
                          <span className="text-slate-600 text-xs">-</span>
                        )}
                      </Td>
                      <Td>
                        {/* Expand row to show inline escalation panel when there is a pending escalation */}
                        {record.escalation_id && (
                          <button
                            onClick={() => setExpandedId(isExpanded ? null : record.id)}
                            className="flex items-center gap-1 text-blue-400 hover:text-blue-300 text-xs"
                          >
                            Escalation {isExpanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                          </button>
                        )}
                      </Td>
                    </Tr>
                    {/* Inline escalation details expand */}
                    {isExpanded && record.escalation_id && (
                      // Use native tr/td here because Td does not support colSpan
                      <tr key={`${record.id}-escalation`}>
                        <td colSpan={7} className="bg-slate-800/50 px-4 py-4">
                          <EscalationPanel
                            escalationId={record.escalation_id}
                            onDecision={load}
                          />
                        </td>
                      </tr>
                    )}
                  </>
                )
              })
            )}
          </Tbody>
        </Table>
      </Card>

      {/* New customer onboarding modal */}
      <Modal isOpen={showForm} onClose={closeForm} title="Onboard New Customer" size="lg">
        {formResult ? (
          // Show screening result after submission
          <div className="space-y-4">
            <div className={`rounded-lg p-4 border ${
              formResult.status === 'blocked'
                ? 'bg-red-900/20 border-red-700 text-red-300'
                : formResult.status === 'pending_approval' || formResult.status === 'pending_escalation'
                ? 'bg-orange-900/20 border-orange-700 text-orange-300'
                : 'bg-emerald-900/20 border-emerald-700 text-emerald-300'
            }`}>
              <div className="flex items-center gap-3 mb-2">
                {formResult.status === 'blocked' ? (
                  <XCircle className="w-5 h-5 text-red-400" />
                ) : formResult.status === 'clear' || formResult.status === 'approved' ? (
                  <CheckCircle className="w-5 h-5 text-emerald-400" />
                ) : (
                  <AlertTriangle className="w-5 h-5 text-orange-400" />
                )}
                <p className="font-semibold text-sm">
                  Onboarding Decision: {formResult.status?.replace(/_/g, ' ').toUpperCase()}
                </p>
              </div>
              {formResult.message && <p className="text-sm">{formResult.message}</p>}
              {formResult.screening_result && (
                <p className="text-xs mt-1 opacity-80">Screening: {formResult.screening_result}</p>
              )}
            </div>
            <button
              onClick={closeForm}
              className="w-full bg-slate-700 hover:bg-slate-600 text-white py-2 rounded-lg text-sm"
            >
              Close
            </button>
          </div>
        ) : (
          // New customer input form
          <form onSubmit={submitNewCustomer} className="space-y-4">
            {formError && (
              <div className="bg-red-900/20 border border-red-700 rounded-lg p-3 text-red-400 text-sm">{formError}</div>
            )}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* Full name */}
              <div className="md:col-span-2">
                <label className="block text-slate-400 text-xs font-medium mb-1.5">
                  Full Name <span className="text-red-400">*</span>
                </label>
                <input
                  type="text"
                  required
                  value={form.name}
                  onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                  placeholder="As on government ID"
                  className="w-full bg-[#0a1120] border border-[#1e293b] rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-blue-500"
                />
              </div>
              {/* BVN */}
              <div>
                <label className="block text-slate-400 text-xs font-medium mb-1.5">BVN</label>
                <input
                  type="text"
                  maxLength={11}
                  value={form.bvn}
                  onChange={e => setForm(f => ({ ...f, bvn: e.target.value.replace(/\D/g, '') }))}
                  placeholder="11-digit BVN"
                  className="w-full bg-[#0a1120] border border-[#1e293b] rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-blue-500 font-mono"
                />
              </div>
              {/* NIN */}
              <div>
                <label className="block text-slate-400 text-xs font-medium mb-1.5">NIN</label>
                <input
                  type="text"
                  maxLength={11}
                  value={form.nin}
                  onChange={e => setForm(f => ({ ...f, nin: e.target.value.replace(/\D/g, '') }))}
                  placeholder="11-digit NIN"
                  className="w-full bg-[#0a1120] border border-[#1e293b] rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-blue-500 font-mono"
                />
              </div>
              {/* Date of birth */}
              <div>
                <label className="block text-slate-400 text-xs font-medium mb-1.5">Date of Birth</label>
                <input
                  type="date"
                  value={form.date_of_birth}
                  onChange={e => setForm(f => ({ ...f, date_of_birth: e.target.value }))}
                  className="w-full bg-[#0a1120] border border-[#1e293b] rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-blue-500"
                />
              </div>
              {/* Phone */}
              <div>
                <label className="block text-slate-400 text-xs font-medium mb-1.5">Phone Number</label>
                <input
                  type="tel"
                  value={form.phone}
                  onChange={e => setForm(f => ({ ...f, phone: e.target.value }))}
                  placeholder="+234..."
                  className="w-full bg-[#0a1120] border border-[#1e293b] rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-blue-500"
                />
              </div>
              {/* Account type */}
              <div>
                <label className="block text-slate-400 text-xs font-medium mb-1.5">Account Type</label>
                <select
                  value={form.account_type}
                  onChange={e => setForm(f => ({ ...f, account_type: e.target.value }))}
                  className="w-full bg-[#0a1120] border border-[#1e293b] rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-blue-500"
                >
                  <option value="savings">Savings</option>
                  <option value="current">Current</option>
                  <option value="domiciliary">Domiciliary</option>
                  <option value="business">Business</option>
                  <option value="joint">Joint</option>
                </select>
              </div>
              {/* Nationality */}
              <div>
                <label className="block text-slate-400 text-xs font-medium mb-1.5">Nationality</label>
                <input
                  type="text"
                  value={form.nationality}
                  onChange={e => setForm(f => ({ ...f, nationality: e.target.value }))}
                  placeholder="Nigeria"
                  className="w-full bg-[#0a1120] border border-[#1e293b] rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-blue-500"
                />
              </div>
              {/* Address */}
              <div className="md:col-span-2">
                <label className="block text-slate-400 text-xs font-medium mb-1.5">Address</label>
                <textarea
                  value={form.address}
                  onChange={e => setForm(f => ({ ...f, address: e.target.value }))}
                  placeholder="Residential address"
                  rows={2}
                  className="w-full bg-[#0a1120] border border-[#1e293b] rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-blue-500 resize-none"
                />
              </div>
            </div>

            <p className="text-slate-600 text-xs">
              Submitting will trigger watchlist screening (sanctions, PEP, adverse media) before any account is created.
            </p>

            <div className="flex gap-3 pt-2">
              <button
                type="button"
                onClick={closeForm}
                className="flex-1 bg-slate-700 hover:bg-slate-600 text-white py-2.5 rounded-lg text-sm font-medium transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={formLoading || !form.name.trim()}
                className="flex-1 flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white py-2.5 rounded-lg text-sm font-medium transition-colors"
              >
                {formLoading ? (
                  <>
                    <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                    Screening...
                  </>
                ) : (
                  <>
                    <UserPlus className="w-4 h-4" /> Submit for Screening
                  </>
                )}
              </button>
            </div>
          </form>
        )}
      </Modal>
    </div>
  )
}
