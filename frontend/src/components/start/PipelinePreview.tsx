import { motion } from 'framer-motion'

/**
 * A small looping picture of what happens after you press Run: blocks light up
 * in turn, a pulse travels along the edges, and the agent stops once to ask.
 */
const BLOCKS = [
  { id: 'Profile', x: 20, y: 34 },
  { id: 'Plan', x: 170, y: 34 },
  { id: 'Validate', x: 320, y: 34 },
  { id: 'Execute', x: 320, y: 154 },
  { id: 'Verify', x: 170, y: 154 },
  { id: 'Insights', x: 20, y: 154 },
]
const BW = 120
const BH = 46
const CYCLE = 9
const step = (i: number) => (0.4 + i * 1.15) / CYCLE // when block i starts working

const IDLE = '#34406a'
const WORK = '#ffb547'
const DONE = '#3ccfae'
const ASK = '#9b8cff'

export function PipelinePreview() {
  const path = `M ${20 + BW / 2} ${34 + BH / 2} H ${320 + BW / 2} V ${154 + BH / 2} H ${20 + BW / 2}`
  return (
    <div className="relative mx-auto w-full max-w-[470px]" aria-hidden>
      <svg viewBox="0 0 460 300" className="w-full overflow-visible">
        <path d={path} fill="none" stroke="var(--line-strong)" strokeWidth="1.5" strokeDasharray="4 5" />
        <motion.path
          d={path}
          fill="none"
          stroke={DONE}
          strokeWidth="2"
          initial={{ pathLength: 0 }}
          animate={{ pathLength: [0, 0, 1, 1, 0] }}
          transition={{ duration: CYCLE, times: [0, 0.04, 0.82, 0.96, 1], repeat: Infinity, ease: 'linear' }}
        />
        <circle r="5" fill={WORK}>
          <animateMotion dur={`${CYCLE * 0.78}s`} begin="0.4s" repeatCount="indefinite" path={path} keyPoints="0;1" keyTimes="0;1" calcMode="linear" />
        </circle>
        {BLOCKS.map((b, i) => {
          const s = step(i)
          const isAsk = b.id === 'Validate'
          return (
            <g key={b.id}>
              <motion.rect
                x={b.x}
                y={b.y}
                width={BW}
                height={BH}
                rx="13"
                fill="var(--surface)"
                strokeWidth="1.6"
                animate={{ stroke: isAsk ? [IDLE, IDLE, WORK, ASK, ASK, DONE, DONE, IDLE] : [IDLE, IDLE, WORK, DONE, DONE, IDLE] }}
                transition={{
                  duration: CYCLE,
                  repeat: Infinity,
                  times: isAsk ? [0, s, s + 0.04, s + 0.08, s + 0.24, s + 0.27, 0.95, 1] : [0, s, s + 0.04, s + 0.12, 0.95, 1],
                }}
              />
              <motion.circle
                cx={b.x + BW - 16}
                cy={b.y + BH / 2}
                r="5"
                animate={{ fill: isAsk ? [IDLE, IDLE, WORK, ASK, ASK, DONE, DONE, IDLE] : [IDLE, IDLE, WORK, DONE, DONE, IDLE] }}
                transition={{
                  duration: CYCLE,
                  repeat: Infinity,
                  times: isAsk ? [0, s, s + 0.04, s + 0.08, s + 0.24, s + 0.27, 0.95, 1] : [0, s, s + 0.04, s + 0.12, 0.95, 1],
                }}
              />
              <text x={b.x + 16} y={b.y + BH / 2 + 4.5} fontSize="13" fontWeight="700" fill="var(--text)">
                {b.id}
              </text>
            </g>
          )
        })}
      </svg>

      {/* The one moment the agent asks */}
      <motion.div
        className="absolute right-0 bottom-0 left-[16%] rounded-2xl border border-mind/50 bg-surface p-3 shadow-[0_20px_50px_-20px_rgb(0_0_0/0.6)]"
        animate={{ opacity: [0, 0, 1, 1, 0, 0], y: [10, 10, 0, 0, 6, 6] }}
        transition={{ duration: CYCLE, repeat: Infinity, times: [0, step(2) + 0.06, step(2) + 0.09, step(2) + 0.23, step(2) + 0.26, 1] }}
      >
        <div className="flex items-center gap-2 text-[12px] font-bold">
          <span className="grid size-5 place-items-center rounded-md bg-mind text-[11px] text-white">?</span>
          Is refund_issued known before a customer churns?
        </div>
        <div className="mt-2 grid grid-cols-3 gap-1.5 text-[11.5px]">
          <span className="rounded-lg border border-mind bg-mind/15 px-2 py-1 font-semibold text-mind">1 · Drop it</span>
          <span className="rounded-lg border border-line px-2 py-1 text-muted">2 · Keep it</span>
          <span className="rounded-lg border border-line px-2 py-1 text-muted">Other…</span>
        </div>
      </motion.div>
    </div>
  )
}
