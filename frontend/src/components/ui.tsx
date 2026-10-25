import clsx from 'clsx'
import { motion } from 'framer-motion'
import { Loader2 } from 'lucide-react'
import type { ButtonHTMLAttributes, ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'ghost' | 'subtle' | 'danger' | 'outline'
  size?: 'sm' | 'md' | 'lg'
  loading?: boolean
  icon?: ReactNode
}

export function Button({ variant = 'subtle', size = 'md', loading, icon, className, children, disabled, ...rest }: BtnProps) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={clsx(
        'inline-flex items-center justify-center gap-2 rounded-[10px] font-semibold transition-[background,color,border,transform] active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50',
        size === 'sm' && 'h-8 px-3 text-[13px]',
        size === 'md' && 'h-10 px-4 text-sm',
        size === 'lg' && 'h-12 px-6 text-[15px]',
        variant === 'primary' && 'bg-mind text-white shadow-[0_8px_24px_-10px_var(--mind)] hover:brightness-110',
        variant === 'subtle' && 'bg-surface-2 text-text hover:bg-surface-3',
        variant === 'ghost' && 'text-muted hover:bg-surface-2 hover:text-text',
        variant === 'outline' && 'border border-line text-text hover:border-line-strong hover:bg-surface-2',
        variant === 'danger' && 'bg-bad/15 text-bad hover:bg-bad/25',
        className,
      )}
    >
      {loading ? <Loader2 className="size-4 animate-spin" /> : icon}
      {children}
    </button>
  )
}

export function Pill({ children, tone = 'neutral', className }: { children: ReactNode; tone?: 'neutral' | 'mind' | 'signal' | 'ok' | 'bad' | 'info'; className?: string }) {
  const tones = {
    neutral: 'bg-surface-3 text-muted',
    mind: 'bg-mind/15 text-mind',
    signal: 'bg-signal/15 text-signal',
    ok: 'bg-ok/15 text-ok',
    bad: 'bg-bad/15 text-bad',
    info: 'bg-info/15 text-info',
  }
  return <span className={clsx('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[12px] font-medium whitespace-nowrap', tones[tone], className)}>{children}</span>
}

export function Tabs<T extends string>({ tabs, value, onChange, className }: { tabs: { id: T; label: ReactNode }[]; value: T; onChange: (v: T) => void; className?: string }) {
  return (
    <div className={clsx('relative inline-flex gap-1 rounded-xl bg-surface-2 p-1', className)} role="tablist">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          aria-selected={value === t.id}
          onClick={() => onChange(t.id)}
          className={clsx('relative z-10 flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[13px] font-semibold transition-colors', value === t.id ? 'text-text' : 'text-muted hover:text-text')}
        >
          {value === t.id && <motion.span layoutId={`tab-${tabs.map((x) => x.id).join('')}`} className="absolute inset-0 -z-10 rounded-lg bg-surface shadow-sm" transition={{ type: 'spring', bounce: 0.2, duration: 0.4 }} />}
          {t.label}
        </button>
      ))}
    </div>
  )
}

export function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[13px] font-semibold text-text">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[12px] text-muted">{hint}</span>}
    </label>
  )
}

export function Toggle({ checked, onChange, label, hint }: { checked: boolean; onChange: (v: boolean) => void; label: string; hint?: string }) {
  return (
    <button type="button" onClick={() => onChange(!checked)} className="flex w-full items-start justify-between gap-4 text-left" role="switch" aria-checked={checked}>
      <span>
        <span className="block text-[14px] font-semibold">{label}</span>
        {hint && <span className="block text-[12.5px] text-muted">{hint}</span>}
      </span>
      <span className={clsx('relative mt-0.5 h-6 w-11 shrink-0 rounded-full transition-colors', checked ? 'bg-mind' : 'bg-surface-3')}>
        <motion.span layout transition={{ type: 'spring', stiffness: 500, damping: 32 }} className={clsx('absolute top-1 size-4 rounded-full bg-white', checked ? 'right-1' : 'left-1')} />
      </span>
    </button>
  )
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={clsx('animate-spin text-muted', className ?? 'size-5')} />
}

export function Empty({ icon, title, children, action }: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-16 text-center">
      {icon && <div className="grid size-12 place-items-center rounded-2xl bg-surface-2 text-muted">{icon}</div>}
      <h3 className="text-base font-bold">{title}</h3>
      {children && <p className="max-w-md text-sm text-muted">{children}</p>}
      {action}
    </div>
  )
}

export function Md({ children, className }: { children: string; className?: string }) {
  return (
    <div className={clsx('prose-dm', className)}>
      <ReactMarkdown>{children}</ReactMarkdown>
    </div>
  )
}

export function Stat({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: string }) {
  return (
    <div className="card px-4 py-3.5">
      <div className="text-[12.5px] text-muted">{label}</div>
      <div className="mt-1 text-[22px] leading-tight font-bold tracking-tight" style={tone ? { color: tone } : undefined}>
        {value}
      </div>
      {hint && <div className="mt-0.5 text-[12px] text-faint">{hint}</div>}
    </div>
  )
}

export function SectionTitle({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-3 flex items-end justify-between gap-4">
      <div>
        <h2 className="text-[17px] font-bold tracking-tight">{title}</h2>
        {children && <p className="text-[13.5px] text-muted">{children}</p>}
      </div>
      {action}
    </div>
  )
}

export function DataTable({ columns, rows, maxHeight = 420 }: { columns: string[]; rows: unknown[][]; maxHeight?: number }) {
  return (
    <div className="overflow-auto rounded-xl border border-line" style={{ maxHeight }}>
      <table className="w-full border-collapse text-[12.5px]">
        <thead className="sticky top-0 z-10 bg-surface-2">
          <tr>
            {columns.map((c) => (
              <th key={c} className="border-b border-line px-3 py-2 text-left font-semibold whitespace-nowrap text-muted">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="odd:bg-surface even:bg-surface-2/40 hover:bg-surface-3/60">
              {r.map((v, j) => (
                <td key={j} className={clsx('max-w-[260px] truncate border-b border-line/60 px-3 py-1.5 whitespace-nowrap', v == null && 'text-faint italic', typeof v === 'number' && 'text-right tabular-nums')}>
                  {v == null ? 'null' : typeof v === 'number' ? (Number.isInteger(v) ? v : Number(v.toFixed(4))) : String(v)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
