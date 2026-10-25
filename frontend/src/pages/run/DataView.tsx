import clsx from 'clsx'
import { motion } from 'framer-motion'
import { AlertTriangle, CheckCircle2, ChevronLeft, ChevronRight, Sparkles, XCircle } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Plot } from '../../components/Plot'
import { Button, DataTable, Empty, Pill, SectionTitle, Spinner, Stat, Tabs } from '../../components/ui'
import { api, type Preview, type RunDetail } from '../../lib/api'
import { num } from '../../lib/format'

type Which = 'cleaned' | 'train' | 'test' | 'raw'
type Filter = 'all' | 'feature' | 'drop' | 'llm'

export default function DataView({ runId, detail }: { runId: string; detail: RunDetail | null }) {
  const r = detail?.result
  const [filter, setFilter] = useState<Filter>('all')
  if (!r) return <Empty title="Not ready yet">The prepared data appears here once the run completes.</Empty>
  const st = r.stats
  const ck = r.checks
  const base = ck.baseline
  const cols = r.plan.columns.filter((c) => filter === 'all' || (filter === 'llm' ? c.source === 'llm' || c.source === 'user' : c.role === filter))

  return (
    <div className="mx-auto max-w-[1280px] space-y-8">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Rows" value={`${st.train_rows.toLocaleString()} / ${st.test_rows.toLocaleString()}`} hint={`train / test from ${st.raw_rows.toLocaleString()} raw`} />
        <Stat label="Columns → features" value={`${st.columns_in} → ${st.features_out}`} hint={`${st.columns_dropped.length} columns dropped`} />
        <Stat label="Cleaned up" value={st.duplicates_removed + st.missing_target_removed} hint={`${st.duplicates_removed} duplicates, ${st.missing_target_removed} missing target`} />
        <Stat label="Checks" value={`${ck.summary.passed}/${ck.summary.total}`} hint={ck.summary.failed ? `${ck.summary.failed} failed` : ck.summary.warnings ? `${ck.summary.warnings} warnings` : 'all passed'} tone={ck.summary.failed ? 'var(--bad)' : 'var(--ok)'} />
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        <div className="card p-5">
          <SectionTitle title="Verification">{r.verdict?.source === 'llm' ? 'Reviewed by the LLM verifier on top of coded checks' : 'Coded checks and a baseline model'}</SectionTitle>
          {r.verdict && <p className="mb-4 text-[14px]">{r.verdict.summary}</p>}
          <div className="space-y-2">
            {ck.checks.map((c, i) => (
              <motion.div key={c.id} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.04 }} className="flex gap-2.5">
                {c.status === 'pass' ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-ok" /> : c.status === 'warn' ? <AlertTriangle className="mt-0.5 size-4 shrink-0 text-signal" /> : <XCircle className="mt-0.5 size-4 shrink-0 text-bad" />}
                <div>
                  <div className="text-[13.5px] font-semibold">{c.name}</div>
                  <div className="text-[12.5px] text-muted">{c.detail}</div>
                </div>
              </motion.div>
            ))}
          </div>
          {r.verdict?.concerns && r.verdict.concerns.length > 0 && (
            <div className="mt-4 rounded-xl bg-signal/10 p-3 text-[13px] text-signal">
              {r.verdict.concerns.map((c, i) => (
                <div key={i}>• {c}</div>
              ))}
            </div>
          )}
        </div>

        <div className="card p-5">
          <SectionTitle title="Does the preparation help?">The same gradient-boosting model trained on raw numeric columns vs. the prepared features, scored on the held-out test set.</SectionTitle>
          {base && base.naive_test != null ? (
            <>
              <Plot
                height={230}
                spec={{
                  data: [
                    {
                      type: 'bar',
                      orientation: 'h',
                      y: ['Naive (raw numbers only)', 'Prepared by Data Mind'],
                      x: [base.naive_test, base.prepared_test],
                      text: [base.naive_test.toFixed(3), base.prepared_test.toFixed(3)],
                      textposition: 'outside',
                      marker: { color: ['#8e98b3', getComputedStyle(document.documentElement).getPropertyValue('--ok').trim() || '#3ccfae'] },
                    },
                  ],
                  layout: { xaxis: { title: { text: base.metric }, range: [Math.min(0, base.naive_test) , Math.max(1, base.prepared_test) * 1.08] }, margin: { l: 170 } },
                }}
              />
              <p className="text-[13px] text-muted">
                {base.metric} {base.delta >= 0 ? 'improves' : 'changes'} by <b className={base.delta >= 0 ? 'text-ok' : 'text-bad'}>{base.delta >= 0 ? '+' : ''}{base.delta.toFixed(3)}</b> using {base.prepared_features} features instead of {base.naive_features}. Cross-validated on train: {base.prepared_cv_mean} ± {base.prepared_cv_std}.
              </p>
            </>
          ) : base ? (
            <p className="text-[13.5px]">
              {base.metric}: {base.prepared_cv_mean} ± {base.prepared_cv_std} (3-fold CV). There were no raw numeric columns to build a naive baseline from.
            </p>
          ) : (
            <p className="text-[13.5px] text-muted">No target was chosen, so no model was trained. The data is cleaned and encoded for exploration.</p>
          )}
        </div>
      </div>

      <div>
        <SectionTitle
          title="What happened to each column"
          action={<Tabs<Filter> value={filter} onChange={setFilter} tabs={[{ id: 'all', label: 'All' }, { id: 'feature', label: 'Kept' }, { id: 'drop', label: 'Dropped' }, { id: 'llm', label: 'By LLM / you' }]} />}
        >
          Every decision with its reason.
        </SectionTitle>
        <div className="card overflow-hidden">
          <div className="max-h-[460px] overflow-auto">
            <table className="w-full text-[13px]">
              <thead className="sticky top-0 bg-surface-2 text-left text-muted">
                <tr>
                  <th className="px-4 py-2.5 font-semibold">Column</th>
                  <th className="px-3 py-2.5 font-semibold">Decision</th>
                  <th className="px-4 py-2.5 font-semibold">Reason</th>
                </tr>
              </thead>
              <tbody>
                {cols.map((c) => (
                  <tr key={c.column} className="border-t border-line align-top">
                    <td className="px-4 py-2.5">
                      <div className="font-semibold">{c.column}</div>
                      <div className="text-[11.5px] text-faint">{c.semantic_type}</div>
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="flex flex-wrap gap-1">
                        <Pill tone={c.role === 'drop' ? 'bad' : c.role === 'target' ? 'mind' : 'ok'}>{c.role === 'feature' ? 'keep' : c.role}</Pill>
                        {c.source === 'llm' && (
                          <Pill tone="mind">
                            <Sparkles className="size-3" />
                            LLM
                          </Pill>
                        )}
                        {c.source === 'user' && <Pill tone="info">you</Pill>}
                        {c.source === 'verifier' && <Pill tone="signal">verifier</Pill>}
                      </div>
                      {c.role === 'feature' && <div className="mt-1 text-[12px] text-muted">{opsOf(c)}</div>}
                    </td>
                    <td className="max-w-[560px] px-4 py-2.5 text-muted">{c.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        {r.plan.notes.length > 0 && (
          <ul className="mt-3 space-y-1 text-[13px] text-muted">
            {r.plan.notes.map((n, i) => (
              <li key={i}>• {n}</li>
            ))}
          </ul>
        )}
      </div>

      {ck.comparisons.length > 0 && (
        <div>
          <SectionTitle title="Before and after">Numeric columns in the raw data compared with the model-ready training set.</SectionTitle>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {ck.comparisons.map((c) => (
              <div key={c.column} className="card p-4">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="font-bold">{c.column}</span>
                  <span className="truncate text-[11.5px] text-muted">{c.transform}</span>
                </div>
                <div className="mt-3 grid grid-cols-[auto_1fr_1fr] gap-x-3 gap-y-1 text-[12.5px]">
                  <span />
                  <span className="text-faint">before</span>
                  <span className="text-faint">after</span>
                  {(['missing', 'mean', 'min', 'max'] as const).map((k) => (
                    <div key={k} className="contents">
                      <span className="text-muted">{k}</span>
                      <span className="tabular-nums">{num(c.before[k] as number)}</span>
                      <span className={clsx('tabular-nums', k === 'missing' && (c.before[k] as number) > 0 && 'font-semibold text-ok')}>{num(c.after[k] as number)}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <DataBrowser runId={runId} />
    </div>
  )
}

function opsOf(c: any) {
  const ops = []
  if (c.dtype_fix) ops.push(`cast ${c.dtype_fix}`)
  if (c.category_map && Object.keys(c.category_map).length) ops.push(`merge ${Object.keys(c.category_map).length} variants`)
  if (c.impute && c.impute !== 'none') ops.push(`impute ${c.impute}`)
  if (c.add_missing_flag) ops.push('missing flag')
  if (c.outliers && c.outliers !== 'none') ops.push(c.outliers)
  if (c.rare_threshold) ops.push(`group rare <${c.rare_threshold}`)
  if (c.encode && c.encode !== 'none') ops.push(`${c.encode} encode`)
  if (c.scale && c.scale !== 'none') ops.push(`${c.scale} scale`)
  if (c.datetime_features) ops.push('date features')
  if (c.text_features) ops.push('text features')
  return ops.join(' → ') || 'unchanged'
}

function DataBrowser({ runId }: { runId: string }) {
  const [which, setWhich] = useState<Which>('cleaned')
  const [offset, setOffset] = useState(0)
  const [page, setPage] = useState<(Preview & { total: number }) | null>(null)
  const [loading, setLoading] = useState(false)
  const limit = 50
  useEffect(() => {
    setLoading(true)
    api
      .table(runId, which, offset, limit)
      .then(setPage)
      .catch(() => setPage(null))
      .finally(() => setLoading(false))
  }, [runId, which, offset])
  useEffect(() => setOffset(0), [which])
  const desc: Record<Which, string> = {
    cleaned: 'Typed and tidied, human-readable — before encoding and scaling.',
    train: 'Model-ready training split (encoded, scaled, imputed).',
    test: 'Model-ready test split, transformed with what was learned on train.',
    raw: 'Exactly what you loaded.',
  }
  return (
    <div>
      <SectionTitle
        title="Browse the data"
        action={<Tabs<Which> value={which} onChange={setWhich} tabs={[{ id: 'cleaned', label: 'Cleaned' }, { id: 'train', label: 'Train' }, { id: 'test', label: 'Test' }, { id: 'raw', label: 'Raw' }]} />}
      >
        {desc[which]}
      </SectionTitle>
      {page ? (
        <div className={clsx('transition-opacity', loading && 'opacity-50')}>
          <DataTable columns={page.columns} rows={page.rows} maxHeight={480} />
          <div className="mt-3 flex items-center justify-between text-[13px] text-muted">
            <span>
              Rows {page.total ? offset + 1 : 0}–{Math.min(offset + limit, page.total)} of {page.total.toLocaleString()} · {page.columns.length} columns
            </span>
            <div className="flex gap-2">
              <Button size="sm" variant="outline" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))} icon={<ChevronLeft className="size-4" />}>
                Previous
              </Button>
              <Button size="sm" variant="outline" disabled={offset + limit >= page.total} onClick={() => setOffset(offset + limit)}>
                Next
                <ChevronRight className="size-4" />
              </Button>
            </div>
          </div>
        </div>
      ) : (
        <div className="grid h-40 place-items-center">{loading ? <Spinner /> : <span className="text-muted">Not available</span>}</div>
      )}
    </div>
  )
}
