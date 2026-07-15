import { useCallback, useEffect, useRef, useState } from 'react'
import { b64Url } from '../api'

type Props = {
  originalB64: string | null
  augmentedB64: string | null
  width?: number
  height?: number
}

export default function PreviewCompare({ originalB64, augmentedB64 }: Props) {
  const [wipe, setWipe] = useState(0.5)
  const [mode, setMode] = useState<'wipe' | 'toggle'>('wipe')
  const [showAug, setShowAug] = useState(true)
  const [wrapWidth, setWrapWidth] = useState(0)
  const wrapRef = useRef<HTMLDivElement>(null)
  const dragging = useRef(false)

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const ro = new ResizeObserver(() => setWrapWidth(el.clientWidth))
    ro.observe(el)
    setWrapWidth(el.clientWidth)
    return () => ro.disconnect()
  }, [originalB64])

  const updateFromClientX = useCallback((clientX: number) => {
    const el = wrapRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    const x = Math.min(Math.max(clientX - rect.left, 0), rect.width)
    setWipe(rect.width ? x / rect.width : 0.5)
  }, [])

  if (!originalB64) {
    return <p className="hint">Select an image to preview.</p>
  }

  const showAfter = mode === 'wipe' ? true : showAug
  const afterSrc = augmentedB64 ?? originalB64

  return (
    <div>
      <div className="row" style={{ maxWidth: 640, marginBottom: '0.4rem' }}>
        <button
          type="button"
          className={mode === 'wipe' ? 'active' : 'ghost'}
          onClick={() => setMode('wipe')}
        >
          Wipe
        </button>
        <button
          type="button"
          className={mode === 'toggle' ? 'active' : 'ghost'}
          onClick={() => setMode('toggle')}
        >
          Toggle
        </button>
        {mode === 'toggle' && (
          <button type="button" className="ghost" onClick={() => setShowAug((v) => !v)}>
            Show {showAug ? 'original' : 'augmented'}
          </button>
        )}
      </div>

      <div
        className="compare-wrap"
        ref={wrapRef}
        onPointerDown={(e) => {
          if (mode !== 'wipe') return
          dragging.current = true
          ;(e.target as HTMLElement).setPointerCapture?.(e.pointerId)
          updateFromClientX(e.clientX)
        }}
        onPointerMove={(e) => {
          if (!dragging.current || mode !== 'wipe') return
          updateFromClientX(e.clientX)
        }}
        onPointerUp={() => {
          dragging.current = false
        }}
        onPointerCancel={() => {
          dragging.current = false
        }}
      >
        <img src={b64Url(originalB64)} alt="original" />
        {showAfter && (
          <div
            className="after"
            style={mode === 'wipe' ? { width: `${wipe * 100}%` } : { width: '100%' }}
          >
            <img
              src={b64Url(afterSrc)}
              alt="augmented"
              style={wrapWidth ? { width: wrapWidth } : undefined}
            />
          </div>
        )}
        {mode === 'wipe' && <div className="handle" style={{ left: `${wipe * 100}%` }} />}
      </div>
      <div className="compare-labels">
        <span>Original</span>
        <span>Augmented (p=1.0)</span>
      </div>
    </div>
  )
}
