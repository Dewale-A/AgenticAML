// SARs tab - SAR queue with mandatory human approval workflow (CBN requirement)
'use client'
import { useEffect, useState } from 'react'
import { AlertTriangle, Search, RefreshCw, CheckCircle, XCircle } from 'lucide-react'
import Card from './ui/Card'
import { Table, Thead, Th, Tbody, Tr, Td } from './ui/Table'
import { Badge, StatusBadge } from './ui/Badge'
import Modal from './ui/Modal'
import { CustomerMap, getCustomerMap, formatCustomer } from '@/lib/customerLookup'

async function fetchAPI(path: string, body?: any, method = 'POST') {
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
  return new Date(isoDate).toLocaleString('en-NG', { timeZone: 'Africa/Lagos', dateStyle: 'short', timeStyle: 'short' })
}

function PriorityBadge({ priority }: { priority: string }) {
  const map: Record<string, 'danger' | 'warning' | 'info' | 'ghost'> = {
    critical: 'danger', high: 'warning', medium: 'info', low: 'ghost',
  }
  return <Badge variant={map[priority?.toLowerCase()] || 'ghost'}>{priority?.toUpperCase()}</Badge>
}

interface SAR {
  sar_id: string
  customer_id: string
  typology: string
  priority: string
  status: string
  drafted_by: string
  approved_by?: string
  nfiu_reference?: string
  narrative?: string
  evidence_summary?: string
  created_at: string
}

export default function SARs() {
  const [sars, setSars] = useState<SAR[]>([])
  const [filtered, setFiltered] = useState<SAR[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [selected, setSelected] = useState<SAR | null>(null)
  const [approvalRationale, setApprovalRationale] = useState('')
  const [actionLoading, setActionLoading] = useState(false)
  const [customerMap, setCustomerMap] = useState<CustomerMap>({})

  function load() {
    setLoading(true)
    fetchAPI('/sars')
      .then(res => {
        const list = res.sars || res || []
        setSars(list)
        setFiltered(list)
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
    getCustomerMap().then(setCustomerMap)
  }

  useEffect(load, [])

  useEffect(() => {
    let result = [...sars]
    if (search) {
      const q = search.toLowerCase()
      result = result.filter(s =>
        s.sar_id?.toLowerCase().includes(q) ||
        s.customer_id?.toLowerCase().includes(q) ||
        formatCustomer(s.customer_id, customerMap).toLowerCase().includes(q) ||
        s.typology?.toLowerCase().includes(q)
      )
    }
    if (statusFilter !== 'all') result = result.filter(s => s.status === statusFilter)
    setFiltered(result)
  }, [sars, search, statusFilter, customerMap])

  async function handleApproval(sarId: string, action: 'approve' | 'reject') {
    if (!approvalRationale.trim()) {
      alert('Rationale is required for SAR approval/rejection (CBN requirement).')
      return
    }
    setActionLoading(true)
    try {
      await fetchAPI(`/sars/${sarId}/${action}`, {
        rationale: approvalRationale,
        reviewed_by: 'compliance_officer',
      })
      load()
      setSelected(null)
      setApprovalRationale('')
    } catch (e: any) {
      alert('Action failed: ' + e.message)
    } finally {
      setActionLoading(false)
    }
  }

  if (loading) return <div className="flex justify-center items-center h-64 text-slate-400">Loading SAR queue...</div>
  if (error) return <div className="bg-red-900/20 border border-red-800 rounded-xl p-6 text-red-400">{error}</div>

  const pendingCount = sars.filter(s => s.status === 'draft').length

  return (
    <div className="space-y-4">
      {/* Human approval required banner */}
      {pendingCount > 0 && (
        <div className="bg-amber-900/30 border border-amber-700/50 rounded-xl p-4 flex items-center gap-3">
          <AlertTriangle className="w-5 h-5 text-amber-400 flex-shrink-0" />
          <div>
            <p className="text-amber-300 font-semibold text-sm">HUMAN APPROVAL REQUIRED</p>
            <p className="text-amber-400/80 text-xs">
              {pendingCount} SAR{pendingCount > 1 ? 's' : ''} pending human review. CBN guidelines require compliance officer approval before NFIU filing.
            </p>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap gap-3 items-center">
        <div className="relative">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            type="text"
            placeholder="Search SARs..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="bg-[#111827] border border-[#1e293b] rounded-lg pl-9 pr-4 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500 w-64"
          />
        </div>
        <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}
          className="bg-[#111827] border border-[#1e293b] rounded-lg px-3 py-2 text-sm text-slate-300 focus:outline-none focus:border-blue-500">
          <option value="all">All Statuses</option>
          <option value="draft">Draft (Pending Review)</option>
          <option value="approved">Approved</option>
          <option value="filed">Filed</option>
          <option value="rejected">Rejected</option>
        </select>
        <button onClick={load} className="ml-auto flex items-center gap-2 text-slate-400 hover:text-slate-200 text-sm">
          <RefreshCw className="w-4 h-4" /> Refresh
        </button>
        <span className="text-slate-500 text-sm">{filtered.length} SARs</span>
      </div>

      <Card>
        <Table>
          <Thead>
            <tr>
              <Th>SAR ID</Th>
              <Th>Customer</Th>
              <Th>Typology</Th>
              <Th>Priority</Th>
              <Th>Status</Th>
              <Th>Drafted By</Th>
              <Th>Approved By</Th>
              <Th>NFIU Ref</Th>
            </tr>
          </Thead>
          <Tbody>
            {filtered.length === 0 ? (
              <Tr><Td className="text-slate-500 text-center py-12">No SARs found.</Td></Tr>
            ) : (
              filtered.map(sar => (
                <Tr key={sar.sar_id} onClick={() => setSelected(sar)}>
                  <Td><code className="text-blue-400 text-xs">{sar.sar_id?.substring(0, 12)}...</code></Td>
                  <Td><span className="text-slate-300">{formatCustomer(sar.customer_id, customerMap)}</span></Td>
                  <Td><span className="text-slate-400 text-xs">{sar.typology?.replace(/_/g, ' ')}</span></Td>
                  <Td><PriorityBadge priority={sar.priority} /></Td>
                  <Td>
                    <div className="flex items-center gap-2">
                      <StatusBadge status={sar.status} />
                      {sar.status === 'draft' && <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />}
                    </div>
                  </Td>
                  <Td><span className="text-slate-500 text-xs">{sar.drafted_by}</span></Td>
                  <Td><span className="text-slate-500 text-xs">{sar.approved_by || 'Pending'}</span></Td>
                  <Td><span className="text-slate-400 text-xs font-mono">{sar.nfiu_reference || '-'}</span></Td>
                </Tr>
              ))
            )}
          </Tbody>
        </Table>
      </Card>

      {/* SAR detail modal */}
      <Modal isOpen={!!selected} onClose={() => { setSelected(null); setApprovalRationale('') }} title="SAR Details" size="xl">
        {selected && (
          <div className="space-y-6">
            {/* Pending approval banner */}
            {selected.status === 'draft' && (
              <div className="bg-amber-900/30 border border-amber-700/50 rounded-lg p-4 flex items-center gap-3">
                <AlertTriangle className="w-5 h-5 text-amber-400" />
                <div>
                  <p className="text-amber-300 font-semibold text-sm">HUMAN APPROVAL REQUIRED</p>
                  <p className="text-amber-400/80 text-xs">This SAR requires compliance officer review before NFIU filing.</p>
                </div>
              </div>
            )}

            {/* Filed reference */}
            {selected.nfiu_reference && (
              <div className="bg-emerald-900/20 border border-emerald-800 rounded-lg p-4">
                <p className="text-emerald-400 text-xs font-semibold uppercase tracking-wider mb-1">NFIU Reference Number</p>
                <p className="text-emerald-300 font-mono text-lg">{selected.nfiu_reference}</p>
              </div>
            )}

            <div className="grid grid-cols-2 gap-4">
              {[
                ['SAR ID', selected.sar_id],
                ['Customer', formatCustomer(selected.customer_id, customerMap)],
                ['Typology', selected.typology?.replace(/_/g, ' ')],
                ['Priority', selected.priority],
                ['Status', selected.status],
                ['Drafted By', selected.drafted_by],
                ['Approved By', selected.approved_by || 'Pending'],
                ['Created (WAT)', selected.created_at ? formatWAT(selected.created_at) : 'N/A'],
              ].map(([label, value]) => (
                <div key={label} className="bg-slate-700/40 rounded-lg p-3">
                  <p className="text-slate-500 text-xs mb-1">{label}</p>
                  <p className="text-slate-200 text-sm font-medium">{value}</p>
                </div>
              ))}
            </div>

            {selected.narrative && (
              <div>
                <h4 className="text-slate-400 text-xs font-semibold uppercase tracking-wider mb-2">SAR Narrative</h4>
                <div className="bg-[#0a1120] rounded-lg p-4 text-sm text-slate-300 leading-relaxed max-h-48 overflow-y-auto">
                  {selected.narrative}
                </div>
              </div>
            )}

            {selected.evidence_summary && (
              <div>
                <h4 className="text-slate-400 text-xs font-semibold uppercase tracking-wider mb-2">Evidence Summary</h4>
                <div className="bg-[#0a1120] rounded-lg p-4 text-sm text-slate-400 leading-relaxed">
                  {selected.evidence_summary}
                </div>
              </div>
            )}

            {/* Approval / rejection controls for draft SARs */}
            {selected.status === 'draft' && (
              <div className="border-t border-[#1e293b] pt-4">
                <h4 className="text-slate-400 text-xs font-semibold uppercase tracking-wider mb-3">
                  Compliance Officer Decision
                  <span className="text-red-400 ml-1">*</span>
                </h4>
                <textarea
                  value={approvalRationale}
                  onChange={e => setApprovalRationale(e.target.value)}
                  placeholder="Rationale is mandatory (CBN requirement). Explain your approval or rejection decision..."
                  className="w-full bg-[#0a1120] border border-[#1e293b] rounded-lg p-3 text-sm text-slate-300 placeholder-slate-600 focus:outline-none focus:border-blue-500 mb-3 h-28 resize-none"
                />
                <div className="flex gap-3">
                  <button
                    onClick={() => handleApproval(selected.sar_id, 'approve')}
                    disabled={actionLoading || !approvalRationale.trim()}
                    className="flex-1 flex items-center justify-center gap-2 bg-emerald-700 hover:bg-emerald-600 text-white py-2.5 px-4 rounded-lg text-sm font-medium disabled:opacity-50 transition-colors"
                  >
                    <CheckCircle className="w-4 h-4" /> Approve for Filing
                  </button>
                  <button
                    onClick={() => handleApproval(selected.sar_id, 'reject')}
                    disabled={actionLoading || !approvalRationale.trim()}
                    className="flex-1 flex items-center justify-center gap-2 bg-red-700 hover:bg-red-600 text-white py-2.5 px-4 rounded-lg text-sm font-medium disabled:opacity-50 transition-colors"
                  >
                    <XCircle className="w-4 h-4" /> Reject
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
