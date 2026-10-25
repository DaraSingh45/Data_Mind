import { motion } from 'framer-motion'
import { Sparkles, X } from 'lucide-react'
import type { AgentEvent, Stage } from '../../lib/api'
import { duration, pct, TYPE_COLORS } from '../../lib/format'
import type { NodeState } from '../../lib/runState'
import { Pill } from '../ui'

const STATUS_TONE: Record<string, any> = { idle: 'neutral', running: 'signal', done: 'ok', waiting: 'mind', error: 'bad' }

export function NodeDetails({ stage, state, events, onClose }: { stage: Stage; state?: NodeState; events: AgentEvent[]; onClose: () => void }) {
  const d = state?.data ?? {}
  const logs = events.filter((e) => e.node === stage.id && (e.type === 'node_log' || e.type === 'llm_call'))
  return (
    <motion.div initial={{ opacity: 0, x: 16 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 16 }} className="flex h-full min-h-0 flex-col">
      <div className="flex items-start justify-between gap-3 border-b border-line px-4 py-3">
        <div>
          <div className="flex items-center gap-2 font-bold">
            {stage.label}
            <Pill tone={STATUS_TONE[state?.status ?? 'idle']}>{state?.status ?? 'not reached'}</Pill>
          </div>
          <div className="text-[12.5px] text-muted">{stage.desc}</div>
        </div>
        <button onClick={onClose} aria-label="Close details" className="rounded-lg p-1 text-muted hover:bg-surface-2 hover:text-text">
          <X className="size-4" />
        </button>
      </div>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4 text-[13px]">
        {state?.message && <p className="font-semibold">{state.message}</p>}
        <div className="flex flex-wrap gap-2 text-[12px] text-muted">
          {state?.visits ? <span>ran {state.visits}×</span> : null}
          {state?.seconds != null && <span>· {duration(state.seconds)}</span>}
          {state?.llmCalls ? <span className="text-mind">· {state.llmCalls} LLM call{state.llmCalls > 1 ? 's' : ''}</span> : null}
        </div>

        {stage.id === 'profile' && d.columns && (
          <div className="space-y-1">
            {d.columns.map((c: any) => (
              <div key={c.name} className="flex items-center gap-2">
                <span className="size-2 rounded-full" style={{ background: TYPE_COLORS[c.type] ?? 'var(--faint)' }} />
                <span className="font-semibold">{c.name}</span>
                <span className="text-faint">{c.type}</span>
                {c.missing > 0 && <span className="ml-auto text-[11.5px] text-bad">{pct(c.missing, 0)}</span>}
              </div>
            ))}
          </div>
        )}
        {stage.id === 'understand' && d.intent && (
          <div className="space-y-1">
            <div>Target: <b>{d.intent.target ?? 'none'}</b></div>
            <div>Task: <b>{d.intent.task}</b></div>
            {d.candidates?.length > 0 && <div className="text-muted">Candidates considered: {d.candidates.join(', ')}</div>}
          </div>
        )}
        {stage.id === 'plan' && d.columns && (
          <div className="space-y-2">
            {d.llm_summary && (
              <p className="flex gap-1.5 rounded-lg bg-mind/10 p-2 text-mind">
                <Sparkles className="mt-0.5 size-3.5 shrink-0" />
                {d.llm_summary}
              </p>
            )}
            {d.columns.map((c: any) => (
              <div key={c.column} className="rounded-lg border border-line p-2">
                <div className="flex items-center gap-2">
                  <span className="font-semibold">{c.column}</span>
                  <Pill tone={c.role === 'drop' ? 'bad' : c.role === 'target' ? 'mind' : 'neutral'}>{c.role === 'feature' ? c.ops : c.role}</Pill>
                  {c.source === 'llm' && <Pill tone="mind">LLM</Pill>}
                </div>
                <div className="mt-1 text-[12px] text-muted">{c.reason}</div>
              </div>
            ))}
          </div>
        )}
        {stage.id === 'validate' && d.errors?.length > 0 && (
          <ul className="space-y-1 text-bad">
            {d.errors.map((e: string, i: number) => (
              <li key={i}>• {e}</li>
            ))}
          </ul>
        )}
        {stage.id === 'execute' && d.stats && (
          <div className="grid grid-cols-2 gap-2">
            {Object.entries(d.stats)
              .filter(([, v]) => typeof v === 'number')
              .map(([k, v]) => (
                <div key={k} className="rounded-lg bg-surface-2 p-2">
                  <div className="text-[11px] text-muted">{k.replaceAll('_', ' ')}</div>
                  <div className="font-bold">{(v as number).toLocaleString()}</div>
                </div>
              ))}
          </div>
        )}
        {stage.id === 'checks' && d.checks && (
          <div className="space-y-1.5">
            {d.checks.map((c: any) => (
              <div key={c.id} className="flex gap-2">
                <Pill tone={c.status === 'pass' ? 'ok' : c.status === 'warn' ? 'signal' : 'bad'}>{c.status}</Pill>
                <div>
                  <div className="font-semibold">{c.name}</div>
                  <div className="text-[12px] text-muted">{c.detail}</div>
                </div>
              </div>
            ))}
          </div>
        )}
        {stage.id === 'verify' && d.verdict && (
          <div className="space-y-2">
            <Pill tone={d.verdict.verdict === 'approve' ? 'ok' : 'signal'}>{d.verdict.verdict}</Pill>
            <p>{d.verdict.summary}</p>
            {d.verdict.concerns?.map((c: string, i: number) => (
              <p key={i} className="text-signal">• {c}</p>
            ))}
          </div>
        )}
        {stage.id === 'export' && d.files && (
          <ul className="space-y-1">
            {d.files.map((f: any) => (
              <li key={f.name} className="font-mono text-[12px]">{f.name}</li>
            ))}
          </ul>
        )}

        {logs.length > 0 && (
          <div>
            <div className="mb-1.5 text-[12px] font-semibold text-muted">Log</div>
            <div className="space-y-1">
              {logs.map((e) => (
                <div key={e.seq} className={e.type === 'llm_call' ? 'text-mind' : 'text-muted'}>
                  {e.message}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </motion.div>
  )
}
