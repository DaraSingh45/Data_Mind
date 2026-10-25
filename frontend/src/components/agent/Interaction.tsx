import clsx from 'clsx'
import { motion } from 'framer-motion'
import { AlertTriangle, CheckCircle2, Sparkles, UserCheck } from 'lucide-react'
import { useMemo, useState } from 'react'
import { api, type PendingInput, type PlanColumn } from '../../lib/api'
import { Button, Pill } from '../ui'

export function Interaction({ runId, pending, onSent }: { runId: string; pending: Extract<PendingInput, { kind: 'review' }>; onSent: () => void }) {
  return (
    <motion.div initial={{ opacity: 0, y: 24, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} transition={{ type: 'spring', bounce: 0.25, duration: 0.5 }} className="card overflow-hidden border-mind/50 shadow-[var(--shadow)]">
      <div className="flex items-center gap-3 border-b border-line bg-mind/10 px-5 py-3.5">
        <motion.div animate={{ scale: [1, 1.12, 1] }} transition={{ repeat: Infinity, duration: 1.6 }} className="grid size-9 place-items-center rounded-xl bg-mind text-white">
          <UserCheck className="size-5" />
        </motion.div>
        <div>
          <div className="font-bold">{pending.title}</div>
          <div className="text-[13px] text-muted">{pending.question}</div>
        </div>
      </div>
      <ReviewForm runId={runId} pending={pending} onSent={onSent} />
    </motion.div>
  )
}

const OPTIONS = {
  role: ['feature', 'drop'],
  impute: ['none', 'mean', 'median', 'most_frequent', 'constant'],
  outliers: ['none', 'clip_iqr', 'winsorize', 'log1p'],
  encode: ['onehot', 'ordinal', 'frequency', 'target'],
  scale: ['none', 'standard', 'robust', 'minmax'],
}

function ReviewForm({ runId, pending, onSent }: { runId: string; pending: Extract<PendingInput, { kind: 'review' }>; onSent: () => void }) {
  const [answers, setAnswers] = useState<Record<string, string>>(() => Object.fromEntries(pending.questions.map((q) => [q.id, q.default ?? q.options[0]])))
  const [overrides, setOverrides] = useState<Record<string, Record<string, string>>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [onlyFlagged, setOnlyFlagged] = useState(pending.low_confidence.length > 0)
  const low = new Set(pending.low_confidence)
  const cols = useMemo(() => pending.plan.columns.filter((c) => !onlyFlagged || low.has(c.column) || c.source === 'llm'), [pending, onlyFlagged])

  const value = (c: PlanColumn, field: keyof typeof OPTIONS) => overrides[c.column]?.[field] ?? (c as any)[field]
  const set = (col: string, field: string, v: string) =>
    setOverrides((o) => {
      const orig = (pending.plan.columns.find((c) => c.column === col) as any)?.[field]
      const next = { ...o, [col]: { ...(o[col] || {}), [field]: v } }
      if (orig === v) delete next[col][field]
      if (!Object.keys(next[col]).length) delete next[col]
      return next
    })

  const approve = async () => {
    setBusy(true)
    setError(null)
    try {
      await api.resume(runId, { approved: true, answers, overrides })
      onSent()
    } catch (e: any) {
      setError(e.message)
      setBusy(false)
    }
  }
  const nOverrides = Object.values(overrides).reduce((n, o) => n + Object.keys(o).length, 0)

  return (
    <div className="space-y-5 p-5">
      <div className="flex flex-wrap gap-2 text-[13px]">
        <Pill tone="mind">target: {pending.plan.target ?? 'none'}</Pill>
        <Pill>task: {pending.plan.task}</Pill>
        <Pill>split: {pending.plan.split?.strategy} {Math.round((pending.plan.split?.test_size ?? 0) * 100)}% test</Pill>
        {pending.plan.imbalance && pending.plan.imbalance !== 'none' && <Pill tone="signal">imbalance: {pending.plan.imbalance}</Pill>}
      </div>
      {pending.plan.notes && pending.plan.notes.length > 0 && (
        <ul className="space-y-1 text-[13px] text-muted">
          {pending.plan.notes.map((n, i) => (
            <li key={i} className="flex gap-2">
              <span className="mt-2 size-1 shrink-0 rounded-full bg-muted" />
              {n}
            </li>
          ))}
        </ul>
      )}

      {pending.questions.length > 0 && (
        <div className="space-y-3">
          {pending.questions.map((q) => (
            <div key={q.id} className="rounded-xl border border-signal/40 bg-signal/5 p-4">
              <div className="flex items-start gap-2 font-semibold">
                {q.id.startsWith('llm') ? <Sparkles className="mt-0.5 size-4 shrink-0 text-mind" /> : <AlertTriangle className="mt-0.5 size-4 shrink-0 text-signal" />}
                {q.question}
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                {q.options.map((o) => (
                  <button key={o} onClick={() => setAnswers((a) => ({ ...a, [q.id]: o }))} className={clsx('rounded-full border px-3 py-1.5 text-[13px] transition-colors', answers[q.id] === o ? 'border-mind bg-mind text-white' : 'border-line hover:border-line-strong')}>
                    {o}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      <div>
        <div className="mb-2 flex items-center justify-between">
          <div className="text-[14px] font-bold">Column decisions</div>
          <label className="flex cursor-pointer items-center gap-1.5 text-[12.5px] text-muted">
            <input type="checkbox" checked={onlyFlagged} onChange={(e) => setOnlyFlagged(e.target.checked)} className="accent-[var(--mind)]" />
            only flagged and LLM-changed
          </label>
        </div>
        <div className="max-h-[380px] overflow-auto rounded-xl border border-line">
          <table className="w-full text-[12.5px]">
            <thead className="sticky top-0 z-10 bg-surface-2 text-left text-muted">
              <tr>
                <th className="px-3 py-2 font-semibold">Column</th>
                <th className="px-2 py-2 font-semibold">Role</th>
                <th className="px-2 py-2 font-semibold">Missing</th>
                <th className="px-2 py-2 font-semibold">Outliers</th>
                <th className="px-2 py-2 font-semibold">Encode / scale</th>
                <th className="px-3 py-2 font-semibold">Why</th>
              </tr>
            </thead>
            <tbody>
              {cols.map((c) => {
                const role = value(c, 'role')
                const isNum = c.kind === 'numeric'
                const sel = (field: keyof typeof OPTIONS, opts = OPTIONS[field]) => (
                  <select className={clsx('input !w-auto !px-2 !py-1 !pr-7 text-[12px]', overrides[c.column]?.[field] && '!border-mind')} value={value(c, field)} onChange={(e) => set(c.column, field, e.target.value)}>
                    {opts.map((o) => (
                      <option key={o}>{o}</option>
                    ))}
                  </select>
                )
                return (
                  <tr key={c.column} className={clsx('border-t border-line align-top', low.has(c.column) && 'bg-signal/5')}>
                    <td className="px-3 py-2">
                      <div className="font-semibold">{c.column}</div>
                      <div className="flex items-center gap-1 text-[11px] text-faint">
                        {c.semantic_type}
                        {c.source === 'llm' && <Pill tone="mind" className="!px-1.5 !text-[10px]">LLM</Pill>}
                        {low.has(c.column) && <Pill tone="signal" className="!px-1.5 !text-[10px]">check</Pill>}
                      </div>
                    </td>
                    <td className="px-2 py-2">{c.role === 'target' ? <Pill tone="mind">target</Pill> : sel('role')}</td>
                    <td className="px-2 py-2">{role === 'feature' && c.role !== 'target' ? sel('impute') : <span className="text-faint">—</span>}</td>
                    <td className="px-2 py-2">{role === 'feature' && isNum ? sel('outliers') : <span className="text-faint">—</span>}</td>
                    <td className="px-2 py-2">{role === 'feature' && c.role !== 'target' ? (isNum ? sel('scale') : sel('encode')) : <span className="text-faint">—</span>}</td>
                    <td className="max-w-[340px] px-3 py-2 text-muted">{c.reason}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-end gap-3">
        {error && <span className="mr-auto text-[13px] text-bad">{error}</span>}
        {nOverrides > 0 && <span className="text-[13px] text-muted">{nOverrides} change{nOverrides > 1 ? 's' : ''} by you</span>}
        <Button variant="primary" onClick={approve} loading={busy} icon={<CheckCircle2 className="size-4" />}>
          {nOverrides ? 'Apply changes and run' : 'Approve and run'}
        </Button>
      </div>
    </div>
  )
}
