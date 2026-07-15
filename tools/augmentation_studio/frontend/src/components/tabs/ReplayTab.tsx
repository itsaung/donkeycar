import { useEffect, useState } from 'react'
import {
  api,
  tubImageUrl,
  type ReplayOptions,
  type ReplayResponse,
} from '../../api'
import ErrorTimeline from '../ErrorTimeline'
import SteeringWheel from '../SteeringWheel'

type Props = {
  options: ReplayOptions
  initialTubId?: string | null
  currentTubPath?: string
  myconfigPath?: string
}

function Value({ label, value, accent = false }: { label: string; value: number; accent?: boolean }) {
  return (
    <div className={accent ? 'replay-value accent' : 'replay-value'}>
      <span>{label}</span>
      <strong>{value.toFixed(3)}</strong>
    </div>
  )
}

export default function ReplayTab({
  options,
  initialTubId,
  currentTubPath = '',
  myconfigPath = '',
}: Props) {
  const [mode, setMode] = useState<'model' | 'cv'>('model')
  const [tubId, setTubId] = useState('')
  const [modelId, setModelId] = useState('')
  const [replay, setReplay] = useState<ReplayResponse | null>(null)
  const [current, setCurrent] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (initialTubId && options.tubs.some((tub) => tub.id === initialTubId)) {
      setTubId(initialTubId)
    } else if (!tubId && options.tubs.length) {
      setTubId(options.tubs[0].id)
    }
    if (!modelId && options.models.length) setModelId(options.models[0].id)
  }, [initialTubId, modelId, options, tubId])

  useEffect(() => {
    if (!playing || !replay?.records.length) return
    const timer = window.setInterval(() => {
      setCurrent((index) => {
        if (index >= replay.records.length - 1) {
          setPlaying(false)
          return index
        }
        return index + 1
      })
    }, 100)
    return () => window.clearInterval(timer)
  }, [playing, replay])

  async function loadReplay() {
    if (mode === 'model' && (!tubId || !modelId)) return
    if (mode === 'cv' && !currentTubPath) return
    setLoading(true)
    setPlaying(false)
    setError(null)
    try {
      const result =
        mode === 'cv'
          ? await api.getCvReplay(currentTubPath, myconfigPath)
          : await api.getReplay(tubId, modelId)
      setReplay(result)
      setCurrent(0)
    } catch (reason) {
      setReplay(null)
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setLoading(false)
    }
  }

  const record = replay?.records[current]
  const delta = record ? record.pred_angle - record.actual_angle : 0

  return (
    <div className="replay-tab">
      <section className="replay-toolbar panel">
        <h2>Replay controller against tub</h2>
        <div className="row replay-mode">
          <button
            type="button"
            className={mode === 'model' ? 'active' : 'ghost'}
            onClick={() => setMode('model')}
          >
            Trained model
          </button>
          <button
            type="button"
            className={mode === 'cv' ? 'active' : 'ghost'}
            onClick={() => setMode('cv')}
          >
            CV controller
          </button>
        </div>
        {mode === 'model' ? (
          <>
            <label>
              Tub
              <select value={tubId} onChange={(event) => setTubId(event.target.value)}>
                {options.tubs.map((tub) => (
                  <option key={tub.id} value={tub.id}>
                    {tub.label} · {tub.tag}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Model
              <select value={modelId} onChange={(event) => setModelId(event.target.value)}>
                {options.models.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.label}
                  </option>
                ))}
              </select>
            </label>
          </>
        ) : (
          <div className="cv-replay-source">
            <strong>{currentTubPath || 'Open a tub first'}</strong>
            <span>Config: {myconfigPath || 'cv_control defaults'}</span>
          </div>
        )}
        <button
          type="button"
          onClick={() => void loadReplay()}
          disabled={
            loading ||
            (mode === 'model' ? !tubId || !modelId : !currentTubPath)
          }
        >
          {loading ? 'Running inference…' : mode === 'cv' ? 'Run CV replay' : 'Load replay'}
        </button>
        {mode === 'model' && !options.tubs.length && (
          <p className="error">No tubs are configured in config/tubs.json.</p>
        )}
        {mode === 'model' && !options.models.length && (
          <p className="error">No models are configured in config/replay_models.json.</p>
        )}
        {error && <p className="error">{error}</p>}
        {replay && (
          <p className="hint">
            {replay.records.length} frames · {replay.cache_hit ? 'disk cache hit' : 'inference cached'}
          </p>
        )}
      </section>

      {replay?.training_warning && (
        <div className="training-warning" role="alert">
          This tub was used in training — numbers here are not a real test.
        </div>
      )}

      {record && replay && (
        <main className="replay-main">
          <div className="replay-comparison">
            <figure className="replay-camera">
              <img
                src={tubImageUrl(replay.tub_path, record.frame_id)}
                alt={`Tub frame ${record.frame_id}`}
              />
              <figcaption>
                Frame #{record.frame_id} · {current + 1} / {replay.records.length}
              </figcaption>
            </figure>
            <div className="replay-steering">
              <SteeringWheel actual={record.actual_angle} predicted={record.pred_angle} />
              <div className="replay-values">
                <Value label="Actual angle" value={record.actual_angle} />
                <Value label="Predicted angle" value={record.pred_angle} accent />
                <Value label="Delta" value={delta} />
                <Value label="Actual throttle" value={record.actual_throttle} />
                <Value label="Predicted throttle" value={record.pred_throttle} accent />
              </div>
            </div>
          </div>

          <section className="replay-controls">
            <button type="button" onClick={() => setPlaying((value) => !value)}>
              {playing ? 'Pause' : 'Play'}
            </button>
            <input
              type="range"
              min={0}
              max={Math.max(0, replay.records.length - 1)}
              value={current}
              aria-label="Replay frame"
              onChange={(event) => {
                setPlaying(false)
                setCurrent(Number(event.target.value))
              }}
            />
          </section>
          <ErrorTimeline records={replay.records} current={current} onSeek={setCurrent} />
        </main>
      )}
    </div>
  )
}
