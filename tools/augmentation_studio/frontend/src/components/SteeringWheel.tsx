type Props = {
  actual: number
  predicted: number
}

function Wheel({ angle, className, label }: { angle: number; className: string; label: string }) {
  const degrees = Math.max(-1, Math.min(1, angle)) * 120
  return (
    <g
      className={className}
      transform={`rotate(${degrees} 100 100)`}
      aria-label={`${label} steering ${angle.toFixed(3)}`}
    >
      <circle cx="100" cy="100" r="72" />
      <line x1="100" y1="100" x2="100" y2="28" />
      <line x1="100" y1="100" x2="42" y2="142" />
      <line x1="100" y1="100" x2="158" y2="142" />
      <circle cx="100" cy="100" r="11" />
    </g>
  )
}

export default function SteeringWheel({ actual, predicted }: Props) {
  return (
    <figure className="steering-visual">
      <svg viewBox="0 0 200 200" role="img" aria-label="Actual and predicted steering">
        <Wheel angle={actual} className="wheel actual" label="Actual" />
        <Wheel angle={predicted} className="wheel predicted" label="Predicted" />
      </svg>
      <figcaption>
        <span className="actual-key">Actual</span>
        <span className="predicted-key">Predicted</span>
      </figcaption>
    </figure>
  )
}
