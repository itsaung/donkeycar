import { useMemo } from 'react'
import ExportPanel from '../ExportPanel'
import PreviewCompare from '../PreviewCompare'
import type { ApplyResult, PreviewResult, RoiState, TransformSpec } from '../../api'

type Props = {
  transformCatalog: TransformSpec[]
  roiDefaults: RoiState
  transformations: string[]
  postTransformations: string[]
  roi: RoiState
  onTransformationsChange: (v: string[]) => void
  onPostTransformationsChange: (v: string[]) => void
  onRoiChange: (roi: RoiState) => void
  preview: PreviewResult | null
  previewError: string | null
  snippet: string
  busyExport: boolean
  onExport: () => Promise<void>
  onApply?: (myconfigPath: string) => Promise<ApplyResult>
  imageWidth: number
  imageHeight: number
  allowPostTransformations?: boolean
}

const CROP_KEYS = ['ROI_CROP_LEFT', 'ROI_CROP_TOP', 'ROI_CROP_RIGHT', 'ROI_CROP_BOTTOM']
const TRAP_KEYS = [
  'ROI_TRAPEZE_UL',
  'ROI_TRAPEZE_UR',
  'ROI_TRAPEZE_LL',
  'ROI_TRAPEZE_LR',
  'ROI_TRAPEZE_MIN_Y',
  'ROI_TRAPEZE_MAX_Y',
]

function toggleName(list: string[], name: string, on: boolean): string[] {
  if (on) return list.includes(name) ? list : [...list, name]
  return list.filter((n) => n !== name)
}

export default function CropTab({
  transformations,
  postTransformations,
  roi,
  onTransformationsChange,
  onPostTransformationsChange,
  onRoiChange,
  preview,
  previewError,
  snippet,
  busyExport,
  onExport,
  onApply,
  imageWidth,
  imageHeight,
  allowPostTransformations = true,
}: Props) {
  const w = imageWidth || 160
  const h = imageHeight || 120

  const cropOn = transformations.includes('CROP') || postTransformations.includes('CROP')
  const trapOn =
    transformations.includes('TRAPEZE') ||
    transformations.includes('TRAPEZE_EDGE') ||
    postTransformations.includes('TRAPEZE') ||
    postTransformations.includes('TRAPEZE_EDGE')

  const trapMode = useMemo(() => {
    if (transformations.includes('TRAPEZE_EDGE') || postTransformations.includes('TRAPEZE_EDGE')) {
      return 'TRAPEZE_EDGE'
    }
    return 'TRAPEZE'
  }, [transformations, postTransformations])

  function setCrop(on: boolean, post: boolean) {
    post = allowPostTransformations && post
    let t = toggleName(transformations, 'CROP', on && !post)
    let p = toggleName(postTransformations, 'CROP', on && post)
    if (on && post) t = toggleName(t, 'CROP', false)
    if (on && !post) p = toggleName(p, 'CROP', false)
    onTransformationsChange(t)
    onPostTransformationsChange(p)
  }

  function setTrap(on: boolean, mode: 'TRAPEZE' | 'TRAPEZE_EDGE', post: boolean) {
    post = allowPostTransformations && post
    let t = transformations.filter((n) => n !== 'TRAPEZE' && n !== 'TRAPEZE_EDGE')
    let p = postTransformations.filter((n) => n !== 'TRAPEZE' && n !== 'TRAPEZE_EDGE')
    if (on) {
      if (post) p = [...p, mode]
      else t = [...t, mode]
    }
    onTransformationsChange(t)
    onPostTransformationsChange(p)
  }

  function setRoi(key: string, value: number) {
    onRoiChange({ ...roi, [key]: value })
  }

  const left = roi.ROI_CROP_LEFT ?? 0
  const top = roi.ROI_CROP_TOP ?? 0
  const right = roi.ROI_CROP_RIGHT ?? 0
  const bottom = roi.ROI_CROP_BOTTOM ?? 0

  return (
    <div className="tab-layout">
      <div className="tab-main">
        <h2 className="section-label">Preview (real ImageTransformations)</h2>
        {previewError && <p className="error">{previewError}</p>}
        <div className="roi-preview-wrap">
          <PreviewCompare
            originalB64={preview?.original_b64 ?? null}
            augmentedB64={preview?.augmented_b64 ?? null}
          />
          {cropOn && preview && (
            <svg className="roi-overlay" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
              <rect
                x={left}
                y={top}
                width={Math.max(0, w - left - right)}
                height={Math.max(0, h - top - bottom)}
                fill="none"
                stroke="#5b9fd4"
                strokeWidth="2"
                strokeDasharray="4 3"
              />
            </svg>
          )}
        </div>
        <p className="hint">
          CROP/TRAPEZE zero out pixels outside the keep-region — they do not resize or rewrite
          tub JPEGs.
        </p>
        <h2 className="section-label">Export</h2>
        <ExportPanel
          snippet={snippet}
          trainingProb={null}
          onExport={onExport}
          busy={busyExport}
          onApply={onApply}
        />
      </div>

      <aside className="tab-side panel">
        <h2>Crop / ROI</h2>

        <div className="aug-card">
          <header>
            <strong>CROP</strong>
            <label className="inline">
              <input
                type="checkbox"
                checked={cropOn}
                onChange={(e) =>
                  setCrop(e.target.checked, postTransformations.includes('CROP'))
                }
              />{' '}
              on
            </label>
          </header>
          {cropOn && (
            <>
              {allowPostTransformations && (
                <label className="inline">
                  <input
                    type="checkbox"
                    checked={postTransformations.includes('CROP')}
                    onChange={(e) => setCrop(true, e.target.checked)}
                  />{' '}
                  POST_TRANSFORMATIONS
                </label>
              )}
              {CROP_KEYS.map((key) => (
                <label key={key}>
                  {key.replace('ROI_CROP_', '')}
                  <div className="param-row">
                    <input
                      type="range"
                      min={0}
                      max={key.includes('TOP') || key.includes('BOTTOM') ? h : w}
                      value={roi[key] ?? 0}
                      onChange={(e) => setRoi(key, Number(e.target.value))}
                    />
                    <input
                      type="number"
                      value={roi[key] ?? 0}
                      onChange={(e) => setRoi(key, Number(e.target.value))}
                    />
                  </div>
                </label>
              ))}
            </>
          )}
        </div>

        <div className="aug-card">
          <header>
            <strong>TRAPEZE</strong>
            <label className="inline">
              <input
                type="checkbox"
                checked={trapOn}
                onChange={(e) => setTrap(e.target.checked, trapMode, false)}
              />{' '}
              on
            </label>
          </header>
          {trapOn && (
            <>
              <div className="row">
                <button
                  type="button"
                  className={trapMode === 'TRAPEZE' ? 'active' : 'ghost'}
                  onClick={() => setTrap(true, 'TRAPEZE', postTransformations.includes(trapMode))}
                >
                  Absolute
                </button>
                <button
                  type="button"
                  className={trapMode === 'TRAPEZE_EDGE' ? 'active' : 'ghost'}
                  onClick={() =>
                    setTrap(true, 'TRAPEZE_EDGE', postTransformations.includes(trapMode))
                  }
                >
                  Edge
                </button>
              </div>
              {allowPostTransformations && (
                <label className="inline">
                  <input
                    type="checkbox"
                    checked={
                      postTransformations.includes('TRAPEZE') ||
                      postTransformations.includes('TRAPEZE_EDGE')
                    }
                    onChange={(e) => setTrap(true, trapMode, e.target.checked)}
                  />{' '}
                  POST_TRANSFORMATIONS
                </label>
              )}
              {TRAP_KEYS.map((key) => (
                <label key={key}>
                  {key.replace('ROI_TRAPEZE_', '')}
                  <div className="param-row">
                    <input
                      type="range"
                      min={0}
                      max={key.includes('Y') ? h : w}
                      value={roi[key] ?? 0}
                      onChange={(e) => setRoi(key, Number(e.target.value))}
                    />
                    <input
                      type="number"
                      value={roi[key] ?? 0}
                      onChange={(e) => setRoi(key, Number(e.target.value))}
                    />
                  </div>
                </label>
              ))}
            </>
          )}
        </div>
      </aside>
    </div>
  )
}
