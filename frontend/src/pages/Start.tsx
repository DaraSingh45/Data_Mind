import clsx from 'clsx'
import { AnimatePresence, motion } from 'framer-motion'
import { ChevronDown, Database, FileSpreadsheet, LineChart, Loader2, Package, ShieldCheck, Table2 } from 'lucide-react'
import { useState } from 'react'
import { DatabasePanel, Upload } from '../components/start/DataSource'
import { DatasetOverview } from '../components/start/DatasetOverview'
import { IntakeChat } from '../components/start/IntakeChat'
import { PipelinePreview } from '../components/start/PipelinePreview'
import { api, type DatasetPayload } from '../lib/api'
import { useStore } from '../lib/store'

const OUTPUTS = [
  { icon: Table2, title: 'Clean, typed data', text: 'Fixed types, merged labels, no duplicates.' },
  { icon: ShieldCheck, title: 'Leak-free train/test', text: 'Every step learned on the training split.' },
  { icon: Package, title: 'A reusable pipeline', text: 'Apply the same steps to tomorrow’s data.' },
  { icon: LineChart, title: 'Insights you can ask', text: 'Tested findings and charts on request.' },
]

export default function Start() {
  const { session, setDataset } = useStore()
  const data = session.dataset
  const [dbOpen, setDbOpen] = useState(() => !!sessionStorage.getItem('dm-db-url'))
  const [sampleBusy, setSampleBusy] = useState<string | null>(null)

  const loadSample = async (id: string) => {
    setSampleBusy(id)
    try {
      const r = await api.loadSample(id)
      if (r.database_url) {
        sessionStorage.setItem('dm-db-url', r.database_url)
        setDbOpen(true)
        setTimeout(() => document.getElementById('db-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 120)
      } else setDataset(r as DatasetPayload)
    } finally {
      setSampleBusy(null)
    }
  }

  if (data) {
    return (
      <div className="mx-auto max-w-[1320px] px-5 py-6 sm:px-8 sm:py-8">
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)]">
          <motion.div initial={{ opacity: 0, x: -12 }} animate={{ opacity: 1, x: 0 }}>
            <DatasetOverview data={data} onClear={() => setDataset(null)} />
          </motion.div>
          <motion.div initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.08 }} className="lg:sticky lg:top-6 lg:self-start">
            <IntakeChat data={data} />
          </motion.div>
        </div>
      </div>
    )
  }

  return (
    <div className="relative">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-[520px] bg-[radial-gradient(60%_60%_at_70%_20%,color-mix(in_srgb,var(--mind)_16%,transparent),transparent_70%)]" />
      <div className="relative mx-auto max-w-[1180px] px-5 pt-10 pb-16 sm:px-8 sm:pt-16">
        <div className="grid items-center gap-12 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
          <motion.div initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
            <h1 className="text-[38px] leading-[1.05] font-extrabold tracking-[-0.035em] sm:text-[50px] xl:text-[54px]">
              Messy data in.
              <br />
              <span className="whitespace-nowrap text-muted">Model-ready data out.</span>
            </h1>
            <p className="mt-5 max-w-[52ch] text-[16px] leading-relaxed text-muted">
              Upload a file or connect a database and say what you want in plain English. Data Mind profiles, plans, checks and prepares your data, then shows what it found. It only stops to ask when something is genuinely unclear.
            </p>

            <div className="mt-8">
              <Upload onLoaded={setDataset} />
            </div>

            <div className="mt-4 flex flex-wrap items-center gap-2 text-[13px]">
              <button
                onClick={() => setDbOpen((o) => !o)}
                className={clsx('flex items-center gap-1.5 rounded-full border px-3 py-1.5 font-semibold transition-colors', dbOpen ? 'border-mind bg-mind/10 text-mind' : 'border-line text-text hover:border-line-strong')}
              >
                <Database className="size-3.5" />
                Connect a database
                <ChevronDown className={clsx('size-3.5 transition-transform', dbOpen && 'rotate-180')} />
              </button>
              <span className="ml-1 text-muted">or try a sample:</span>
              {[
                { id: 'customer_churn', label: 'Customer churn CSV', icon: FileSpreadsheet },
                { id: 'retail_db', label: 'Retail database', icon: Database },
              ].map((s) => (
                <button key={s.id} onClick={() => loadSample(s.id)} disabled={!!sampleBusy} className="flex items-center gap-1.5 rounded-full border border-line px-3 py-1.5 text-muted transition-colors hover:border-line-strong hover:text-text">
                  {sampleBusy === s.id ? <Loader2 className="size-3.5 animate-spin" /> : <s.icon className="size-3.5" />}
                  {s.label}
                </button>
              ))}
            </div>
          </motion.div>

          <motion.div initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: 0.15, duration: 0.6 }} className="hidden lg:block">
            <PipelinePreview />
          </motion.div>
        </div>

        <AnimatePresence>
          {dbOpen && (
            <motion.div id="db-panel" initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} className="overflow-hidden">
              <div className="card mt-8 p-5 sm:p-6">
                <div className="mb-4">
                  <h2 className="text-[17px] font-bold">Connect a database</h2>
                  <p className="text-[13.5px] text-muted">PostgreSQL, MySQL, SQLite or any SQLAlchemy URL. Pick tables (joins are suggested) or write a read-only query.</p>
                </div>
                <DatabasePanel onLoaded={setDataset} />
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }} className="mt-14 grid gap-px overflow-hidden rounded-2xl border border-line bg-line sm:grid-cols-2 lg:grid-cols-4">
          {OUTPUTS.map(({ icon: Icon, title, text }) => (
            <div key={title} className="bg-surface/80 p-5 backdrop-blur">
              <Icon className="size-5 text-mind" />
              <div className="mt-3 text-[14.5px] font-bold">{title}</div>
              <div className="mt-0.5 text-[13px] text-muted">{text}</div>
            </div>
          ))}
        </motion.div>
      </div>
    </div>
  )
}
