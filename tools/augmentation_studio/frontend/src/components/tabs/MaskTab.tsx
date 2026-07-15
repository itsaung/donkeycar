import { useCallback, useEffect, useRef, useState } from 'react'
import { b64Url, type ApplyResult, type MaskData, type MaskRegion, type PreviewResult } from '../../api'
import ExportPanel from '../ExportPanel'
import PreviewCompare from '../PreviewCompare'

type Props = {
  masksPath: string
  onMasksPathChange: (path: string) => void
  maskData: MaskData
  onMaskDataChange: (data: MaskData) => void
  focusIndex: number | null
  preview: PreviewResult | null
  previewError: string | null
  snippet: string
  busy: boolean
  onLoad: () => Promise<void>
  onSave: () => Promise<void>
  onExport: () => Promise<void>
  onApply?: (myconfigPath: string) => Promise<ApplyResult>
  status: string | null
}

export default function MaskTab({
  masksPath,
  onMasksPathChange,
  maskData,
  onMaskDataChange,
  focusIndex,
  preview,
  previewError,
  snippet,
  busy,
  onLoad,
  onSave,
  onExport,
  onApply,
  status,
}: Props) {
  const [draftPath, setDraftPath] = useState(masksPath)
  const [drawing, setDrawing] = useState(false)
  const start = useRef<{ x: number; y: number } | null>(null)
  const imgRef = useRef<HTMLImageElement>(null)
  const [draftRect, setDraftRect] = useState<MaskRegion | null>(null)

  const key = focusIndex != null ? String(focusIndex) : null
  const regions: MaskRegion[] =
    key && maskData.by_index[key] ? maskData.by_index[key] : []

  useEffect(() => setDraftPath(masksPath), [masksPath])

  const commitRect = useCallback(
    (rect: Extract<MaskRegion, { type: 'rect' }>) => {
      if (!key || rect.w < 2 || rect.h < 2) return
      const next: MaskData = {
        ...maskData,
        by_index: {
          ...maskData.by_index,
          [key]: [...(maskData.by_index[key] || []), rect],
        },
      }
      onMaskDataChange(next)
    },
    [key, maskData, onMaskDataChange],
  )

  function toImageCoords(clientX: number, clientY: number) {
    const el = imgRef.current
    if (!el || !preview) return null
    const rect = el.getBoundingClientRect()
    const x = ((clientX - rect.left) / rect.width) * preview.width
    const y = ((clientY - rect.top) / rect.height) * preview.height
    return { x: Math.round(x), y: Math.round(y) }
  }

  function clearRegions() {
    if (!key) return
    const by_index = { ...maskData.by_index }
    delete by_index[key]
    onMaskDataChange({ ...maskData, by_index })
  }

  return (
    <div className="tab-layout">
      <div className="tab-main">
        <h2 className="section-label">
          Mask draw {focusIndex != null ? `(record #${focusIndex})` : '(select a frame)'}
        </h2>
        <p className="hint">
          Drag on the original to block out a rectangle. Regions are stored in a sidecar and
          applied via REGION_MASK at train time — originals are never overwritten.
        </p>
        {previewError && <p className="error">{previewError}</p>}
        {status && <p className="hint">{status}</p>}

        <div className="mask-draw-row">
          <div
            className="mask-canvas"
            onPointerDown={(e) => {
              if (!key) return
              const pt = toImageCoords(e.clientX, e.clientY)
              if (!pt) return
              drawing && e.currentTarget.setPointerCapture(e.pointerId)
              setDrawing(true)
              start.current = pt
              setDraftRect({ type: 'rect', x: pt.x, y: pt.y, w: 0, h: 0 })
            }}
            onPointerMove={(e) => {
              if (!drawing || !start.current) return
              const pt = toImageCoords(e.clientX, e.clientY)
              if (!pt) return
              const x = Math.min(start.current.x, pt.x)
              const y = Math.min(start.current.y, pt.y)
              const w = Math.abs(pt.x - start.current.x)
              const h = Math.abs(pt.y - start.current.y)
              setDraftRect({ type: 'rect', x, y, w, h })
            }}
            onPointerUp={() => {
              if (draftRect && draftRect.type === 'rect') commitRect(draftRect)
              setDrawing(false)
              start.current = null
              setDraftRect(null)
            }}
          >
            {preview?.original_b64 && (
              <>
                <img
                  ref={imgRef}
                  src={b64Url(preview.original_b64)}
                  alt="draw"
                  draggable={false}
                />
                <svg
                  className="roi-overlay"
                  viewBox={`0 0 ${preview.width} ${preview.height}`}
                  preserveAspectRatio="none"
                >
                  {regions.map((r, i) =>
                    r.type === 'rect' ? (
                      <rect
                        key={i}
                        x={r.x}
                        y={r.y}
                        width={r.w}
                        height={r.h}
                        fill="rgba(212,107,107,0.35)"
                        stroke="#d46b6b"
                        strokeWidth="2"
                      />
                    ) : null,
                  )}
                  {draftRect && draftRect.type === 'rect' && (
                    <rect
                      x={draftRect.x}
                      y={draftRect.y}
                      width={draftRect.w}
                      height={draftRect.h}
                      fill="rgba(91,159,212,0.25)"
                      stroke="#5b9fd4"
                      strokeWidth="2"
                    />
                  )}
                </svg>
              </>
            )}
          </div>
          <div>
            <h2 className="section-label">Result</h2>
            <PreviewCompare
              originalB64={preview?.original_b64 ?? null}
              augmentedB64={preview?.augmented_b64 ?? null}
            />
          </div>
        </div>
      </div>

      <aside className="tab-side panel">
        <h2>Mask sidecar</h2>
        <label>
          Path (outside tub)
          <input
            type="text"
            value={draftPath}
            onChange={(e) => setDraftPath(e.target.value)}
            onBlur={() => onMasksPathChange(draftPath.trim())}
          />
        </label>
        <div className="row" style={{ marginTop: '0.5rem' }}>
          <button type="button" onClick={() => void onLoad()}>
            Load
          </button>
          <button type="button" onClick={() => void onSave()}>
            Save
          </button>
          <button type="button" className="ghost" onClick={clearRegions} disabled={!key}>
            Clear frame
          </button>
        </div>
        <p className="hint">
          Regions on this frame: {regions.length}
          {maskData.default_preset ? ` · default preset: ${maskData.default_preset}` : ''}
        </p>
        <h2 className="section-label">Export</h2>
        <ExportPanel
          snippet={snippet}
          trainingProb={null}
          onExport={onExport}
          busy={busy}
          onApply={onApply}
        />
      </aside>
    </div>
  )
}
