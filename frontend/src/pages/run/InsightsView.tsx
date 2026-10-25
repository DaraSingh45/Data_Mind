import clsx from 'clsx'
import { AnimatePresence, motion } from 'framer-motion'
import { ArrowUp, Bot, Lightbulb, MessageSquareText, Pin, PinOff, Sparkles, User, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Plot } from '../../components/Plot'
import { Button, DataTable, Empty, Md, Pill, Spinner, Tabs } from '../../components/ui'
import { api, type ChartAnswer, type ChatMessage, type Insight, type InsightsPayload } from '../../lib/api'
import { loadPins, savePins } from '../../lib/store'

const KIND_LABEL: Record<string, string> = {
  driver: 'Driver',
  trend: 'Trend',
  segment: 'Segment',
  distribution: 'Distribution',
  correlation: 'Relationship',
  composition: 'Mix',
  quality: 'Data quality',
}

type Turn = ChatMessage & { answer?: ChartAnswer; question?: string }

export default function InsightsView({ runId }: { runId: string }) {
  const [data, setData] = useState<InsightsPayload | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [kind, setKind] = useState('all')
  const [chatOpen, setChatOpen] = useState(true)
  const [pins, setPins] = useState<any[]>(() => loadPins(runId))
  const [expanded, setExpanded] = useState<Insight | null>(null)

  useEffect(() => {
    api.insights(runId).then(setData).catch((e) => setError(e.message))
  }, [runId])

  const kinds = useMemo(() => ['all', ...Array.from(new Set((data?.insights ?? []).map((i) => i.kind)))], [data])
  const shown = (data?.insights ?? []).filter((i) => kind === 'all' || i.kind === kind)

  const pin = (a: ChartAnswer, question: string) => {
    const next = [...pins, { id: Date.now(), title: question, chart: a.chart, reply: a.reply }]
    setPins(next)
    savePins(runId, next)
  }
  const unpin = (id: number) => {
    const next = pins.filter((p) => p.id !== id)
    setPins(next)
    savePins(runId, next)
  }

  if (error) return <Empty title="Insights aren't available">{error}</Empty>
  if (!data)
    return (
      <div className="mx-auto grid max-w-[1280px] gap-4 md:grid-cols-2">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="skeleton h-72" />
        ))}
      </div>
    )

  return (
    <div className={clsx('mx-auto grid max-w-[1500px] gap-6', chatOpen && 'xl:grid-cols-[minmax(0,1fr)_400px]')}>
      <div className="min-w-0 space-y-6">
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="card relative overflow-hidden p-6">
          <div className="pointer-events-none absolute -top-16 -right-16 size-56 rounded-full bg-mind/15 blur-3xl" />
          <div className="flex items-center gap-2 text-[13px] text-muted">
            <Lightbulb className="size-4 text-signal" />
            {data.insights.length} findings from {data.candidates_considered} tested patterns
            {data.narrative.source === 'llm' && (
              <Pill tone="mind">
                <Sparkles className="size-3" />
                written by LLM
              </Pill>
            )}
          </div>
          <h2 className="mt-2 max-w-[40ch] text-[26px] leading-tight font-extrabold tracking-tight">{data.narrative.headline}</h2>
          <p className="mt-2 max-w-[75ch] text-[14.5px] text-muted">{data.narrative.summary}</p>
          {data.narrative.next_steps?.length > 0 && (
            <div className="mt-4 flex flex-wrap gap-2">
              {data.narrative.next_steps.map((s, i) => (
                <span key={i} className="rounded-full border border-line px-3 py-1 text-[12.5px] text-muted">
                  {s}
                </span>
              ))}
            </div>
          )}
        </motion.div>

        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 2xl:grid-cols-6">
          {data.kpis.map((k, i) => (
            <motion.div key={k.label} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 * i }} className="card px-4 py-3">
              <div className="truncate text-[12px] text-muted">{k.label}</div>
              <div className="mt-0.5 truncate text-[20px] font-extrabold tracking-tight">{k.value}</div>
              {k.hint && <div className="truncate text-[11.5px] text-faint">{k.hint}</div>}
            </motion.div>
          ))}
        </div>

        {pins.length > 0 && (
          <div>
            <h3 className="mb-3 text-[15px] font-bold">Your pinned charts</h3>
            <div className="grid gap-4 lg:grid-cols-2">
              {pins.map((p) => (
                <div key={p.id} className="card p-4">
                  <div className="flex items-start justify-between gap-2">
                    <div className="font-bold">{p.title}</div>
                    <button onClick={() => unpin(p.id)} className="rounded-lg p-1 text-muted hover:bg-surface-2 hover:text-text" aria-label="Unpin">
                      <PinOff className="size-4" />
                    </button>
                  </div>
                  <Md className="mt-1 text-[13px] text-muted">{p.reply}</Md>
                  {p.chart && <Plot spec={p.chart} height={260} />}
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="flex flex-wrap items-center justify-between gap-3">
          <Tabs value={kind} onChange={setKind} tabs={kinds.map((k) => ({ id: k, label: k === 'all' ? 'All' : KIND_LABEL[k] ?? k }))} />
          {!chatOpen && (
            <Button variant="primary" onClick={() => setChatOpen(true)} icon={<MessageSquareText className="size-4" />}>
              Ask for a chart
            </Button>
          )}
        </div>

        <motion.div layout className="grid gap-4 lg:grid-cols-2">
          <AnimatePresence mode="popLayout">
            {shown.map((ins, i) => (
              <motion.article
                layout
                key={ins.id}
                initial={{ opacity: 0, y: 14 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.96 }}
                transition={{ delay: Math.min(i * 0.05, 0.4) }}
                className={clsx('card flex flex-col p-5', i === 0 && kind === 'all' && 'lg:col-span-2')}
              >
                <div className="flex items-center gap-2 text-[12px]">
                  <Pill tone={ins.kind === 'driver' ? 'mind' : ins.kind === 'trend' ? 'signal' : ins.kind === 'quality' ? 'bad' : 'info'}>{KIND_LABEL[ins.kind] ?? ins.kind}</Pill>
                  <ScoreBar score={ins.score} />
                  {ins.stats?.p_value != null && <span className="text-faint">p = {ins.stats.p_value < 0.001 ? '<0.001' : ins.stats.p_value.toFixed(3)}</span>}
                  <button onClick={() => setExpanded(ins)} className="ml-auto text-[12px] font-semibold text-muted hover:text-text">
                    Expand
                  </button>
                </div>
                <h3 className="mt-2 text-[16px] font-bold">{ins.title}</h3>
                <Md className="mt-1 text-[13.5px] text-muted">{ins.text}</Md>
                <div className="mt-3">
                  <Plot spec={ins.chart} height={i === 0 && kind === 'all' ? 320 : 260} />
                </div>
              </motion.article>
            ))}
          </AnimatePresence>
        </motion.div>
      </div>

      <AnimatePresence>
        {chatOpen && (
          <motion.aside initial={{ opacity: 0, x: 30 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 30 }} className="xl:sticky xl:top-6 xl:h-[calc(100vh-200px)] xl:self-start">
            <InsightChat runId={runId} roles={data.roles} onPin={pin} onClose={() => setChatOpen(false)} />
          </motion.aside>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {expanded && (
          <motion.div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setExpanded(null)}>
            <motion.div initial={{ scale: 0.94, y: 20 }} animate={{ scale: 1, y: 0 }} exit={{ scale: 0.96 }} className="card w-full max-w-5xl p-6" onClick={(e) => e.stopPropagation()}>
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h3 className="text-xl font-bold">{expanded.title}</h3>
                  <Md className="mt-1 text-[14px] text-muted">{expanded.text}</Md>
                </div>
                <button onClick={() => setExpanded(null)} className="rounded-lg p-1.5 text-muted hover:bg-surface-2" aria-label="Close">
                  <X className="size-5" />
                </button>
              </div>
              <Plot spec={expanded.chart} height={480} compact={false} />
              <div className="mt-2 flex flex-wrap gap-2 text-[12px] text-muted">
                {Object.entries(expanded.stats || {})
                  .filter(([, v]) => typeof v !== 'object')
                  .map(([k, v]) => (
                    <span key={k} className="rounded-md bg-surface-2 px-2 py-1">
                      {k.replaceAll('_', ' ')}: {String(v)}
                    </span>
                  ))}
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function ScoreBar({ score }: { score: number }) {
  return (
    <span className="flex items-center gap-1.5 text-faint" title={`Interest score ${score}`}>
      <span className="h-1.5 w-12 overflow-hidden rounded-full bg-surface-3">
        <motion.span className="block h-full rounded-full bg-signal" initial={{ width: 0 }} animate={{ width: `${Math.min(score, 1) * 100}%` }} transition={{ duration: 0.8, delay: 0.2 }} />
      </span>
    </span>
  )
}

function InsightChat({ runId, roles, onPin, onClose }: { runId: string; roles: Record<string, any>; onPin: (a: ChartAnswer, q: string) => void; onClose: () => void }) {
  const [turns, setTurns] = useState<Turn[]>([])
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    box.current?.scrollTo({ top: box.current.scrollHeight, behavior: 'smooth' })
  }, [turns.length, busy])

  const m = roles.measure?.[0]
  const d = roles.dimension?.[0]
  const t = roles.time?.[0]
  const target = roles.target
  const ideas = [
    target && d && `${target} rate by ${d}`,
    m && d && `average ${m} by ${d}`,
    t && `${m ? `total ${m}` : 'count'} by month`,
    m && roles.measure?.[1] && `${m} vs ${roles.measure[1]}`,
    m && `distribution of ${m}`,
    d && `top 5 ${d} by count`,
  ].filter(Boolean) as string[]

  const ask = async (q: string) => {
    if (!q.trim() || busy) return
    const history = turns.map(({ role, content }) => ({ role, content }))
    setTurns((ts) => [...ts, { role: 'user', content: q }])
    setText('')
    setBusy(true)
    try {
      const a = await api.insightChat(runId, q, history)
      setTurns((ts) => [...ts, { role: 'assistant', content: a.reply, answer: a, question: q }])
    } catch (e: any) {
      setTurns((ts) => [...ts, { role: 'assistant', content: `Something went wrong: ${e.message}` }])
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card flex h-[640px] flex-col overflow-hidden xl:h-full">
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <div className="flex items-center gap-2 font-bold">
          <MessageSquareText className="size-4 text-mind" />
          Ask your data
        </div>
        <button onClick={onClose} className="rounded-lg p-1 text-muted hover:bg-surface-2 hover:text-text" aria-label="Close chat">
          <X className="size-4" />
        </button>
      </div>
      <div ref={box} className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
        {turns.length === 0 && (
          <div className="space-y-3">
            <p className="text-[13.5px] text-muted">Ask for any breakdown, trend or comparison. Each answer is computed from the cleaned data and drawn as a chart you can pin to the dashboard.</p>
            <div className="flex flex-wrap gap-2">
              {ideas.map((q) => (
                <button key={q} onClick={() => ask(q)} className="rounded-full border border-line px-3 py-1.5 text-left text-[12.5px] text-muted transition-colors hover:border-mind hover:text-text">
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}
        <AnimatePresence initial={false}>
          {turns.map((tn, i) => (
            <motion.div key={i} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className={clsx('flex gap-2', tn.role === 'user' && 'flex-row-reverse')}>
              <div className={clsx('grid size-6 shrink-0 place-items-center rounded-lg', tn.role === 'user' ? 'bg-surface-3 text-muted' : 'bg-mind/15 text-mind')}>
                {tn.role === 'user' ? <User className="size-3.5" /> : <Bot className="size-3.5" />}
              </div>
              <div className={clsx('min-w-0 rounded-2xl px-3 py-2 text-[13px]', tn.role === 'user' ? 'max-w-[85%] rounded-tr-md bg-mind text-white' : 'w-full rounded-tl-md bg-surface-2')}>
                {tn.role === 'user' ? tn.content : <Md>{tn.content}</Md>}
                {tn.answer?.kpi && (
                  <div className="mt-2 rounded-xl bg-surface p-3">
                    <div className="text-[12px] text-muted">{tn.answer.kpi.label}</div>
                    <div className="text-2xl font-extrabold">{tn.answer.kpi.value}</div>
                  </div>
                )}
                {tn.answer?.chart && (
                  <div className="mt-2 rounded-xl bg-surface p-1">
                    <Plot spec={tn.answer.chart} height={220} />
                  </div>
                )}
                {tn.answer?.table && (
                  <div className="mt-2">
                    <DataTable columns={tn.answer.table.columns} rows={tn.answer.table.rows} maxHeight={220} />
                  </div>
                )}
                {tn.answer?.chart && (
                  <div className="mt-2 flex items-center gap-2">
                    <button onClick={() => onPin(tn.answer!, tn.question!)} className="flex items-center gap-1 text-[12px] font-semibold text-mind hover:underline">
                      <Pin className="size-3.5" />
                      Pin to dashboard
                    </button>
                    <span className="ml-auto text-[11px] text-faint">{tn.answer.source === 'llm' ? 'spec by LLM' : 'spec by rules'}</span>
                  </div>
                )}
              </div>
            </motion.div>
          ))}
          {busy && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex items-center gap-2 text-[13px] text-muted">
              <Spinner className="size-4" />
              Computing…
            </motion.div>
          )}
        </AnimatePresence>
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          ask(text)
        }}
        className="flex gap-2 border-t border-line p-3"
      >
        <input className="input" value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. churn rate by contract for the North region" />
        <Button type="submit" variant="primary" disabled={!text.trim() || busy} aria-label="Ask" className="!px-3">
          <ArrowUp className="size-4" />
        </Button>
      </form>
    </div>
  )
}
