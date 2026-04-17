// Cases tab - case management with SLA tracking and priority indicators
'use client'
import { useEffect, useState } from 'react'
import { Search, Clock, RefreshCw } from 'lucide-react'
import Card from './ui/Card'
import { Table, Thead, Th, Tbody, Tr, Td } from './ui/Table'
import { PriorityBadge, StatusBadge } from './ui/Badge'
import Modal from './ui/Modal'

async function fetchAPI(path: string) {
  const res = await fetch(`/api/proxy?path=${encodeURIComponent(path)}`)
  return res.json()
}

function formatWAT(isoDate: string) {
  return new Date(isoDate).toLocaleString('en-NG', { timeZone: 'Africa/Lagos', dateStyle: 'short', timeStyle: 'short' })
}

// Calculate SLA countdown from due date
function SLACountdown({ slaDate }: { slaDate: string }) {
  const now = new Date()
  const due = new Date(slaDate)
  const diffMs = due.getTime() - now.getTime()
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60))
  const diffDays = Math.floor(diffHours / 24)

  if (diffMs < 0) return <span className="text-red-400 text-xs font-medium">SLA BREACHED</span>
  if (diffHours < 24) return <span className="text-amber-400 text-xs font-medium">{diffHours}h remaining</span>
  return <span className="text-emerald-400 text-xs">{diffDays}d {diffHours % 24}h remaining</span>
}

interface Case {
  case_id: string
  customer_id: string
  case_type: string
  priority: string
  status: string
  assigned_to: string
  sla_due_date: string
  created_at: string
  description?: string
}

export default function Cases() {
  const [cases, setCases] = useState<Case[]>([])
  const [filtered, setFiltered] = useState<Case[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [priorityFilter, setPriorityFilter] = useState('all')
  const [selected, setSelected] = useState<Case | null>(null)

  function load() {
    setLoading(true)
    fetchAPI('/cases')
      .then(res => {
        const list = res.cases || res || []
        setCases(list)
        setFiltered(list)
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  useEffect(() => {
    let result = [...cases]
    if (search) {
      const q = search.toLowerCase()
      result = result.filter(c =>
        c.case_id?.toLowerCase().includes(q) ||
        c.customer_id?.toLowerCase().includes(q) ||
        c.case_type?.toLowerCase().includes(q)
      )
    }
    if (statusFilter !== 'all') result = result.filter(c => c.status === statusFilter)
    if (priorityFilter !== 'all') result = result.filter(c => c.priority === priorityFilter)
    setFiltered(result)
  }, [cases, search, statusFilter, priorityFilter])

  if (loading) return <div className="flex justify-center items-center h-64 text-slate-400">Loading cases...</div>
  if (error) return <div className="bg-red-900/20 border border-red-800 rounded-xl p-6 text-red-400">{error}</div>

  const breachedCount = cases.filter(c => c.sla_due_date && new Date(c.sla_due_date) < new Date() && c.status !== 'closed').length

  return (
    <div className="space-y-4">
      {/* SLA breach warning */}
      {breachedCount > 0 && (
        <div className="bg-red-900/30 border border-red-700/50 rounded-xl p-4 flex items-center gap-3">
          <Clock className="w-5 h-5 text-red-400 flex-shrink-0" />
          <p className="text-red-300 text-sm">
            <span className="font-semibold">{breachedCount} case{breachedCount > 1 ? 's' : ''}</span> have breached SLA and require immediate attention.
          </p>
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap gap-3 items-center">
        <div className="relative">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            type="text"
            placeholder="Search cases..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="bg-[#111827] border border-[#1e293b] rounded-lg pl-9 pr-4 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500 w-64"
          />
        </div>
        <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}
          className="bg-[#111827] border border-[#1e293b] rounded-lg px-3 py-2 text-sm text-slate-300 focus:outline-none focus:border-blue-500">
          <option value="all">All Statuses</option>
          <option value="open">Open</option>
          <option value="investigating">Investigating</option>
          <option value="pending_review">Pending Review</option>
          <option value="closed">Closed</option>
        </select>
        <select value={priorityFilter} onChange={e => setPriorityFilter(e.target.value)}
          className="bg-[#111827] border border-[#1e293b] rounded-lg px-3 py-2 text-sm text-slate-300 focus:outline-none focus:border-blue-500">
          <option value="all">All Priorities</option>
          <option value="critical">Critical</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
        <button onClick={load} className="ml-auto flex items-center gap-2 text-slate-400 hover:text-slate-200 text-sm">
          <RefreshCw className="w-4 h-4" /> Refresh
        </button>
        <span className="text-slate-500 text-sm">{filtered.length} cases</span>
      </div>

      <Card>
        <Table>
          <Thead>
            <tr>
              <Th>Case ID</Th>
              <Th>Customer</Th>
              <Th>Type</Th>
              <Th>Priority</Th>
              <Th>Status</Th>
              <Th>Assigned To</Th>
              <Th>SLA</Th>
              <Th>Created (WAT)</Th>
            </tr>
          </Thead>
          <Tbody>
            {filtered.length === 0 ? (
              <Tr><Td className="text-slate-500 text-center py-12">No cases match your filters.</Td></Tr>
            ) : (
              filtered.map(c => (
                <Tr key={c.case_id} onClick={() => setSelected(c)}>
                  <Td><code className="text-blue-400 text-xs">{c.case_id?.substring(0, 12)}...</code></Td>
                  <Td><span className="text-slate-300">{c.customer_id}</span></Td>
                  <Td><span className="text-slate-400 text-xs">{c.case_type?.replace(/_/g, ' ')}</span></Td>
                  <Td><PriorityBadge priority={c.priority} /></Td>
                  <Td><StatusBadge status={c.status} /></Td>
                  <Td><span className="text-slate-400 text-xs">{c.assigned_to}</span></Td>
                  <Td>{c.sla_due_date ? <SLACountdown slaDate={c.sla_due_date} /> : <span className="text-slate-600 text-xs">No SLA</span>}</Td>
                  <Td><span className="text-slate-500 text-xs">{c.created_at ? formatWAT(c.created_at) : 'N/A'}</span></Td>
                </Tr>
              ))
            )}
          </Tbody>
        </Table>
      </Card>

      {/* Case detail modal */}
      <Modal isOpen={!!selected} onClose={() => setSelected(null)} title="Case Details" size="lg">
        {selected && (
          <div className="space-y-6">
            <div className="grid grid-cols-2 gap-4">
              {[
                ['Case ID', selected.case_id],
                ['Customer ID', selected.customer_id],
                ['Type', selected.case_type?.replace(/_/g, ' ')],
                ['Priority', selected.priority],
                ['Status', selected.status],
                ['Assigned To', selected.assigned_to],
                ['SLA Due Date (WAT)', selected.sla_due_date ? formatWAT(selected.sla_due_date) : 'N/A'],
                ['Created (WAT)', selected.created_at ? formatWAT(selected.created_at) : 'N/A'],
              ].map(([label, value]) => (
                <div key={label} className="bg-slate-700/40 rounded-lg p-3">
                  <p className="text-slate-500 text-xs mb-1">{label}</p>
                  <p className="text-slate-200 text-sm font-medium">{value}</p>
                </div>
              ))}
            </div>
            {selected.description && (
              <div>
                <h4 className="text-slate-400 text-xs font-semibold uppercase tracking-wider mb-2">Description</h4>
                <p className="bg-[#0a1120] rounded-lg p-4 text-sm text-slate-300">{selected.description}</p>
              </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  )
}
