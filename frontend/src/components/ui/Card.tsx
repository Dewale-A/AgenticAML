// Card container component for dashboard sections
interface CardProps {
  title?: string
  subtitle?: string
  children: React.ReactNode
  className?: string
  headerRight?: React.ReactNode
}

export default function Card({ title, subtitle, children, className = '', headerRight }: CardProps) {
  return (
    <div className={`bg-[#111827] border border-[#1e293b] rounded-xl ${className}`}>
      {(title || headerRight) && (
        <div className="px-5 py-4 border-b border-[#1e293b] flex items-center justify-between">
          <div>
            {title && <h3 className="text-slate-100 font-semibold text-sm">{title}</h3>}
            {subtitle && <p className="text-slate-500 text-xs mt-0.5">{subtitle}</p>}
          </div>
          {headerRight && <div>{headerRight}</div>}
        </div>
      )}
      <div className="p-5">{children}</div>
    </div>
  )
}

// Stat card for the dashboard KPI row
interface StatCardProps {
  label: string
  value: string | number
  sub?: string
  icon?: React.ReactNode
  trend?: 'up' | 'down' | 'neutral'
}

export function StatCard({ label, value, sub, icon, trend }: StatCardProps) {
  return (
    <div className="bg-[#111827] border border-[#1e293b] rounded-xl p-5 flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="text-slate-400 text-xs font-medium uppercase tracking-wider">{label}</span>
        {icon && <div className="text-slate-500">{icon}</div>}
      </div>
      <div className="text-2xl font-bold text-white">{value}</div>
      {sub && <div className="text-xs text-slate-500">{sub}</div>}
    </div>
  )
}
