import { useEffect, useRef, useState } from 'react'
import type { PlotSpec } from '../lib/api'

let plotlyPromise: Promise<any> | null = null
/** Plotly is large, so it loads on first use instead of with the app. */
const loadPlotly = () => (plotlyPromise ??= import('plotly.js-dist-min').then((m: any) => m.default ?? m))

const css = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim()

function themed(spec: PlotSpec, compact: boolean) {
  const text = css('--text')
  const muted = css('--muted')
  const grid = css('--line')
  const colorway = [css('--mind'), css('--ok'), css('--signal'), css('--info'), css('--bad'), '#d58cf0', '#7dd3fc', '#fca5a5']
  const layout = spec.layout || {}
  const axis = (a: any = {}) => ({
    gridcolor: grid,
    zerolinecolor: grid,
    linecolor: grid,
    tickfont: { color: muted, size: 11 },
    automargin: true,
    ...a,
    title: { ...(a.title || {}), font: { color: muted, size: 12 } },
  })
  const data = (spec.data || []).map((t: any, i: number) => {
    const c = colorway[i % colorway.length]
    const tr = { ...t }
    if (tr.type === 'bar' && !tr.marker) tr.marker = { color: c, line: { width: 0 } }
    if (tr.type === 'bar') tr.textfont = { color: muted, size: 11 }
    if ((tr.type === 'scatter' || tr.type === 'scattergl') && tr.mode?.includes('lines')) {
      tr.line = { color: tr.name === 'trend' ? muted : c, ...(tr.line || {}) }
      if (tr.fill) tr.fillcolor = c + '22'
    }
    if (tr.name === 'anomaly') tr.marker = { ...(tr.marker || {}), color: css('--bad') }
    if (tr.type === 'histogram' && !tr.marker) tr.marker = { color: c }
    if (tr.type === 'box') tr.marker = { color: c }
    if (tr.type === 'pie') tr.marker = { colors: colorway, line: { color: css('--surface'), width: 2 } }
    if (tr.type === 'pie') tr.textfont = { color: text }
    if (tr.type === 'heatmap') tr.textfont = { color: text, size: 10 }
    return tr
  })
  const multi = data.filter((t: any) => t.type !== 'pie' && t.name !== 'trend' && t.name !== 'anomaly').length > 1 && layout.showlegend !== false
  return {
    data,
    layout: {
      ...layout,
      title: compact ? undefined : layout.title,
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      font: { family: 'Plus Jakarta Sans, sans-serif', color: text, size: 12 },
      colorway,
      margin: { l: 48, r: 16, t: (compact ? 10 : 40) + (multi ? 28 : 0), b: 40, ...(layout.margin || {}) },
      xaxis: axis(layout.xaxis),
      yaxis: axis(layout.yaxis),
      showlegend: layout.showlegend ?? multi,
      legend: { orientation: 'h', x: 0, y: 1.02, xanchor: 'left', yanchor: 'bottom', font: { color: muted, size: 11 }, ...(layout.legend || {}) },
      hoverlabel: { bgcolor: css('--surface-2'), bordercolor: css('--line-strong'), font: { color: text } },
      bargap: layout.bargap ?? 0.28,
      autosize: true,
    },
  }
}

export function Plot({ spec, height = 300, compact = true }: { spec: PlotSpec; height?: number; compact?: boolean }) {
  const ref = useRef<HTMLDivElement>(null)
  const [Plotly, setPlotly] = useState<any>(null)
  useEffect(() => {
    let alive = true
    loadPlotly().then((p) => alive && setPlotly(() => p))
    return () => {
      alive = false
    }
  }, [])
  useEffect(() => {
    const el = ref.current
    if (!el || !Plotly) return
    const draw = () => {
      const t = themed(spec, compact)
      Plotly.react(el, t.data, t.layout, { displaylogo: false, responsive: true, modeBarButtonsToRemove: ['lasso2d', 'select2d', 'autoScale2d'] })
    }
    draw()
    const ro = new ResizeObserver(() => Plotly.Plots.resize(el))
    ro.observe(el)
    const mo = new MutationObserver(draw) // redraw when the theme changes
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => {
      ro.disconnect()
      mo.disconnect()
      Plotly.purge(el)
    }
  }, [spec, compact, Plotly])
  return <div ref={ref} style={{ height, width: '100%' }} className={Plotly ? undefined : 'skeleton'} />
}
