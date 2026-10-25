import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, type AgentEvent, type RunDetail } from './api'
import { buildView, emptyView, reduce, type RunView } from './runState'
import { useStore } from './store'

/** How long each kind of event stays on screen before the next one when pacing a live run (ms, at 1× speed). */
const PACE: Partial<Record<AgentEvent['type'], number>> = {
  node_started: 520,
  node_completed: 420,
  node_log: 110,
  node_error: 900,
  llm_call: 260,
  input_received: 250,
  run_resumed: 200,
}

/**
 * Live run: events arrive over Server-Sent Events (with a polling fallback)
 * and are *played* at a readable pace so you can watch each stage work.
 * Events that happened before you opened the page are shown at once.
 */
export function useRunStream(runId: string | undefined) {
  const pace = useStore((s) => s.settings?.ui.pace_runs ?? true)
  const speed = useStore((s) => s.settings?.ui.animation_speed ?? 1)
  const [events, setEvents] = useState<AgentEvent[]>([])
  const [played, setPlayed] = useState(0)
  const [detail, setDetail] = useState<RunDetail | null>(null)
  const [connected, setConnected] = useState(false)
  const lastSeq = useRef(-1)
  const lastEventAt = useRef(Date.now())
  const openedAt = useRef(Date.now() / 1000)

  const refresh = useCallback(async () => {
    if (!runId) return
    try {
      setDetail(await api.run(runId))
    } catch {
      /* transient */
    }
  }, [runId])

  const merge = useCallback(
    (incoming: AgentEvent[]) => {
      const fresh = incoming.filter((e) => e.seq > lastSeq.current).sort((a, b) => a.seq - b.seq)
      if (!fresh.length) return
      lastSeq.current = fresh[fresh.length - 1].seq
      lastEventAt.current = Date.now()
      setEvents((prev) => [...prev, ...fresh])
      if (fresh.some((e) => ['awaiting_input', 'run_completed', 'run_failed', 'node_completed', 'node_error', 'run_resumed'].includes(e.type))) refresh()
    },
    [refresh],
  )

  // Server-Sent Events
  useEffect(() => {
    if (!runId) return
    setEvents([])
    setPlayed(0)
    lastSeq.current = -1
    openedAt.current = Date.now() / 1000
    let es: EventSource | null = null
    let closed = false
    let retry: ReturnType<typeof setTimeout>
    const open = () => {
      es = new EventSource(api.streamUrl(runId, lastSeq.current))
      es.onopen = () => setConnected(true)
      es.onmessage = (m) => merge([JSON.parse(m.data)])
      es.onerror = () => {
        setConnected(false)
        es?.close()
        if (!closed) retry = setTimeout(open, 1500)
      }
    }
    refresh()
    open()
    return () => {
      closed = true
      clearTimeout(retry)
      es?.close()
    }
  }, [runId, refresh, merge])

  // Polling fallback: if the stream goes quiet while the run is active
  // (some antivirus or proxies buffer event streams), fetch events directly.
  useEffect(() => {
    if (!runId) return
    const t = setInterval(async () => {
      const status = detail?.meta?.status
      const active = !status || status === 'running' || status === 'waiting'
      if (!active && lastSeq.current >= 0) return
      if (Date.now() - lastEventAt.current < 2500) return
      try {
        merge(await api.events(runId))
        if (status === 'running') refresh()
      } catch {
        /* server busy */
      }
    }, 2000)
    return () => clearInterval(t)
  }, [runId, detail?.meta?.status, merge, refresh])

  // Playback: history instantly, live events at a readable pace.
  useEffect(() => {
    if (played >= events.length) return
    const e = events[played]
    const historical = e.ts < openedAt.current - 1.5
    if (!pace || historical) {
      // jump over everything that is historical (or when pacing is off)
      let j = played
      while (j < events.length && (!pace || events[j].ts < openedAt.current - 1.5)) j++
      setPlayed(Math.max(j, played + 1))
      return
    }
    const backlog = events.length - played
    const base = PACE[e.type] ?? 160
    const delay = (base / Math.max(speed, 0.25)) / (backlog > 60 ? 4 : backlog > 25 ? 2 : 1)
    const t = setTimeout(() => setPlayed((p) => p + 1), delay)
    return () => clearTimeout(t)
  }, [events, played, pace, speed])

  const shown = useMemo(() => events.slice(0, played), [events, played])
  const view = useMemo(() => buildView(shown), [shown])
  const catchingUp = events.length - played > 2
  return { events: shown, allEvents: events, view, detail, refresh, connected, catchingUp }
}

/** Replays recorded events through the same reducer at a chosen speed. */
export function useReplay(events: AgentEvent[]) {
  const [playing, setPlaying] = useState(false)
  const [index, setIndex] = useState(0)
  const [speed, setSpeed] = useState(1)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (!playing) return
    if (index >= events.length) {
      setPlaying(false)
      return
    }
    const cur = events[index]
    const delay = PACE[cur.type] ?? 160
    timer.current = setTimeout(() => setIndex((i) => i + 1), delay / speed)
    return () => {
      if (timer.current) clearTimeout(timer.current)
    }
  }, [playing, index, events, speed])

  const view: RunView = useMemo(() => {
    const v = emptyView()
    for (const e of events.slice(0, index)) reduce(v, e)
    return v
  }, [events, index])

  return {
    view,
    shown: events.slice(0, index),
    playing,
    index,
    speed,
    setSpeed,
    play: () => {
      if (index >= events.length) setIndex(0)
      setPlaying(true)
    },
    pause: () => setPlaying(false),
    reset: () => {
      setPlaying(false)
      setIndex(0)
    },
    seek: (i: number) => setIndex(Math.max(0, Math.min(events.length, i))),
  }
}
