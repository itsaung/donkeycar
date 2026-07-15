import { b64Url, type PreviewResult } from '../api'

type Props = {
  results: PreviewResult[]
}

export default function BatchGrid({ results }: Props) {
  if (!results.length) {
    return <p className="hint">Select multiple images for batch preview.</p>
  }

  return (
    <div className="batch-grid">
      {results.map((r) => (
        <div className="batch-card" key={r.index}>
          <div className="pair">
            <img src={b64Url(r.original_b64)} alt={`orig ${r.index}`} />
            <img src={b64Url(r.augmented_b64)} alt={`aug ${r.index}`} />
          </div>
          <div className="cap">#{r.index} · orig / aug</div>
        </div>
      ))}
    </div>
  )
}
