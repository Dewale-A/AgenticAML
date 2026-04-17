// Sanctions tab - sanctions screening matches with action controls
'use client'
import { useEffect, useState } from 'react'
import { Search, RefreshCw } from 'lucide-react'
import Card from './ui/Card'
import { Table, Thead, Th, Tbody, Tr, Td } from './ui/Table'
import { Badge } from './ui/Badge'
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

function MatchTypeBadge({ matchType }: { matchType: string }) {
  const map: Record<string, 'danger' | 'warning' | 'info' | 'ghost'> = {
    exact: 'danger',
    strong: 'warning',
    partial: 'info',
    weak: 'ghost',
  }
  return <Badge variant={map[matchType?.toLowerCase()] || 'ghost'}>{matchType?.toUpperCase()}</Badge>
}

interface SanctionsMatch {
  match_id: string
  customer_id: string
  matched_entity: string
  sanctions_list: string
  match_type: string
  match_score: number
  action: string
  reviewed_by?: string
  created_at: string
}

export default function Sanctions() {
  const [matches, setMatches] = useState<SanctionsMatch[]>([])
  const [filtered, setFiltered] = useState<SanctionsMatch[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [matchTypeFilter, setMatchTypeFilter] = useState('all')
  const [selected, setSelected] = useState<SanctionsMatch | null>(null)
  const [actionLoading, setActionLoading] = useState(false)
  const [customerMap, setCustomerMap] = useState<CustomerMap>({})

  function load() {
    setLoading(true)
    fetchAPI('/sanctions/matches')
      .then(res => {
        const list = res.matches || res || []
        setMatches(list)
        setFiltered(list)
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
    getCustomerMap().then(setCustomerMap)
  }

  useEffect(load, [])

  useEffect(() => {
    let result = [...matches]
    if (search) {
      const q = search.toLowerCase()
      result = result.filter(m =>
        m.customer_id?.toLowerCase().includes(q) ||
        formatCustomer(m.customer_id, customerMap).toLowerCase().includes(q) ||
        m.matched_entity?.toLowerCase().includes(q) ||
        m.sanctions_list?.toLowerCase().includes(q)
      )
    }
    if (matchTypeFilter !== 'all') result = result.filter(m => m.match_type === matchTypeFilter)
    setFiltered(result)
  }, [matches, search, matchTypeFilter, customerMap])

  async function takeAction(matchId: string, action: string) {
    setActionLoading(true)
    try {
      await fetchAPI(`/sanctions/matches/${matchId}/action`, { action })
      load()
      setSelected(null)
    } catch (e: any) {
      alert('Action failed: ' + e.message)
    } finally {
      setActionLoading(false)
    }
  }

  if (loading) return <div className="flex justify-center items-center h-64 text-slate-400">Loading sanctions data...</div>
  if (error) return <div className="bg-red-900/20 border border-red-800 rounded-xl p-6 text-red-400">{error}</div>

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex flex-wrap gap-3 items-center">
        <div className="relative">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            type="text"
            placeholder="Search customer or entity..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="bg-[#111827] border border-[#1e293b] rounded-lg pl-9 pr-4 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500 w-64"
          />
        </div>
        <select value={matchTypeFilter} onChange={e => setMatchTypeFilter(e.target.value)}
          className="bg-[#111827] border border-[#1e293b] rounded-lg px-3 py-2 text-sm text-slate-300 focus:outline-none focus:border-blue-500">
          <option value="all">All Match Types</option>
          <option value="exact">Exact</option>
          <option value="strong">Strong</option>
          <option value="partial">Partial</option>
          <option value="weak">Weak</option>
        </select>
        <button onClick={load} className="ml-auto flex items-center gap-2 text-slate-400 hover:text-slate-200 text-sm">
          <RefreshCw className="w-4 h-4" /> Refresh
        </button>
        <span className="text-slate-500 text-sm">{filtered.length} matches</span>
      </div>

      <Card>
        <Table>
          <Thead>
            <tr>
              <Th>Customer</Th>
              <Th>Matched Entity</Th>
              <Th>List</Th>
              <Th>Match Type</Th>
              <Th>Score</Th>
              <Th>Action Taken</Th>
              <Th>Reviewed By</Th>
            </tr>
          </Thead>
          <Tbody>
            {filtered.length === 0 ? (
              <Tr><Td className="text-slate-500 text-center py-12">No sanctions matches found.</Td></Tr>
            ) : (
              filtered.map(match => (
                <Tr key={match.match_id} onClick={() => setSelected(match)}>
                  <Td><span className="text-slate-300">{formatCustomer(match.customer_id, customerMap)}</span></Td>
                  <Td><span className="text-slate-200 font-medium">{match.matched_entity}</span></Td>
                  <Td><span className="text-slate-400 text-xs">{match.sanctions_list}</span></Td>
                  <Td><MatchTypeBadge matchType={match.match_type} /></Td>
                  <Td><span className="font-mono text-slate-300">{match.match_score ? `${(match.match_score * 100).toFixed(1)}%` : 'N/A'}</span></Td>
                  <Td><Badge variant={match.action === 'block' ? 'danger' : match.action === 'review' ? 'warning' : 'ghost'}>{match.action?.toUpperCase() || 'PENDING'}</Badge></Td>
                  <Td><span className="text-slate-500 text-xs">{match.reviewed_by || 'Unreviewed'}</span></Td>
                </Tr>
              ))
            )}
          </Tbody>
        </Table>
      </Card>

      {/* Match detail modal */}
      <Modal isOpen={!!selected} onClose={() => setSelected(null)} title="Sanctions Match Details" size="lg">
        {selected && (
          <div className="space-y-6">
            <div className="grid grid-cols-2 gap-4">
              {[
                ['Match ID', selected.match_id],
                ['Customer', formatCustomer(selected.customer_id, customerMap)],
                ['Matched Entity', selected.matched_entity],
                ['Sanctions List', selected.sanctions_list],
                ['Match Type', selected.match_type],
                ['Match Score', `${((selected.match_score || 0) * 100).toFixed(1)}%`],
                ['Current Action', selected.action || 'Pending'],
                ['Reviewed By', selected.reviewed_by || 'Not yet reviewed'],
              ].map(([label, value]) => (
                <div key={label} className="bg-slate-700/40 rounded-lg p-3">
                  <p className="text-slate-500 text-xs mb-1">{label}</p>
                  <p className="text-slate-200 text-sm font-medium">{value}</p>
                </div>
              ))}
            </div>

            {/* Action buttons */}
            <div className="border-t border-[#1e293b] pt-4">
              <h4 className="text-slate-400 text-xs font-semibold uppercase tracking-wider mb-3">Actions</h4>
              <div className="flex gap-3">
                <button
                  onClick={() => takeAction(selected.match_id, 'block')}
                  disabled={actionLoading}
                  className="flex-1 bg-red-700 hover:bg-red-600 text-white py-2 px-4 rounded-lg text-sm font-medium disabled:opacity-50 transition-colors"
                >
                  Block
                </button>
                <button
                  onClick={() => takeAction(selected.match_id, 'review')}
                  disabled={actionLoading}
                  className="flex-1 bg-amber-700 hover:bg-amber-600 text-white py-2 px-4 rounded-lg text-sm font-medium disabled:opacity-50 transition-colors"
                >
                  Review
                </button>
                <button
                  onClick={() => takeAction(selected.match_id, 'dismiss')}
                  disabled={actionLoading}
                  className="flex-1 bg-slate-600 hover:bg-slate-500 text-white py-2 px-4 rounded-lg text-sm font-medium disabled:opacity-50 transition-colors"
                >
                  Dismiss
                </button>
              </div>
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}
