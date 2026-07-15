import { useState } from 'react'
import type { ApplyResult } from '../api'

type Props = {
  snippet: string
  trainingProb: number | null
  onExport: () => Promise<void>
  busy: boolean
  onApply?: (myconfigPath: string) => Promise<ApplyResult>
}

export const MYCONFIG_STORAGE_KEY = 'lok.myconfigPath'

function rememberMyconfigPath(path: string) {
  localStorage.setItem(MYCONFIG_STORAGE_KEY, path)
  window.dispatchEvent(new CustomEvent('lok:myconfig-path', { detail: path }))
}

export default function ExportPanel({ snippet, trainingProb, onExport, busy, onApply }: Props) {
  const [copied, setCopied] = useState(false)
  const [myconfigPath, setMyconfigPath] = useState(
    () => localStorage.getItem(MYCONFIG_STORAGE_KEY) ?? '~/mycar/myconfig.py',
  )
  const [applying, setApplying] = useState(false)
  const [applyStatus, setApplyStatus] = useState<string | null>(null)
  const [applyError, setApplyError] = useState<string | null>(null)

  async function copy() {
    await navigator.clipboard.writeText(snippet)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  async function apply() {
    if (!onApply) return
    const path = myconfigPath.trim()
    if (!path) return
    rememberMyconfigPath(path)
    setApplying(true)
    setApplyStatus(null)
    setApplyError(null)
    try {
      const res = await onApply(path)
      const parts: string[] = []
      if (res.updated.length) parts.push(`updated ${res.updated.join(', ')}`)
      if (res.added.length) parts.push(`added ${res.added.join(', ')}`)
      if (res.blocks_replaced) parts.push(`${res.blocks_replaced} code block(s)`)
      setApplyStatus(
        `Wrote ${res.path} (${parts.join(' · ') || 'no changes'}) — backup at ${res.backup_path}`,
      )
    } catch (e) {
      setApplyError(e instanceof Error ? e.message : String(e))
    } finally {
      setApplying(false)
    }
  }

  return (
    <div>
      <div className="row" style={{ marginBottom: '0.5rem' }}>
        <button type="button" onClick={() => void onExport()} disabled={busy}>
          Generate snippet
        </button>
        <button type="button" className="ghost" onClick={() => void copy()} disabled={!snippet}>
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      {trainingProb != null && (
        <p className="hint">
          Training applies each aug with p={trainingProb} (surfaced in snippet comment).
        </p>
      )}
      <textarea className="export-box" readOnly value={snippet} placeholder="Export will appear here…" />

      {onApply && (
        <div className="apply-panel">
          <label>
            myconfig.py path
            <input
              type="text"
              value={myconfigPath}
              placeholder="~/mycar/myconfig.py"
              onChange={(e) => {
                setMyconfigPath(e.target.value)
                rememberMyconfigPath(e.target.value)
              }}
            />
          </label>
          <div className="row" style={{ marginTop: '0.4rem' }}>
            <button
              type="button"
              onClick={() => void apply()}
              disabled={applying || !myconfigPath.trim()}
            >
              {applying ? 'Applying…' : 'Apply to myconfig.py'}
            </button>
          </div>
          <p className="hint">
            Patches matching lines in place (uncomments templates, keeps everything else).
            A .bak backup is written first.
          </p>
          {applyStatus && <p className="hint ok">{applyStatus}</p>}
          {applyError && <p className="error">{applyError}</p>}
        </div>
      )}
    </div>
  )
}
