// EscalationPanel - renders a single escalation with full evidence, match details,
// approve/reject workflow (mandatory rationale), SLA breach indicator, and decision history.
// Used inline within CustomerOnboarding and as a standalone view.
'use client'
import { useEffect, useState } from 'react'
import { CheckCircle, XCircle, Clock, AlertTriangle, ChevronDown, ChevronUp, Shield } from 'lucide-react'
import { Badge } from './ui/Badge'

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

function formatWAT(isoDate: string) {
  return new Date(isoDate).toLocaleString('en-NG', {
    timeZone: 'Africa/Lagos',
    dateStyle: 'short',
    timeStyle: 'short',
  })
}

// Returns SLA display label and whether it is breached
function getSLAStatus(expiresAt: string | null): { label: string; breached: boolean } {
  if (!expiresAt) return { label: 'No SLA set', breached: false }
  const ms = new Date(expiresAt).getTime() - Date.now()
  if (ms <= 0) return { label: 'SLA BREACHED', breached: true }
  const hours = Math.floor(ms / 3600000)
  const mins = Math.floor((ms % 3600000) / 60000)
  if (hours > 0) return { label: `${hours}h ${mins}m remaining`, breached: false }
  return { label: `${mins}m remaining`, breached: mins < 30 }
}

// Category badge matching WatchlistScreening colors
function CategoryBadge({ category }: { category: string }) {
  const c = category?.toLowerCase()
  if (c === 'pep') {
    return (
      <span className="inline-flex items-center rounded-full border font-medium text-xs px-2 py-0.5 bg-orange-900/50 text-orange-400 border-orange-700/50">PEP</span>
    )
  }
  if (c === 'adverse_media') {
    return (
      <span className="inline-flex items-center rounded-full border font-medium text-xs px-2 py-0.5 bg-yellow-900/50 text-yellow-400 border-yellow-700/50">ADVERSE MEDIA</span>
    )
  }
  return (
    <span className="inline-flex items-center rounded-full border font-medium text-xs px-2 py-0.5 bg-red-900/50 text-red-400 border-red-700/50">SANCTIONS</span>
  )
}

interface EscalationDetail {
  id: string
  entity_type: string
  entity_id: string
  escalation_reason: string
  required_approver_role: string
  current_status: string
  assigned_to?: string
  decision_rationale?: string
  evidence_summary?: string | object
  created_at: string
  decided_at?: string
  expires_at?: string
  sla_hours?: number
  // Match details embedded in evidence_summary or as top-level fields
  match_details?: {
    matched_entity?: string
    list?: string
    score?: number
    category?: string
  }
}

interface Props {
  escalationId: string
  // Callback after approve/reject so parent can refresh queue
  onDecision?: () => void
}

export default function EscalationPanel({ escalationId, onDecision }: Props) {
  const [escalation, setEscalation] = useState<EscalationDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [rationale, setRationale] = useState('')
  const [actionLoading, setActionLoading] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [historyExpanded, setHistoryExpanded] = useState(false)

  useEffect(() => {
    setLoading(true)
    setError(null)
    fetchAPI(`/escalations/${escalationId}`)
      .then(res => {
        setEscalation(res.escalation || res)
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [escalationId])

  async function handleDecision(action: 'approve' | 'reject') {
    // Rationale is mandatory per CBN governance requirements
    if (!rationale.trim()) {
      setActionError('Rationale is mandatory for escalation decisions (CBN requirement).')
      return
    }
    setActionLoading(true)
    setActionError(null)
    try {
      await fetchAPI(`/escalations/${escalationId}/${action}`, {
        rationale,
        reviewed_by: 'compliance_officer',
      }, 'POST')
      // Refresh escalation detail and notify parent
      const res = await fetchAPI(`/escalations/${escalationId}`)
      setEscalation(res.escalation || res)
      setRationale('')
      if (onDecision) onDecision()
    } catch (e: any) {
      setActionError(e.message || 'Decision failed.')
    } finally {
      setActionLoading(false)
    }
  }

  if (loading) return (
    <div className="flex items-center gap-2 text-slate-400 text-sm py-2">
      <div className="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
      Loading escalation...
    </div>
  )

  if (error) return (
    <div className="bg-red-900/20 border border-red-800 rounded-lg p-3 text-red-400 text-sm">{error}</div>
  )

  if (!escalation) return null

  // Parse evidence summary - may be JSON string or already an object
  let evidence: Record<string, any> = {}
  if (escalation.evidence_summary) {
    if (typeof escalation.evidence_summary === 'string') {
      try { evidence = JSON.parse(escalation.evidence_summary) } catch { evidence = {} }
    } else {
      evidence = escalation.evidence_summary as Record<string, any>
    }
  }

  const sla = getSLAStatus(escalation.expires_at || null)
  const isPending = escalation.current_status === 'pending'
  const matchCategory = evidence.category || escalation.match_details?.category || escalation.escalation_reason || 'sanctions'

  return (
    <div className="space-y-4">
      {/* SLA breach indicator - red banner if overdue */}
      {sla.breached && (
        <div className="bg-red-900/30 border border-red-700/50 rounded-lg p-3 flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 text-red-400 flex-shrink-0" />
          <p className="text-red-300 text-sm font-semibold">SLA BREACHED - Immediate action required</p>
        </div>
      )}

      {/* Status bar */}
      <div className="flex flex-wrap items-center gap-3">
        <Badge variant={
          escalation.current_status === 'approved' ? 'success' :
          escalation.current_status === 'rejected' ? 'danger' :
          escalation.current_status === 'expired' ? 'ghost' : 'warning'
        }>
          {escalation.current_status?.toUpperCase()}
        </Badge>
        <CategoryBadge category={matchCategory} />
        <span className="text-slate-500 text-xs">
          Approver required: <span className="text-slate-300">{escalation.required_approver_role?.replace(/_/g, ' ')}</span>
        </span>
        {/* SLA countdown */}
        <span className={`flex items-center gap-1 text-xs ml-auto ${sla.breached ? 'text-red-400' : 'text-slate-500'}`}>
          <Clock className="w-3 h-3" /> {sla.label}
        </span>
      </div>

      {/* Match details section */}
      <div className="bg-[#0a1120] rounded-lg p-4 space-y-3">
        <h4 className="text-slate-400 text-xs font-semibold uppercase tracking-wider">Match Details</h4>
        <div className="grid grid-cols-2 gap-3">
          {[
            ['Entity Type', escalation.entity_type?.replace(/_/g, ' ')],
            ['Escalation Reason', escalation.escalation_reason?.replace(/_/g, ' ')],
            ['Matched Entity', evidence.matched_entity || escalation.match_details?.matched_entity || 'N/A'],
            ['Screening List', evidence.list || evidence.sanctions_list || escalation.match_details?.list || 'N/A'],
            ['Match Score', evidence.score !== undefined ? `${(Number(evidence.score) * 100).toFixed(1)}%` : escalation.match_details?.score !== undefined ? `${(Number(escalation.match_details.score) * 100).toFixed(1)}%` : 'N/A'],
            ['Created (WAT)', escalation.created_at ? formatWAT(escalation.created_at) : 'N/A'],
          ].map(([label, value]) => (
            <div key={label} className="bg-slate-800/50 rounded p-2">
              <p className="text-slate-500 text-xs mb-0.5">{label}</p>
              <p className="text-slate-200 text-sm capitalize">{value}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Evidence summary free-form text */}
      {evidence.notes && (
        <div>
          <h4 className="text-slate-400 text-xs font-semibold uppercase tracking-wider mb-2">Evidence Notes</h4>
          <div className="bg-[#0a1120] rounded-lg p-3 text-sm text-slate-400 leading-relaxed">
            {evidence.notes}
          </div>
        </div>
      )}

      {/* Decision history for resolved escalations */}
      {!isPending && escalation.decision_rationale && (
        <div>
          <button
            onClick={() => setHistoryExpanded(v => !v)}
            className="flex items-center gap-2 text-slate-400 hover:text-slate-200 text-xs font-semibold uppercase tracking-wider w-full mb-2"
          >
            <Shield className="w-3.5 h-3.5" />
            Decision History
            {historyExpanded ? <ChevronUp className="w-3.5 h-3.5 ml-auto" /> : <ChevronDown className="w-3.5 h-3.5 ml-auto" />}
          </button>
          {historyExpanded && (
            <div className="space-y-2">
              <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-3">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-slate-300 text-xs font-medium">
                    Decision: {escalation.current_status?.toUpperCase()}
                  </span>
                  {escalation.decided_at && (
                    <span className="text-slate-600 text-xs">{formatWAT(escalation.decided_at)}</span>
                  )}
                </div>
                {escalation.assigned_to && (
                  <p className="text-blue-400 text-xs mb-1">By: {escalation.assigned_to}</p>
                )}
                <p className="text-slate-400 text-sm leading-relaxed">{escalation.decision_rationale}</p>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Approve / Reject controls - only shown for pending escalations */}
      {isPending && (
        <div className="border-t border-[#1e293b] pt-4">
          <h4 className="text-slate-400 text-xs font-semibold uppercase tracking-wider mb-3">
            Escalation Decision
            <span className="text-red-400 ml-1">*</span>
          </h4>
          {actionError && (
            <div className="bg-red-900/20 border border-red-700 rounded-lg p-3 text-red-400 text-sm mb-3">{actionError}</div>
          )}
          {/* Rationale is mandatory - button stays disabled until text is entered */}
          <textarea
            value={rationale}
            onChange={e => setRationale(e.target.value)}
            placeholder="Rationale is mandatory (CBN requirement). Document your decision, supporting evidence review, and basis for approval or rejection..."
            rows={4}
            className="w-full bg-[#0a1120] border border-[#1e293b] rounded-lg p-3 text-sm text-slate-300 placeholder-slate-600 focus:outline-none focus:border-blue-500 mb-3 resize-none"
          />
          <div className="flex gap-3">
            <button
              onClick={() => handleDecision('approve')}
              disabled={actionLoading || !rationale.trim()}
              className="flex-1 flex items-center justify-center gap-2 bg-emerald-700 hover:bg-emerald-600 text-white py-2.5 px-4 rounded-lg text-sm font-medium disabled:opacity-50 transition-colors"
            >
              <CheckCircle className="w-4 h-4" />
              {actionLoading ? 'Processing...' : 'Approve Onboarding'}
            </button>
            <button
              onClick={() => handleDecision('reject')}
              disabled={actionLoading || !rationale.trim()}
              className="flex-1 flex items-center justify-center gap-2 bg-red-700 hover:bg-red-600 text-white py-2.5 px-4 rounded-lg text-sm font-medium disabled:opacity-50 transition-colors"
            >
              <XCircle className="w-4 h-4" />
              {actionLoading ? 'Processing...' : 'Reject Application'}
            </button>
          </div>
          <p className="text-slate-600 text-xs mt-2 text-center">
            Both buttons require a written rationale. Decisions are logged to the immutable audit trail.
          </p>
        </div>
      )}
    </div>
  )
}
