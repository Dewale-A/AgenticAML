// Donut chart showing distribution of transactions across risk tiers
'use client'
import { PieChart, Pie, Cell, Tooltip, Legend, ResponsiveContainer } from 'recharts'

const RISK_COLORS = {
  low: '#10b981',      // emerald
  medium: '#f59e0b',   // amber
  high: '#f97316',     // orange
  critical: '#ef4444', // red
}

interface Props {
  data: { tier: string; count: number }[]
}

export default function RiskDistribution({ data }: Props) {
  const chartData = data.map(d => ({
    name: d.tier.charAt(0).toUpperCase() + d.tier.slice(1),
    value: d.count,
    color: RISK_COLORS[d.tier as keyof typeof RISK_COLORS] || '#64748b',
  }))

  const total = chartData.reduce((sum, d) => sum + d.value, 0)

  return (
    <div className="relative">
      <ResponsiveContainer width="100%" height={240}>
        <PieChart>
          <Pie
            data={chartData}
            cx="50%"
            cy="50%"
            innerRadius={60}
            outerRadius={90}
            paddingAngle={3}
            dataKey="value"
          >
            {chartData.map((entry, index) => (
              <Cell key={index} fill={entry.color} />
            ))}
          </Pie>
          <Tooltip
            contentStyle={{
              backgroundColor: '#1e293b',
              border: '1px solid #334155',
              borderRadius: '8px',
              color: '#f8fafc',
            }}
            formatter={(value) => [`${value} txns (${total > 0 ? ((Number(value) / total) * 100).toFixed(1) : 0}%)`, '']}
          />
          <Legend
            iconType="circle"
            iconSize={8}
            formatter={(value) => <span className="text-xs text-slate-400">{value}</span>}
          />
        </PieChart>
      </ResponsiveContainer>
      {/* Center label showing total */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-7 text-center pointer-events-none">
        <div className="text-2xl font-bold text-white">{total}</div>
        <div className="text-xs text-slate-500">Total</div>
      </div>
    </div>
  )
}
