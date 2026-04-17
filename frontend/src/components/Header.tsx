// Sticky top navigation bar with branding and CBN compliance badge
import { Shield, Activity } from 'lucide-react'

export default function Header() {
  return (
    <header className="sticky top-0 z-50 bg-slate-900 border-b border-slate-800 shadow-lg">
      <div className="max-w-screen-2xl mx-auto px-4 h-16 flex items-center justify-between">
        {/* Logo and product name */}
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 bg-blue-600 rounded-lg flex items-center justify-center">
            <Shield className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="text-white font-bold text-lg leading-tight">AgenticAML</h1>
            <p className="text-slate-500 text-xs leading-tight">AI-Powered AML Compliance</p>
          </div>
        </div>

        {/* Right side: status indicators */}
        <div className="flex items-center gap-4">
          {/* Live indicator */}
          <div className="flex items-center gap-1.5 text-emerald-400 text-sm">
            <Activity className="w-4 h-4" />
            <span className="hidden sm:inline text-xs">System Live</span>
          </div>

          {/* CBN Compliant badge */}
          <div className="flex items-center gap-2 bg-emerald-900/40 border border-emerald-700/50 rounded-full px-3 py-1.5">
            <div className="w-2 h-2 bg-emerald-400 rounded-full animate-pulse" />
            <span className="text-emerald-400 text-xs font-semibold tracking-wide">CBN COMPLIANT</span>
          </div>
        </div>
      </div>
    </header>
  )
}
