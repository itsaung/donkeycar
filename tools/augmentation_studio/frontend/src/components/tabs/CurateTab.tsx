import { useMemo, useState } from 'react'
import { b64Url, type ApplyResult, type TubImageMeta } from '../../api'
import ExportPanel from '../ExportPanel'

type Props = {
  images: TubImageMeta[]
  excluded: Set<number>
  onToggleExclude: (index: number) => void
  onExcludeVisible: () => void
  onKeepVisible: () => void
  excludesPath: string
  onExcludesPathChange: (path: string) => void
  onLoad: () => Promise<void>
  onSave: () => Promise<void>
  snippet: string
  busy: boolean
  onExport: () => Promise<void>
  onApply?: (myconfigPath: string) => Promise<ApplyResult>
  error: string | null
  status: string | null
}

export default function CurateTab({
  images,
  excluded,
  onToggleExclude,
  onExcludeVisible,
  onKeepVisible,
  excludesPath,
  onExcludesPathChange,
  onLoad,
  onSave,
  snippet,
  busy,
  onExport,
  onApply,
  error,
  status,
}: Props) {
  const [draft, setDraft] = useState(excludesPath)
  const counts = useMemo(() => {
    const ex = images.filter((i) => excluded.has(i.index)).length
    return { excluded: excluded.size, pageExcluded: ex, page: images.length }
  }, [images, excluded])

  return (
    <div className="tab-layout">
      <div className="tab-main">
        <h2 className="section-label">Culling grid</h2>
        <p className="hint">
          Click a frame to toggle exclude. Uses TRAIN_FILTER + external sidecar — never
          Tub.delete_records (that rewrites manifest.json). Tub images/catalogs stay untouched.
        </p>
        {error && <p className="error">{error}</p>}
        {status && <p className="hint">{status}</p>}
        <p className="hint">
          Excluded total: {counts.excluded} · this page: {counts.pageExcluded}/{counts.page}
        </p>
        <div className="thumb-grid curate-grid">
          {images.map((img) => {
            const isEx = excluded.has(img.index)
            return (
              <button
                key={img.index}
                type="button"
                className={`thumb${isEx ? ' excluded' : ' keep'}`}
                onClick={() => onToggleExclude(img.index)}
                title={isEx ? 'Excluded — click to keep' : 'Keep — click to exclude'}
              >
                {img.thumb_b64 ? (
                  <img src={b64Url(img.thumb_b64)} alt={`#${img.index}`} />
                ) : null}
                <span className="idx">
                  {img.index} {isEx ? '✕' : '✓'}
                </span>
              </button>
            )
          })}
        </div>
      </div>

      <aside className="tab-side panel">
        <h2>Curation sidecar</h2>
        <label>
          Sidecar path (outside tub)
          <input
            type="text"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={() => onExcludesPathChange(draft.trim())}
          />
        </label>
        <div className="row" style={{ marginTop: '0.5rem' }}>
          <button type="button" onClick={() => void onLoad()}>
            Load
          </button>
          <button type="button" onClick={() => void onSave()}>
            Save
          </button>
        </div>
        <div className="row" style={{ marginTop: '0.5rem' }}>
          <button type="button" className="ghost" onClick={onExcludeVisible}>
            Exclude page
          </button>
          <button type="button" className="ghost" onClick={onKeepVisible}>
            Keep page
          </button>
        </div>
        <h2 className="section-label" style={{ marginTop: '1rem' }}>
          Export TRAIN_FILTER
        </h2>
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
