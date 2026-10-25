import clsx from 'clsx'
import { AnimatePresence, motion } from 'framer-motion'
import { AlertOctagon, CheckCircle2, CircleDot, Flag, MessageCircleQuestion, Play, Reply, Sparkles, Terminal } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { AgentEvent, Stage } from '../../lib/api'

const ICON: Record<string, { icon: any; color: string }> = {
  run_started: { icon: Play, color: 'var(--info)' },
  run_resumed: { icon: Reply, color: 'var(--mind)' },
  node_started: { icon: CircleDot, color: 'var(--signal)' },
  node_log: { icon: Terminal, color: 'var(--faint)' },
  node_completed: { icon: CheckCircle2, color: 'var(--ok)' },
  node_failed: { icon: AlertOctagon, color: 'var(--bad)' },
  awaiting_input: { icon: MessageCircleQuestion, color: 'var(--mind)' },
  input_received: { icon: Reply, color: 'var(--mind)' },
  llm_call: { icon: Sparkles, color: 'var(--mind)' },
  run_completed: { icon: Flag, color: 'var(--ok)' },
  run_failed: { icon: AlertOctagon, color: 'var(--bad)' },
}

export function Console({ events, stages, filter, onClearFilter }: { events: AgentEvent[]; stages: Stage[]; filter: string | null; onClearFilter: () => void }) {
  const [showLogs, setShowLogs] = useState(true)
  const box = useRef<HTMLDivElement>(null)
  const stick = useRef(true)
  const label = (id: string | null) => stages.find((s) => s.id === id)?.label ?? id
  const t0 = events[0]?.ts ?? 0
  const shown = events.filter((e) => e.type !== 'node_started' && (showLogs || e.type !== 'node_log') && (!filter || e.node === filter))

  useEffect(() => {
    const el = box.current
    if (el && stick.current) el.scrollTop = el.scrollHeight
  }, [shown.length])

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between gap-2 border-b border-line px-4 py-3">
        <div className="flex items-center gap-2 font-bold">
          <Terminal className="size-4 text-muted" />
          Agent log
          {filter && (
            <button onClick={onClearFilter} className="rounded-full bg-mind/15 px-2 py-0.5 text-[12px] font-semibold text-mind">
              {label(filter)} ✕
            </button>
          )}
        </div>
        <label className="flex cursor-pointer items-center gap-1.5 text-[12px] text-muted">
          <input type="checkbox" checked={showLogs} onChange={(e) => setShowLogs(e.target.checked)} className="accent-[var(--mind)]" />
          details
        </label>
      </div>
      <div
        ref={box}
        onScroll={(e) => {
          const el = e.currentTarget
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40
        }}
        className="min-h-0 flex-1 overflow-y-auto px-3 py-2"
      >
        {shown.length === 0 && <p className="px-2 py-6 text-center text-[13px] text-faint">Waiting for the agent…</p>}
        <AnimatePresence initial={false}>
          {shown.map((e) => {
            const meta = ICON[e.type] ?? ICON.node_log
            const Icon = meta.icon
            const major = e.type !== 'node_log'
            return (
              <motion.div
                key={e.seq}
                layout="position"
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.22 }}
                className={clsx('flex gap-2.5 rounded-lg px-2 py-1.5 text-[12.5px]', major ? 'text-text' : 'text-muted', e.type === 'awaiting_input' && 'bg-mind/10')}
              >
                <Icon className="mt-0.5 size-3.5 shrink-0" style={{ color: meta.color }} />
                <div className="min-w-0 flex-1">
                  {e.node && major && <span className="mr-1.5 font-bold">{label(e.node)}</span>}
                  <span className={clsx(e.type === 'llm_call' && 'text-mind', e.type === 'node_failed' && 'text-bad')}>{e.message}</span>
                </div>
                <span className="shrink-0 text-[10.5px] text-faint tabular-nums">+{(e.ts - t0).toFixed(1)}s</span>
              </motion.div>
            )
          })}
        </AnimatePresence>
      </div>
    </div>
  )
}
