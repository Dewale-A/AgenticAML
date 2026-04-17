// Screen Transaction modal - submits a transaction through the full 6-agent AML pipeline
// and shows a live stepped visualization of each agent stage result.
'use client'
import { useState, useEffect, useRef } from 'react'
import {
  Activity, User, Shield, BarChart2, FileText, Briefcase,
  CheckCircle, AlertTriangle, XCircle, Loader2, Play,
} from 'lucide-react'
import Modal from './ui/Modal'

type Phase = 'form' | 'screening' | 'complete' | 'error'
type StageStatus = 'pending' | 'running' | 'pass' | 'warn' | 'fail' | 'skipped'

interface Stage {
  id: string
  label: string
  Icon: React.ComponentType<{ className?: string }>
  status: StageStatus
  statusLabel: string
  detail: string
  govStatus?: string
}

const STAGE_DEFS = [
  { id: 'monitor', label: 'Transaction Monitor', Icon: Activity },
  { id: 'kyc', label: 'KYC Verifier', Icon: User },
  { id: 'sanctions', label: 'Sanctions Screener', Icon: Shield },
  { id: 'pattern', label: 'Pattern Analyzer', Icon: BarChart2 },
  { id: 'sar', label: 'SAR Generator', Icon: FileText },
  { id: 'case', label: 'Case Manager', Icon: Briefcase },
]

const RUNNING_LABELS = ['Checking...', 'Verifying...', 'Screening...', 'Analyzing...', 'Evaluating...', 'Processing...']

function blankStages(): Stage[] {
  return STAGE_DEFS.map(s => ({ ...s, status: 'pending', statusLabel: 'Pending', detail: '' }))
}

function mapResultsToStages(result: any): Stage[] {
  const gov: any[] = result.governance_decisions || []
  const stages = blankStages()

  const govLabel = (g: any) => g ? (g.blocked ? 'blocked' : g.escalated ? 'escalated' : 'passed') : undefined

  // Stage 0: Transaction Monitor
  if (result.monitor_result) {
    const m = result.monitor_result
    stages[0].status = m.flagged ? 'warn' : 'pass'
    stages[0].statusLabel = m.flagged ? 'Flagged' : 'Cleared'
    stages[0].detail = `Risk: ${(m.risk_score * 100).toFixed(0)}% | Confidence: ${(m.confidence * 100).toFixed(0)}% | Rules triggered: ${m.triggered_rules?.length ?? 0}`
    stages[0].govStatus = govLabel(gov[0])
  }

  // Stage 1: KYC Verifier
  if (result.kyc_result) {
    const k = result.kyc_result
    stages[1].status = k.kyc_status === 'verified' ? 'pass' : k.kyc_status === 'failed' ? 'fail' : 'warn'
    stages[1].statusLabel = k.kyc_status?.replace(/_/g, ' ') || 'Unknown'
    stages[1].detail = `Risk tier: ${k.risk_tier} | Confidence: ${(k.verification_confidence * 100).toFixed(0)}%${k.pep_detected ? ' | PEP detected' : ''}${k.missing_fields?.length ? ` | Missing: ${k.missing_fields.join(', ')}` : ''}`
    stages[1].govStatus = govLabel(gov[1])
  }

  // Stage 2: Sanctions Screener
  if (result.sanctions_result) {
    const s = result.sanctions_result
    const recMap: Record<string, StageStatus> = { clear: 'pass', review: 'warn', block: 'fail' }
    stages[2].status = recMap[s.overall_recommendation] ?? 'pass'
    stages[2].statusLabel = s.overall_recommendation?.toUpperCase() ?? 'CLEAR'
    stages[2].detail = `Recommendation: ${s.overall_recommendation} | Matches: ${s.matches?.length ?? 0}`
    stages[2].govStatus = govLabel(gov[2])
  }

  // Stage 3: Pattern Analyzer
  if (result.pattern_result) {
    const p = result.pattern_result
    const riskMap: Record<string, StageStatus> = { low: 'pass', medium: 'warn', high: 'warn', critical: 'fail' }
    stages[3].status = riskMap[p.overall_risk] ?? 'pass'
    stages[3].statusLabel = `${p.overall_risk?.toUpperCase()} risk`
    const patterns = p.patterns_detected ?? []
    stages[3].detail = `Patterns found: ${patterns.length}${patterns.length ? ` | ${patterns.map((pt: any) => pt.pattern_name).join(', ')}` : ''}`
    stages[3].govStatus = govLabel(gov[3])
  } else {
    stages[3].status = 'skipped'
    stages[3].statusLabel = 'Skipped'
    stages[3].detail = 'Not flagged - pattern analysis skipped'
  }

  // Stage 4: SAR Generator
  if (result.sar_result) {
    const sar = result.sar_result
    stages[4].status = 'warn'
    stages[4].statusLabel = 'Draft Generated'
    stages[4].detail = `Typology: ${sar.typology} | Priority: ${sar.priority} | Requires human approval`
    stages[4].govStatus = govLabel(gov[4])
  } else {
    stages[4].status = 'skipped'
    stages[4].statusLabel = 'Not Required'
    stages[4].detail = 'Thresholds not met'
  }

  // Stage 5: Case Manager
  if (result.case_result) {
    const c = result.case_result
    stages[5].status = 'warn'
    stages[5].statusLabel = 'Case Created'
    stages[5].detail = `Assigned to: ${c.assigned_to} | Priority: ${c.priority}`
    stages[5].govStatus = govLabel(gov[5])
  } else {
    stages[5].status = 'skipped'
    stages[5].statusLabel = 'Not Required'
    stages[5].detail = 'No case creation needed'
  }

  return stages
}

function StageIcon({ status }: { status: StageStatus }) {
  if (status === 'running') return <Loader2 className="w-5 h-5 text-blue-400 animate-spin" />
  if (status === 'pass') return <CheckCircle className="w-5 h-5 text-emerald-400" />
  if (status === 'warn') return <AlertTriangle className="w-5 h-5 text-amber-400" />
  if (status === 'fail') return <XCircle className="w-5 h-5 text-red-400" />
  if (status === 'skipped') return (
    <div className="w-5 h-5 flex items-center justify-center">
      <div className="w-3 h-0.5 bg-slate-600 rounded" />
    </div>
  )
  return <div className="w-5 h-5 rounded-full border-2 border-slate-700" />
}

const STATUS_BG: Record<StageStatus, string> = {
  running: 'bg-blue-900/15 border-blue-700/40',
  pass: 'bg-emerald-900/15 border-emerald-800/40',
  warn: 'bg-amber-900/15 border-amber-700/40',
  fail: 'bg-red-900/15 border-red-800/40',
  skipped: 'bg-slate-800/20 border-slate-700/20',
  pending: 'bg-slate-800/10 border-slate-700/20',
}

const BADGE_COLORS: Record<StageStatus, string> = {
  running: 'bg-blue-900/60 text-blue-300',
  pass: 'bg-emerald-900/60 text-emerald-300',
  warn: 'bg-amber-900/60 text-amber-300',
  fail: 'bg-red-900/60 text-red-300',
  skipped: 'bg-slate-700/50 text-slate-400',
  pending: 'bg-slate-700/30 text-slate-500',
}

const FINAL_STATUS_COLORS: Record<string, string> = {
  cleared: 'text-emerald-300 bg-emerald-900/30 border-emerald-800',
  flagged: 'text-amber-300 bg-amber-900/30 border-amber-700',
  blocked: 'text-red-300 bg-red-900/30 border-red-800',
  escalated: 'text-orange-300 bg-orange-900/30 border-orange-800',
}

interface Props {
  isOpen: boolean
  onClose: () => void
}

export default function ScreenTransaction({ isOpen, onClose }: Props) {
  const [phase, setPhase] = useState<Phase>('form')
  const [stages, setStages] = useState<Stage[]>(blankStages())
  const [result, setResult] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)
  const [customers, setCustomers] = useState<{ id: string; name: string }[]>([])

  // Form state
  const [customerId, setCustomerId] = useState('')
  const [amount, setAmount] = useState('')
  const [txType, setTxType] = useState('transfer')
  const [channel, setChannel] = useState('mobile_app')
  const [counterparty, setCounterparty] = useState('')
  const [direction, setDirection] = useState('outbound')
  const [geoLocation, setGeoLocation] = useState('')

  const timers = useRef<ReturnType<typeof setTimeout>[]>([])

  useEffect(() => {
    if (!isOpen) return
    fetch('/api/proxy?path=' + encodeURIComponent('/customers'))
      .then(r => r.json())
      .then(data => {
        const list: any[] = data.customers || data || []
        const mapped = list.map(c => ({ id: c.id, name: c.name || c.id }))
        setCustomers(mapped)
        if (mapped.length > 0 && !customerId) setCustomerId(mapped[0].id)
      })
      .catch(() => {})
  }, [isOpen])

  function clearTimers() {
    timers.current.forEach(t => clearTimeout(t))
    timers.current = []
  }

  function resetForm() {
    clearTimers()
    setPhase('form')
    setStages(blankStages())
    setResult(null)
    setError(null)
  }

  function handleClose() {
    resetForm()
    onClose()
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!customerId || !amount) return

    setPhase('screening')
    const fresh = blankStages()
    setStages(fresh)

    // Animate stages with progressive delays while waiting for response
    const animDelays = [0, 1000, 2200, 3600, 5100, 6700]
    animDelays.forEach((delay, idx) => {
      const t = setTimeout(() => {
        setStages(prev => prev.map((s, i) =>
          i === idx ? { ...s, status: 'running', statusLabel: RUNNING_LABELS[idx] } : s
        ))
      }, delay)
      timers.current.push(t)
    })

    try {
      const body = {
        customer_id: customerId,
        amount: parseFloat(amount),
        transaction_type: txType,
        channel,
        counterparty_name: counterparty || undefined,
        direction,
        geo_location: geoLocation || undefined,
        timestamp: new Date().toISOString(),
      }

      const res = await fetch('/api/proxy?path=' + encodeURIComponent('/transactions/screen'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })

      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || `Request failed: ${res.status}`)
      }

      const data = await res.json()
      clearTimers()
      setStages(mapResultsToStages(data))
      setResult(data)
      setPhase('complete')
    } catch (err: any) {
      clearTimers()
      setError(err.message)
      setPhase('error')
    }
  }

  const inputCls = 'w-full bg-[#111827] border border-[#1e293b] rounded-lg px-3 py-2.5 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-blue-500'
  const selectCls = 'w-full bg-[#111827] border border-[#1e293b] rounded-lg px-3 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-blue-500'
  const labelCls = 'block text-slate-400 text-xs font-medium mb-1.5'

  return (
    <Modal isOpen={isOpen} onClose={handleClose} title="Screen Transaction" size="xl">

      {/* FORM */}
      {phase === 'form' && (
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="col-span-2">
              <label className={labelCls}>Customer *</label>
              <select value={customerId} onChange={e => setCustomerId(e.target.value)} required className={selectCls}>
                <option value="">Select customer...</option>
                {customers.map(c => (
                  <option key={c.id} value={c.id}>{c.name} ({c.id})</option>
                ))}
              </select>
            </div>

            <div>
              <label className={labelCls}>Amount (NGN) *</label>
              <input
                type="number" value={amount} onChange={e => setAmount(e.target.value)}
                required min="1" placeholder="e.g. 500000"
                className={inputCls}
              />
            </div>

            <div>
              <label className={labelCls}>Transaction Type</label>
              <select value={txType} onChange={e => setTxType(e.target.value)} className={selectCls}>
                <option value="transfer">Transfer</option>
                <option value="cash_deposit">Cash Deposit</option>
                <option value="cash_withdrawal">Cash Withdrawal</option>
                <option value="international_wire">International Wire</option>
                <option value="mobile_money">Mobile Money</option>
              </select>
            </div>

            <div>
              <label className={labelCls}>Channel</label>
              <select value={channel} onChange={e => setChannel(e.target.value)} className={selectCls}>
                <option value="branch">Branch</option>
                <option value="mobile_app">Mobile App</option>
                <option value="internet_banking">Internet Banking</option>
                <option value="atm">ATM</option>
                <option value="pos">POS</option>
              </select>
            </div>

            <div>
              <label className={labelCls}>Direction</label>
              <select value={direction} onChange={e => setDirection(e.target.value)} className={selectCls}>
                <option value="outbound">Outbound</option>
                <option value="inbound">Inbound</option>
              </select>
            </div>

            <div>
              <label className={labelCls}>Counterparty Name</label>
              <input
                type="text" value={counterparty} onChange={e => setCounterparty(e.target.value)}
                placeholder="e.g. John Doe / First Bank"
                className={inputCls}
              />
            </div>

            <div>
              <label className={labelCls}>Geo Location</label>
              <input
                type="text" value={geoLocation} onChange={e => setGeoLocation(e.target.value)}
                placeholder="e.g. Lagos, NG"
                className={inputCls}
              />
            </div>
          </div>

          <div className="flex gap-3 pt-2">
            <button type="button" onClick={handleClose}
              className="flex-1 bg-slate-700 hover:bg-slate-600 text-slate-300 py-2.5 px-4 rounded-lg text-sm font-medium transition-colors">
              Cancel
            </button>
            <button type="submit"
              className="flex-1 flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-500 text-white py-2.5 px-4 rounded-lg text-sm font-medium transition-colors">
              <Play className="w-4 h-4" /> Run AML Pipeline
            </button>
          </div>
        </form>
      )}

      {/* PIPELINE VISUALIZATION */}
      {(phase === 'screening' || phase === 'complete') && (
        <div className="space-y-4">
          <div className="space-y-2">
            {stages.map((stage, idx) => {
              const active = stage.status !== 'pending'
              return (
                <div
                  key={stage.id}
                  className={`flex items-start gap-3 p-3 rounded-lg border transition-all duration-500 ${STATUS_BG[stage.status]}`}
                >
                  {/* Stage number + icon */}
                  <div className="flex items-center gap-2 flex-shrink-0 mt-0.5">
                    <div className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${
                      active && stage.status !== 'skipped'
                        ? BADGE_COLORS[stage.status].replace('bg-', 'bg-').split(' ')[0] + ' ' + BADGE_COLORS[stage.status].split(' ')[1]
                        : 'bg-slate-800 text-slate-500'
                    }`}>{idx + 1}</div>
                    <stage.Icon className={`w-4 h-4 flex-shrink-0 ${
                      stage.status === 'pass' ? 'text-emerald-400'
                      : stage.status === 'warn' ? 'text-amber-400'
                      : stage.status === 'fail' ? 'text-red-400'
                      : stage.status === 'running' ? 'text-blue-400'
                      : 'text-slate-600'
                    }`} />
                  </div>

                  {/* Label + badges + detail */}
                  <div className="flex-1 min-w-0">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className={`text-sm font-medium ${active ? 'text-slate-200' : 'text-slate-500'}`}>
                        {stage.label}
                      </span>
                      {active && (
                        <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${BADGE_COLORS[stage.status]}`}>
                          {stage.status === 'running' && <Loader2 className="w-3 h-3 inline mr-1 animate-spin" />}
                          {stage.statusLabel}
                        </span>
                      )}
                      {stage.govStatus && (
                        <span className={`text-xs px-1.5 py-0.5 rounded border ${
                          stage.govStatus === 'passed' ? 'border-slate-600 text-slate-500'
                          : stage.govStatus === 'escalated' ? 'border-amber-700 text-amber-400'
                          : 'border-red-700 text-red-400'
                        }`}>
                          Gov: {stage.govStatus}
                        </span>
                      )}
                    </div>
                    {stage.detail && (
                      <p className="text-xs text-slate-400 mt-0.5">{stage.detail}</p>
                    )}
                  </div>

                  <div className="flex-shrink-0 mt-0.5">
                    <StageIcon status={stage.status} />
                  </div>
                </div>
              )
            })}
          </div>

          {/* Pending indicator */}
          {phase === 'screening' && (
            <div className="flex items-center justify-center gap-2 py-3 text-slate-400 text-sm">
              <Loader2 className="w-4 h-4 animate-spin" />
              Running 6-agent AML pipeline...
            </div>
          )}

          {/* Final result summary */}
          {phase === 'complete' && result && (
            <div className="border-t border-[#1e293b] pt-4 space-y-4">
              <div className={`rounded-lg border p-4 flex items-center justify-between ${FINAL_STATUS_COLORS[result.final_status] ?? 'text-slate-300 bg-slate-800/30 border-slate-700'}`}>
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wider opacity-70 mb-1">Final Status</p>
                  <p className="text-2xl font-bold uppercase tracking-wide">{result.final_status}</p>
                </div>
                <div className="text-right">
                  <p className="text-xs opacity-70 mb-1">Processing Time</p>
                  <p className="text-lg font-mono">{result.processing_time_ms?.toFixed(0)}ms</p>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                {[
                  ['Risk Score', result.monitor_result ? `${(result.monitor_result.risk_score * 100).toFixed(1)}%` : 'N/A', result.monitor_result?.flagged ? 'text-amber-300' : 'text-emerald-300'],
                  ['Rules Triggered', result.monitor_result?.triggered_rules?.length ?? 0, result.monitor_result?.triggered_rules?.length ? 'text-amber-300' : 'text-emerald-300'],
                  ['SAR Drafted', result.sar_result ? 'Yes (pending review)' : 'No', result.sar_result ? 'text-amber-300' : 'text-emerald-300'],
                  ['Case Created', result.case_result ? 'Yes' : 'No', result.case_result ? 'text-amber-300' : 'text-emerald-300'],
                ].map(([label, value, color]) => (
                  <div key={String(label)} className="bg-slate-800/40 rounded-lg p-3">
                    <p className="text-slate-500 text-xs mb-1">{label}</p>
                    <p className={`text-base font-bold ${color}`}>{String(value)}</p>
                  </div>
                ))}
              </div>

              {result.monitor_result?.triggered_rules?.length > 0 && (
                <div>
                  <h4 className="text-slate-400 text-xs font-semibold uppercase tracking-wider mb-2">Triggered Rules</h4>
                  <div className="space-y-1.5">
                    {result.monitor_result.triggered_rules.map((rule: any, i: number) => (
                      <div key={i} className="bg-amber-900/10 border border-amber-800/30 rounded px-3 py-2 flex items-start gap-2">
                        <AlertTriangle className="w-3.5 h-3.5 text-amber-500 flex-shrink-0 mt-0.5" />
                        <div>
                          <p className="text-amber-300 text-xs font-medium">{rule.rule}</p>
                          {rule.description && <p className="text-slate-400 text-xs">{rule.description}</p>}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {result.pattern_result?.patterns_detected?.length > 0 && (
                <div>
                  <h4 className="text-slate-400 text-xs font-semibold uppercase tracking-wider mb-2">Patterns Detected</h4>
                  <div className="space-y-1.5">
                    {result.pattern_result.patterns_detected.map((p: any, i: number) => (
                      <div key={i} className="bg-red-900/10 border border-red-800/30 rounded px-3 py-2">
                        <p className="text-red-300 text-xs font-medium">{p.pattern_name}</p>
                        {p.description && <p className="text-slate-400 text-xs">{p.description}</p>}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div className="flex gap-3">
                <button onClick={resetForm}
                  className="flex-1 bg-slate-700 hover:bg-slate-600 text-slate-300 py-2.5 px-4 rounded-lg text-sm font-medium transition-colors">
                  Screen Another
                </button>
                <button onClick={handleClose}
                  className="flex-1 bg-blue-600 hover:bg-blue-500 text-white py-2.5 px-4 rounded-lg text-sm font-medium transition-colors">
                  Done
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ERROR */}
      {phase === 'error' && (
        <div className="space-y-4">
          <div className="bg-red-900/20 border border-red-800 rounded-lg p-4">
            <p className="text-red-400 font-medium mb-1">Screening Failed</p>
            <p className="text-red-300 text-sm">{error}</p>
          </div>
          <div className="flex gap-3">
            <button onClick={resetForm}
              className="flex-1 bg-slate-700 hover:bg-slate-600 text-slate-300 py-2.5 px-4 rounded-lg text-sm font-medium transition-colors">
              Try Again
            </button>
            <button onClick={handleClose}
              className="flex-1 bg-red-700 hover:bg-red-600 text-white py-2.5 px-4 rounded-lg text-sm font-medium transition-colors">
              Close
            </button>
          </div>
        </div>
      )}
    </Modal>
  )
}
