// Reusable table primitives with dark theme styling
interface TableProps {
  children: React.ReactNode
  className?: string
}

export function Table({ children, className = '' }: TableProps) {
  return (
    <div className="overflow-x-auto">
      <table className={`w-full text-sm ${className}`}>
        {children}
      </table>
    </div>
  )
}

export function Thead({ children }: { children: React.ReactNode }) {
  return (
    <thead className="border-b border-[#1e293b]">
      {children}
    </thead>
  )
}

export function Th({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return (
    <th className={`text-left text-xs font-semibold text-slate-400 uppercase tracking-wider py-3 px-4 ${className}`}>
      {children}
    </th>
  )
}

export function Tbody({ children }: { children: React.ReactNode }) {
  return <tbody className="divide-y divide-slate-800">{children}</tbody>
}

export function Tr({ children, onClick, className = '' }: {
  children: React.ReactNode
  onClick?: () => void
  className?: string
}) {
  return (
    <tr
      onClick={onClick}
      className={`
        text-slate-300 hover:bg-slate-750 transition-colors
        ${onClick ? 'cursor-pointer hover:bg-slate-700/50' : ''}
        ${className}
      `}
    >
      {children}
    </tr>
  )
}

export function Td({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return (
    <td className={`py-3 px-4 ${className}`}>
      {children}
    </td>
  )
}
