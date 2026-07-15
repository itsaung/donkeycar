import AugPicker from '../AugPicker'
import BatchGrid from '../BatchGrid'
import ExportPanel from '../ExportPanel'
import PreviewCompare from '../PreviewCompare'
import type { ApplyResult, AugEntry, AugmentationSpec, PreviewResult } from '../../api'

type Props = {
  catalog: AugmentationSpec[]
  stack: AugEntry[]
  onStackChange: (stack: AugEntry[]) => void
  preview: PreviewResult | null
  batch: PreviewResult[]
  previewError: string | null
  snippet: string
  trainingProb: number | null
  busyExport: boolean
  onExport: () => Promise<void>
  onApply?: (myconfigPath: string) => Promise<ApplyResult>
}

export default function AugmentTab({
  catalog,
  stack,
  onStackChange,
  preview,
  batch,
  previewError,
  snippet,
  trainingProb,
  busyExport,
  onExport,
  onApply,
}: Props) {
  return (
    <div className="tab-layout">
      <div className="tab-main">
        <h2 className="section-label">Preview</h2>
        {previewError && <p className="error">{previewError}</p>}
        <PreviewCompare
          originalB64={preview?.original_b64 ?? null}
          augmentedB64={preview?.augmented_b64 ?? null}
        />
        <h2 className="section-label">Batch ({batch.length})</h2>
        <BatchGrid results={batch} />
        <h2 className="section-label">Export</h2>
        <ExportPanel
          snippet={snippet}
          trainingProb={trainingProb}
          onExport={onExport}
          busy={busyExport}
          onApply={onApply}
        />
      </div>
      <aside className="tab-side">
        <AugPicker catalog={catalog} stack={stack} onChange={onStackChange} />
      </aside>
    </div>
  )
}
