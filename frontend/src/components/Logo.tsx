import { motion } from 'framer-motion'

/** Three linked nodes: data (violet), model (teal), insight (amber). The pulse
 * travelling between them echoes the agent graph. */
export function Logo({ size = 34, animate = true }: { size?: number; animate?: boolean }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden>
      <rect width="64" height="64" rx="16" fill="var(--surface-2)" />
      <path d="M20 22L44 20L32 44Z" fill="none" stroke="var(--line-strong)" strokeWidth="2.5" strokeLinejoin="round" />
      {animate && (
        <motion.circle
          r="3"
          fill="var(--text)"
          initial={{ cx: 20, cy: 22 }}
          animate={{ cx: [20, 44, 32, 20], cy: [22, 20, 44, 22] }}
          transition={{ duration: 3.2, repeat: Infinity, ease: 'easeInOut' }}
        />
      )}
      <circle cx="20" cy="22" r="6" fill="var(--mind)" />
      <circle cx="44" cy="20" r="5" fill="var(--ok)" />
      <circle cx="32" cy="44" r="7" fill="var(--signal)" />
    </svg>
  )
}
