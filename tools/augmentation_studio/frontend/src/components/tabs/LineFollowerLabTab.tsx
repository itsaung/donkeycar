import {
  b64Url,
  type ApplyResult,
  type LineFollowerParams,
  type LineFollowerPreviewResult,
} from '../../api'
import ExportPanel from '../ExportPanel'

type Props = {
  preview: LineFollowerPreviewResult | null
  error: string | null
  cvPreprocess: string[]
  lineFollower: LineFollowerParams
  onLineFollowerChange: (value: LineFollowerParams) => void
  snippet: string
  busy: boolean
  onExport: () => Promise<void>
  onApply: (myconfigPath: string) => Promise<ApplyResult>
}

function setHsv(
  params: LineFollowerParams,
  key: 'COLOR_THRESHOLD_LOW' | 'COLOR_THRESHOLD_HIGH',
  channel: 0 | 1 | 2,
  value: number,
): LineFollowerParams {
  const next: [number, number, number] = [...params[key]]
  next[channel] = value
  return { ...params, [key]: next }
}

function NumberRow({
  label,
  value,
  min,
  max,
  step,
  onChange,
}: {
  label: string
  value: number
  min: number
  max: number
  step: number
  onChange: (value: number) => void
}) {
  return (
    <label>
      {label}
      <div className="param-row">
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(event) => onChange(Number(event.target.value))}
        />
        <input
          type="number"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(event) => onChange(Number(event.target.value))}
        />
      </div>
    </label>
  )
}

export default function LineFollowerLabTab({
  preview,
  error,
  cvPreprocess,
  lineFollower,
  onLineFollowerChange,
  snippet,
  busy,
  onExport,
  onApply,
}: Props) {
  const targetPixel =
    lineFollower.TARGET_PIXEL === null ? '' : String(lineFollower.TARGET_PIXEL)

  return (
    <div className="tab-layout">
      <div className="tab-main">
        <h2 className="section-label">LineFollower lab</h2>
        {error && <p className="error">{error}</p>}
        {preview ? (
          <>
            <div className="debug-preview-grid">
              {[
                ['Original', preview.original_b64],
                ['Preprocessed', preview.preprocessed_b64],
                ['Overlay', preview.overlay_b64],
              ].map(([label, image]) => (
                <figure key={label}>
                  <img src={b64Url(image)} alt={label} />
                  <figcaption>{label}</figcaption>
                </figure>
              ))}
            </div>
            <p className="hint metrics-strip">
              max yellow: {preview.max_yellow} · confidence:{' '}
              {preview.confidence.toFixed(2)} · steering:{' '}
              {preview.steering.toFixed(3)} · throttle:{' '}
              {preview.throttle.toFixed(3)} · target: {preview.target_pixel} ·{' '}
              {preview.line_detected ? 'line detected' : 'no line'}
            </p>
          </>
        ) : (
          <p className="hint">
            Select one or more tub frames to preview LineFollower detection and
            steering.
          </p>
        )}
        <p className="hint">
          Preprocess: {cvPreprocess.join(' → ') || 'none'} (set in Crop / ROI)
        </p>
        <h2 className="section-label">Export</h2>
        <ExportPanel
          snippet={snippet}
          trainingProb={null}
          onExport={onExport}
          busy={busy}
          onApply={onApply}
        />
      </div>

      <aside className="tab-side panel">
        <h2>Line Follow</h2>
        <div className="aug-card">
          <strong>Detection</strong>
          <NumberRow
            label="Scan Y"
            value={lineFollower.SCAN_Y}
            min={0}
            max={240}
            step={1}
            onChange={(value) =>
              onLineFollowerChange({ ...lineFollower, SCAN_Y: value })
            }
          />
          <NumberRow
            label="Scan height"
            value={lineFollower.SCAN_HEIGHT}
            min={1}
            max={80}
            step={1}
            onChange={(value) =>
              onLineFollowerChange({ ...lineFollower, SCAN_HEIGHT: value })
            }
          />
          <NumberRow
            label="HSV low H"
            value={lineFollower.COLOR_THRESHOLD_LOW[0]}
            min={0}
            max={179}
            step={1}
            onChange={(value) =>
              onLineFollowerChange(setHsv(lineFollower, 'COLOR_THRESHOLD_LOW', 0, value))
            }
          />
          <NumberRow
            label="HSV low S"
            value={lineFollower.COLOR_THRESHOLD_LOW[1]}
            min={0}
            max={255}
            step={1}
            onChange={(value) =>
              onLineFollowerChange(setHsv(lineFollower, 'COLOR_THRESHOLD_LOW', 1, value))
            }
          />
          <NumberRow
            label="HSV low V"
            value={lineFollower.COLOR_THRESHOLD_LOW[2]}
            min={0}
            max={255}
            step={1}
            onChange={(value) =>
              onLineFollowerChange(setHsv(lineFollower, 'COLOR_THRESHOLD_LOW', 2, value))
            }
          />
          <NumberRow
            label="HSV high H"
            value={lineFollower.COLOR_THRESHOLD_HIGH[0]}
            min={0}
            max={179}
            step={1}
            onChange={(value) =>
              onLineFollowerChange(setHsv(lineFollower, 'COLOR_THRESHOLD_HIGH', 0, value))
            }
          />
          <NumberRow
            label="HSV high S"
            value={lineFollower.COLOR_THRESHOLD_HIGH[1]}
            min={0}
            max={255}
            step={1}
            onChange={(value) =>
              onLineFollowerChange(setHsv(lineFollower, 'COLOR_THRESHOLD_HIGH', 1, value))
            }
          />
          <NumberRow
            label="HSV high V"
            value={lineFollower.COLOR_THRESHOLD_HIGH[2]}
            min={0}
            max={255}
            step={1}
            onChange={(value) =>
              onLineFollowerChange(setHsv(lineFollower, 'COLOR_THRESHOLD_HIGH', 2, value))
            }
          />
          <NumberRow
            label="Confidence threshold"
            value={lineFollower.CONFIDENCE_THRESHOLD}
            min={0}
            max={5000}
            step={0.0005}
            onChange={(value) =>
              onLineFollowerChange({
                ...lineFollower,
                CONFIDENCE_THRESHOLD: value,
              })
            }
          />
          <label>
            Target pixel
            <div className="param-row">
              <input
                type="number"
                min={0}
                max={320}
                step={1}
                placeholder="auto → width/2"
                value={targetPixel}
                onChange={(event) => {
                  const raw = event.target.value.trim()
                  onLineFollowerChange({
                    ...lineFollower,
                    TARGET_PIXEL: raw === '' ? null : Number(raw),
                  })
                }}
              />
            </div>
          </label>
          <NumberRow
            label="Target threshold"
            value={lineFollower.TARGET_THRESHOLD}
            min={0}
            max={80}
            step={1}
            onChange={(value) =>
              onLineFollowerChange({ ...lineFollower, TARGET_THRESHOLD: value })
            }
          />
        </div>

        <div className="aug-card">
          <strong>Control</strong>
          <NumberRow
            label="PID P"
            value={lineFollower.PID_P}
            min={-0.2}
            max={0.2}
            step={0.001}
            onChange={(value) =>
              onLineFollowerChange({ ...lineFollower, PID_P: value })
            }
          />
          <NumberRow
            label="PID I"
            value={lineFollower.PID_I}
            min={-0.05}
            max={0.05}
            step={0.0001}
            onChange={(value) =>
              onLineFollowerChange({ ...lineFollower, PID_I: value })
            }
          />
          <NumberRow
            label="PID D"
            value={lineFollower.PID_D}
            min={-0.05}
            max={0.05}
            step={0.00005}
            onChange={(value) =>
              onLineFollowerChange({ ...lineFollower, PID_D: value })
            }
          />
          <NumberRow
            label="Throttle min"
            value={lineFollower.THROTTLE_MIN}
            min={0}
            max={1}
            step={0.01}
            onChange={(value) =>
              onLineFollowerChange({
                ...lineFollower,
                THROTTLE_MIN: value,
                THROTTLE_INITIAL: value,
              })
            }
          />
          <NumberRow
            label="Throttle max"
            value={lineFollower.THROTTLE_MAX}
            min={0}
            max={1}
            step={0.01}
            onChange={(value) =>
              onLineFollowerChange({ ...lineFollower, THROTTLE_MAX: value })
            }
          />
          <NumberRow
            label="Throttle step"
            value={lineFollower.THROTTLE_STEP}
            min={0}
            max={0.5}
            step={0.01}
            onChange={(value) =>
              onLineFollowerChange({ ...lineFollower, THROTTLE_STEP: value })
            }
          />
        </div>
      </aside>
    </div>
  )
}
