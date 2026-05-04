// Horizontal tab navigation - switches between the main dashboard sections.
// Tab order follows the customer lifecycle: Dashboard > Onboarding > Transactions > Alerts > Screening > SARs > Cases > Governance
'use client'
import { LayoutDashboard, ArrowLeftRight, Bell, ShieldAlert, FileText, Briefcase, BookOpen, UserPlus } from 'lucide-react'

const TABS = [
  { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { id: 'onboarding', label: 'Customer Onboarding', icon: UserPlus },
  { id: 'transactions', label: 'Transactions', icon: ArrowLeftRight },
  { id: 'alerts', label: 'Alerts', icon: Bell },
  // Renamed from "Sanctions" to "Watchlist Screening" per CBN terminology (covers Sanctions + PEP + Adverse Media)
  { id: 'watchlist', label: 'Watchlist Screening', icon: ShieldAlert },
  { id: 'sars', label: 'SARs', icon: FileText },
  { id: 'cases', label: 'Cases', icon: Briefcase },
  { id: 'governance', label: 'Governance', icon: BookOpen },
] as const

interface Props {
  activeTab: string
  onTabChange: (tab: string) => void
}

export default function TabNav({ activeTab, onTabChange }: Props) {
  return (
    <nav className="bg-[#0a1120] border-b border-[#1e293b] sticky top-16 z-40">
      <div className="max-w-screen-2xl mx-auto px-4">
        <div className="flex items-center gap-1 overflow-x-auto hide-scrollbar">
          {TABS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => onTabChange(id)}
              className={`
                flex items-center gap-2 px-4 py-3.5 text-sm font-medium whitespace-nowrap
                border-b-2 transition-colors duration-150
                ${activeTab === id
                  ? 'border-blue-500 text-blue-400'
                  : 'border-transparent text-slate-400 hover:text-slate-200 hover:border-slate-600'
                }
              `}
            >
              <Icon className="w-4 h-4" />
              {label}
            </button>
          ))}
        </div>
      </div>
    </nav>
  )
}
