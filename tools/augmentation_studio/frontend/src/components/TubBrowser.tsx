import { useEffect, useState } from 'react'
import { b64Url, type TubImageMeta } from '../api'

type Props = {
  path: string
  total: number | null
  images: TubImageMeta[]
  selected: number[]
  offset: number
  limit: number
  loading: boolean
  error: string | null
  onOpen: (path: string) => void
  onPage: (offset: number) => void
  onToggle: (index: number) => void
  onSelectAllVisible: () => void
  onClearSelection: () => void
  canEvaluate: boolean
  evaluateHint: string
  onEvaluate: () => void
}

export default function TubBrowser({
  path,
  total,
  images,
  selected,
  offset,
  limit,
  loading,
  error,
  onOpen,
  onPage,
  onToggle,
  onSelectAllVisible,
  onClearSelection,
  canEvaluate,
  evaluateHint,
  onEvaluate,
}: Props) {
  const [draft, setDraft] = useState(path)

  useEffect(() => {
    setDraft(path)
  }, [path])

  return (
    <section className="panel">
      <h2>Tub</h2>
      <div className="row">
        <input
          type="text"
          value={draft}
          placeholder="/path/to/tub"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              onOpen(draft.trim())
            }
          }}
        />
        <button
          type="button"
          disabled={loading || !draft.trim()}
          onClick={() => onOpen(draft.trim())}
        >
          Open
        </button>
      </div>
      {total != null && (
        <p className="hint">
          {total} records · selected {selected.length}
        </p>
      )}
      {error && <p className="error">{error}</p>}

      <div className="row" style={{ marginTop: '0.5rem' }}>
        <button type="button" className="ghost" onClick={onSelectAllVisible} disabled={!images.length}>
          Select page
        </button>
        <button type="button" className="ghost" onClick={onClearSelection} disabled={!selected.length}>
          Clear
        </button>
      </div>
      <button
        type="button"
        className="evaluate-tub"
        disabled={!canEvaluate}
        title={evaluateHint}
        onClick={onEvaluate}
      >
        Evaluate this tub
      </button>
      {!canEvaluate && total != null && <p className="hint">{evaluateHint}</p>}

      <div className="pager">
        <button
          type="button"
          className="ghost"
          disabled={offset <= 0 || loading}
          onClick={() => onPage(Math.max(0, offset - limit))}
        >
          Prev
        </button>
        <span>
          {total != null ? `${offset + 1}–${Math.min(offset + limit, total)} / ${total}` : '—'}
        </span>
        <button
          type="button"
          className="ghost"
          disabled={total == null || offset + limit >= total || loading}
          onClick={() => onPage(offset + limit)}
        >
          Next
        </button>
      </div>

      <div className="thumb-grid">
        {images.map((img) => {
          const isSelected = selected.includes(img.index)
          return (
            <button
              key={img.index}
              type="button"
              className={`thumb${isSelected ? ' selected' : ''}`}
              onClick={() => onToggle(img.index)}
              title={`#${img.index}`}
            >
              {img.thumb_b64 ? (
                <img src={b64Url(img.thumb_b64)} alt={`#${img.index}`} />
              ) : (
                <span className="idx">#{img.index}</span>
              )}
              <span className="idx">{img.index}</span>
            </button>
          )
        })}
      </div>
      {loading && <p className="hint">Loading…</p>}
    </section>
  )
}
