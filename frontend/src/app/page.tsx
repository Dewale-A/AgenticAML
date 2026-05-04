'use client'
// Main entry point - renders the full dashboard SPA.
// Tab order: Dashboard | Customer Onboarding | Transactions | Alerts | Watchlist Screening | SARs | Cases | Governance
import { useState } from 'react'
import Header from '@/components/Header'
import TabNav from '@/components/TabNav'
import Dashboard from '@/components/Dashboard'
import Transactions from '@/components/Transactions'
import Alerts from '@/components/Alerts'
import WatchlistScreening from '@/components/WatchlistScreening'
import CustomerOnboarding from '@/components/CustomerOnboarding'
import SARs from '@/components/SARs'
import Cases from '@/components/Cases'
import Governance from '@/components/Governance'

// Updated type includes new tabs; 'sanctions' removed and replaced by 'watchlist' + 'onboarding'
type Tab = 'dashboard' | 'onboarding' | 'transactions' | 'alerts' | 'watchlist' | 'sars' | 'cases' | 'governance'

export default function Home() {
  const [activeTab, setActiveTab] = useState<Tab>('dashboard')
  const isDemoMode = process.env.NEXT_PUBLIC_DEMO_MODE === 'true'

  return (
    <div className="min-h-screen bg-slate-900 flex flex-col">
      {/* Demo mode banner */}
      {isDemoMode && (
        <div className="bg-amber-600 text-white text-center py-1.5 text-sm font-medium">
          DEMO MODE - Sample data only. Not for production use.
        </div>
      )}

      <Header />

      <TabNav activeTab={activeTab} onTabChange={(tab) => setActiveTab(tab as Tab)} />

      {/* Main content area */}
      <main className="flex-1 max-w-screen-2xl mx-auto w-full px-4 py-6">
        {activeTab === 'dashboard' && <Dashboard />}
        {activeTab === 'onboarding' && <CustomerOnboarding />}
        {activeTab === 'transactions' && <Transactions />}
        {activeTab === 'alerts' && <Alerts />}
        {/* WatchlistScreening replaces Sanctions - backward compatible with /sanctions API */}
        {activeTab === 'watchlist' && <WatchlistScreening />}
        {activeTab === 'sars' && <SARs />}
        {activeTab === 'cases' && <Cases />}
        {activeTab === 'governance' && <Governance />}
      </main>

      {/* Footer with VeriStack branding */}
      <footer className="border-t border-slate-800 py-4 text-center text-slate-500 text-sm">
        AgenticAML v2.0 | Governance-First AML Compliance | Powered by{' '}
        <a href="https://veristack.ca" className="text-slate-400 hover:text-slate-300 underline" target="_blank" rel="noopener noreferrer">
          VeriStack
        </a>
      </footer>
    </div>
  )
}
