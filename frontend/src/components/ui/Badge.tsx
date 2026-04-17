// Reusable badge component for status, severity, priority, and match type indicators
interface BadgeProps {
  variant?: 'default' | 'success' | 'warning' | 'danger' | 'info' | 'ghost'
  size?: 'sm' | 'md'
  children: React.ReactNode
  className?: string
}

export function Badge({ variant = 'default', size = 'sm', children, className = '' }: BadgeProps) {
  const variantClasses = {
    default: 'bg-slate-700 text-slate-300 border-slate-600',
    success: 'bg-emerald-900/50 text-emerald-400 border-emerald-700/50',
    warning: 'bg-amber-900/50 text-amber-400 border-amber-700/50',
    danger: 'bg-red-900/50 text-red-400 border-red-700/50',
    info: 'bg-blue-900/50 text-blue-400 border-blue-700/50',
    ghost: 'bg-[#111827] text-slate-400 border-[#1e293b]',
  }

  const sizeClasses = {
    sm: 'text-xs px-2 py-0.5',
    md: 'text-sm px-2.5 py-1',
  }

  return (
    <span className={`
      inline-flex items-center rounded-full border font-medium
      ${variantClasses[variant]} ${sizeClasses[size]} ${className}
    `}>
      {children}
    </span>
  )
}

// Risk score badge - color coded by score value
export function RiskBadge({ score }: { score: number }) {
  if (score >= 0.8) return <Badge variant="danger">{(score * 100).toFixed(0)}%</Badge>
  if (score >= 0.6) return <Badge variant="warning">{(score * 100).toFixed(0)}%</Badge>
  if (score >= 0.4) return <Badge variant="info">{(score * 100).toFixed(0)}%</Badge>
  return <Badge variant="success">{(score * 100).toFixed(0)}%</Badge>
}

// Severity badge - for alerts
export function SeverityBadge({ severity }: { severity: string }) {
  const map: Record<string, 'danger' | 'warning' | 'info' | 'ghost'> = {
    critical: 'danger',
    high: 'warning',
    medium: 'info',
    low: 'ghost',
  }
  return <Badge variant={map[severity?.toLowerCase()] || 'ghost'}>{severity?.toUpperCase()}</Badge>
}

// Status badge - for transactions, alerts, cases
export function StatusBadge({ status }: { status: string }) {
  const map: Record<string, 'success' | 'warning' | 'info' | 'ghost' | 'danger'> = {
    clean: 'success',
    flagged: 'warning',
    blocked: 'danger',
    open: 'warning',
    investigating: 'info',
    resolved: 'success',
    closed: 'ghost',
    draft: 'ghost',
    approved: 'success',
    filed: 'info',
    rejected: 'danger',
    pending_review: 'warning',
  }
  return <Badge variant={map[status?.toLowerCase()] || 'ghost'}>{status?.replace(/_/g, ' ').toUpperCase()}</Badge>
}

// Priority badge - for cases
export function PriorityBadge({ priority }: { priority: string }) {
  const map: Record<string, 'danger' | 'warning' | 'info' | 'ghost'> = {
    critical: 'danger',
    high: 'warning',
    medium: 'info',
    low: 'ghost',
  }
  return <Badge variant={map[priority?.toLowerCase()] || 'ghost'}>{priority?.toUpperCase()}</Badge>
}
