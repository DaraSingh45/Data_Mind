import { AnimatePresence, motion } from 'framer-motion'
import { Lightbulb, MousePointerClick, Pause, Play, Radio, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Console } from '../../components/agent/Console'
import { Interaction } from '../../components/agent/Interaction'
import { NodeDetails } from '../../components/agent/NodeDetails'
import { QuestionCards } from '../../components/agent/QuestionCards'
import { FailurePanel, RepairStrip, RepairSummary } from '../../components/agent/RepairPanels'
import { SimulationCanvas } from '../../components/agent/SimulationCanvas'
import { Button } from '../../components/ui'
import type { GraphDef, PendingInput, QuestionCard } from '../../lib/api'
import { useReplay, type useRunStream } from '../../lib/useRun'

/** Older runs sent a single "question"; show it as a question card too. */
function asCards(p: PendingInput): { title: string; questions: QuestionCard[] } | null {
  if (p.kind === 'questions') return { title: p.title, questions: p.questions }
  if ((p as any).kind === 'question') {
    const q = p as any
    return { title: q.title, questions: [{ id: 'target', header: 'Goal', question: q.question, options: q.options, allow_other: q.allow_free_text }] }
  }
  return null
}

export default function AgentView({ runId, graph, stream }: { runId: string; graph: GraphDef; stream: ReturnType<typeof useRunStream> }) {
  const [selected, setSelected] = useState<string | null>(null)
  const [replaying, setReplaying] = useState(false)
  const replay = useReplay(stream.allEvents)
  const meta = stream.detail?.meta
  // what the canvas has *played* so far decides what is shown, so panels appear in step with the animation
  const done = meta?.status === 'completed' && stream.view.status === 'completed'
  const view = replaying ? replay.view : stream.view
  const events = replaying ? replay.shown : stream.events
  const pending = !replaying && meta?.status === 'waiting' && stream.view.status === 'waiting' ? meta.pending : null
  const cards = pending ? asCards(pending) : null
  const stage = graph.stages.find((s) => s.id === selected)
  const llmCalls = stream.events.filter((e) => e.type === 'llm_call').length

  const overlay = pending ? (
    cards ? (
      <QuestionCards key={pending.id + JSON.stringify(cards.questions.map((q) => q.id))} runId={runId} title={cards.title} questions={cards.questions} onSent={stream.refresh} />
    ) : (
      <div className="max-h-full w-full max-w-5xl overflow-y-auto">
        <Interaction runId={runId} pending={pending as Extract<PendingInput, { kind: 'review' }>} onSent={stream.refresh} />
      </div>
    )
  ) : null

  const toolbar = (
    <div className="flex items-center gap-2">
      {llmCalls > 0 && (
        <span className="flex items-center gap-1 rounded-xl border border-line bg-surface/85 px-2.5 py-1.5 text-[11.5px] font-semibold text-mind backdrop-blur">
          <Sparkles className="size-3.5" />
          {llmCalls} LLM call{llmCalls > 1 ? 's' : ''}
        </span>
      )}
      {done && (
        <div className="flex items-center gap-1.5 rounded-xl border border-line bg-surface/90 p-1 pl-2.5 backdrop-blur">
          {replaying ? (
            <>
              <input type="range" min={0} max={stream.allEvents.length} value={replay.index} onChange={(e) => replay.seek(Number(e.target.value))} className="w-24 accent-[var(--mind)]" aria-label="Replay position" />
              <select className="input !w-auto !py-1 !pr-7 text-[12px]" value={replay.speed} onChange={(e) => replay.setSpeed(Number(e.target.value))} aria-label="Replay speed">
                {[0.5, 1, 2, 4].map((s) => (
                  <option key={s} value={s}>
                    {s}×
                  </option>
                ))}
              </select>
              <Button size="sm" variant="subtle" onClick={() => (replay.playing ? replay.pause() : replay.play())} icon={replay.playing ? <Pause className="size-3.5" /> : <Play className="size-3.5" />}>
                {replay.playing ? 'Pause' : 'Play'}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setReplaying(false)} icon={<Radio className="size-3.5" />}>
                Live
              </Button>
            </>
          ) : (
            <Button
              size="sm"
              variant="primary"
              onClick={() => {
                setReplaying(true)
                replay.reset()
                setTimeout(replay.play, 50)
              }}
              icon={<Play className="size-3.5" />}
            >
              Replay run
            </Button>
          )}
        </div>
      )}
    </div>
  )

  return (
    <div className="space-y-5">
      {!replaying && <RepairStrip events={stream.events} active={stream.view.status === 'running'} />}
      <div className="card h-[520px] p-0 sm:h-[620px]">
        <SimulationCanvas stages={graph.stages} view={view} selected={selected} onSelect={setSelected} overlay={overlay} toolbar={toolbar} />
      </div>

      <AnimatePresence>
        {done && !replaying && (
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="card flex flex-wrap items-center gap-4 border-ok/40 p-5">
            <motion.div initial={{ scale: 0, rotate: -30 }} animate={{ scale: 1, rotate: 0 }} transition={{ type: 'spring', bounce: 0.5, delay: 0.1 }} className="grid size-11 place-items-center rounded-2xl bg-ok/15 text-ok">
              <Lightbulb className="size-6" />
            </motion.div>
            <div className="min-w-0 flex-1">
              <div className="font-bold">{stream.detail?.result?.verdict?.summary ?? 'Your data is ready.'}</div>
              <div className="text-[13px] text-muted">
                {stream.detail?.result?.checks.summary.passed}/{stream.detail?.result?.checks.summary.total} checks passed · {stream.detail?.result?.stats.features_out} model-ready features ·{' '}
                {stream.detail?.result?.files.length} files exported
              </div>
            </div>
            <div className="flex gap-2">
              <Link to={`/runs/${runId}/data`}>
                <Button variant="outline">See prepared data</Button>
              </Link>
              <Link to={`/runs/${runId}/insights`}>
                <Button variant="primary">Open insights</Button>
              </Link>
            </div>
          </motion.div>
        )}
        {done && !replaying && (meta?.repairs?.length ?? 0) > 0 && <RepairSummary key="repairs" repairs={meta!.repairs!} />}
        {meta?.status === 'failed' && stream.view.status === 'failed' && <FailurePanel key="failed" meta={meta} />}
      </AnimatePresence>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_400px]">
        <div className="card h-[400px] overflow-hidden">
          <Console events={events} stages={graph.stages} filter={selected} onClearFilter={() => setSelected(null)} />
        </div>
        <div className="card h-[400px] overflow-hidden">
          <AnimatePresence mode="wait">
            {stage ? (
              <NodeDetails key={stage.id} stage={stage} state={view.nodes[stage.id]} events={events} onClose={() => setSelected(null)} />
            ) : (
              <motion.div key="hint" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex h-full flex-col items-center justify-center gap-2 p-8 text-center">
                <MousePointerClick className="size-6 text-faint" />
                <div className="font-bold">Click any block</div>
                <p className="max-w-[30ch] text-[13px] text-muted">See what that stage decided and why, its log and any LLM calls. The log on the left filters to it too.</p>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </div>
  )
}
