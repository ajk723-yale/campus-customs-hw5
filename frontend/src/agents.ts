import type { AgentName } from './api'

export interface AgentIdentity {
  name: AgentName
  label: string
  role: string
  icon: 'boss' | 'inventory' | 'accounting' | 'facilities' | 'customer_service'
}

/** The five agents, in delegation order. Colors live in App.css (.agent-<name>). */
export const AGENTS: AgentIdentity[] = [
  { name: 'boss', label: 'Boss', role: 'Coordinates and decides', icon: 'boss' },
  { name: 'inventory', label: 'Inventory', role: 'Stock, vendors, restocks', icon: 'inventory' },
  { name: 'accounting', label: 'Accounting', role: 'Invoices, cash, payments', icon: 'accounting' },
  { name: 'facilities', label: 'Facilities', role: 'Lease and rent', icon: 'facilities' },
  { name: 'customer_service', label: 'Customer service', role: 'Orders, pricing, replies', icon: 'customer_service' },
]

export function isAgent(name: string | null | undefined): name is AgentName {
  return AGENTS.some((a) => a.name === name)
}

export function agentLabel(name: string | null | undefined): string {
  return AGENTS.find((a) => a.name === name)?.label ?? (name ? name.replace(/_/g, ' ') : 'Human')
}

export const money = (n: number) =>
  n.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 })

export const timeOf = (iso: string) =>
  new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
