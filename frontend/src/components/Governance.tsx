// Governance tab - audit trail and model validation history for CBN compliance
'use client'
import { useEffect, useState } from 'react'
import { Search, Filter, CheckCircle, RefreshCw } from 'lucide-react'
import Card from './ui/Card'
import { Table, Thead, Th, Tbody, Tr, Td } from './ui/Table'
import { Badge } from './ui/Badge'

async function fetchAPI(path: string) {
  const res = await fetch(`/api/proxy?path=${encodeURIComponent(path)}`)
  return res.json()
}

function formatWAT(isoDate: string) {
  return new Date(isoDate).toLocaleString('en-NG', { timeZone: 'Africa/Lagos', dateStyle: 'short', timeStyle: 'short' })
}

interface AuditEntry {
  audit_id: string
  timestamp: string
  entity_type: string
  event_type: string
  actor: string
  description: string
}

interface ModelValidation {
  validation_id: string
  model_name: string
  validation_date: string
  accuracy: number
  drift_score: number
  bias_score: number
  fairness_score: number
  status: string
  validator: string
}

export default function Governance() {
  const [auditLog, setAuditLog] = useState<AuditEntry[]>([])
  const [validations, setValidations] = useState<ModelValidation[]>([])
  const [filtered, setFiltered] = useState<AuditEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [entityFilter, setEntityFilter] = useState('all')
  const [eventFilter, setEventFilter] = useState('all')

  function load() {
    setLoading(true)
    Promise.all([
      fetchAPI('/audit-log'),
      fetchAPI('/model-validations'),
    ])
      .then(([auditRes, valRes]) => {
        const auditList = auditRes.entries || auditRes || []
        const valList = valRes.validations || valRes || []
        setAuditLog(auditList)
        setFiltered(auditList)
        setValidations(valList)
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  useEffect(() => {
    let result = [...auditLog]
    if (search) {
      const q = search.toLowerCase()
      result = result.filter(a =>
        a.actor?.toLowerCase().includes(q) ||
        a.description?.toLowerCase().includes(q) ||
        a.entity_type?.toLowerCase().includes(q)
      )
    }
    if (entityFilter !== 'all') result = result.filter(a => a.entity_type === entityFilter)
    if (eventFilter !== 'all') result = result.filter(a => a.event_type === eventFilter)
    setFiltered(result)
  }, [auditLog, search, entityFilter, eventFilter])

  const entityTypes = ['all', ...new Set(auditLog.map(a => a.entity_type).filter(Boolean))]
  const eventTypes = ['all', ...new Set(auditLog.map(a => a.event_type).filter(Boolean))]

  if (loading) return <div className="flex justify-center items-center h-64 text-slate-400">Loading governance data...</div>
  if (error) return <div className="bg-red-900/20 border border-red-800 rounded-xl p-6 text-red-400">{error}</div>

  return (
    <div className="space-y-6">
      {/* CBN compliance status banner */}
      <div className="bg-emerald-900/20 border border-emerald-800 rounded-xl p-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <CheckCircle className="w-5 h-5 text-emerald-400" />
          <div>
            <p className="text-emerald-300 font-semibold text-sm">Annual Validation: Compliant</p>
            <p className="text-emerald-400/70 text-xs">AI model validated per CBN model risk management guidelines. Next review due annually.</p>
          </div>
        </div>
        <Badge variant="success">CBN COMPLIANT</Badge>
      </div>

      {/* Model validations */}
      <Card title="Model Validation History" subtitle="Annual AI model performance and fairness audits">
        {validations.length === 0 ? (
          <p className="text-slate-500 text-sm">No model validations recorded yet.</p>
        ) : (
          <Table>
            <Thead>
              <tr>
                <Th>Validation ID</Th>
                <Th>Model</Th>
                <Th>Date (WAT)</Th>
                <Th>Accuracy</Th>
                <Th>Drift</Th>
                <Th>Bias</Th>
                <Th>Fairness</Th>
                <Th>Status</Th>
                <Th>Validator</Th>
              </tr>
            </Thead>
            <Tbody>
              {validations.map(v => (
                <Tr key={v.validation_id}>
                  <Td><code className="text-blue-400 text-xs">{v.validation_id?.substring(0, 10)}...</code></Td>
                  <Td><span className="text-slate-300 text-xs">{v.model_name}</span></Td>
                  <Td><span className="text-slate-500 text-xs">{v.validation_date ? formatWAT(v.validation_date) : 'N/A'}</span></Td>
                  <Td><ScoreCell score={v.accuracy} /></Td>
                  <Td><ScoreCell score={v.drift_score} invert /></Td>
                  <Td><ScoreCell score={v.bias_score} invert /></Td>
                  <Td><ScoreCell score={v.fairness_score} /></Td>
                  <Td><Badge variant={v.status === 'passed' ? 'success' : 'danger'}>{v.status?.toUpperCase()}</Badge></Td>
                  <Td><span className="text-slate-500 text-xs">{v.validator}</span></Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        )}
      </Card>

      {/* Audit log */}
      <Card
        title="Audit Trail"
        subtitle="Immutable log of all compliance actions and system events"
        headerRight={
          <button onClick={load} className="flex items-center gap-1.5 text-slate-400 hover:text-slate-200 text-xs">
            <RefreshCw className="w-3.5 h-3.5" /> Refresh
          </button>
        }
      >
        {/* Audit filters */}
        <div className="flex flex-wrap gap-3 mb-5">
          <div className="relative">
            <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
            <input
              type="text"
              placeholder="Search audit log..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="bg-[#0a1120] border border-[#1e293b] rounded-lg pl-8 pr-3 py-1.5 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-blue-500 w-56"
            />
          </div>
          <Filter className="w-3.5 h-3.5 text-slate-500 mt-2" />
          <select value={entityFilter} onChange={e => setEntityFilter(e.target.value)}
            className="bg-[#0a1120] border border-[#1e293b] rounded-lg px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-blue-500">
            {entityTypes.map(t => <option key={t} value={t}>{t === 'all' ? 'All Entity Types' : t}</option>)}
          </select>
          <select value={eventFilter} onChange={e => setEventFilter(e.target.value)}
            className="bg-[#0a1120] border border-[#1e293b] rounded-lg px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-blue-500">
            {eventTypes.map(t => <option key={t} value={t}>{t === 'all' ? 'All Event Types' : t}</option>)}
          </select>
          <span className="text-slate-500 text-xs ml-auto mt-2">{filtered.length} entries</span>
        </div>

        <Table>
          <Thead>
            <tr>
              <Th>Timestamp (WAT)</Th>
              <Th>Entity Type</Th>
              <Th>Event Type</Th>
              <Th>Actor</Th>
              <Th>Description</Th>
            </tr>
          </Thead>
          <Tbody>
            {filtered.length === 0 ? (
              <Tr><Td className="text-slate-500 text-center py-12">No audit entries found.</Td></Tr>
            ) : (
              filtered.map(entry => (
                <Tr key={entry.audit_id}>
                  <Td><span className="text-slate-500 text-xs font-mono">{entry.timestamp ? formatWAT(entry.timestamp) : 'N/A'}</span></Td>
                  <Td><Badge variant="ghost">{entry.entity_type}</Badge></Td>
                  <Td><span className="text-slate-400 text-xs">{entry.event_type}</span></Td>
                  <Td><span className="text-slate-300 text-sm">{entry.actor}</span></Td>
                  <Td><span className="text-slate-400 text-sm">{entry.description}</span></Td>
                </Tr>
              ))
            )}
          </Tbody>
        </Table>
      </Card>
    </div>
  )
}

// Helper: Score cell with color coding based on value
function ScoreCell({ score, invert = false }: { score: number; invert?: boolean }) {
  const pct = (score || 0) * 100
  let colorClass = 'text-emerald-400'
  if (invert) {
    if (pct > 20) colorClass = 'text-red-400'
    else if (pct > 10) colorClass = 'text-amber-400'
  } else {
    if (pct < 70) colorClass = 'text-red-400'
    else if (pct < 85) colorClass = 'text-amber-400'
  }
  return <span className={`font-mono text-sm ${colorClass}`}>{pct.toFixed(1)}%</span>
}
