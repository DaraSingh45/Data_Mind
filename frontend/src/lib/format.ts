export const pct = (v: number | null | undefined, digits = 1) => (v == null ? '—' : `${(v * 100).toFixed(digits)}%`)

export const num = (v: number | null | undefined) => {
  if (v == null || Number.isNaN(v)) return '—'
  const a = Math.abs(v)
  if (a >= 1e6) return `${(v / 1e6).toFixed(2)}M`
  if (a >= 1e4) return Math.round(v).toLocaleString()
  if (a >= 100) return v.toLocaleString(undefined, { maximumFractionDigits: 1 })
  return Number(v.toPrecision(3)).toString()
}

export const bytes = (b: number) => (b > 1e6 ? `${(b / 1e6).toFixed(1)} MB` : b > 1e3 ? `${(b / 1e3).toFixed(0)} KB` : `${b} B`)

export const ago = (ts: number) => {
  const s = Date.now() / 1000 - ts
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`
  return new Date(ts * 1000).toLocaleDateString()
}

export const duration = (s?: number) => (s == null ? '' : s < 1 ? `${Math.round(s * 1000)} ms` : s < 60 ? `${s.toFixed(1)} s` : `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`)

export const TYPE_COLORS: Record<string, string> = {
  numeric: 'var(--info)',
  categorical: 'var(--mind)',
  datetime: 'var(--signal)',
  boolean: 'var(--ok)',
  text: '#d58cf0',
  id: 'var(--faint)',
  email: 'var(--faint)',
  phone: 'var(--faint)',
  url: 'var(--faint)',
  constant: 'var(--bad)',
  empty: 'var(--bad)',
}

export const PROVIDER_LABEL: Record<string, string> = {
  heuristic: 'Rules engine',
  ollama: 'Ollama (local)',
  groq: 'Groq',
  gemini: 'Gemini',
}
