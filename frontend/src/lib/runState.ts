import type { AgentEvent } from './api'

export type NodeStatus = 'idle' | 'running' | 'done' | 'waiting' | 'error'

export type NodeState = {
  status: NodeStatus
  visits: number
  message: string
  seconds?: number
  llmCalls: number
  llmLast?: string
  data?: any
}

export type RunView = {
  nodes: Record<string, NodeState>
  current: string | null
  lastDone: string | null
  activeEdge: string | null
  traversed: Set<string>
  status: 'idle' | 'running' | 'waiting' | 'completed' | 'failed'
  repairs: number
  startedAt?: number
  endedAt?: number
}

export const edgeKey = (a: string, b: string) => `${a}->${b}`

export function emptyView(): RunView {
  return { nodes: {}, current: null, lastDone: null, activeEdge: null, traversed: new Set(), status: 'idle', repairs: 0 }
}

function node(v: RunView, id: string): NodeState {
  if (!v.nodes[id]) v.nodes[id] = { status: 'idle', visits: 0, message: '', llmCalls: 0 }
  return v.nodes[id]
}

/** Folds one agent event into the view. Mutates and returns ``v``. */
export function reduce(v: RunView, e: AgentEvent): RunView {
  switch (e.type) {
    case 'run_started':
      v.status = 'running'
      v.startedAt = e.ts
      break
    case 'run_resumed':
      v.status = 'running'
      break
    case 'node_started': {
      const n = node(v, e.node!)
      if (v.lastDone && v.lastDone !== e.node) {
        v.activeEdge = edgeKey(v.lastDone, e.node!)
        v.traversed.add(v.activeEdge)
      }
      n.status = 'running'
      n.visits += 1
      n.message = e.message
      v.current = e.node
      v.status = 'running'
      break
    }
    case 'node_log':
      if (e.node) node(v, e.node).message = e.message
      break
    case 'llm_call':
      if (e.node) {
        const n = node(v, e.node)
        n.llmCalls += 1
        n.llmLast = e.message
      }
      break
    case 'node_completed': {
      const n = node(v, e.node!)
      n.status = 'done'
      n.message = e.message
      n.seconds = e.data?.seconds
      n.data = e.data
      v.lastDone = e.node
      v.current = null
      break
    }
    case 'awaiting_input': {
      const n = node(v, e.node!)
      n.status = 'waiting'
      n.message = e.message
      if (v.lastDone && v.lastDone !== e.node) {
        v.activeEdge = edgeKey(v.lastDone, e.node!)
        v.traversed.add(v.activeEdge)
      }
      v.current = e.node
      v.status = 'waiting'
      break
    }
    case 'input_received':
      if (e.node) node(v, e.node).status = 'running'
      break
    case 'node_error': {
      // a recoverable crash: the block turns red and the run continues into self-repair
      const n = node(v, e.node!)
      n.status = 'error'
      n.message = e.message
      n.data = e.data
      v.lastDone = e.node
      v.current = null
      v.repairs += 1
      break
    }
    case 'node_failed':
      node(v, e.node!).status = 'error'
      node(v, e.node!).message = e.message
      v.status = 'failed'
      break
    case 'run_completed':
      v.status = 'completed'
      v.activeEdge = null
      v.current = null
      v.endedAt = e.ts
      break
    case 'run_failed':
      v.status = 'failed'
      v.activeEdge = null
      v.endedAt = e.ts
      break
  }
  return v
}

export function buildView(events: AgentEvent[]): RunView {
  const v = emptyView()
  for (const e of events) reduce(v, e)
  return v
}
