// WatchlistScreening tab - renamed from Sanctions to reflect full scope:
// Sanctions, PEP, and Adverse Media screening in one unified view.
// Keeps backward compatibility with /sanctions API endpoints.
'use client'
import { useEffect, useState } from 'react'
import { Search, RefreshCw, ShieldAlert, User, Newspaper } from 'lucide-react'
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

// Match strength badge - color coded by confidence
function MatchTypeBadge({ matchType }: { matchType: string }) {
  const map: Record<string, 'danger' | 'warning' | 'info' | 'ghost'> = {
    exact: 'danger',
    strong: 'warning',
    partial: 'info',
    weak: 'ghost',
  }
  return <Badge variant={map[matchType?.toLowerCase()] || 'ghost'}>{matchType?.toUpperCase()}</Badge>
}

// Category badge with distinct colors per CBN terminology:
// Sanctions = red, PEP = orange (amber), Adverse Media = yellow
function CategoryBadge({ category }: { category: string }) {
  const cat = category?.toLowerCase()
  if (cat === 'sanctions') {
    return (
      <span className="inline-flex items-center gap-1 rounded-full border font-medium text-xs px-2 py-0.5 bg-red-900/50 text-red-400 border-red-700/50">
        <ShieldAlert className="w-3 h-3" /> SANCTIONS
      </span>
    )
  }
  if (cat === 'pep') {
    return (
      <span className="inline-flex items-center gap-1 rounded-full border font-medium text-xs px-2 py-0.5 bg-orange-900/50 text-orange-400 border-orange-700/50">
        <User className="w-3 h-3" /> PEP
      </span>
    )
  }
  if (cat === 'adverse_media') {
    return (
      <span className="inline-flex items-center gap-1 rounded-full border font-medium text-xs px-2 py-0.5 bg-yellow-900/50 text-yellow-400 border-yellow-700/50">
        <Newspaper className="w-3 h-3" /> ADVERSE MEDIA
      </span>
    )
  }
  // Default: treat unknown category as sanctions
  return <Badge variant="ghost">{category?.toUpperCase() || 'UNKNOWN'}</Badge>
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
  // match_category added in v2 schema; defaults to 'sanctions' for legacy records
  match_category?: string
}

// The three sub-category filter options and their display config
const CATEGORY_FILTERS = [
  { id: 'all', label: 'All Categories', color: 'text-slate-300' },
  { id: 'sanctions', label: 'Sanctions', color: 'text-red-400' },
  { id: 'pep', label: 'PEP', color: 'text-orange-400' },
  { id: 'adverse_media', label: 'Adverse Media', color: 'text-yellow-400' },
] as const

export default function WatchlistScreening() {
  const [matches, setMatches] = useState<SanctionsMatch[]>([])
  const [filtered, setFiltered] = useState<SanctionsMatch[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  // Match type filter (exact/strong/partial/weak)
  const [matchTypeFilter, setMatchTypeFilter] = useState('all')
  // Category filter: sanctions | pep | adverse_media | all
  const [categoryFilter, setCategoryFilter] = useState('all')
  const [selected, setSelected] = useState<SanctionsMatch | null>(null)
  const [actionLoading, setActionLoading] = useState(false)
  const [customerMap, setCustomerMap] = useState<CustomerMap>({})

  function load() {
    setLoading(true)
    // Backward compatible: still calls /sanctions/matches endpoint
    fetchAPI('/sanctions/matches')
      .then(res => {
        const list = (res.matches || res || []) as SanctionsMatch[]
        // Ensure every record has a match_category; legacy records default to 'sanctions'
        const normalized = list.map(m => ({
          ...m,
          match_category: m.match_category || 'sanctions',
        }))
        setMatches(normalized)
        setFiltered(normalized)
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
    getCustomerMap().then(setCustomerMap)
  }

  useEffect(load, [])

  // Re-filter whenever search, match type, or category changes
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
    if (categoryFilter !== 'all') result = result.filter(m => m.match_category === categoryFilter)
    setFiltered(result)
  }, [matches, search, matchTypeFilter, categoryFilter, customerMap])

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

  // Category counts for the toggle pills
  const categoryCounts = {
    all: matches.length,
    sanctions: matches.filter(m => m.match_category === 'sanctions').length,
    pep: matches.filter(m => m.match_category === 'pep').length,
    adverse_media: matches.filter(m => m.match_category === 'adverse_media').length,
  }

  if (loading) return (
    <div className="flex justify-center items-center h-64 text-slate-400">
      <div className="text-center">
        <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
        <p>Loading watchlist screening data...</p>
      </div>
    </div>
  )
  if (error) return <div className="bg-red-900/20 border border-red-800 rounded-xl p-6 text-red-400">{error}</div>

  return (
    <div className="space-y-4">
      {/* Sub-category toggle pills: Sanctions / PEP / Adverse Media */}
      <div className="flex flex-wrap gap-2">
        {CATEGORY_FILTERS.map(cat => {
          const count = categoryCounts[cat.id as keyof typeof categoryCounts]
          const isActive = categoryFilter === cat.id
          return (
            <button
              key={cat.id}
              onClick={() => setCategoryFilter(cat.id)}
              className={`flex items-center gap-2 px-4 py-2 rounded-full border text-sm font-medium transition-colors ${
                isActive
                  ? 'bg-slate-700 border-slate-500 text-slate-100'
                  : 'bg-[#111827] border-[#1e293b] text-slate-400 hover:border-slate-600 hover:text-slate-200'
              }`}
            >
              <span className={isActive ? 'text-slate-100' : cat.color}>{cat.label}</span>
              {/* Count badge for each category */}
              <span className={`text-xs rounded-full px-1.5 py-0.5 min-w-[20px] text-center ${
                isActive ? 'bg-slate-600 text-slate-200' : 'bg-slate-800 text-slate-500'
              }`}>{count}</span>
            </button>
          )
        })}
      </div>

      {/* Search and match type filters */}
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
        <select
          value={matchTypeFilter}
          onChange={e => setMatchTypeFilter(e.target.value)}
          className="bg-[#111827] border border-[#1e293b] rounded-lg px-3 py-2 text-sm text-slate-300 focus:outline-none focus:border-blue-500"
        >
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
              <Th>Category</Th>
              <Th>Match Type</Th>
              <Th>Score</Th>
              <Th>Action Taken</Th>
              <Th>Reviewed By</Th>
            </tr>
          </Thead>
          <Tbody>
            {filtered.length === 0 ? (
              <Tr><Td className="text-slate-500 text-center py-12">No watchlist matches found.</Td></Tr>
            ) : (
              filtered.map(match => (
                <Tr key={match.match_id} onClick={() => setSelected(match)}>
                  <Td><span className="text-slate-300">{formatCustomer(match.customer_id, customerMap)}</span></Td>
                  <Td><span className="text-slate-200 font-medium">{match.matched_entity}</span></Td>
                  <Td><span className="text-slate-400 text-xs">{match.sanctions_list}</span></Td>
                  <Td><CategoryBadge category={match.match_category || 'sanctions'} /></Td>
                  <Td><MatchTypeBadge matchType={match.match_type} /></Td>
                  <Td><span className="font-mono text-slate-300">{match.match_score ? `${(match.match_score * 100).toFixed(1)}%` : 'N/A'}</span></Td>
                  <Td>
                    <Badge variant={match.action === 'block' ? 'danger' : match.action === 'review' ? 'warning' : 'ghost'}>
                      {match.action?.toUpperCase() || 'PENDING'}
                    </Badge>
                  </Td>
                  <Td><span className="text-slate-500 text-xs">{match.reviewed_by || 'Unreviewed'}</span></Td>
                </Tr>
              ))
            )}
          </Tbody>
        </Table>
      </Card>

      {/* Match detail modal with actions */}
      <Modal isOpen={!!selected} onClose={() => setSelected(null)} title="Watchlist Match Details" size="lg">
        {selected && (
          <div className="space-y-6">
            <div className="grid grid-cols-2 gap-4">
              {[
                ['Match ID', selected.match_id],
                ['Customer', formatCustomer(selected.customer_id, customerMap)],
                ['Matched Entity', selected.matched_entity],
                ['Screening List', selected.sanctions_list],
                ['Category', selected.match_category || 'sanctions'],
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

            {/* Category badge in modal for quick visual reference */}
            <div className="flex items-center gap-3">
              <span className="text-slate-500 text-xs">Category:</span>
              <CategoryBadge category={selected.match_category || 'sanctions'} />
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
