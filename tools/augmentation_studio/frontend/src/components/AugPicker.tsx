import type { AugEntry, AugmentationSpec } from '../api'

type Props = {
  catalog: AugmentationSpec[]
  stack: AugEntry[]
  onChange: (stack: AugEntry[]) => void
}

function defaultParams(spec: AugmentationSpec): Record<string, number | number[] | string> {
  const params: Record<string, number | number[] | string> = {}
  for (const p of spec.params) {
    params[p.name] = p.default
  }
  return params
}

function asNumber(value: number | number[] | string): number {
  if (Array.isArray(value)) return Number(value[0] ?? 0)
  return Number(value)
}

export default function AugPicker({ catalog, stack, onChange }: Props) {
  const available = catalog.filter((c) => !stack.some((s) => s.name === c.name))

  function add(name: string) {
    const spec = catalog.find((c) => c.name === name)
    if (!spec) return
    onChange([...stack, { name, params: defaultParams(spec) }])
  }

  function remove(index: number) {
    onChange(stack.filter((_, i) => i !== index))
  }

  function move(index: number, dir: -1 | 1) {
    const next = [...stack]
    const j = index + dir
    if (j < 0 || j >= next.length) return
    ;[next[index], next[j]] = [next[j], next[index]]
    onChange(next)
  }

  function setParam(augIndex: number, paramName: string, value: number) {
    const next = stack.map((entry, i) => {
      if (i !== augIndex) return entry
      return {
        ...entry,
        params: { ...entry.params, [paramName]: value },
      }
    })
    onChange(next)
  }

  return (
    <section className="panel">
      <h2>Augmentations</h2>
      <p className="hint">Order = Compose order (training). Preview uses p=1.0.</p>

      <div className="row">
        <select
          id="add-aug"
          defaultValue=""
          onChange={(e) => {
            if (e.target.value) {
              add(e.target.value)
              e.target.value = ''
            }
          }}
        >
          <option value="" disabled>
            Add augmentation…
          </option>
          {available.map((a) => (
            <option key={a.name} value={a.name}>
              {a.name}
            </option>
          ))}
          {!available.length && (
            <option value="" disabled>
              All added
            </option>
          )}
        </select>
      </div>

      {stack.map((entry, i) => {
        const spec = catalog.find((c) => c.name === entry.name)
        return (
          <div className="aug-card" key={`${entry.name}-${i}`}>
            <header>
              <strong>{entry.name}</strong>
              <div className="row" style={{ flex: '0 0 auto', gap: '0.25rem' }}>
                <button type="button" className="ghost" onClick={() => move(i, -1)} disabled={i === 0}>
                  ↑
                </button>
                <button
                  type="button"
                  className="ghost"
                  onClick={() => move(i, 1)}
                  disabled={i === stack.length - 1}
                >
                  ↓
                </button>
                <button type="button" className="ghost" onClick={() => remove(i)}>
                  ✕
                </button>
              </div>
            </header>
            {spec?.description && <p className="hint">{spec.description}</p>}
            {(spec?.params ?? []).map((p) => {
              const raw = entry.params[p.name] ?? p.default
              const value = asNumber(raw)
              const min = p.min ?? 0
              const max = p.max ?? 1
              const step = p.step ?? 0.01
              return (
                <label key={p.name}>
                  {p.name}
                  <div className="param-row">
                    <input
                      type="range"
                      min={min}
                      max={max}
                      step={step}
                      value={value}
                      onChange={(e) => setParam(i, p.name, Number(e.target.value))}
                    />
                    <input
                      type="number"
                      min={min}
                      max={max}
                      step={step}
                      value={value}
                      onChange={(e) => setParam(i, p.name, Number(e.target.value))}
                    />
                  </div>
                </label>
              )
            })}
          </div>
        )
      })}

      {!stack.length && <p className="hint">No augmentations selected — preview shows original.</p>}
    </section>
  )
}
