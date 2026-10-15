/** Small inline SVG icons (24x24, stroke = currentColor), so the dashboard needs no icon package. */

const PATHS: Record<string, string> = {
  boss: 'M4 8h16v11H4zM9 8V5h6v3M4 13h16',
  inventory: 'M12 3l8 4.5v9L12 21l-8-4.5v-9zM12 12l8-4.5M12 12v9M12 12L4 7.5',
  accounting: 'M6 3h12v18H6zM9 7h6M9 11h.01M12 11h.01M15 11h.01M9 14h.01M12 14h.01M15 14h.01M9 17h.01M12 17h.01M15 17h.01',
  facilities: 'M4 21V8l8-5 8 5v13M9 21v-6h6v6M3 21h18',
  customer_service: 'M5 13v-1a7 7 0 0114 0v1M5 13h2v5H5zM17 13h2v5h-2zM19 18a3 3 0 01-3 3h-3',
  play: 'M7 4v16l13-8z',
  check: 'M5 12l5 5L20 7',
  x: 'M6 6l12 12M18 6L6 18',
  refresh: 'M20 11a8 8 0 10-2.3 5.7M20 4v7h-7',
  tool: 'M14.7 6.3a4 4 0 015 5L18 13l-7 7-4-4 7-7zM4 20l3-3',
  arrow: 'M5 12h14M13 6l6 6-6 6',
  alert: 'M12 9v4M12 17h.01M10.3 3.9L2.5 18a2 2 0 001.7 3h15.6a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z',
  clock: 'M12 7v5l3 2M12 21a9 9 0 110-18 9 9 0 010 18z',
  chevronDown: 'M6 9l6 6 6-6',
  chevronRight: 'M9 6l6 6-6 6',
  cash: 'M3 7h18v10H3zM12 15a3 3 0 110-6 3 3 0 010 6zM6 10h.01M18 14h.01',
  cart: 'M3 4h2l2.5 11h11L21 7H6.5M9 20h.01M17 20h.01',
  bank: 'M3 10l9-6 9 6M5 10v8M9.5 10v8M14.5 10v8M19 10v8M3 21h18',
  flag: 'M5 21V4h13l-2 4 2 4H5',
  info: 'M12 8h.01M11 12h1v5h1M12 21a9 9 0 110-18 9 9 0 010 18z',
  store: 'M4 9l1.5-5h13L20 9M4 9h16M5 9v11h14V9M10 20v-5h4v5',
  hourglass: 'M7 3h10M7 21h10M8 3c0 5 8 5 8 9s-8 4-8 9M16 3c0 5-8 5-8 9',
}

export type IconName = keyof typeof PATHS

export function Icon({ name, size = 16, title }: { name: IconName; size?: number; title?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={title ? undefined : true}
      role={title ? 'img' : undefined}
      className="icon"
    >
      {title && <title>{title}</title>}
      <path d={PATHS[name]} />
    </svg>
  )
}

export function Spinner({ label }: { label?: string }) {
  return <span className="spinner" role="status" aria-label={label ?? 'Working'} />
}
