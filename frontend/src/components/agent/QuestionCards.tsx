import clsx from 'clsx'
import { AnimatePresence, motion } from 'framer-motion'
import { ArrowLeft, Check, CornerDownLeft, PencilLine, Sparkles } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { api, type QuestionCard } from '../../lib/api'
import { Button } from '../ui'

const OTHER = '__other__'

/**
 * The agent's questions, one card at a time: numbered options with a short
 * explanation each, plus "Other" for answering in your own words.
 * Keyboard: 1–9 picks an option, Enter continues.
 */
export function QuestionCards({ runId, title, questions, onSent }: { runId: string; title: string; questions: QuestionCard[]; onSent: () => void }) {
  const [step, setStep] = useState(0)
  const [choice, setChoice] = useState<Record<string, string>>({})
  const [other, setOther] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [dir, setDir] = useState(1)
  const otherInput = useRef<HTMLInputElement>(null)
  const q = questions[step]
  const last = step === questions.length - 1
  const picked = choice[q.id]
  const answerOf = (qq: QuestionCard) => (choice[qq.id] === OTHER ? (other[qq.id] || '').trim() : choice[qq.id])
  const ready = !!answerOf(q)
  const options = useMemo(() => q.options, [q])

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      const answers = Object.fromEntries(questions.map((qq) => [qq.id, answerOf(qq)]))
      await api.resume(runId, { approved: true, answers, overrides: {} })
      onSent()
    } catch (e: any) {
      setError(e.message)
      setBusy(false)
    }
  }
  const next = () => {
    if (!ready || busy) return
    if (last) submit()
    else {
      setDir(1)
      setStep((s) => s + 1)
    }
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (document.activeElement === otherInput.current) {
        if (e.key === 'Enter') next()
        return
      }
      const n = Number(e.key)
      if (n >= 1 && n <= options.length) setChoice((c) => ({ ...c, [q.id]: options[n - 1].value }))
      if (q.allow_other && n === options.length + 1) setChoice((c) => ({ ...c, [q.id]: OTHER }))
      if (e.key === 'Enter') next()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  useEffect(() => {
    if (picked === OTHER) setTimeout(() => otherInput.current?.focus(), 60)
  }, [picked])

  return (
    <motion.div
      initial={{ opacity: 0, y: 24, scale: 0.97 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: 16, scale: 0.98 }}
      transition={{ type: 'spring', bounce: 0.22, duration: 0.5 }}
      className="w-full max-w-[560px] overflow-hidden rounded-2xl border border-mind/40 bg-surface shadow-[0_30px_80px_-30px_rgb(0_0_0/0.75)]"
      role="dialog"
      aria-label={title}
    >
      <div className="flex items-center gap-2.5 border-b border-line px-5 py-3">
        <motion.span animate={{ rotate: [0, 12, -8, 0] }} transition={{ repeat: Infinity, duration: 2.4, repeatDelay: 1 }} className="grid size-7 place-items-center rounded-lg bg-mind/15 text-mind">
          <Sparkles className="size-4" />
        </motion.span>
        <span className="text-[14px] font-bold">{title}</span>
        {questions.length > 1 && <span className="ml-auto text-[12px] text-muted tabular-nums">{step + 1} of {questions.length}</span>}
      </div>

      {questions.length > 1 && (
        <div className="flex gap-1.5 px-5 pt-3">
          {questions.map((qq, i) => (
            <button
              key={qq.id}
              onClick={() => {
                setDir(i > step ? 1 : -1)
                setStep(i)
              }}
              className={clsx(
                'flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-[11.5px] font-semibold transition-colors',
                i === step ? 'border-mind text-mind' : answerOf(qq) ? 'border-ok/50 text-ok' : 'border-line text-muted',
              )}
            >
              {answerOf(qq) && i !== step && <Check className="size-3" />}
              {qq.header}
            </button>
          ))}
        </div>
      )}

      <div className="relative overflow-hidden">
        <AnimatePresence mode="wait" initial={false} custom={dir}>
          <motion.div
            key={q.id}
            custom={dir}
            initial={{ opacity: 0, x: 30 * dir }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -30 * dir }}
            transition={{ duration: 0.2 }}
            className="px-5 pt-4 pb-2"
          >
            <p className="mb-3 text-[15px] leading-snug font-semibold">{q.question}</p>
            <div className="space-y-1.5" role="radiogroup">
              {options.map((o, i) => {
                const on = picked === o.value
                return (
                  <button
                    key={o.value}
                    role="radio"
                    aria-checked={on}
                    onClick={() => setChoice((c) => ({ ...c, [q.id]: o.value }))}
                    className={clsx('group flex w-full items-start gap-3 rounded-xl border px-3 py-2.5 text-left transition-[border-color,background]', on ? 'border-mind bg-mind/10' : 'border-line hover:border-line-strong hover:bg-surface-2/60')}
                  >
                    <span className={clsx('mt-0.5 grid size-5 shrink-0 place-items-center rounded-md text-[11px] font-bold transition-colors', on ? 'bg-mind text-white' : 'bg-surface-3 text-muted')}>
                      {on ? <Check className="size-3" strokeWidth={3} /> : i + 1}
                    </span>
                    <span className="min-w-0">
                      <span className="block text-[13.5px] font-semibold">{o.label}</span>
                      {o.description && <span className="block text-[12.5px] text-muted">{o.description}</span>}
                    </span>
                  </button>
                )
              })}
              {q.allow_other && (
                <div className={clsx('rounded-xl border transition-colors', picked === OTHER ? 'border-mind bg-mind/10' : 'border-line hover:border-line-strong')}>
                  <button role="radio" aria-checked={picked === OTHER} onClick={() => setChoice((c) => ({ ...c, [q.id]: OTHER }))} className="flex w-full items-center gap-3 px-3 py-2.5 text-left">
                    <span className={clsx('grid size-5 shrink-0 place-items-center rounded-md', picked === OTHER ? 'bg-mind text-white' : 'bg-surface-3 text-muted')}>
                      <PencilLine className="size-3" />
                    </span>
                    <span className="text-[13.5px] font-semibold">Other</span>
                    <span className="text-[12.5px] text-muted">Answer in your own words</span>
                  </button>
                  <AnimatePresence>
                    {picked === OTHER && (
                      <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
                        <div className="px-3 pb-3">
                          <input
                            ref={otherInput}
                            className="input"
                            value={other[q.id] || ''}
                            placeholder={q.other_placeholder || 'Type your answer…'}
                            onChange={(e) => setOther((o) => ({ ...o, [q.id]: e.target.value }))}
                          />
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              )}
            </div>
          </motion.div>
        </AnimatePresence>
      </div>

      <div className="flex items-center gap-2 px-5 pt-2 pb-4">
        {step > 0 && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setDir(-1)
              setStep((s) => s - 1)
            }}
            icon={<ArrowLeft className="size-4" />}
          >
            Back
          </Button>
        )}
        {error && <span className="text-[12.5px] text-bad">{error}</span>}
        <span className="ml-auto hidden items-center gap-1 text-[11.5px] text-faint sm:flex">
          press 1–{options.length + (q.allow_other ? 1 : 0)}, then <CornerDownLeft className="size-3" />
        </span>
        <Button variant="primary" size="sm" onClick={next} disabled={!ready} loading={busy}>
          {last ? 'Continue' : 'Next'}
        </Button>
      </div>
    </motion.div>
  )
}
