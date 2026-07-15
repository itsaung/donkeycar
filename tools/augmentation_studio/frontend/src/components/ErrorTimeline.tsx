import { useMemo } from 'react'
import type { ReplayRecord } from '../api'

type Props = {
  records: ReplayRecord[]
  current: number
  onSeek: (index: number) => void
}

const WIDTH = 1000
const HEIGHT = 120
const PAD = 10

export default function ErrorTimeline({ records, current, onSeek }: Props) {
  const errors = useMemo(
    () => records.map((record) => Math.abs(record.actual_angle - record.pred_angle)),
    [records],
  )
  const worst = useMemo(
    () =>
      errors
        .map((error, index) => ({ error, index }))
        .sort((a, b) => b.error - a.error)
        .slice(0, Math.min(5, errors.length)),
    [errors],
  )
  const maxError = Math.max(...errors, 0.001)
  const xFor = (index: number) =>
    records.length <= 1 ? WIDTH / 2 : PAD + (index / (records.length - 1)) * (WIDTH - PAD * 2)
  const yFor = (error: number) => HEIGHT - PAD - (error / maxError) * (HEIGHT - PAD * 2)
  const points = errors.map((error, index) => `${xFor(index)},${yFor(error)}`).join(' ')

  function seekFromClientX(clientX: number, left: number, width: number) {
    const ratio = Math.max(0, Math.min(1, (clientX - left) / width))
    onSeek(Math.round(ratio * Math.max(0, records.length - 1)))
  }

  if (!records.length) return null

  return (
    <section className="error-timeline-panel" aria-label="Absolute steering error timeline">
      <div className="timeline-heading">
        <span>|actual − predicted| angle error</span>
        <span>max {maxError.toFixed(3)}</span>
      </div>
      <svg
        className="error-timeline"
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        preserveAspectRatio="none"
        role="slider"
        tabIndex={0}
        aria-valuemin={0}
        aria-valuemax={records.length - 1}
        aria-valuenow={current}
        onClick={(event) => {
          const bounds = event.currentTarget.getBoundingClientRect()
          seekFromClientX(event.clientX, bounds.left, bounds.width)
        }}
        onKeyDown={(event) => {
          if (event.key === 'ArrowLeft') {
            event.preventDefault()
            onSeek(Math.max(0, current - 1))
          } else if (event.key === 'ArrowRight') {
            event.preventDefault()
            onSeek(Math.min(records.length - 1, current + 1))
          }
        }}
      >
        <line className="timeline-baseline" x1={PAD} y1={HEIGHT - PAD} x2={WIDTH - PAD} y2={HEIGHT - PAD} />
        <polyline className="timeline-line" points={points} />
        <line
          className="timeline-current"
          x1={xFor(current)}
          y1={PAD}
          x2={xFor(current)}
          y2={HEIGHT - PAD}
        />
        {worst.map(({ error, index }, rank) => (
          <circle
            key={index}
            className="timeline-worst"
            cx={xFor(index)}
            cy={yFor(error)}
            r={rank === 0 ? 7 : 5}
            onClick={(event) => {
              event.stopPropagation()
              onSeek(index)
            }}
          >
            <title>
              #{records[index].frame_id}: error {error.toFixed(3)}
            </title>
          </circle>
        ))}
      </svg>
      <div className="worst-jumps">
        <span>Worst:</span>
        {worst.map(({ error, index }) => (
          <button key={index} type="button" className="ghost" onClick={() => onSeek(index)}>
            #{records[index].frame_id} ({error.toFixed(3)})
          </button>
        ))}
      </div>
    </section>
  )
}
