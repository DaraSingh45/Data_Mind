import clsx from 'clsx'
import { motion } from 'framer-motion'
import { Activity, Database, Download, Lightbulb, Loader2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, useParams } from 'react-router-dom'
import { Pill, Spinner } from '../components/ui'
import { api, type GraphDef } from '../lib/api'
import { PROVIDER_LABEL } from '../lib/format'
import { useRunStream } from '../lib/useRun'
import AgentView from './run/AgentView'
import DataView from './run/DataView'
import ExportsView from './run/ExportsView'
import InsightsView from './run/InsightsView'

const TABS = [
  { id: 'agent', label: 'Agent', icon: Activity },
  { id: 'data', label: 'Prepared data', icon: Database },
  { id: 'insights', label: 'Insights', icon: Lightbulb },
  { id: 'exports', label: 'Exports', icon: Download },
]

const STATUS: Record<string, { tone: any; label: string }> = {
  running: { tone: 'signal', label: 'Working' },
  waiting: { tone: 'mind', label: 'Needs your input' },
  completed: { tone: 'ok', label: 'Complete' },
  failed: { tone: 'bad', label: 'Failed' },
  interrupted: { tone: 'neutral', label: 'Interrupted' },
}

function Elapsed({ from, to }: { from?: number; to?: number }) {
  const [now, setNow] = useState(Date.now() / 1000)
  useEffect(() => {
    if (to) return
    const t = setInterval(() => setNow(Date.now() / 1000), 500)
    return () => clearInterval(t)
  }, [to])
  if (!from) return null
  const s = Math.max(0, (to ?? now) - from)
  return <span className="tabular-nums">{s < 60 ? `${s.toFixed(1)}s` : `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`}</span>
}

export default function RunPage() {
  const { runId, tab = 'agent' } = useParams()
  const stream = useRunStream(runId)
  const [graph, setGraph] = useState<GraphDef | null>(null)
  useEffect(() => {
    api.graph().then(setGraph).catch(() => {})
  }, [])
  const meta = stream.detail?.meta
  const v = stream.view.status
  // follow the animation: until the canvas has played the end, the run still shows as working
  const status = !meta ? 'running' : meta.status === 'interrupted' ? 'interrupted' : v === 'completed' || v === 'failed' || v === 'waiting' ? v : 'running'
  const done = status === 'completed'

  if (!runId) return null
  return (
    <div className="flex min-h-full flex-col">
      <header className="border-b border-line bg-surface/60 px-5 pt-5 backdrop-blur sm:px-8">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h1 className="truncate text-[22px] font-extrabold tracking-tight">{meta?.dataset?.name ?? 'Loading run…'}</h1>
              <Pill tone={STATUS[status]?.tone}>
                {status === 'running' && <Loader2 className="size-3 animate-spin" />}
                {status === 'waiting' && <motion.span className="size-1.5 rounded-full bg-mind" animate={{ opacity: [1, 0.2, 1] }} transition={{ repeat: Infinity, duration: 1 }} />}
                {STATUS[status]?.label}
              </Pill>
            </div>
            <div className="mt-0.5 flex flex-wrap gap-x-3 text-[13px] text-muted">
              <span>{meta ? PROVIDER_LABEL[meta.provider] ?? meta.provider : ''}</span>
              {meta?.dataset && <span>{meta.dataset.rows.toLocaleString()} rows × {meta.dataset.columns} columns</span>}
              <span>
                <Elapsed from={meta?.created_at} to={done || status === 'failed' ? stream.view.endedAt ?? meta?.completed_at : undefined} />
              </span>
            </div>
          </div>
        </div>
        <nav className="mt-4 flex gap-1 overflow-x-auto">
          {TABS.map(({ id, label, icon: Icon }) => {
            const disabled = id !== 'agent' && !done
            return (
              <NavLink
                key={id}
                to={`/runs/${runId}/${id}`}
                onClick={(e) => disabled && e.preventDefault()}
                aria-disabled={disabled}
                className={clsx('relative flex items-center gap-2 px-3 pt-1 pb-3 text-[14px] font-semibold whitespace-nowrap', tab === id ? 'text-text' : 'text-muted hover:text-text', disabled && 'pointer-events-none opacity-40')}
              >
                <Icon className="size-4" />
                {label}
                {tab === id && <motion.span layoutId="run-tab" className="absolute inset-x-1 bottom-0 h-[3px] rounded-full bg-mind" />}
              </NavLink>
            )
          })}
        </nav>
      </header>
      <div className="flex-1 px-5 py-6 sm:px-8">
        {!graph ? (
          <div className="grid h-64 place-items-center">
            <Spinner />
          </div>
        ) : tab === 'agent' ? (
          <AgentView runId={runId} graph={graph} stream={stream} />
        ) : tab === 'data' ? (
          <DataView runId={runId} detail={stream.detail} />
        ) : tab === 'insights' ? (
          <InsightsView runId={runId} />
        ) : (
          <ExportsView runId={runId} detail={stream.detail} />
        )}
      </div>
    </div>
  )
}
