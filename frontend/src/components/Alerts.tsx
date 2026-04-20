// Alerts tab - alert queue with severity filtering and action buttons
'use client'
import { useEffect, useState } from 'react'
import { Search, Filter, RefreshCw } from 'lucide-react'
import Card from './ui/Card'
import { Table, Thead, Th, Tbody, Tr, Td } from './ui/Table'
import { SeverityBadge, StatusBadge } from './ui/Badge'
import Modal from './ui/Modal'
import { CustomerMap, getCustomerMap, formatCustomer } from '@/lib/customerLookup'

async function fetchAPI(path: string, body?: any) {
  if (body) {
    const res = await fetch(`/api/proxy?path=${encodeURIComponent(path)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    return res.json()
  }
  const res = await fetch(`/api/proxy?path=${encodeURIComponent(path)}`)
  return res.json()
}

function formatWAT(isoDate: string) {
  return new Date(isoDate).toLocaleString('en-NG', { timeZone: 'Africa/Lagos', dateStyle: 'short', timeStyle: 'short' })
}

interface Alert {
  id: string
  alert_id?: string
  customer_id: string
  alert_type: string
  severity: string
  agent_source: string
  status: string
  confidence: number
  recommended_action: string
  rationale: string
  transaction_id?: string
  created_at: string
}

export default function Alerts() {
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [filtered, setFiltered] = useState<Alert[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [severityFilter, setSeverityFilter] = useState('all')
  const [selected, setSelected] = useState<Alert | null>(null)
  const [actionRationale, setActionRationale] = useState('')
  const [actionLoading, setActionLoading] = useState(false)
  const [customerMap, setCustomerMap] = useState<CustomerMap>({})

  function load() {
    setLoading(true)
    fetchAPI('/alerts')
      .then(res => {
        const list = res.alerts || res || []
        setAlerts(list)
        setFiltered(list)
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
    getCustomerMap().then(setCustomerMap)
  }

  useEffect(load, [])

  useEffect(() => {
    let result = [...alerts]
    if (search) {
      const q = search.toLowerCase()
      result = result.filter(a =>
        (a.id || a.alert_id || '').toLowerCase().includes(q) ||
        a.customer_id?.toLowerCase().includes(q) ||
        formatCustomer(a.customer_id, customerMap).toLowerCase().includes(q) ||
        a.alert_type?.toLowerCase().includes(q)
      )
    }
    if (statusFilter !== 'all') result = result.filter(a => a.status === statusFilter)
    if (severityFilter !== 'all') result = result.filter(a => a.severity === severityFilter)
    setFiltered(result)
  }, [alerts, search, statusFilter, severityFilter, customerMap])

  async function updateStatus(alertId: string, newStatus: string) {
    setActionLoading(true)
    try {
      await fetchAPI(`/alerts/${alertId}/status`, {
        status: newStatus,
        rationale: actionRationale || `Status updated to ${newStatus}`,
      })
      load()
      setSelected(null)
      setActionRationale('')
    } catch (e: any) {
      alert('Failed to update alert: ' + e.message)
    } finally {
      setActionLoading(false)
    }
  }

  if (loading) return <div className="flex justify-center items-center h-64 text-slate-400">Loading alerts...</div>
  if (error) return <div className="bg-red-900/20 border border-red-800 rounded-xl p-6 text-red-400">{error}</div>

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex flex-wrap gap-3 items-center">
        <div className="relative">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            type="text"
            placeholder="Search alerts..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="bg-[#111827] border border-[#1e293b] rounded-lg pl-9 pr-4 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500 w-64"
          />
        </div>
        <Filter className="w-4 h-4 text-slate-500" />
        <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}
          className="bg-[#111827] border border-[#1e293b] rounded-lg px-3 py-2 text-sm text-slate-300 focus:outline-none focus:border-blue-500">
          <option value="all">All Statuses</option>
          <option value="open">Open</option>
          <option value="investigating">Investigating</option>
          <option value="resolved">Resolved</option>
        </select>
        <select value={severityFilter} onChange={e => setSeverityFilter(e.target.value)}
          className="bg-[#111827] border border-[#1e293b] rounded-lg px-3 py-2 text-sm text-slate-300 focus:outline-none focus:border-blue-500">
          <option value="all">All Severities</option>
          <option value="critical">Critical</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
        <button onClick={load} className="ml-auto flex items-center gap-2 text-slate-400 hover:text-slate-200 text-sm">
          <RefreshCw className="w-4 h-4" /> Refresh
        </button>
        <span className="text-slate-500 text-sm">{filtered.length} alerts</span>
      </div>

      <Card>
        <Table>
          <Thead>
            <tr>
              <Th>Alert ID</Th>
              <Th>Customer</Th>
              <Th>Type</Th>
              <Th>Severity</Th>
              <Th>Agent Source</Th>
              <Th>Confidence</Th>
              <Th>Status</Th>
              <Th>Created (WAT)</Th>
            </tr>
          </Thead>
          <Tbody>
            {filtered.length === 0 ? (
              <Tr><Td className="text-slate-500 text-center py-12">No alerts match your filters.</Td></Tr>
            ) : (
              filtered.map(alert => (
                <Tr key={alert.id || alert.alert_id} onClick={() => setSelected(alert)}>
                  <Td><code className="text-blue-400 text-xs">{(alert.id || alert.alert_id || '').substring(0, 16)}</code></Td>
                  <Td><span className="text-slate-300">{formatCustomer(alert.customer_id, customerMap)}</span></Td>
                  <Td><span className="text-slate-400 text-xs">{alert.alert_type?.replace(/_/g, ' ')}</span></Td>
                  <Td><SeverityBadge severity={alert.severity} /></Td>
                  <Td><span className="text-slate-500 text-xs">{alert.agent_source}</span></Td>
                  <Td><span className="text-slate-300 text-sm">{alert.confidence != null ? `${(alert.confidence * 100).toFixed(0)}%` : 'N/A'}</span></Td>
                  <Td><StatusBadge status={alert.status} /></Td>
                  <Td><span className="text-slate-500 text-xs">{alert.created_at ? formatWAT(alert.created_at) : 'N/A'}</span></Td>
                </Tr>
              ))
            )}
          </Tbody>
        </Table>
      </Card>

      {/* Alert detail modal */}
      <Modal isOpen={!!selected} onClose={() => { setSelected(null); setActionRationale('') }} title="Alert Details" size="xl">
        {selected && (
          <div className="space-y-6">
            <div className="grid grid-cols-2 gap-4">
              {[
                ['Alert ID', selected.id || selected.alert_id],
                ['Customer', formatCustomer(selected.customer_id, customerMap)],
                ['Type', selected.alert_type],
                ['Severity', selected.severity],
                ['Agent Source', selected.agent_source],
                ['Confidence', selected.confidence != null ? `${(selected.confidence * 100).toFixed(1)}%` : 'N/A'],
                ['Status', selected.status],
                ['Transaction ID', selected.transaction_id || 'N/A'],
                ['Created (WAT)', selected.created_at ? formatWAT(selected.created_at) : 'N/A'],
              ].map(([label, value]) => (
                <div key={label} className="bg-slate-700/40 rounded-lg p-3">
                  <p className="text-slate-500 text-xs mb-1">{label}</p>
                  <p className="text-slate-200 text-sm font-medium">{value}</p>
                </div>
              ))}
            </div>

            {selected.rationale && (
              <div>
                <h4 className="text-slate-400 text-xs font-semibold uppercase tracking-wider mb-2">AI Rationale</h4>
                <p className="bg-[#0a1120] rounded-lg p-4 text-sm text-slate-300">{selected.rationale}</p>
              </div>
            )}

            {selected.recommended_action && (
              <div>
                <h4 className="text-slate-400 text-xs font-semibold uppercase tracking-wider mb-2">Recommended Action</h4>
                <p className="bg-blue-900/20 border border-blue-800 rounded-lg p-4 text-sm text-blue-300">{selected.recommended_action}</p>
              </div>
            )}

            {/* Action buttons */}
            {selected.status === 'open' && (
              <div className="border-t border-[#1e293b] pt-4">
                <h4 className="text-slate-400 text-xs font-semibold uppercase tracking-wider mb-3">Take Action</h4>
                <textarea
                  value={actionRationale}
                  onChange={e => setActionRationale(e.target.value)}
                  placeholder="Enter rationale for this action (required for audit trail)..."
                  className="w-full bg-[#0a1120] border border-[#1e293b] rounded-lg p-3 text-sm text-slate-300 placeholder-slate-600 focus:outline-none focus:border-blue-500 mb-3 h-24 resize-none"
                />
                <div className="flex gap-3">
                  <button
                    onClick={() => updateStatus(selected.id || selected.alert_id, 'investigating')}
                    disabled={actionLoading}
                    className="flex-1 bg-blue-600 hover:bg-blue-500 text-white py-2 px-4 rounded-lg text-sm font-medium disabled:opacity-50 transition-colors"
                  >
                    Investigate
                  </button>
                  <button
                    onClick={() => updateStatus(selected.id || selected.alert_id, 'resolved')}
                    disabled={actionLoading}
                    className="flex-1 bg-emerald-600 hover:bg-emerald-500 text-white py-2 px-4 rounded-lg text-sm font-medium disabled:opacity-50 transition-colors"
                  >
                    Resolve
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  )
}
