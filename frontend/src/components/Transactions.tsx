// Transactions tab - sortable, filterable table with expandable row details
'use client'
import { useEffect, useState } from 'react'
import { Search, ChevronDown, ChevronUp, Filter } from 'lucide-react'
import Card from './ui/Card'
import { Table, Thead, Th, Tbody, Tr, Td } from './ui/Table'
import { RiskBadge, StatusBadge } from './ui/Badge'
import Modal from './ui/Modal'
import { CustomerMap, getCustomerMap, formatCustomer } from '@/lib/customerLookup'

async function fetchAPI(path: string, query?: string) {
  const params = new URLSearchParams({ path })
  if (query) params.set('query', query)
  const res = await fetch(`/api/proxy?${params}`)
  if (!res.ok) throw new Error(`API error ${res.status}`)
  return res.json()
}

function formatNGN(amount: number) {
  return new Intl.NumberFormat('en-NG', { style: 'currency', currency: 'NGN', maximumFractionDigits: 0 }).format(amount)
}

function formatWAT(isoDate: string) {
  return new Date(isoDate).toLocaleString('en-NG', { timeZone: 'Africa/Lagos', dateStyle: 'short', timeStyle: 'short' })
}

interface Transaction {
  transaction_id: string
  customer_id: string
  amount: number
  transaction_type: string
  channel: string
  risk_score: number
  status: string
  timestamp: string
  currency?: string
  metadata?: any
}

export default function Transactions() {
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [filtered, setFiltered] = useState<Transaction[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [channelFilter, setChannelFilter] = useState('all')
  const [riskFilter, setRiskFilter] = useState('all')
  const [selected, setSelected] = useState<Transaction | null>(null)
  const [linkedAlerts, setLinkedAlerts] = useState<any[]>([])
  const [sortCol, setSortCol] = useState<keyof Transaction>('timestamp')
  const [sortAsc, setSortAsc] = useState(false)
  const [customerMap, setCustomerMap] = useState<CustomerMap>({})

  useEffect(() => {
    fetchAPI('/transactions')
      .then(res => {
        const list = res.transactions || res || []
        setTransactions(list)
        setFiltered(list)
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
    getCustomerMap().then(setCustomerMap)
  }, [])

  // Apply filters and search
  useEffect(() => {
    let result = [...transactions]

    if (search) {
      const q = search.toLowerCase()
      result = result.filter(t =>
        t.transaction_id?.toLowerCase().includes(q) ||
        t.customer_id?.toLowerCase().includes(q) ||
        formatCustomer(t.customer_id, customerMap).toLowerCase().includes(q)
      )
    }
    if (statusFilter !== 'all') result = result.filter(t => t.status === statusFilter)
    if (channelFilter !== 'all') result = result.filter(t => t.channel === channelFilter)
    if (riskFilter !== 'all') {
      result = result.filter(t => {
        const score = t.risk_score || 0
        if (riskFilter === 'low') return score < 0.4
        if (riskFilter === 'medium') return score >= 0.4 && score < 0.6
        if (riskFilter === 'high') return score >= 0.6 && score < 0.8
        if (riskFilter === 'critical') return score >= 0.8
        return true
      })
    }

    // Sort
    result.sort((a, b) => {
      const av = a[sortCol] ?? ''
      const bv = b[sortCol] ?? ''
      return sortAsc ? (av > bv ? 1 : -1) : (av < bv ? 1 : -1)
    })

    setFiltered(result)
  }, [transactions, search, statusFilter, channelFilter, riskFilter, sortCol, sortAsc, customerMap])

  function toggleSort(col: keyof Transaction) {
    if (sortCol === col) setSortAsc(a => !a)
    else { setSortCol(col); setSortAsc(true) }
  }

  async function openDetail(tx: Transaction) {
    setSelected(tx)
    // Load linked alerts
    try {
      const alertRes = await fetchAPI('/alerts')
      const allAlerts = alertRes.alerts || alertRes || []
      setLinkedAlerts(allAlerts.filter((a: any) =>
        a.transaction_id === tx.transaction_id ||
        a.customer_id === tx.customer_id
      ))
    } catch { setLinkedAlerts([]) }
  }

  // Unique values for filter dropdowns
  const statuses = ['all', ...new Set(transactions.map(t => t.status).filter(Boolean))]
  const channels = ['all', ...new Set(transactions.map(t => t.channel).filter(Boolean))]

  const SortIcon = ({ col }: { col: keyof Transaction }) => (
    sortCol === col
      ? (sortAsc ? <ChevronUp className="w-3 h-3 inline ml-1" /> : <ChevronDown className="w-3 h-3 inline ml-1" />)
      : null
  )

  if (loading) return <div className="flex justify-center items-center h-64 text-slate-400">Loading transactions...</div>
  if (error) return <div className="bg-red-900/20 border border-red-800 rounded-xl p-6 text-red-400">{error}</div>

  return (
    <div className="space-y-4">
      {/* Filters row */}
      <div className="flex flex-wrap gap-3 items-center">
        <div className="relative">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            type="text"
            placeholder="Search ID or customer..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="bg-[#111827] border border-[#1e293b] rounded-lg pl-9 pr-4 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500 w-64"
          />
        </div>

        <Filter className="w-4 h-4 text-slate-500" />

        <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}
          className="bg-[#111827] border border-[#1e293b] rounded-lg px-3 py-2 text-sm text-slate-300 focus:outline-none focus:border-blue-500">
          {statuses.map(s => <option key={s} value={s}>{s === 'all' ? 'All Statuses' : s}</option>)}
        </select>

        <select value={channelFilter} onChange={e => setChannelFilter(e.target.value)}
          className="bg-[#111827] border border-[#1e293b] rounded-lg px-3 py-2 text-sm text-slate-300 focus:outline-none focus:border-blue-500">
          {channels.map(c => <option key={c} value={c}>{c === 'all' ? 'All Channels' : c}</option>)}
        </select>

        <select value={riskFilter} onChange={e => setRiskFilter(e.target.value)}
          className="bg-[#111827] border border-[#1e293b] rounded-lg px-3 py-2 text-sm text-slate-300 focus:outline-none focus:border-blue-500">
          <option value="all">All Risk Tiers</option>
          <option value="low">Low (0-40%)</option>
          <option value="medium">Medium (40-60%)</option>
          <option value="high">High (60-80%)</option>
          <option value="critical">Critical (80%+)</option>
        </select>

        <span className="text-slate-500 text-sm ml-auto">{filtered.length} transactions</span>
      </div>

      <Card>
        <Table>
          <Thead>
            <tr>
              <Th><button onClick={() => toggleSort('transaction_id')} className="hover:text-slate-200">ID <SortIcon col="transaction_id" /></button></Th>
              <Th><button onClick={() => toggleSort('customer_id')} className="hover:text-slate-200">Customer <SortIcon col="customer_id" /></button></Th>
              <Th><button onClick={() => toggleSort('amount')} className="hover:text-slate-200">Amount (NGN) <SortIcon col="amount" /></button></Th>
              <Th>Type</Th>
              <Th>Channel</Th>
              <Th><button onClick={() => toggleSort('risk_score')} className="hover:text-slate-200">Risk <SortIcon col="risk_score" /></button></Th>
              <Th>Status</Th>
              <Th><button onClick={() => toggleSort('timestamp')} className="hover:text-slate-200">Timestamp (WAT) <SortIcon col="timestamp" /></button></Th>
            </tr>
          </Thead>
          <Tbody>
            {filtered.length === 0 ? (
              <Tr><Td className="text-slate-500 text-center py-12">No transactions match your filters.</Td></Tr>
            ) : (
              filtered.map(tx => (
                <Tr key={tx.transaction_id} onClick={() => openDetail(tx)}>
                  <Td><code className="text-blue-400 text-xs">{tx.transaction_id?.substring(0, 12)}...</code></Td>
                  <Td><span className="text-slate-300">{formatCustomer(tx.customer_id, customerMap)}</span></Td>
                  <Td><span className="font-mono text-slate-200">{formatNGN(tx.amount)}</span></Td>
                  <Td><span className="text-slate-400">{tx.transaction_type}</span></Td>
                  <Td><span className="text-slate-400">{tx.channel}</span></Td>
                  <Td><RiskBadge score={tx.risk_score || 0} /></Td>
                  <Td><StatusBadge status={tx.status} /></Td>
                  <Td><span className="text-slate-500 text-xs">{tx.timestamp ? formatWAT(tx.timestamp) : 'N/A'}</span></Td>
                </Tr>
              ))
            )}
          </Tbody>
        </Table>
      </Card>

      {/* Transaction detail modal */}
      <Modal isOpen={!!selected} onClose={() => setSelected(null)} title="Transaction Details" size="xl">
        {selected && (
          <div className="space-y-6">
            <div className="grid grid-cols-2 gap-4">
              {[
                ['Transaction ID', selected.transaction_id],
                ['Customer', formatCustomer(selected.customer_id, customerMap)],
                ['Amount', formatNGN(selected.amount)],
                ['Currency', selected.currency || 'NGN'],
                ['Type', selected.transaction_type],
                ['Channel', selected.channel],
                ['Risk Score', `${((selected.risk_score || 0) * 100).toFixed(1)}%`],
                ['Status', selected.status],
                ['Timestamp (WAT)', selected.timestamp ? formatWAT(selected.timestamp) : 'N/A'],
              ].map(([label, value]) => (
                <div key={label} className="bg-slate-700/40 rounded-lg p-3">
                  <p className="text-slate-500 text-xs mb-1">{label}</p>
                  <p className="text-slate-200 text-sm font-medium">{value}</p>
                </div>
              ))}
            </div>

            {selected.metadata && (
              <div>
                <h4 className="text-slate-400 text-xs font-semibold uppercase tracking-wider mb-2">Metadata</h4>
                <pre className="bg-[#0a1120] rounded-lg p-4 text-xs text-slate-400 overflow-x-auto">
                  {JSON.stringify(selected.metadata, null, 2)}
                </pre>
              </div>
            )}

            <div>
              <h4 className="text-slate-400 text-xs font-semibold uppercase tracking-wider mb-3">Linked Alerts ({linkedAlerts.length})</h4>
              {linkedAlerts.length === 0 ? (
                <p className="text-slate-500 text-sm">No linked alerts for this transaction.</p>
              ) : (
                <div className="space-y-2">
                  {linkedAlerts.map((a: any) => (
                    <div key={a.alert_id} className="bg-slate-700/40 rounded-lg p-3 flex items-center justify-between">
                      <div>
                        <p className="text-slate-300 text-sm">{a.alert_type || a.type}</p>
                        <p className="text-slate-500 text-xs">{a.alert_id}</p>
                      </div>
                      <StatusBadge status={a.status} />
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}
