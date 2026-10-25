import clsx from 'clsx'
import { AnimatePresence, motion } from 'framer-motion'
import { Database, FileSpreadsheet, Link2, Sparkles, Table2, UploadCloud } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api, type DatasetPayload, type DBTable, type JoinSpec, type Preview } from '../../lib/api'
import { Button, DataTable, Field, Pill, Tabs } from '../ui'

type Mode = 'upload' | 'database' | 'samples'

export function DataSource({ onLoaded }: { onLoaded: (d: DatasetPayload) => void }) {
  const [mode, setMode] = useState<Mode>('upload')
  return (
    <div className="card p-5 sm:p-6">
      <Tabs<Mode>
        value={mode}
        onChange={setMode}
        tabs={[
          { id: 'upload', label: <><UploadCloud className="size-4" />Upload file</> },
          { id: 'database', label: <><Database className="size-4" />Database</> },
          { id: 'samples', label: <><Sparkles className="size-4" />Samples</> },
        ]}
      />
      <div className="mt-5">
        <AnimatePresence mode="wait">
          <motion.div key={mode} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.18 }}>
            {mode === 'upload' && <Upload onLoaded={onLoaded} />}
            {mode === 'database' && <DatabasePanel onLoaded={onLoaded} />}
            {mode === 'samples' && <Samples onLoaded={onLoaded} onDatabase={() => setMode('database')} />}
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  )
}

export function Upload({ onLoaded }: { onLoaded: (d: DatasetPayload) => void }) {
  const [drag, setDrag] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const input = useRef<HTMLInputElement>(null)

  const handle = async (file?: File) => {
    if (!file) return
    setError(null)
    setBusy(file.name)
    try {
      onLoaded(await api.upload(file))
    } catch (e: any) {
      setError(e.message)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div>
      <button
        type="button"
        onClick={() => input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault()
          setDrag(true)
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDrag(false)
          handle(e.dataTransfer.files?.[0])
        }}
        className={clsx(
          'group relative flex w-full flex-col items-center justify-center gap-3 overflow-hidden rounded-2xl border-2 border-dashed px-6 py-14 transition-colors',
          drag ? 'border-mind bg-mind/10' : 'border-line hover:border-line-strong hover:bg-surface-2/60',
        )}
      >
        <motion.div animate={busy ? { rotate: [0, 8, -8, 0] } : drag ? { y: -6, scale: 1.08 } : { y: 0, scale: 1 }} transition={busy ? { repeat: Infinity, duration: 0.8 } : { type: 'spring' }}>
          <FileSpreadsheet className={clsx('size-11', drag ? 'text-mind' : 'text-muted group-hover:text-text')} />
        </motion.div>
        <div className="text-center">
          <div className="text-[15px] font-bold">{busy ? `Reading ${busy}…` : drag ? 'Drop it' : 'Drop a file here, or click to choose one'}</div>
          <div className="mt-1 text-[13px] text-muted">CSV, TSV, Excel, Parquet or JSON. Encoding and delimiter are detected for you.</div>
        </div>
        {busy && <motion.div className="absolute inset-x-0 bottom-0 h-1 bg-mind" initial={{ scaleX: 0 }} animate={{ scaleX: 1 }} transition={{ duration: 2.5 }} style={{ originX: 0 }} />}
      </button>
      <input ref={input} type="file" hidden accept=".csv,.tsv,.txt,.xlsx,.xls,.parquet,.json" onChange={(e) => handle(e.target.files?.[0])} />
      {error && <p className="mt-3 text-sm text-bad">{error}</p>}
      <p className="mt-4 text-[12.5px] text-muted">Your file stays on this computer. A language model, if you enable one, only sees column statistics — never rows.</p>
    </div>
  )
}

function Samples({ onLoaded, onDatabase }: { onLoaded: (d: DatasetPayload) => void; onDatabase: () => void }) {
  const [samples, setSamples] = useState<{ id: string; title: string; description: string }[]>([])
  const [busy, setBusy] = useState<string | null>(null)
  useEffect(() => {
    api.samples().then(setSamples).catch(() => {})
  }, [])
  const load = async (id: string) => {
    setBusy(id)
    try {
      const r = await api.loadSample(id)
      if (r.database_url) {
        sessionStorage.setItem('dm-db-url', r.database_url)
        onDatabase()
      } else onLoaded(r)
    } finally {
      setBusy(null)
    }
  }
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {samples.map((s) => (
        <button key={s.id} onClick={() => load(s.id)} disabled={!!busy} className="card flex flex-col items-start gap-2 p-4 text-left transition-colors hover:border-line-strong hover:bg-surface-2/50">
          <div className="flex items-center gap-2">
            {s.id === 'retail_db' ? <Database className="size-4 text-info" /> : <FileSpreadsheet className="size-4 text-mind" />}
            <span className="font-bold">{s.title}</span>
          </div>
          <p className="text-[13px] text-muted">{s.description}</p>
          <span className="mt-1 text-[13px] font-semibold text-mind">{busy === s.id ? 'Loading…' : s.id === 'retail_db' ? 'Open in database connector' : 'Load this sample'}</span>
        </button>
      ))}
    </div>
  )
}

export function DatabasePanel({ onLoaded }: { onLoaded: (d: DatasetPayload) => void }) {
  const [url, setUrl] = useState(() => sessionStorage.getItem('dm-db-url') || '')
  const [tables, setTables] = useState<DBTable[] | null>(null)
  const [selected, setSelected] = useState<string[]>([])
  const [joins, setJoins] = useState<JoinSpec[]>([])
  const [mode, setMode] = useState<'tables' | 'sql'>('tables')
  const [sql, setSql] = useState('')
  const [preview, setPreview] = useState<{ sql: string; preview: Preview } | null>(null)
  const [limit, setLimit] = useState(100000)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const run = async <T,>(what: string, fn: () => Promise<T>) => {
    setBusy(what)
    setError(null)
    try {
      return await fn()
    } catch (e: any) {
      setError(e.message)
    } finally {
      setBusy(null)
    }
  }

  const connect = () =>
    run('connect', async () => {
      const r = await api.dbConnect(url)
      setTables(r.tables)
      setSelected(r.tables.slice(0, 1).map((t) => t.name))
      setJoins([])
      setPreview(null)
      sessionStorage.setItem('dm-db-url', url)
    })

  useEffect(() => {
    if (!tables || selected.length < 2) {
      setJoins([])
      return
    }
    api.dbJoins(url, selected).then((r) => setJoins(r.joins)).catch(() => setJoins([]))
  }, [selected, tables, url])

  const body = () =>
    mode === 'sql' ? { url, sql, limit } : selected.length > 1 ? { url, base: selected[0], joins, limit, name: `${selected[0]}_joined` } : { url, table: selected[0], limit }

  const unjoined = selected.slice(1).filter((t) => !joins.some((j) => j.left === t || j.right === t))
  const canQuery = mode === 'sql' ? sql.trim().length > 6 : selected.length > 0 && unjoined.length === 0

  return (
    <div className="space-y-4">
      <Field label="Connection URL" hint={<>e.g. <code className="font-mono">postgresql://user:pass@localhost:5432/shop</code>, <code className="font-mono">mysql+pymysql://…</code> or <code className="font-mono">sqlite:///path/file.db</code>. Credentials stay on this machine.</>}>
        <div className="flex gap-2">
          <input className="input font-mono text-[13px]" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="postgresql://user:password@host:5432/database" />
          <Button variant="primary" onClick={connect} loading={busy === 'connect'} disabled={!url.trim()} icon={<Link2 className="size-4" />}>
            Connect
          </Button>
        </div>
      </Field>

      {tables && (
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="space-y-4">
          <Tabs<'tables' | 'sql'> value={mode} onChange={setMode} tabs={[{ id: 'tables', label: 'Pick tables' }, { id: 'sql', label: 'Write SQL' }]} />
          {mode === 'tables' ? (
            <>
              <div className="grid gap-2 sm:grid-cols-2">
                {tables.map((t) => {
                  const on = selected.includes(t.name)
                  const idx = selected.indexOf(t.name)
                  return (
                    <button
                      key={t.name}
                      onClick={() => setSelected((s) => (on ? s.filter((x) => x !== t.name) : [...s, t.name]))}
                      className={clsx('flex items-start gap-3 rounded-xl border p-3 text-left transition-colors', on ? 'border-mind bg-mind/10' : 'border-line hover:border-line-strong')}
                    >
                      <Table2 className={clsx('mt-0.5 size-4', on ? 'text-mind' : 'text-muted')} />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 font-semibold">
                          {t.name}
                          {idx === 0 && selected.length > 1 && <Pill tone="mind">base</Pill>}
                        </div>
                        <div className="text-[12px] text-muted">
                          {t.rows?.toLocaleString() ?? '?'} rows · {t.columns.length} columns
                          {t.foreign_keys.length > 0 && ` · ${t.foreign_keys.length} foreign key${t.foreign_keys.length > 1 ? 's' : ''}`}
                        </div>
                      </div>
                    </button>
                  )
                })}
              </div>
              {selected.length > 1 && (
                <div className="rounded-xl border border-line p-3">
                  <div className="mb-2 text-[13px] font-semibold">Joins</div>
                  {joins.length === 0 && <p className="text-[13px] text-muted">No relationship found between the selected tables.</p>}
                  <div className="space-y-2">
                    {joins.map((j, i) => (
                      <div key={i} className="flex flex-wrap items-center gap-2 text-[13px]">
                        <code className="rounded bg-surface-2 px-2 py-1 font-mono">{j.left}.{j.left_on}</code>
                        <select className="input !w-auto !py-1" value={j.how} onChange={(e) => setJoins((js) => js.map((x, k) => (k === i ? { ...x, how: e.target.value } : x)))}>
                          <option value="left">left join</option>
                          <option value="inner">inner join</option>
                        </select>
                        <code className="rounded bg-surface-2 px-2 py-1 font-mono">{j.right}.{j.right_on}</code>
                        <Pill tone={j.confidence === 1 ? 'ok' : 'signal'}>{j.reason}</Pill>
                      </div>
                    ))}
                  </div>
                  {unjoined.length > 0 && <p className="mt-2 text-[12.5px] text-bad">No join path for: {unjoined.join(', ')}. Deselect it or use SQL.</p>}
                </div>
              )}
            </>
          ) : (
            <Field label="Read-only query" hint="Only a single SELECT is allowed; anything that writes is blocked.">
              <textarea className="input min-h-[120px] font-mono text-[13px]" value={sql} onChange={(e) => setSql(e.target.value)} placeholder="SELECT o.*, c.city FROM orders o JOIN customers c ON c.customer_id = o.customer_id" />
            </Field>
          )}
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Row limit">
              <input type="number" className="input !w-36" value={limit} min={100} max={500000} step={1000} onChange={(e) => setLimit(Number(e.target.value))} />
            </Field>
            <Button onClick={() => run('preview', async () => setPreview(await api.dbPreview(body())))} loading={busy === 'preview'} disabled={!canQuery} variant="outline">
              Preview
            </Button>
            <Button variant="primary" onClick={() => run('import', async () => onLoaded(await api.dbImport(body())))} loading={busy === 'import'} disabled={!canQuery}>
              Import as dataset
            </Button>
          </div>
          {preview && (
            <div className="space-y-2">
              <pre className="overflow-x-auto rounded-lg bg-surface-2 p-3 font-mono text-[12px] whitespace-pre-wrap text-muted">{preview.sql}</pre>
              <DataTable columns={preview.preview.columns} rows={preview.preview.rows} maxHeight={260} />
            </div>
          )}
        </motion.div>
      )}
      {error && <p className="text-sm text-bad">{error}</p>}
    </div>
  )
}
