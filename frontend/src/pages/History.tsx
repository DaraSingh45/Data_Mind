import { motion } from 'framer-motion'
import { History as HistoryIcon, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Button, Empty, Pill, Spinner } from '../components/ui'
import { api, type RunMeta } from '../lib/api'
import { ago, PROVIDER_LABEL } from '../lib/format'

const TONE: Record<string, any> = { running: 'signal', waiting: 'mind', completed: 'ok', failed: 'bad', interrupted: 'neutral' }

export default function History() {
  const [runs, setRuns] = useState<RunMeta[] | null>(null)
  const [confirm, setConfirm] = useState<string | null>(null)
  const load = () => api.runs().then(setRuns).catch(() => setRuns([]))
  useEffect(() => {
    load()
  }, [])

  return (
    <div className="mx-auto max-w-[1000px] px-5 py-8 sm:px-8">
      <h1 className="text-[26px] font-extrabold tracking-tight">Runs</h1>
      <p className="mb-6 text-muted">Every analysis is kept on this computer with its data, pipeline, log and insights.</p>
      {!runs ? (
        <div className="grid h-40 place-items-center">
          <Spinner />
        </div>
      ) : runs.length === 0 ? (
        <Empty icon={<HistoryIcon className="size-5" />} title="No runs yet" action={<Link to="/"><Button variant="primary">Start an analysis</Button></Link>}>
          Load a file or a database table and run Data Mind. Each run shows up here.
        </Empty>
      ) : (
        <div className="space-y-2">
          {runs.map((r, i) => (
            <motion.div key={r.run_id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: Math.min(i * 0.03, 0.3) }} className="card flex items-center gap-4 p-4 hover:border-line-strong">
              <Link to={`/runs/${r.run_id}`} className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="truncate font-bold">{r.dataset?.name}</span>
                  <Pill tone={TONE[r.status]}>{r.status}</Pill>
                </div>
                <div className="mt-0.5 text-[13px] text-muted">
                  {ago(r.created_at)} · {PROVIDER_LABEL[r.provider] ?? r.provider}
                  {r.intent?.target ? ` · predict ${r.intent.target}` : r.intent?.task === 'none' ? ' · clean and explore' : ''}
                  {r.dataset ? ` · ${r.dataset.rows.toLocaleString()} rows` : ''}
                </div>
              </Link>
              {confirm === r.run_id ? (
                <div className="flex items-center gap-2">
                  <span className="text-[13px] text-muted">Delete this run and its files?</span>
                  <Button size="sm" variant="danger" onClick={async () => { await api.deleteRun(r.run_id); setConfirm(null); load() }}>
                    Delete
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setConfirm(null)}>
                    Keep
                  </Button>
                </div>
              ) : (
                <button onClick={() => setConfirm(r.run_id)} className="rounded-lg p-2 text-faint hover:bg-surface-2 hover:text-bad" aria-label="Delete run">
                  <Trash2 className="size-4" />
                </button>
              )}
            </motion.div>
          ))}
        </div>
      )}
    </div>
  )
}
