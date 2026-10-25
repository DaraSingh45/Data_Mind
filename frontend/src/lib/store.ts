import { create } from 'zustand'
import type { ChatMessage, DatasetPayload, Intent, Settings } from './api'

export type AgentReplyTurn = { role: 'agent'; steps: { label: string; detail: string }[]; reply: string; source: string; action?: string }
export type AgentTurn = { role: 'user'; text: string } | AgentReplyTurn

type StartSession = {
  dataset: DatasetPayload | null
  messages: ChatMessage[]
  turns: AgentTurn[]
  intent: Intent
  ready: boolean
}

type Store = {
  settings: Settings | null
  ollamaModels: string[]
  setSettings: (s: Settings, models?: string[]) => void
  session: StartSession
  setDataset: (d: DatasetPayload | null) => void
  setChat: (messages: ChatMessage[], intent?: Intent, ready?: boolean, turns?: AgentTurn[]) => void
  resetSession: () => void
}

const emptySession: StartSession = { dataset: null, messages: [], turns: [], intent: {}, ready: false }

export const useStore = create<Store>((set) => ({
  settings: null,
  ollamaModels: [],
  setSettings: (settings, models) => set((s) => ({ settings, ollamaModels: models ?? s.ollamaModels })),
  session: emptySession,
  setDataset: (dataset) => set({ session: { ...emptySession, dataset } }),
  setChat: (messages, intent, ready, turns) =>
    set((s) => ({ session: { ...s.session, messages, intent: intent ?? s.session.intent, ready: ready ?? s.session.ready, turns: turns ?? s.session.turns } })),
  resetSession: () => set({ session: emptySession }),
}))

export function applyUi(settings: Settings | null) {
  const ui = settings?.ui
  const root = document.documentElement
  let theme = ui?.theme ?? 'dark'
  if (theme === 'system') theme = window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
  root.dataset.theme = theme
  root.classList.toggle('reduce-motion', !!ui?.reduce_motion)
  root.style.setProperty('--speed', String(ui?.animation_speed ?? 1))
}

/** Charts the user pinned from the insight chat, kept per run in this browser. */
export function loadPins(runId: string): any[] {
  try {
    return JSON.parse(localStorage.getItem(`dm-pins-${runId}`) || '[]')
  } catch {
    return []
  }
}
export function savePins(runId: string, pins: any[]) {
  try {
    localStorage.setItem(`dm-pins-${runId}`, JSON.stringify(pins))
  } catch {
    /* storage unavailable */
  }
}
