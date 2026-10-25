import clsx from 'clsx'
import { AnimatePresence, motion } from 'framer-motion'
import { History, Menu, PlusCircle, Settings2, X } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { PROVIDER_LABEL } from '../lib/format'
import { useStore } from '../lib/store'
import { Logo } from './Logo'

const NAV = [
  { to: '/', label: 'New analysis', icon: PlusCircle, end: true },
  { to: '/runs', label: 'Runs', icon: History },
  { to: '/settings', label: 'Settings', icon: Settings2 },
]

function NavItems({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav className="flex flex-col gap-1">
      {NAV.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          onClick={onNavigate}
          className={({ isActive }) =>
            clsx('relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-[14px] font-semibold transition-colors', isActive ? 'text-text' : 'text-muted hover:text-text')
          }
        >
          {({ isActive }) => (
            <>
              {isActive && <motion.span layoutId="nav-active" className="absolute inset-0 -z-10 rounded-xl bg-surface-2" transition={{ type: 'spring', bounce: 0.2, duration: 0.45 }} />}
              <Icon className="size-[18px]" />
              {label}
            </>
          )}
        </NavLink>
      ))}
    </nav>
  )
}

export function Layout({ children }: { children: ReactNode }) {
  const settings = useStore((s) => s.settings)
  const [open, setOpen] = useState(false)
  const loc = useLocation()
  useEffect(() => setOpen(false), [loc.pathname])
  const provider = settings?.llm.provider ?? 'heuristic'
  const model =
    provider === 'ollama' ? settings?.llm.ollama_model : provider === 'groq' ? settings?.llm.groq_model : provider === 'gemini' ? settings?.llm.gemini_model : 'no LLM'

  const brand = (
    <div className="flex items-center gap-3 px-2">
      <Logo />
      <div>
        <div className="text-[17px] leading-tight font-extrabold tracking-tight">Data Mind</div>
        <div className="text-[12px] text-muted">raw data → model-ready</div>
      </div>
    </div>
  )
  const footer = (
    <NavLink to="/settings" className="mt-auto block rounded-xl border border-line p-3 text-[12.5px] hover:border-line-strong">
      <div className="flex items-center gap-2 font-semibold">
        <span className={clsx('size-2 rounded-full', provider === 'heuristic' ? 'bg-faint' : 'bg-ok')} />
        {PROVIDER_LABEL[provider]}
      </div>
      <div className="mt-0.5 truncate text-muted">{model}</div>
    </NavLink>
  )

  return (
    <div className="app-backdrop flex h-full">
      <aside className="hidden w-[232px] shrink-0 flex-col gap-8 border-r border-line bg-surface/70 px-3 py-5 backdrop-blur md:flex">
        {brand}
        <NavItems />
        {footer}
      </aside>

      <div className="fixed inset-x-0 top-0 z-40 flex h-14 items-center justify-between border-b border-line bg-surface/90 px-4 backdrop-blur md:hidden">
        <div className="flex items-center gap-2">
          <Logo size={28} />
          <span className="font-extrabold">Data Mind</span>
        </div>
        <button aria-label="Open menu" onClick={() => setOpen(true)} className="rounded-lg p-2 hover:bg-surface-2">
          <Menu className="size-5" />
        </button>
      </div>
      <AnimatePresence>
        {open && (
          <motion.div className="fixed inset-0 z-50 bg-black/50 md:hidden" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setOpen(false)}>
            <motion.aside
              initial={{ x: -260 }}
              animate={{ x: 0 }}
              exit={{ x: -260 }}
              transition={{ type: 'spring', bounce: 0, duration: 0.35 }}
              className="flex h-full w-[250px] flex-col gap-8 bg-surface px-3 py-5"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between">
                {brand}
                <button aria-label="Close menu" onClick={() => setOpen(false)} className="rounded-lg p-2 hover:bg-surface-2">
                  <X className="size-5" />
                </button>
              </div>
              <NavItems onNavigate={() => setOpen(false)} />
              {footer}
            </motion.aside>
          </motion.div>
        )}
      </AnimatePresence>

      <main className="min-w-0 flex-1 overflow-y-auto pt-14 md:pt-0">{children}</main>
    </div>
  )
}
