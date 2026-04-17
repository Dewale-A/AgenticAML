/**
 * Customer name lookup utility.
 * Fetches customer list from the API and builds a map of customer_id -> display name.
 * Used across all components to show "Name (ID)" instead of raw IDs.
 * This is standard practice in AML systems: IDs for compliance, names for readability.
 */

export type CustomerMap = Record<string, string>

let cachedMap: CustomerMap | null = null

/**
 * Fetch customers from API and build lookup map.
 * Returns a map: { "cust_001": "Adaeze Okonkwo", "cust_002": "Emeka Nwosu", ... }
 * Caches after first call to avoid repeated API hits.
 */
export async function getCustomerMap(): Promise<CustomerMap> {
  if (cachedMap) return cachedMap

  try {
    const res = await fetch('/api/proxy?path=/customers')
    const data = await res.json()
    const customers = data.customers || data || []
    const map: CustomerMap = {}
    for (const c of customers) {
      map[c.id] = c.name || c.id
    }
    cachedMap = map
    return map
  } catch {
    return {}
  }
}

/**
 * Format a customer_id for display: "Name (ID)"
 * Falls back to just the ID if name not found.
 */
export function formatCustomer(customerId: string, map: CustomerMap): string {
  const name = map[customerId]
  if (name && name !== customerId) {
    return `${name} (${customerId})`
  }
  return customerId
}
