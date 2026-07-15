import { b64Url, type ApplyResult, type CvParams, type CvPreviewResult } from '../../api'
import ExportPanel from '../ExportPanel'

type Props = {
  preview: CvPreviewResult | null
  error: string | null
  cvPreprocess: string[]
  debugTransforms: string[]
  cvParams: CvParams
  onDebugTransformsChange: (value: string[]) => void
  onCvParamsChange: (value: CvParams) => void
  snippet: string
  busy: boolean
  onExport: () => Promise<void>
  onApply: (myconfigPath: string) => Promise<ApplyResult>
}

const NUMBER_PARAMS: Array<{
  key: keyof CvParams
  label: string
  min: number
  max: number
  step: number
}> = [
  { key: 'BLUR_KERNEL', label: 'Blur kernel', min: 1, max: 31, step: 2 },
  { key: 'CANNY_LOW_THRESHOLD', label: 'Canny low', min: 0, max: 255, step: 1 },
  { key: 'CANNY_HIGH_THRESHOLD', label: 'Canny high', min: 0, max: 255, step: 1 },
  { key: 'CANNY_APERTURE', label: 'Canny aperture', min: 3, max: 7, step: 2 },
]

function toggle(list: string[], name: string, enabled: boolean): string[] {
  const ordered = ['RGB2GRAY', 'BLUR', 'CANNY']
  const selected = new Set(list)
  if (enabled) selected.add(name)
  else selected.delete(name)
  selected.add('RGB2GRAY')
  return ordered.filter((item) => selected.has(item))
}

export default function DebugTab({
  preview,
  error,
  cvPreprocess,
  debugTransforms,
  cvParams,
  onDebugTransformsChange,
  onCvParamsChange,
  snippet,
  busy,
  onExport,
  onApply,
}: Props) {
  return (
    <div className="tab-layout">
      <div className="tab-main">
        <h2 className="section-label">CV pipeline</h2>
        {error && <p className="error">{error}</p>}
        {preview ? (
          <div className="debug-preview-grid">
            {[
              ['Original', preview.original_b64],
              ['Preprocessed', preview.preprocessed_b64],
              ['Edges', preview.edges_b64],
            ].map(([label, image]) => (
              <figure key={label}>
                <img src={b64Url(image)} alt={label} />
                <figcaption>{label}</figcaption>
              </figure>
            ))}
          </div>
        ) : (
          <p className="hint">Select one or more tub frames to preview the CV pipeline.</p>
        )}
        <p className="hint">
          Preprocess: {cvPreprocess.join(' → ') || 'none'} · Debug:{' '}
          {debugTransforms.join(' → ') || 'none'}
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
        <h2>Debug / Edges</h2>
        <div className="aug-card">
          <strong>Pipeline</strong>
          <label className="inline">
            <input type="checkbox" checked disabled /> RGB2GRAY
          </label>
          {['BLUR', 'CANNY'].map((name) => (
            <label className="inline" key={name}>
              <input
                type="checkbox"
                checked={debugTransforms.includes(name)}
                onChange={(event) =>
                  onDebugTransformsChange(toggle(debugTransforms, name, event.target.checked))
                }
              />{' '}
              {name}
            </label>
          ))}
        </div>

        <div className="aug-card">
          <strong>Parameters</strong>
          {NUMBER_PARAMS.map(({ key, label, min, max, step }) => (
            <label key={key}>
              {label}
              <div className="param-row">
                <input
                  type="range"
                  min={min}
                  max={max}
                  step={step}
                  value={Number(cvParams[key])}
                  onChange={(event) =>
                    onCvParamsChange({ ...cvParams, [key]: Number(event.target.value) })
                  }
                />
                <input
                  type="number"
                  min={min}
                  max={max}
                  step={step}
                  value={Number(cvParams[key])}
                  onChange={(event) =>
                    onCvParamsChange({ ...cvParams, [key]: Number(event.target.value) })
                  }
                />
              </div>
            </label>
          ))}
          <label className="inline">
            <input
              type="checkbox"
              checked={cvParams.BLUR_GAUSSIAN}
              onChange={(event) =>
                onCvParamsChange({ ...cvParams, BLUR_GAUSSIAN: event.target.checked })
              }
            />{' '}
            Gaussian blur
          </label>
          <label className="inline">
            <input
              type="checkbox"
              checked={cvParams.CV_SHOW_DEBUG_PIPELINE}
              onChange={(event) =>
                onCvParamsChange({
                  ...cvParams,
                  CV_SHOW_DEBUG_PIPELINE: event.target.checked,
                })
              }
            />{' '}
            Show debug pipeline on car
          </label>
        </div>
      </aside>
    </div>
  )
}
