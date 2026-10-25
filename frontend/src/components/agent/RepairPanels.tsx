import clsx from 'clsx'
import { AnimatePresence, motion } from 'framer-motion'
import { AlertOctagon, Check, ChevronDown, Copy, Cpu, RotateCcw, Settings2, Wrench } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, type AgentEvent, type RepairAttempt, type RunMeta } from '../../lib/api'
import { useStore } from '../../lib/store'
import { Button, Pill } from '../ui'

/** Live strip above the canvas while the agent is fixing a crash. */
export function RepairStrip({ events, active }: { events: AgentEvent[]; active: boolean }) {
  let lastError: AgentEvent | undefined
  let lastFix: AgentEvent | undefined
  for (const e of events) {
    if (e.type === 'node_error') {
      lastError = e
      lastFix = undefined
    } else if (e.type === 'node_completed' && e.node === 'repair') lastFix = e
  }
  const show = active && !!lastError
  const repairing = show && !lastFix
  const d = lastError?.data ?? {}
  const fix: RepairAttempt | undefined = lastFix?.data?.repair
  return (
    <AnimatePresence>
      {show && (
        <motion.div
          key={lastError!.seq}
          initial={{ opacity: 0, y: -8, height: 0 }}
          animate={{ opacity: 1, y: 0, height: 'auto' }}
          exit={{ opacity: 0, height: 0 }}
          className={clsx('card flex items-start gap-3 overflow-hidden p-4', repairing ? 'border-signal/50' : 'border-mind/50')}
        >
          <motion.div
            animate={repairing ? { rotate: [0, -25, 20, -10, 0] } : { rotate: 0 }}
            transition={{ repeat: repairing ? Infinity : 0, duration: 1.4 }}
            className={clsx('grid size-9 shrink-0 place-items-center rounded-xl', repairing ? 'bg-signal/15 text-signal' : 'bg-mind/15 text-mind')}
          >
            <Wrench className="size-[18px]" />
          </motion.div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2 text-[14px] font-bold">
              {repairing ? `${d.label} failed — the agent is fixing it` : 'Fix applied — trying again'}
              <Pill tone={repairing ? 'signal' : 'mind'}>
                attempt {d.attempt} of {d.limit}
              </Pill>
            </div>
            <p className="mt-0.5 text-[13.5px] text-muted">{d.reason}</p>
            {fix?.fixes?.[0] && <p className="mt-1 text-[13px]">→ {fix.fixes[0]}</p>}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

function Attempt({ a }: { a: RepairAttempt }) {
  const [open, setOpen] = useState(false)
  return (
    <li className="relative pl-7">
      <span className="absolute top-1 left-0 grid size-[18px] place-items-center rounded-full bg-signal/20 text-signal">
        <Wrench className="size-2.5" />
      </span>
      <div className="flex flex-wrap items-center gap-2 text-[13.5px]">
        <span className="font-bold">
          Attempt {a.attempt} · {a.label} failed
        </span>
        <Pill tone={a.source.includes('llm') ? 'mind' : 'neutral'}>{a.source.includes('llm') ? 'LLM + rules' : 'rules engine'}</Pill>
      </div>
      <p className="mt-0.5 text-[13px] text-muted">{a.diagnosis || a.reason}</p>
      {a.culprits.length > 0 && (
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[12px] text-muted">
          Caused by
          {a.culprits.map((c) => (
            <code key={c} className="rounded-md bg-bad/10 px-1.5 py-0.5 text-bad">
              {c}
            </code>
          ))}
        </div>
      )}
      <ul className="mt-1.5 space-y-0.5 text-[13px]">
        {a.fixes.map((f, i) => (
          <li key={i} className="flex gap-1.5">
            <Check className="mt-[3px] size-3.5 shrink-0 text-ok" />
            {f}
          </li>
        ))}
      </ul>
      {a.changes.length > 0 && (
        <button onClick={() => setOpen(!open)} className="mt-1 flex items-center gap-1 text-[12px] font-semibold text-faint hover:text-text">
          <ChevronDown className={clsx('size-3.5 transition-transform', open && 'rotate-180')} />
          {a.changes.length} plan change{a.changes.length > 1 ? 's' : ''}
        </button>
      )}
      {open && <div className="mt-1 rounded-lg bg-surface-2 p-2 font-mono text-[11.5px] text-muted">{a.changes.join('\n')}</div>}
    </li>
  )
}

/** Full explanation of why a run failed, every repair attempt, and what to do next. */
export function FailurePanel({ meta }: { meta: RunMeta }) {
  const f = meta.failure
  const [tech, setTech] = useState(false)
  const [copied, setCopied] = useState(false)
  const [retrying, setRetrying] = useState(false)
  const navigate = useNavigate()
  const provider = useStore((s) => s.settings?.llm.provider ?? 'heuristic')
  const reason = f?.reason ?? meta.error ?? 'The run stopped.'
  const retry = async () => {
    setRetrying(true)
    try {
      const { run_id } = await api.startRun(meta.dataset.id, [], meta.intent ?? {})
      navigate(`/runs/${run_id}`)
    } finally {
      setRetrying(false)
    }
  }
  const details = f ? `${f.error_type}: ${f.error}\n\n${f.traceback ?? ''}` : reason
  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="card overflow-hidden border-bad/40">
      <div className="flex flex-wrap items-start gap-4 p-5">
        <div className="grid size-11 shrink-0 place-items-center rounded-2xl bg-bad/15 text-bad">
          <AlertOctagon className="size-6" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-[16px] font-bold">The run failed{f?.label ? ` at ${f.label}` : ''}</div>
          {f?.why_stopped && <div className="text-[13px] text-muted">{f.why_stopped}</div>}
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <div className="rounded-xl bg-surface-2 p-3">
              <div className="text-[11px] font-bold tracking-wide text-faint uppercase">What went wrong</div>
              <p className="mt-1 text-[13.5px]">{reason}</p>
              {f?.columns && f.columns.length > 0 && (
                <p className="mt-1 text-[12.5px] text-muted">
                  Columns involved: {f.columns.map((c) => <code key={c} className="mx-0.5 rounded bg-bad/10 px-1 text-bad">{c}</code>)}
                </p>
              )}
            </div>
            <div className="rounded-xl bg-surface-2 p-3">
              <div className="text-[11px] font-bold tracking-wide text-faint uppercase">What you can do</div>
              <p className="mt-1 text-[13.5px]">{f?.hint ?? 'Start the run again.'}</p>
            </div>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="primary" onClick={retry} loading={retrying} icon={<RotateCcw className="size-4" />}>
            Try again
          </Button>
          <Link to="/settings?section=agent">
            <Button variant="outline" icon={<Settings2 className="size-4" />}>
              Repair settings
            </Button>
          </Link>
        </div>
      </div>

      {f && f.attempts.length > 0 && (
        <div className="border-t border-line px-5 py-4">
          <div className="mb-3 text-[13px] font-bold">
            What the agent tried ({f.attempts.length} of {f.limit} repair attempt{f.limit === 1 ? '' : 's'})
          </div>
          <ol className="space-y-4">
            {f.attempts.map((a) => (
              <Attempt key={a.attempt} a={a} />
            ))}
          </ol>
        </div>
      )}

      {provider === 'heuristic' && (
        <div className="flex items-center gap-2 border-t border-line px-5 py-3 text-[13px] text-muted">
          <Cpu className="size-4 text-mind" />
          Repairs used the rules engine only.
          <Link to="/settings" className="font-semibold text-mind hover:underline">
            Connect an LLM
          </Link>
          for smarter diagnosis and fixes.
        </div>
      )}

      <div className="border-t border-line px-5 py-3">
        <div className="flex items-center justify-between gap-2">
          <button onClick={() => setTech(!tech)} className="flex items-center gap-1 text-[12.5px] font-semibold text-muted hover:text-text">
            <ChevronDown className={clsx('size-4 transition-transform', tech && 'rotate-180')} />
            Technical details
          </button>
          {tech && (
            <button
              onClick={() => {
                navigator.clipboard?.writeText(details).catch(() => {})
                setCopied(true)
                setTimeout(() => setCopied(false), 1500)
              }}
              className="flex items-center gap-1 text-[12px] font-semibold text-muted hover:text-text"
            >
              {copied ? <Check className="size-3.5 text-ok" /> : <Copy className="size-3.5" />}
              {copied ? 'Copied' : 'Copy'}
            </button>
          )}
        </div>
        {tech && <pre className="chat-scroll mt-2 max-h-72 overflow-auto rounded-lg bg-bg p-3 font-mono text-[11.5px] leading-relaxed whitespace-pre-wrap text-muted">{details}</pre>}
      </div>
    </motion.div>
  )
}

/** Shown on a finished run that needed self-repair. */
export function RepairSummary({ repairs }: { repairs: RepairAttempt[] }) {
  const [open, setOpen] = useState(false)
  if (!repairs.length) return null
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="card border-mind/40 p-4">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-3 text-left">
        <div className="grid size-9 place-items-center rounded-xl bg-mind/15 text-mind">
          <Wrench className="size-[18px]" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-[14px] font-bold">
            Self-repaired after {repairs.length} attempt{repairs.length > 1 ? 's' : ''}
          </div>
          <div className="truncate text-[13px] text-muted">{repairs.map((r) => `${r.label}: ${r.reason}`).join(' · ')}</div>
        </div>
        <ChevronDown className={clsx('size-4 text-muted transition-transform', open && 'rotate-180')} />
      </button>
      {open && (
        <ol className="mt-4 space-y-4 border-t border-line pt-4">
          {repairs.map((a) => (
            <Attempt key={a.attempt} a={a} />
          ))}
        </ol>
      )}
    </motion.div>
  )
}
