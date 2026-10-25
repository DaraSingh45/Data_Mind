import clsx from 'clsx'
import { motion } from 'framer-motion'
import { Check, Cloud, Cpu, Eye, Gauge, HardDrive, Lightbulb, Palette, RefreshCw, ShieldCheck, Sparkles, Workflow, X } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { Button, Field, Pill, Spinner, Toggle } from '../components/ui'
import { api, type Settings } from '../lib/api'
import { applyUi, useStore } from '../lib/store'

const SECTIONS = [
  { id: 'models', label: 'Models', icon: Sparkles },
  { id: 'privacy', label: 'Privacy', icon: ShieldCheck },
  { id: 'agent', label: 'Agent behaviour', icon: Workflow },
  { id: 'prep', label: 'Preparation', icon: Gauge },
  { id: 'insights', label: 'Insights', icon: Lightbulb },
  { id: 'ui', label: 'Appearance', icon: Palette },
]

const PROVIDERS = [
  { id: 'heuristic', name: 'Rules engine only', icon: Cpu, desc: 'No LLM. Fast, deterministic and fully offline.' },
  { id: 'ollama', name: 'Ollama', icon: HardDrive, desc: 'A local model on this machine. Free and private.' },
  { id: 'groq', name: 'Groq', icon: Cloud, desc: 'Fast hosted open models. Free tier with rate limits.' },
  { id: 'gemini', name: 'Gemini', icon: Cloud, desc: "Google's models. Free tier with rate limits." },
] as const

export default function SettingsPage() {
  const { settings: stored, ollamaModels, setSettings } = useStore()
  const [s, setS] = useState<Settings | null>(stored)
  const [models, setModels] = useState<string[]>(ollamaModels)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [tests, setTests] = useState<Record<string, { busy?: boolean; ok?: boolean; msg?: string }>>({})
  const [section, setSection] = useState(() => new URLSearchParams(window.location.search).get('section') || 'models')

  useEffect(() => {
    if (stored && !s) setS(stored)
  }, [stored, s])
  useEffect(() => setModels(ollamaModels), [ollamaModels])

  if (!s)
    return (
      <div className="grid h-64 place-items-center">
        <Spinner />
      </div>
    )

  const upd = <K extends Exclude<keyof Settings, 'env_file'>>(sec: K, patch: Partial<Settings[K]>) => {
    setS((cur) => {
      const next = { ...cur!, [sec]: { ...cur![sec], ...patch } }
      if (sec === 'ui') applyUi(next)
      return next
    })
    setSaved(false)
  }
  const dirty = JSON.stringify(s) !== JSON.stringify(stored)

  const save = async () => {
    setSaving(true)
    try {
      const r = await api.saveSettings(s)
      setSettings(r.settings)
      setS(r.settings)
      setSaved(true)
    } finally {
      setSaving(false)
    }
  }
  const test = async (provider: string) => {
    if (dirty) await save()
    setTests((t) => ({ ...t, [provider]: { busy: true } }))
    try {
      const r = await api.testProvider(provider)
      setTests((t) => ({ ...t, [provider]: { ok: r.ok, msg: r.ok ? `Responded in ${r.seconds}s` : r.error || 'No valid reply' } }))
    } catch (e: any) {
      setTests((t) => ({ ...t, [provider]: { ok: false, msg: e.message } }))
    }
  }
  const refreshModels = async () => setModels((await api.ollamaModels(s.llm.ollama_base_url)).models)

  const TestButton = ({ provider }: { provider: string }) => {
    const t = tests[provider]
    return (
      <div className="flex flex-wrap items-center gap-3">
        <Button size="sm" variant="outline" onClick={() => test(provider)} loading={t?.busy}>
          Test connection
        </Button>
        {t && !t.busy && (
          <span className={clsx('flex items-center gap-1 text-[13px]', t.ok ? 'text-ok' : 'text-bad')}>
            {t.ok ? <Check className="size-4" /> : <X className="size-4" />}
            {t.msg}
          </span>
        )}
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-[1100px] px-5 py-8 sm:px-8">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-[26px] font-extrabold tracking-tight">Settings</h1>
          <p className="text-muted">API keys, the provider and model names are kept in <code className="rounded bg-surface-2 px-1 font-mono text-[13px]">backend/.env</code>; everything else in the app's data folder. Keys never leave this computer except to call the provider you choose.</p>
        </div>
        <div className="flex items-center gap-3">
          {saved && !dirty && (
            <motion.span initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex items-center gap-1 text-[13px] text-ok">
              <Check className="size-4" /> Saved
            </motion.span>
          )}
          <Button variant="primary" onClick={save} loading={saving} disabled={!dirty}>
            Save changes
          </Button>
        </div>
      </div>

      <div className="grid gap-6 md:grid-cols-[200px_minmax(0,1fr)]">
        <nav className="flex gap-1 overflow-x-auto md:flex-col">
          {SECTIONS.map(({ id, label, icon: Icon }) => (
            <button key={id} onClick={() => setSection(id)} className={clsx('relative flex items-center gap-2.5 rounded-xl px-3 py-2 text-left text-[14px] font-semibold whitespace-nowrap', section === id ? 'text-text' : 'text-muted hover:text-text')}>
              {section === id && <motion.span layoutId="settings-nav" className="absolute inset-0 -z-10 rounded-xl bg-surface-2" />}
              <Icon className="size-4" />
              {label}
            </button>
          ))}
        </nav>

        <motion.div key={section} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="space-y-5">
          {section === 'models' && (
            <>
              <Card title="Which model plans and verifies" desc="The rules engine always drafts the plan and does every calculation. An LLM, if chosen, refines the plan, checks results and writes summaries.">
                <div className="grid gap-2 sm:grid-cols-2">
                  {PROVIDERS.map((p) => (
                    <button key={p.id} onClick={() => upd('llm', { provider: p.id })} className={clsx('flex gap-3 rounded-xl border p-3.5 text-left transition-colors', s.llm.provider === p.id ? 'border-mind bg-mind/10' : 'border-line hover:border-line-strong')}>
                      <p.icon className={clsx('mt-0.5 size-5 shrink-0', s.llm.provider === p.id ? 'text-mind' : 'text-muted')} />
                      <div>
                        <div className="font-bold">{p.name}</div>
                        <div className="text-[12.5px] text-muted">{p.desc}</div>
                      </div>
                    </button>
                  ))}
                </div>
              </Card>

              <Card title="Ollama" desc="Install from ollama.com, then run: ollama pull llama3.2:3b" badge={s.llm.provider === 'ollama' ? 'active' : undefined}>
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label="Server URL">
                    <input className="input" value={s.llm.ollama_base_url} onChange={(e) => upd('llm', { ollama_base_url: e.target.value })} />
                  </Field>
                  <Field label="Model" hint={models.length ? `${models.length} models found` : 'No models found — is Ollama running?'}>
                    <div className="flex gap-2">
                      {models.length ? (
                        <select className="input" value={s.llm.ollama_model} onChange={(e) => upd('llm', { ollama_model: e.target.value })}>
                          {!models.includes(s.llm.ollama_model) && <option>{s.llm.ollama_model}</option>}
                          {models.map((m) => (
                            <option key={m}>{m}</option>
                          ))}
                        </select>
                      ) : (
                        <input className="input" value={s.llm.ollama_model} onChange={(e) => upd('llm', { ollama_model: e.target.value })} />
                      )}
                      <Button variant="outline" onClick={refreshModels} aria-label="Refresh models" className="!px-3">
                        <RefreshCw className="size-4" />
                      </Button>
                    </div>
                  </Field>
                </div>
                <TestButton provider="ollama" />
              </Card>

              <Card title="Groq" desc="Free API key at console.groq.com" badge={s.llm.provider === 'groq' ? 'active' : undefined}>
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label="API key" hint="Stored as GROQ_API_KEY in backend/.env">
                    <input className="input font-mono" type="password" autoComplete="off" value={s.llm.groq_api_key} placeholder="gsk_…" onChange={(e) => upd('llm', { groq_api_key: e.target.value })} />
                  </Field>
                  <Field label="Model">
                    <input className="input" value={s.llm.groq_model} onChange={(e) => upd('llm', { groq_model: e.target.value })} />
                  </Field>
                </div>
                <TestButton provider="groq" />
              </Card>

              <Card title="Gemini" desc="Free API key at aistudio.google.com" badge={s.llm.provider === 'gemini' ? 'active' : undefined}>
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label="API key" hint="Stored as GEMINI_API_KEY in backend/.env">
                    <input className="input font-mono" type="password" autoComplete="off" value={s.llm.gemini_api_key} placeholder="AIza…" onChange={(e) => upd('llm', { gemini_api_key: e.target.value })} />
                  </Field>
                  <Field label="Model">
                    <input className="input" value={s.llm.gemini_model} onChange={(e) => upd('llm', { gemini_model: e.target.value })} />
                  </Field>
                </div>
                <TestButton provider="gemini" />
              </Card>

              <Card title="Reliability">
                <Toggle checked={s.llm.use_fallback} onChange={(v) => upd('llm', { use_fallback: v })} label="Fall back to other providers" hint={`If the chosen model fails or hits a rate limit, try: ${s.llm.fallback_order.join(' → ')}. If all fail, the rules engine continues alone.`} />
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label={`Temperature: ${s.llm.temperature}`} hint="Lower is more consistent.">
                    <input type="range" min={0} max={1} step={0.05} value={s.llm.temperature} onChange={(e) => upd('llm', { temperature: Number(e.target.value) })} className="w-full accent-[var(--mind)]" />
                  </Field>
                  <Field label="Timeout per call (seconds)">
                    <input type="number" className="input" min={10} max={600} value={s.llm.timeout_seconds} onChange={(e) => upd('llm', { timeout_seconds: Number(e.target.value) })} />
                  </Field>
                </div>
              </Card>
            </>
          )}

          {section === 'privacy' && (
            <Card title="What the LLM may see" desc="Raw rows are never sent. The model receives column statistics: types, missing share, ranges, skew and warnings.">
              <Toggle checked={s.privacy.share_labels_with_local} onChange={(v) => upd('privacy', { share_labels_with_local: v })} label="Share category labels with the local model" hint="Lets Ollama merge spellings like 'M' and 'Male'. Data never leaves this computer." />
              <Toggle checked={s.privacy.share_labels_with_cloud} onChange={(v) => upd('privacy', { share_labels_with_cloud: v })} label="Share category labels with cloud models" hint="Off by default. Turn on only for non-sensitive data." />
              <Field label="Max labels per column">
                <input type="number" className="input !w-32" min={1} max={50} value={s.privacy.max_labels_per_column} onChange={(e) => upd('privacy', { max_labels_per_column: Number(e.target.value) })} />
              </Field>
              <div className="flex items-start gap-2 rounded-xl bg-surface-2 p-3 text-[13px] text-muted">
                <Eye className="mt-0.5 size-4 shrink-0" />
                Database credentials and API keys are never included in prompts.
              </div>
            </Card>
          )}

          {section === 'agent' && (
            <Card title="When the agent asks you">
              <div className="grid gap-2 sm:grid-cols-3">
                {(
                  [
                    ['on_uncertainty', 'When unsure', 'Asks only when a decision is risky, such as possible leakage or an unclear target.'],
                    ['always', 'Always review', 'Shows you the full plan before running anything.'],
                    ['never', 'Never', 'Runs end to end using safe defaults for every open question.'],
                  ] as const
                ).map(([id, name, desc]) => (
                  <button key={id} onClick={() => upd('agent', { human_review: id })} className={clsx('rounded-xl border p-3 text-left', s.agent.human_review === id ? 'border-mind bg-mind/10' : 'border-line hover:border-line-strong')}>
                    <div className="font-bold">{name}</div>
                    <div className="text-[12.5px] text-muted">{desc}</div>
                  </button>
                ))}
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Plan retries" hint="How often an invalid LLM plan is sent back before using the rules plan.">
                  <input type="number" className="input" min={0} max={5} value={s.agent.max_plan_retries} onChange={(e) => upd('agent', { max_plan_retries: Number(e.target.value) })} />
                </Field>
                <Field label="Verifier revision loops" hint="How often the verifier can send the plan back.">
                  <input type="number" className="input" min={0} max={3} value={s.agent.max_revise_loops} onChange={(e) => upd('agent', { max_revise_loops: Number(e.target.value) })} />
                </Field>
              </div>
              <Field
                label={`Self-repair attempts: ${s.agent.max_repair_attempts === 0 ? 'off' : s.agent.max_repair_attempts}`}
                hint="When a stage crashes, the agent explains why, finds the column that caused it, changes the plan (with the LLM's help if one is connected) and tries again — up to this many times. 0 turns self-repair off."
              >
                <div className="flex items-center gap-3">
                  <input type="range" min={0} max={5} step={1} value={s.agent.max_repair_attempts} onChange={(e) => upd('agent', { max_repair_attempts: Number(e.target.value) })} className="w-56 accent-[var(--mind)]" aria-label="Self-repair attempts" />
                  <div className="flex gap-1">
                    {[0, 1, 2, 3, 4, 5].map((n) => (
                      <button key={n} onClick={() => upd('agent', { max_repair_attempts: n })} className={clsx('grid size-7 place-items-center rounded-lg text-[12px] font-bold', s.agent.max_repair_attempts === n ? 'bg-mind text-white' : 'bg-surface-2 text-muted hover:text-text')}>
                        {n}
                      </button>
                    ))}
                  </div>
                </div>
              </Field>
              <Toggle checked={s.agent.run_baseline_model} onChange={(v) => upd('agent', { run_baseline_model: v })} label="Train a baseline model to verify" hint="Compares a model on raw numbers with one on the prepared features." />
              <Field label="Baseline sample rows">
                <input type="number" className="input !w-40" min={1000} max={500000} step={1000} value={s.agent.baseline_max_rows} onChange={(e) => upd('agent', { baseline_max_rows: Number(e.target.value) })} />
              </Field>
            </Card>
          )}

          {section === 'prep' && (
            <Card title="Defaults for preparation" desc="The planner starts from these. You can still override any column during review.">
              <div className="grid gap-4 sm:grid-cols-2">
                <Sel label="Model family" value={s.prep.model_family} onChange={(v) => upd('prep', { model_family: v })} options={[['auto', 'Auto (scale for linear models)'], ['tree', 'Tree models (no scaling)'], ['linear', 'Linear / distance models']]} />
                <Sel label="Scaling" value={s.prep.scaling} onChange={(v) => upd('prep', { scaling: v })} options={[['auto', 'Auto'], ['standard', 'Standard'], ['robust', 'Robust'], ['minmax', 'Min-max'], ['none', 'None']]} />
                <Sel label="Outliers" value={s.prep.outlier_strategy} onChange={(v) => upd('prep', { outlier_strategy: v })} options={[['auto', 'Auto'], ['clip_iqr', 'Clip to IQR fences'], ['winsorize', 'Winsorize 1–99%'], ['log1p', 'Log transform'], ['none', 'Leave as is']]} />
                <Sel label="Class imbalance" value={s.prep.imbalance} onChange={(v) => upd('prep', { imbalance: v })} options={[['auto', 'Auto (oversample if ≥ 3:1)'], ['oversample', 'Always oversample train'], ['none', 'Leave as is']]} />
                <Num label="Test set share" value={s.prep.test_size} step={0.05} min={0.05} max={0.5} onChange={(v) => upd('prep', { test_size: v })} />
                <Num label="Random seed" value={s.prep.random_seed} step={1} min={0} max={99999} onChange={(v) => upd('prep', { random_seed: v })} />
                <Num label="Drop columns missing more than" value={s.prep.drop_missing_threshold} step={0.05} min={0.1} max={1} onChange={(v) => upd('prep', { drop_missing_threshold: v })} />
                <Num label="Max categories to one-hot" value={s.prep.max_onehot_categories} step={1} min={2} max={100} onChange={(v) => upd('prep', { max_onehot_categories: v })} />
                <Num label="Group categories rarer than" value={s.prep.rare_category_threshold} step={0.005} min={0} max={0.2} onChange={(v) => upd('prep', { rare_category_threshold: v })} />
              </div>
              <Toggle checked={s.prep.add_missing_flags} onChange={(v) => upd('prep', { add_missing_flags: v })} label="Add missing-value flags" hint="A 0/1 column marking where a value was imputed, when 5% or more is missing." />
              <Toggle checked={s.prep.drop_duplicates} onChange={(v) => upd('prep', { drop_duplicates: v })} label="Remove exact duplicate rows" />
            </Card>
          )}

          {section === 'insights' && (
            <Card title="Insight engine">
              <div className="grid gap-4 sm:grid-cols-2">
                <Num label="Insights on the dashboard" value={s.insights.max_insights} step={1} min={3} max={30} onChange={(v) => upd('insights', { max_insights: v })} />
                <Num label="Significance level (α)" value={s.insights.significance_level} step={0.01} min={0.001} max={0.2} onChange={(v) => upd('insights', { significance_level: v })} />
              </div>
              <Toggle checked={s.insights.narrative} onChange={(v) => upd('insights', { narrative: v })} label="Let the LLM write the summary" hint="Numbers always come from the computed insights." />
            </Card>
          )}

          {section === 'ui' && (
            <Card title="Appearance">
              <div className="grid gap-2 sm:grid-cols-3">
                {(['dark', 'light', 'system'] as const).map((t) => (
                  <button key={t} onClick={() => upd('ui', { theme: t })} className={clsx('rounded-xl border p-3 text-left font-semibold capitalize', s.ui.theme === t ? 'border-mind bg-mind/10' : 'border-line hover:border-line-strong')}>
                    {t}
                  </button>
                ))}
              </div>
              <Toggle
                checked={s.ui.pace_runs}
                onChange={(v) => upd('ui', { pace_runs: v })}
                label="Follow runs at a readable pace"
                hint="Without a language model a run finishes in about two seconds. This plays each stage on the canvas so you can watch it; the work itself is not slowed down."
              />
              <Field label={`Playback speed: ${s.ui.animation_speed}×`}>
                <input type="range" min={0.5} max={3} step={0.25} value={s.ui.animation_speed} onChange={(e) => upd('ui', { animation_speed: Number(e.target.value) })} className="w-full accent-[var(--mind)]" />
              </Field>
              <Toggle checked={s.ui.reduce_motion} onChange={(v) => upd('ui', { reduce_motion: v })} label="Reduce motion" hint="Turns off the agent graph pulses and other animation." />
            </Card>
          )}
        </motion.div>
      </div>
    </div>
  )
}

function Card({ title, desc, badge, children }: { title: string; desc?: string; badge?: string; children: ReactNode }) {
  return (
    <section className="card space-y-4 p-5">
      <div>
        <div className="flex items-center gap-2">
          <h2 className="text-[16px] font-bold">{title}</h2>
          {badge && <Pill tone="ok">{badge}</Pill>}
        </div>
        {desc && <p className="text-[13px] text-muted">{desc}</p>}
      </div>
      {children}
    </section>
  )
}

function Sel({ label, value, onChange, options }: { label: string; value: string; onChange: (v: any) => void; options: [string, string][] }) {
  return (
    <Field label={label}>
      <select className="input" value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map(([v, l]) => (
          <option key={v} value={v}>
            {l}
          </option>
        ))}
      </select>
    </Field>
  )
}

function Num({ label, value, onChange, step, min, max }: { label: string; value: number; onChange: (v: number) => void; step: number; min: number; max: number }) {
  return (
    <Field label={label}>
      <input type="number" className="input" value={value} step={step} min={min} max={max} onChange={(e) => onChange(Number(e.target.value))} />
    </Field>
  )
}
