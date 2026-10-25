import clsx from 'clsx'
import { AnimatePresence, motion } from 'framer-motion'
import { ArrowUp, Check, Cpu, Loader2, Play, Sparkles, Zap } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, type ChatMessage, type DatasetPayload, type IntakeReply } from '../../lib/api'
import { PROVIDER_LABEL } from '../../lib/format'
import { useStore, type AgentReplyTurn, type AgentTurn } from '../../lib/store'
import { Button, Md } from '../ui'

const STEP_GAP = 320 // ms between revealing finished steps, so you can read them

/** One agent turn: the steps it performed, then its reply, then what it does next. */
function AgentTurnView({ turn, animate, onDone }: { turn: AgentReplyTurn; animate: boolean; onDone: () => void }) {
  const [shown, setShown] = useState(animate ? 0 : turn.steps.length)
  useEffect(() => {
    if (shown >= turn.steps.length) {
      onDone()
      return
    }
    const t = setTimeout(() => setShown((n) => n + 1), STEP_GAP)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shown, turn.steps.length])
  const finished = shown >= turn.steps.length
  return (
    <div className="relative pl-6">
      <span className="absolute top-1.5 bottom-1 left-[7px] w-px bg-gradient-to-b from-mind/60 to-transparent" />
      <span className="absolute top-0.5 left-0 grid size-[15px] place-items-center rounded-full bg-mind text-white">
        <Sparkles className="size-2.5" />
      </span>
      <div className="mb-2 flex items-center gap-2 text-[12px] text-muted">
        <span className="font-bold text-text">Data Mind</span>
        {turn.source === 'llm' ? 'used the language model' : 'used the rules engine'}
      </div>
      <div className="space-y-1.5">
        {turn.steps.map((s, i) => {
          const state = i < shown ? 'done' : i === shown ? 'working' : 'todo'
          if (state === 'todo') return null
          return (
            <motion.div key={i} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} className="flex items-start gap-2 text-[13px]">
              <span className={clsx('mt-[3px] grid size-4 shrink-0 place-items-center rounded-full', state === 'done' ? 'bg-ok/20 text-ok' : 'text-signal')}>
                {state === 'done' ? <Check className="size-3" strokeWidth={3} /> : <Loader2 className="size-3.5 animate-spin" />}
              </span>
              <span>
                <span className="font-semibold">{s.label}</span>
                {state === 'done' && <span className="text-muted"> — {s.detail}</span>}
              </span>
            </motion.div>
          )
        })}
      </div>
      <AnimatePresence>
        {finished && (
          <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="mt-3 text-[14px] leading-relaxed">
            <Md>{turn.reply}</Md>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

/** "Starting the run in 3…" — the agent acts on its own, but you can stop it. */
function RunCountdown({ seconds, onGo, onCancel, label }: { seconds: number; onGo: () => void; onCancel: () => void; label: string }) {
  const [left, setLeft] = useState(seconds)
  useEffect(() => {
    if (left <= 0) {
      onGo()
      return
    }
    const t = setTimeout(() => setLeft((l) => l - 1), 1000)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [left])
  const r = 15
  const c = 2 * Math.PI * r
  return (
    <motion.div initial={{ opacity: 0, y: 8, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} className="ml-6 flex items-center gap-3 rounded-xl border border-mind/40 bg-mind/10 p-3">
      <svg width="38" height="38" viewBox="0 0 38 38" className="shrink-0 -rotate-90">
        <circle cx="19" cy="19" r={r} fill="none" stroke="var(--line)" strokeWidth="3" />
        <motion.circle cx="19" cy="19" r={r} fill="none" stroke="var(--mind)" strokeWidth="3" strokeLinecap="round" strokeDasharray={c} initial={{ strokeDashoffset: 0 }} animate={{ strokeDashoffset: c }} transition={{ duration: seconds, ease: 'linear' }} />
        <text x="19" y="19" textAnchor="middle" dominantBaseline="central" className="rotate-90" style={{ transformOrigin: '19px 19px', fontSize: 13, fontWeight: 800, fill: 'var(--text)' }}>
          {left}
        </text>
      </svg>
      <div className="min-w-0 flex-1">
        <div className="text-[13.5px] font-bold">Starting the run</div>
        <div className="truncate text-[12.5px] text-muted">{label}</div>
      </div>
      <Button size="sm" variant="ghost" onClick={onCancel}>
        Not yet
      </Button>
      <Button size="sm" variant="primary" onClick={onGo} icon={<Play className="size-3.5" />}>
        Start now
      </Button>
    </motion.div>
  )
}

export function IntakeChat({ data }: { data: DatasetPayload }) {
  const { session, setChat, settings } = useStore()
  const [text, setText] = useState('')
  const [thinking, setThinking] = useState(false)
  const [starting, setStarting] = useState(false)
  const [countdown, setCountdown] = useState(false)
  const [animating, setAnimating] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const scroller = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()
  const turns = session.turns
  const provider = settings?.llm.provider ?? 'heuristic'
  const model = provider === 'ollama' ? settings?.llm.ollama_model : provider === 'groq' ? settings?.llm.groq_model : provider === 'gemini' ? settings?.llm.gemini_model : ''

  const pushAgent = (r: IntakeReply, msgs: ChatMessage[], prior: AgentTurn[]) => {
    const turn: AgentReplyTurn = { role: 'agent', steps: r.steps ?? [], reply: r.reply, source: r.source, action: r.action }
    const nextTurns = [...prior, turn]
    setAnimating(nextTurns.length - 1)
    setChat([...msgs, { role: 'assistant', content: r.reply }], { ...session.intent, ...r.intent }, r.ready, nextTurns)
  }

  // The agent's first look at the data
  useEffect(() => {
    if (turns.length) return
    setThinking(true)
    api
      .intake(data.dataset.id, [])
      .then((r) => pushAgent(r, [], []))
      .catch((e) => setError(e.message))
      .finally(() => setThinking(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data.dataset.id])

  // Keep the newest message in view while the agent writes, unless you scrolled up to read.
  const pinned = useRef(true)
  const content = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const el = scroller.current
    const inner = content.current
    if (!el || !inner) return
    const onScroll = () => {
      pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
    }
    const ro = new ResizeObserver(() => {
      if (pinned.current) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
    })
    el.addEventListener('scroll', onScroll, { passive: true })
    ro.observe(inner)
    return () => {
      el.removeEventListener('scroll', onScroll)
      ro.disconnect()
    }
  }, [])

  const send = async (content: string) => {
    if (!content.trim() || thinking) return
    setCountdown(false)
    const msgs: ChatMessage[] = [...session.messages, { role: 'user', content: content.trim() }]
    const prior: AgentTurn[] = [...turns, { role: 'user', text: content.trim() }]
    setChat(msgs, undefined, undefined, prior)
    setText('')
    setThinking(true)
    setError(null)
    try {
      const r = await api.intake(data.dataset.id, msgs)
      pushAgent(r, msgs, prior)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setThinking(false)
    }
  }

  const start = async () => {
    if (starting) return
    setCountdown(false)
    setStarting(true)
    setError(null)
    try {
      const { run_id } = await api.startRun(data.dataset.id, session.messages, session.intent)
      navigate(`/runs/${run_id}`)
    } catch (e: any) {
      setError(e.message)
      setStarting(false)
    }
  }

  const columns = data.profile.columns_detail.map((c) => c.name)
  const idCol = columns.find((c) => /email|_id$|^id$/i.test(c))
  const suggestions = [
    ...data.candidates.slice(0, 2).map((c) => `Predict ${c}`),
    'Just clean it and show insights',
    ...(idCol && data.candidates[0] ? [`Predict ${data.candidates[0]}, ignore ${idCol}`] : []),
  ]
  const userTurns = turns.filter((t) => t.role === 'user').length
  const intent = session.intent
  const goal = intent.target ? `Predict ${intent.target}${intent.exclude_columns?.length ? ` · leave out ${intent.exclude_columns.join(', ')}` : ''}` : intent.task === 'none' ? 'Clean and explore' : 'Goal will be asked during the run'

  return (
    <div className="card flex h-[calc(100dvh-6rem)] max-h-[860px] min-h-[520px] flex-col overflow-hidden">
      <div className="flex shrink-0 items-center gap-3 border-b border-line px-5 py-3.5">
        <div className="relative grid size-9 place-items-center rounded-xl bg-mind/15 text-mind">
          <Sparkles className="size-5" />
          <motion.span className="absolute -top-0.5 -right-0.5 size-2.5 rounded-full border-2 border-surface bg-ok" animate={{ scale: [1, 1.25, 1] }} transition={{ repeat: Infinity, duration: 2 }} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="font-bold">Data Mind agent</div>
          <div className="truncate text-[12.5px] text-muted">Tell it your goal — it plans, runs and asks only if unsure.</div>
        </div>
        <Link
          to="/settings"
          title={provider === 'heuristic' ? 'No language model connected — click to connect one' : `Using ${PROVIDER_LABEL[provider]}`}
          className={clsx('flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11.5px] font-semibold', provider === 'heuristic' ? 'border-signal/40 text-signal' : 'border-ok/40 text-ok')}
        >
          {provider === 'heuristic' ? <Zap className="size-3" /> : <Cpu className="size-3" />}
          {provider === 'heuristic' ? 'Rules engine · instant' : `${PROVIDER_LABEL[provider]} · ${model}`}
        </Link>
      </div>

      <div ref={scroller} className="chat-scroll min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 py-5">
        <div ref={content} className="space-y-5">
        {turns.map((t, i) =>
          t.role === 'user' ? (
            <motion.div key={i} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="flex justify-end">
              <div className="max-w-[85%] rounded-xl border border-line bg-surface-2 px-3.5 py-2 text-[14px]">
                <div className="mb-0.5 text-[11px] font-semibold text-faint">You</div>
                {t.text}
              </div>
            </motion.div>
          ) : (
            <div key={i}>
              <AgentTurnView
                turn={t}
                animate={animating === i}
                onDone={() => {
                  if (animating === i) {
                    setAnimating(null)
                    if (t.action === 'run' && i === turns.length - 1) setCountdown(true)
                  }
                }}
              />
            </div>
          ),
        )}
        {thinking && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="relative flex items-center gap-2 pl-6 text-[13px] text-muted">
            <span className="absolute top-0.5 left-0 grid size-[15px] place-items-center rounded-full bg-mind text-white">
              <Sparkles className="size-2.5" />
            </span>
            <Loader2 className="size-3.5 animate-spin text-signal" />
            {turns.length ? (provider === 'heuristic' ? 'Reading your request…' : `Thinking with ${model}…`) : 'Profiling your data…'}
          </motion.div>
        )}
        <AnimatePresence>{countdown && <RunCountdown key="cd" seconds={3} label={goal} onGo={start} onCancel={() => setCountdown(false)} />}</AnimatePresence>
        {userTurns === 0 && !thinking && animating === null && turns.length > 0 && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex flex-wrap gap-2 pl-6">
            {suggestions.map((s) => (
              <button key={s} onClick={() => send(s)} className="rounded-full border border-line px-3 py-1.5 text-[13px] text-muted transition-colors hover:border-mind hover:text-text">
                {s}
              </button>
            ))}
          </motion.div>
        )}
        </div>
      </div>

      <div className="shrink-0 border-t border-line p-4">
        <form
          onSubmit={(e) => {
            e.preventDefault()
            send(text)
          }}
          className="flex items-end gap-2"
        >
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                send(text)
              }
            }}
            rows={1}
            placeholder="Tell the agent what to do, e.g. “predict churn, ignore email”"
            className="input max-h-32 min-h-[42px] resize-none"
          />
          <Button type="submit" variant="primary" disabled={!text.trim() || thinking} aria-label="Send" className="!h-[42px] !px-3">
            <ArrowUp className="size-4" />
          </Button>
        </form>
        <div className="mt-2.5 flex items-center justify-between gap-3">
          <span className="truncate text-[12px] text-faint">{goal}</span>
          <Button variant="outline" size="sm" onClick={start} loading={starting} icon={<Play className="size-3.5" />}>
            Run now
          </Button>
        </div>
        {error && <p className="mt-2 text-[13px] text-bad">{error}</p>}
      </div>
    </div>
  )
}
