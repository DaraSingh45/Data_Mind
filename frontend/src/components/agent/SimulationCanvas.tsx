import {
  applyNodeChanges,
  Background,
  BackgroundVariant,
  BaseEdge,
  EdgeLabelRenderer,
  getSmoothStepPath,
  Handle,
  MiniMap,
  Panel,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeChange,
  type NodeProps,
} from '@xyflow/react'
import clsx from 'clsx'
import { AnimatePresence, motion } from 'framer-motion'
import {
  BadgeCheck,
  Check,
  Cog,
  Crosshair,
  FileInput,
  FlaskConical,
  Lightbulb,
  ListChecks,
  Loader2,
  LocateFixed,
  Maximize2,
  MessageCircleQuestion,
  Minimize2,
  Minus,
  PackageOpen,
  Plus,
  RotateCcw,
  ScanSearch,
  ShieldCheck,
  Sparkles,
  Target,
  UserCheck,
  X,
  Wrench,
} from 'lucide-react'
import { memo, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import type { Stage } from '../../lib/api'
import { duration } from '../../lib/format'
import { edgeKey, type NodeState, type RunView } from '../../lib/runState'

const ICONS: Record<string, any> = {
  ingest: FileInput,
  profile: ScanSearch,
  understand: Target,
  clarify: MessageCircleQuestion,
  plan: ListChecks,
  validate: ShieldCheck,
  review: UserCheck,
  execute: Cog,
  checks: FlaskConical,
  verify: BadgeCheck,
  export: PackageOpen,
  insights: Lightbulb,
  repair: Wrench,
}

// Layout of the 2D world. Two lanes that snake; "Ask you" floats above
// "Understand". Users can drag blocks anywhere; "Reset layout" restores this.
const W = 176
const GX = 236
const HOME: Record<string, { x: number; y: number }> = {
  ingest: { x: 0, y: 160 },
  profile: { x: GX, y: 160 },
  understand: { x: 2 * GX, y: 160 },
  clarify: { x: 2 * GX, y: 10 },
  plan: { x: 3 * GX, y: 160 },
  validate: { x: 4 * GX, y: 160 },
  review: { x: 5 * GX, y: 160 },
  execute: { x: 5 * GX, y: 330 },
  checks: { x: 4 * GX, y: 330 },
  verify: { x: 3 * GX, y: 330 },
  export: { x: 2 * GX, y: 330 },
  insights: { x: GX, y: 330 },
  repair: { x: 3 * GX, y: 500 },
}

const EDGES: { from: string; to: string; s: string; t: string; loop?: string; offset?: number }[] = [
  { from: 'ingest', to: 'profile', s: 'r', t: 'l' },
  { from: 'profile', to: 'understand', s: 'r', t: 'l' },
  { from: 'understand', to: 'clarify', s: 't1', t: 'b1', loop: 'unsure' },
  { from: 'clarify', to: 'understand', s: 'b2', t: 't2', loop: 'answered' },
  { from: 'understand', to: 'plan', s: 'r', t: 'l' },
  { from: 'plan', to: 'validate', s: 'r', t: 'l' },
  { from: 'validate', to: 'plan', s: 't1', t: 't2', loop: 'invalid', offset: 28 },
  { from: 'validate', to: 'review', s: 'r', t: 'l' },
  { from: 'review', to: 'plan', s: 't2', t: 't1', loop: 'your answers', offset: 58 },
  { from: 'review', to: 'execute', s: 'b', t: 't' },
  { from: 'execute', to: 'checks', s: 'l', t: 'r' },
  { from: 'checks', to: 'verify', s: 'l', t: 'r' },
  { from: 'verify', to: 'plan', s: 't', t: 'b', loop: 'revise' },
  { from: 'verify', to: 'export', s: 'l', t: 'r' },
  { from: 'export', to: 'insights', s: 'l', t: 'r' },
  { from: 'execute', to: 'repair', s: 'b', t: 'r', loop: 'error' },
  { from: 'checks', to: 'repair', s: 'b', t: 't2', loop: 'error' },
  { from: 'export', to: 'repair', s: 'b', t: 't1', loop: 'error' },
  { from: 'insights', to: 'repair', s: 'b', t: 'l', loop: 'error' },
  { from: 'repair', to: 'plan', s: 'b2', t: 't', loop: 'retry with fix', offset: 90 },
  { from: 'repair', to: 'insights', s: 'b1', t: 'b', loop: 'retry', offset: 40 },
]

const HANDLES: { id: string; pos: Position; style?: React.CSSProperties }[] = [
  { id: 'l', pos: Position.Left },
  { id: 'r', pos: Position.Right },
  { id: 't', pos: Position.Top },
  { id: 'b', pos: Position.Bottom },
  { id: 't1', pos: Position.Top, style: { left: '28%' } },
  { id: 't2', pos: Position.Top, style: { left: '72%' } },
  { id: 'b1', pos: Position.Bottom, style: { left: '28%' } },
  { id: 'b2', pos: Position.Bottom, style: { left: '72%' } },
]

const COLOR: Record<string, string> = { idle: 'var(--line-strong)', running: 'var(--signal)', done: 'var(--ok)', waiting: 'var(--mind)', error: 'var(--bad)' }
const MINI: Record<string, string> = { idle: '#3a4566', running: '#ffb547', done: '#3ccfae', waiting: '#9b8cff', error: '#ff6b7a' }

type BlockData = { stage: Stage; state: NodeState; index: number; selected: boolean }

const Block = memo(function Block({ data, dragging }: NodeProps<Node<BlockData>>) {
  const { stage, state, index, selected } = data
  const Icon = ICONS[stage.id] ?? Cog
  const st = state.status
  const c = COLOR[st]
  const live = st === 'running' || st === 'waiting'
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.8 }}
      animate={{ opacity: 1, scale: dragging ? 1.04 : 1 }}
      transition={{ delay: dragging ? 0 : 0.04 * index, type: 'spring', bounce: 0.3, duration: 0.45 }}
      className={clsx('stage-node', st)}
      style={{ width: W, ['--ring-color' as any]: c }}
    >
      {live && <div className="ring" />}
      {HANDLES.map((h) => (
        <span key={h.id}>
          <Handle type="source" id={`${h.id}-s`} position={h.pos} style={h.style} />
          <Handle type="target" id={`${h.id}-t`} position={h.pos} style={h.style} />
        </span>
      ))}
      <div
        className={clsx('rounded-[14px] border px-2.5 py-2 transition-[border-color,background,box-shadow] duration-300', selected && 'shadow-[0_0_0_3px_color-mix(in_srgb,var(--mind)_45%,transparent)]', dragging && 'shadow-xl')}
        style={{
          borderColor: st === 'idle' ? 'var(--line)' : c,
          background: st === 'idle' ? 'var(--surface)' : `color-mix(in srgb, ${c} 9%, var(--surface))`,
        }}
      >
        <div className="flex items-center gap-2">
          <span className="grid size-7 shrink-0 place-items-center rounded-lg" style={{ background: st === 'idle' ? 'var(--surface-2)' : `color-mix(in srgb, ${c} 22%, transparent)`, color: st === 'idle' ? 'var(--muted)' : c }}>
            <Icon className="size-[15px]" />
          </span>
          <span className={clsx('min-w-0 flex-1 truncate text-[12.5px] font-bold', st === 'idle' && 'text-muted')}>{stage.label}</span>
          {state.visits > 1 && <span className="rounded bg-surface-3 px-1 text-[10px] font-bold text-muted">×{state.visits}</span>}
          <AnimatePresence mode="wait">
            <motion.span key={st} initial={{ scale: 0 }} animate={{ scale: 1 }} exit={{ scale: 0 }} transition={{ type: 'spring', bounce: 0.5, duration: 0.35 }} className="shrink-0">
              {st === 'running' && <Loader2 className="size-3.5 animate-spin text-signal" />}
              {st === 'done' && (
                <span className="grid size-4 place-items-center rounded-full bg-ok text-white">
                  <Check className="size-2.5" strokeWidth={3.5} />
                </span>
              )}
              {st === 'waiting' && <span className="grid size-4 place-items-center rounded-full bg-mind text-[10px] font-black text-white">?</span>}
              {st === 'error' && (
                <span className="grid size-4 place-items-center rounded-full bg-bad text-white">
                  <X className="size-2.5" strokeWidth={3.5} />
                </span>
              )}
              {st === 'idle' && <span className="block size-1.5 rounded-full bg-line-strong" />}
            </motion.span>
          </AnimatePresence>
        </div>
        <div className="mt-1.5 flex items-center gap-1 pl-0.5 text-[10.5px]">
          {state.llmCalls > 0 && (
            <span className="flex shrink-0 items-center gap-0.5 rounded bg-mind/15 px-1 font-bold text-mind" title={state.llmLast}>
              <Sparkles className="size-2.5" />
              LLM
            </span>
          )}
          <span className="truncate text-faint" title={state.message || stage.desc}>
            {st === 'idle' ? stage.desc : st === 'waiting' ? 'Waiting for you' : state.message}
          </span>
          {st === 'done' && state.seconds != null && <span className="ml-auto shrink-0 text-faint tabular-nums">{duration(state.seconds)}</span>}
        </div>
      </div>
    </motion.div>
  )
})

type LinkData = { mode: 'idle' | 'traversed' | 'active'; loop?: string; offset?: number }

function Link({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data }: EdgeProps<Edge<LinkData>>) {
  const [path, lx, ly] = getSmoothStepPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, borderRadius: 16, offset: data?.offset ?? 22 })
  const mode = data?.mode ?? 'idle'
  const loop = !!data?.loop
  const stroke = mode === 'active' ? 'var(--signal)' : mode === 'traversed' ? 'var(--ok)' : 'var(--line-strong)'
  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        className={mode === 'active' ? 'edge-active' : undefined}
        style={{
          stroke,
          strokeWidth: mode === 'active' ? 2.4 : mode === 'traversed' ? 1.8 : 1.3,
          strokeDasharray: mode === 'active' ? undefined : loop ? '5 5' : undefined,
          opacity: mode === 'idle' ? (loop ? 0.5 : 0.85) : 0.9,
          transition: 'stroke .4s, opacity .4s',
        }}
      />
      {mode === 'active' && (
        <g>
          <circle r="8" fill="var(--signal)" opacity="0.2">
            <animateMotion dur="1s" repeatCount="indefinite" path={path} />
          </circle>
          <circle r="3.5" fill="var(--signal)">
            <animateMotion dur="1s" repeatCount="indefinite" path={path} />
          </circle>
        </g>
      )}
      {loop && (
        <EdgeLabelRenderer>
          <div
            className="nodrag nopan pointer-events-none absolute rounded-full border px-1.5 py-px text-[10px] font-semibold"
            style={{ transform: `translate(-50%,-50%) translate(${lx}px,${ly}px)`, background: 'var(--surface)', borderColor: mode === 'idle' ? 'var(--line)' : stroke, color: mode === 'idle' ? 'var(--faint)' : stroke }}
          >
            {data?.loop}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  )
}

const nodeTypes = { block: Block }
const edgeTypes = { link: Link }

type Props = {
  stages: Stage[]
  view: RunView
  selected: string | null
  onSelect: (id: string | null) => void
  overlay?: ReactNode
  toolbar?: ReactNode
}

function World({ stages, view, selected, onSelect, overlay, toolbar }: Props) {
  const rf = useReactFlow()
  const [follow, setFollow] = useState(true)
  const [full, setFull] = useState(false)
  const [zoom, setZoom] = useState(1)
  const box = useRef<HTMLDivElement>(null)

  const blockData = useCallback(
    (s: Stage, i: number): BlockData => ({ stage: s, index: i, selected: selected === s.id, state: view.nodes[s.id] ?? { status: 'idle', visits: 0, message: '', llmCalls: 0 } }),
    [view, selected],
  )
  // Full node objects live in state so React Flow keeps their measured size
  // and dragged positions; only `data` is refreshed as the run progresses.
  const [nodes, setNodes] = useState<Node<BlockData>[]>(() =>
    stages.map((s, i) => ({ id: s.id, type: 'block', position: HOME[s.id] ?? { x: i * GX, y: 520 }, data: blockData(s, i) })),
  )
  useEffect(() => {
    setNodes((ns) => {
      const byId = new Map(ns.map((n) => [n.id, n]))
      return stages.map((s, i) => {
        const prev = byId.get(s.id)
        return prev ? { ...prev, data: blockData(s, i) } : { id: s.id, type: 'block', position: HOME[s.id] ?? { x: i * GX, y: 520 }, data: blockData(s, i) }
      })
    })
  }, [stages, blockData])
  const onNodesChange = useCallback((changes: NodeChange<Node<BlockData>>[]) => setNodes((ns) => applyNodeChanges(changes, ns)), [])

  const fit = useCallback(() => rf.fitView({ padding: 0.14, duration: 450 }), [rf])
  useEffect(() => {
    const t = setTimeout(fit, 120)
    return () => clearTimeout(t)
  }, [fit, full])

  // Camera follows the stage that is working right now. While a question card
  // is open (docked on the right), the asking block is kept in the left part.
  const asking = !!overlay
  useEffect(() => {
    if (!follow || !view.current) return
    const n = rf.getNode(view.current)
    if (!n) return
    const z = Math.max(rf.getZoom(), 0.95)
    const shift = asking && box.current ? (box.current.clientWidth * 0.24) / z : 0
    rf.setCenter(n.position.x + W / 2 + shift, n.position.y + 30, { zoom: z, duration: 650 })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view.current, follow, asking])

  // When the run finishes, step back and show the whole flow.
  useEffect(() => {
    if (view.status === 'completed' || view.status === 'failed') {
      const t = setTimeout(fit, 400)
      return () => clearTimeout(t)
    }
  }, [view.status, fit])

  useEffect(() => {
    if (!full) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setFull(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [full])

  const edges: Edge<LinkData>[] = useMemo(
    () =>
      EDGES.map((e) => {
        const key = edgeKey(e.from, e.to)
        const mode: LinkData['mode'] = view.activeEdge === key && view.status !== 'completed' ? 'active' : view.traversed.has(key) ? 'traversed' : 'idle'
        return { id: key, source: e.from, target: e.to, sourceHandle: `${e.s}-s`, targetHandle: `${e.t}-t`, type: 'link', data: { mode, loop: e.loop, offset: e.offset }, zIndex: mode === 'active' ? 10 : 0 }
      }),
    [view],
  )

  const tool = 'grid size-8 place-items-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-text'
  return (
    <div ref={box} className={clsx('overflow-hidden bg-bg', full ? 'fixed inset-0 z-[60]' : 'relative h-full rounded-[14px]')}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodesChange={onNodesChange}
        onNodeClick={(_, n) => onSelect(selected === n.id ? null : n.id)}
        onNodeDragStart={() => setFollow(false)}
        onMoveStart={(e) => e && setFollow(false)}
        onMove={(_, vp) => setZoom(vp.zoom)}
        onPaneClick={() => onSelect(null)}
        nodesConnectable={false}
        elementsSelectable={false}
        nodesDraggable
        panOnDrag
        zoomOnScroll
        zoomOnPinch
        minZoom={0.25}
        maxZoom={2.2}
        proOptions={{ hideAttribution: true }}
        fitView
      >
        <Background variant={BackgroundVariant.Dots} gap={22} size={1.4} color="var(--line-strong)" />
        <MiniMap
          pannable
          zoomable
          nodeColor={(n) => MINI[(n.data as BlockData).state.status]}
          nodeStrokeWidth={0}
          nodeBorderRadius={6}
          maskColor="color-mix(in srgb, var(--bg) 70%, transparent)"
          style={{ background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 12, width: 168, height: 104 }}
          className="!hidden sm:!block"
        />
        <Panel position="top-left" className="!m-3">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border border-line bg-surface/85 px-3 py-1.5 text-[11.5px] text-muted backdrop-blur">
            {[
              ['working', 'var(--signal)'],
              ['needs you', 'var(--mind)'],
              ['done', 'var(--ok)'],
              ['failed', 'var(--bad)'],
            ].map(([l, c]) => (
              <span key={l} className="flex items-center gap-1.5">
                <span className="size-2 rounded-full" style={{ background: c }} />
                {l}
              </span>
            ))}
          </div>
        </Panel>
        <Panel position="top-right" className="!m-3 flex items-center gap-2">
          {toolbar}
        </Panel>
        <Panel position="bottom-left" className="!m-3">
          <div className="flex items-center gap-0.5 rounded-xl border border-line bg-surface/90 p-1 backdrop-blur">
            <button className={tool} onClick={() => rf.zoomOut({ duration: 200 })} aria-label="Zoom out" title="Zoom out">
              <Minus className="size-4" />
            </button>
            <span className="w-11 text-center text-[11.5px] font-semibold text-muted tabular-nums">{Math.round(zoom * 100)}%</span>
            <button className={tool} onClick={() => rf.zoomIn({ duration: 200 })} aria-label="Zoom in" title="Zoom in">
              <Plus className="size-4" />
            </button>
            <span className="mx-1 h-5 w-px bg-line" />
            <button className={tool} onClick={fit} aria-label="Fit to screen" title="Fit to screen">
              <LocateFixed className="size-4" />
            </button>
            <button className={clsx(tool, follow && '!bg-signal/15 !text-signal')} onClick={() => setFollow((f) => !f)} aria-label="Follow the agent" title="Follow the active stage">
              <Crosshair className="size-4" />
            </button>
            <button
              className={tool}
              onClick={() => {
                setNodes((ns) => ns.map((n) => ({ ...n, position: HOME[n.id] ?? n.position })))
                setTimeout(fit, 50)
              }}
              aria-label="Reset layout"
              title="Reset layout"
            >
              <RotateCcw className="size-4" />
            </button>
            <button className={tool} onClick={() => setFull((f) => !f)} aria-label={full ? 'Exit full screen' : 'Full screen'} title={full ? 'Exit full screen (Esc)' : 'Full screen'}>
              {full ? <Minimize2 className="size-4" /> : <Maximize2 className="size-4" />}
            </button>
            <span className="hidden px-2 text-[11px] text-faint xl:inline">scroll to zoom · drag to pan · drag blocks</span>
          </div>
        </Panel>
      </ReactFlow>

      <AnimatePresence>
        {overlay && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="absolute inset-0 z-20 flex items-center justify-center overflow-y-auto bg-gradient-to-l from-bg/85 via-bg/25 to-transparent p-4 md:justify-end md:pr-6">
            {overlay}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

export function SimulationCanvas(props: Props) {
  return (
    <ReactFlowProvider>
      <World {...props} />
    </ReactFlowProvider>
  )
}
