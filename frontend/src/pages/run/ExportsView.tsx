import { motion } from 'framer-motion'
import { Archive, Code2, Download, FileJson, FileSpreadsheet, FileText, Package } from 'lucide-react'
import { Button, Empty, SectionTitle } from '../../components/ui'
import { api, type RunDetail } from '../../lib/api'
import { bytes } from '../../lib/format'

const ICON: Record<string, any> = { data: FileSpreadsheet, pipeline: Package, code: Code2, plan: FileJson, report: FileText }
const DESC: Record<string, string> = {
  'cleaned.csv': 'Tidied data in its original shape — types fixed, labels merged, duplicates removed. Best for analysis and BI tools.',
  'train.csv': 'Model-ready training split: every feature numeric, imputed, encoded and scaled.',
  'test.csv': 'Model-ready test split, transformed only with what was learned on train.',
  'pipeline.joblib': 'The fitted scikit-learn pipeline. Load it to transform new raw data exactly the same way.',
  'datamind_transformers.py': 'The small runtime the pipeline needs. Keep it next to pipeline.joblib.',
  'reproduce.py': 'Rebuilds everything from the plan without Data Mind, or applies the saved pipeline to new data.',
  'plan.json': 'Every decision the agent made, in a format you can edit and re-run.',
  'decisions.json': 'The agent log: what each stage did, in order.',
  'report.html': 'A standalone report with checks, decisions and the agent log. Open in any browser.',
}

export default function ExportsView({ runId, detail }: { runId: string; detail: RunDetail | null }) {
  const files = detail?.result?.files ?? []
  if (!files.length) return <Empty title="Nothing exported yet">Files appear here when the run completes.</Empty>
  const order = ['train.csv', 'test.csv', 'cleaned.csv', 'pipeline.joblib', 'datamind_transformers.py', 'reproduce.py', 'report.html', 'plan.json', 'decisions.json']
  const sorted = [...files].sort((a, b) => order.indexOf(a.name) - order.indexOf(b.name))
  const target = detail?.result?.plan.target

  return (
    <div className="mx-auto max-w-[1100px] space-y-8">
      <div className="card flex flex-wrap items-center gap-4 p-5">
        <div className="grid size-11 place-items-center rounded-2xl bg-mind/15 text-mind">
          <Archive className="size-5" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="font-bold">Everything in one archive</div>
          <div className="text-[13px] text-muted">Data, fitted pipeline, reproducible script and report.</div>
        </div>
        <a href={api.fileUrl(runId, 'datamind_outputs.zip')} download>
          <Button variant="primary" icon={<Download className="size-4" />}>
            Download all
          </Button>
        </a>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        {sorted.map((f, i) => {
          const Icon = ICON[f.kind] ?? FileText
          return (
            <motion.a
              key={f.name}
              href={api.fileUrl(runId, f.name)}
              download={f.name !== 'report.html'}
              target={f.name === 'report.html' ? '_blank' : undefined}
              rel="noreferrer"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.04 }}
              className="card group flex gap-3 p-4 transition-colors hover:border-line-strong"
            >
              <Icon className="mt-0.5 size-5 shrink-0 text-muted group-hover:text-mind" />
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="truncate font-mono text-[13px] font-medium">{f.name}</span>
                  <span className="shrink-0 text-[12px] text-faint">{bytes(f.size)}</span>
                </div>
                <p className="mt-1 text-[12.5px] text-muted">{DESC[f.name] ?? ''}</p>
              </div>
            </motion.a>
          )
        })}
      </div>

      <div>
        <SectionTitle title="Use the pipeline on new data">Unzip the archive, then in Python:</SectionTitle>
        <pre className="overflow-x-auto rounded-xl border border-line bg-surface p-4 font-mono text-[12.5px] leading-relaxed">{`import joblib, pandas as pd
import datamind_transformers  # must sit next to pipeline.joblib

pipe = joblib.load("pipeline.joblib")
X_new = pipe.transform(pd.read_csv("new_customers.csv"))   # raw file, same columns as before
${target ? `
# train a model on the prepared split
from sklearn.ensemble import HistGradientBoostingClassifier
train = pd.read_csv("train.csv")
model = HistGradientBoostingClassifier().fit(train.drop(columns="${target}"), train["${target}"])
predictions = model.predict(X_new)` : ''}`}</pre>
        <p className="mt-2 text-[13px] text-muted">
          Or run <code className="rounded bg-surface-2 px-1 font-mono">python reproduce.py raw.csv</code> to rebuild everything from the plan, and{' '}
          <code className="rounded bg-surface-2 px-1 font-mono">python reproduce.py new.csv --apply</code> to transform new rows.
        </p>
      </div>
    </div>
  )
}
