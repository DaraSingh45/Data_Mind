import { motion } from 'framer-motion'
import { AlertTriangle, ChevronDown, Rows3, X } from 'lucide-react'
import { useState } from 'react'
import type { DatasetPayload } from '../../lib/api'
import { pct, TYPE_COLORS } from '../../lib/format'
import { Button, DataTable, Pill } from '../ui'

export function DatasetOverview({ data, onClear }: { data: DatasetPayload; onClear: () => void }) {
  const [showPreview, setShowPreview] = useState(false)
  const p = data.profile
  const typeTotal = Object.values(p.type_counts).reduce((a, b) => a + b, 0)
  const issues = p.columns_detail.reduce((n, c) => n + c.warnings.length, 0) + (p.duplicate_rows ? 1 : 0)

  return (
    <div className="card overflow-hidden">
      <div className="flex items-start justify-between gap-3 border-b border-line p-5">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-[12.5px] text-muted">
            <Rows3 className="size-3.5" />
            {data.dataset.source === 'database' ? 'Imported from database' : data.dataset.source === 'sample' ? 'Sample dataset' : 'Uploaded file'}
          </div>
          <h2 className="mt-0.5 truncate text-xl font-extrabold tracking-tight">{data.dataset.name}</h2>
          <div className="mt-1 text-[13.5px] text-muted">
            {p.rows.toLocaleString()} rows · {p.columns} columns · {pct(p.missing_cells_pct)} cells missing
            {p.duplicate_rows > 0 && ` · ${p.duplicate_rows} duplicate rows`}
          </div>
        </div>
        <Button variant="ghost" size="sm" onClick={onClear} icon={<X className="size-4" />}>
          Change
        </Button>
      </div>

      <div className="p-5">
        <div className="mb-2 flex items-center justify-between text-[13px]">
          <span className="font-semibold">Column types</span>
          <span className="text-muted">{issues} things to fix</span>
        </div>
        <div className="flex h-2.5 overflow-hidden rounded-full bg-surface-2">
          {Object.entries(p.type_counts).map(([t, n], i) => (
            <motion.div key={t} initial={{ width: 0 }} animate={{ width: `${(n / typeTotal) * 100}%` }} transition={{ delay: 0.1 + i * 0.06, duration: 0.5 }} style={{ background: TYPE_COLORS[t] ?? 'var(--faint)' }} title={`${n} ${t}`} />
          ))}
        </div>
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-muted">
          {Object.entries(p.type_counts).map(([t, n]) => (
            <span key={t} className="flex items-center gap-1.5">
              <span className="size-2 rounded-full" style={{ background: TYPE_COLORS[t] ?? 'var(--faint)' }} />
              {n} {t}
            </span>
          ))}
        </div>

        <div className="mt-5 max-h-[340px] space-y-1 overflow-y-auto pr-1">
          {p.columns_detail.map((c, i) => (
            <motion.div
              key={c.name}
              initial={{ opacity: 0, x: -6 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: Math.min(i * 0.025, 0.5) }}
              className="flex items-center gap-3 rounded-lg px-2 py-1.5 hover:bg-surface-2/60"
            >
              <span className="size-2 shrink-0 rounded-full" style={{ background: TYPE_COLORS[c.type] ?? 'var(--faint)' }} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="truncate text-[13.5px] font-semibold">{c.name}</span>
                  <span className="text-[12px] text-faint">{c.type}</span>
                  {data.candidates[0] === c.name && <Pill tone="mind">likely target</Pill>}
                </div>
                {c.warnings.length > 0 && (
                  <div className="flex items-center gap-1 truncate text-[12px] text-signal">
                    <AlertTriangle className="size-3 shrink-0" />
                    {c.warnings.join(' · ')}
                  </div>
                )}
              </div>
              <div className="w-20 shrink-0" title={`${pct(c.missing_pct)} missing`}>
                <div className="h-1.5 overflow-hidden rounded-full bg-surface-3">
                  <div className="h-full rounded-full bg-bad/80" style={{ width: `${c.missing_pct * 100}%` }} />
                </div>
                <div className="mt-0.5 text-right text-[11px] text-faint">{c.missing_pct > 0 ? `${pct(c.missing_pct, 0)} missing` : 'complete'}</div>
              </div>
            </motion.div>
          ))}
        </div>

        <button onClick={() => setShowPreview((v) => !v)} className="mt-4 flex items-center gap-1.5 text-[13px] font-semibold text-muted hover:text-text">
          <ChevronDown className={`size-4 transition-transform ${showPreview ? 'rotate-180' : ''}`} />
          {showPreview ? 'Hide' : 'Show'} the first rows
        </button>
        {showPreview && (
          <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} className="mt-3">
            <DataTable columns={data.preview.columns} rows={data.preview.rows} maxHeight={300} />
          </motion.div>
        )}
      </div>
    </div>
  )
}
