import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  api,
  type AugEntry,
  type AugmentationSpec,
  type CvParams,
  type CvPreviewResult,
  type MaskData,
  type PreviewResult,
  type ReplayOptions,
  type RoiState,
  type TransformSpec,
  type TubImageMeta,
} from './api'
import TubBrowser from './components/TubBrowser'
import AugmentTab from './components/tabs/AugmentTab'
import CropTab from './components/tabs/CropTab'
import CurateTab from './components/tabs/CurateTab'
import DebugTab from './components/tabs/DebugTab'
import MaskTab from './components/tabs/MaskTab'
import ReplayTab from './components/tabs/ReplayTab'
import { MYCONFIG_STORAGE_KEY } from './components/ExportPanel'

const PAGE_SIZE = 48
const PREVIEW_DEBOUNCE_MS = 200

type TabId = 'augment' | 'crop' | 'debug' | 'curate' | 'mask' | 'replay'
type ExportProfile = 'cv_control' | 'training'

function useDebouncedEffect(effect: () => void | (() => void), deps: unknown[], delay: number) {
  const cleanupRef = useRef<void | (() => void)>()
  useEffect(() => {
    const handle = window.setTimeout(() => {
      cleanupRef.current = effect()
    }, delay)
    return () => {
      window.clearTimeout(handle)
      if (typeof cleanupRef.current === 'function') cleanupRef.current()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
}

const DEFAULT_ROI: RoiState = {
  ROI_CROP_LEFT: 0,
  ROI_CROP_TOP: 45,
  ROI_CROP_RIGHT: 0,
  ROI_CROP_BOTTOM: 0,
  ROI_TRAPEZE_UL: 20,
  ROI_TRAPEZE_UR: 140,
  ROI_TRAPEZE_LL: 0,
  ROI_TRAPEZE_LR: 160,
  ROI_TRAPEZE_MIN_Y: 60,
  ROI_TRAPEZE_MAX_Y: 120,
}

const DEFAULT_CV_PARAMS: CvParams = {
  CANNY_LOW_THRESHOLD: 60,
  CANNY_HIGH_THRESHOLD: 110,
  CANNY_APERTURE: 3,
  BLUR_KERNEL: 5,
  BLUR_KERNEL_Y: null,
  BLUR_GAUSSIAN: true,
  CV_SHOW_DEBUG_PIPELINE: false,
}

export default function App() {
  const [tab, setTab] = useState<TabId>('augment')
  const [exportProfile, setExportProfile] = useState<ExportProfile>('cv_control')
  const [catalog, setCatalog] = useState<AugmentationSpec[]>([])
  const [transformCatalog, setTransformCatalog] = useState<TransformSpec[]>([])
  const [replayOptions, setReplayOptions] = useState<ReplayOptions>({ models: [], tubs: [] })
  const [requestedReplayTubId, setRequestedReplayTubId] = useState<string | null>(null)
  const [trainingProb, setTrainingProb] = useState<number | null>(null)
  const [roiDefaults, setRoiDefaults] = useState<RoiState>(DEFAULT_ROI)

  const [path, setPath] = useState('/tmp/dc_tub_inspect/tub')
  const [total, setTotal] = useState<number | null>(null)
  const [images, setImages] = useState<TubImageMeta[]>([])
  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState<number[]>([])
  const [focusIndex, setFocusIndex] = useState<number | null>(null)

  const [stack, setStack] = useState<AugEntry[]>([])
  const [transformations, setTransformations] = useState<string[]>([])
  const [postTransformations, setPostTransformations] = useState<string[]>([])
  const [roi, setRoi] = useState<RoiState>(DEFAULT_ROI)
  const [cvPreprocess, setCvPreprocess] = useState<string[]>([])
  const [cvDebugTransformations, setCvDebugTransformations] = useState<string[]>([
    'RGB2GRAY',
    'BLUR',
    'CANNY',
  ])
  const [cvParams, setCvParams] = useState<CvParams>(DEFAULT_CV_PARAMS)
  const [myconfigPath, setMyconfigPath] = useState(
    () => localStorage.getItem(MYCONFIG_STORAGE_KEY) ?? '~/mycar/myconfig.py',
  )

  const [excludesPath, setExcludesPath] = useState('/tmp/lok_excludes.json')
  const [excluded, setExcluded] = useState<Set<number>>(new Set())
  const [masksPath, setMasksPath] = useState('/tmp/lok_masks.json')
  const [maskData, setMaskData] = useState<MaskData>({
    version: 1,
    presets: {},
    by_index: {},
    default_preset: null,
  })

  const [preview, setPreview] = useState<PreviewResult | null>(null)
  const [cvPreview, setCvPreview] = useState<CvPreviewResult | null>(null)
  const [batch, setBatch] = useState<PreviewResult[]>([])
  const [snippet, setSnippet] = useState('')
  const [tubError, setTubError] = useState<string | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [loadingTub, setLoadingTub] = useState(false)
  const [busyExport, setBusyExport] = useState(false)
  const [status, setStatus] = useState<string | null>(null)

  useEffect(() => {
    void Promise.all([api.getAugmentations(), api.getTransforms(), api.getReplayOptions()])
      .then(([aug, tr, replay]) => {
        setCatalog(aug.augmentations)
        setTrainingProb(aug.training_prob)
        setTransformCatalog(tr.transforms)
        setRoiDefaults(tr.roi_defaults)
        setRoi((prev) => ({ ...tr.roi_defaults, ...prev }))
        setReplayOptions(replay)
      })
      .catch((e: Error) => setPreviewError(e.message))
  }, [])

  const importMyconfig = useCallback(async (configPath: string, quiet = false) => {
    const trimmed = configPath.trim()
    if (!trimmed) return
    try {
      const imported = await api.importConfig(trimmed)
      setMyconfigPath(imported.path)
      localStorage.setItem(MYCONFIG_STORAGE_KEY, imported.path)
      setCvPreprocess(imported.cv_preprocess)
      setCvDebugTransformations(imported.cv_debug_transformations)
      setCvParams(imported.cv_params)
      setRoi(imported.roi)
      if (imported.mask_metadata_path) setMasksPath(imported.mask_metadata_path)
      if (!quiet) setStatus(`Imported CV settings from ${imported.path}`)
    } catch (error) {
      if (!quiet) setPreviewError(error instanceof Error ? error.message : String(error))
    }
  }, [])

  useEffect(() => {
    const stored = localStorage.getItem(MYCONFIG_STORAGE_KEY)
    if (stored) void importMyconfig(stored, true)
    const onPath = (event: Event) => {
      const value = (event as CustomEvent<string>).detail
      if (value) setMyconfigPath(value)
    }
    window.addEventListener('lok:myconfig-path', onPath)
    return () => window.removeEventListener('lok:myconfig-path', onPath)
  }, [importMyconfig])

  const loadPage = useCallback(
    async (tubPath: string, pageOffset: number) => {
      setLoadingTub(true)
      setTubError(null)
      try {
        const listing = await api.listImages(
          tubPath,
          pageOffset,
          PAGE_SIZE,
          true,
          excludesPath,
        )
        setImages(listing.images)
        setTotal(listing.total)
        setOffset(listing.offset)
      } catch (e) {
        setTubError(e instanceof Error ? e.message : String(e))
      } finally {
        setLoadingTub(false)
      }
    },
    [excludesPath],
  )

  const openTub = useCallback(
    async (overridePath?: string) => {
      const tubPath = (overridePath ?? path).trim()
      if (!tubPath) return
      setPath(tubPath)
      setLoadingTub(true)
      setTubError(null)
      setSelected([])
      setFocusIndex(null)
      setPreview(null)
      setBatch([])
      try {
        const info = await api.openTub(tubPath)
        setTotal(info.total)
        await loadPage(info.path, 0)
      } catch (e) {
        setTubError(e instanceof Error ? e.message : String(e))
        setImages([])
        setTotal(null)
      } finally {
        setLoadingTub(false)
      }
    },
    [path, loadPage],
  )

  function toggleSelect(index: number) {
    setSelected((prev) => {
      const exists = prev.includes(index)
      const next = exists ? prev.filter((i) => i !== index) : [...prev, index]
      setFocusIndex(index)
      return next
    })
  }

  const previewIndexes = useMemo(() => {
    if (selected.length > 0) return selected
    if (focusIndex != null) return [focusIndex]
    return []
  }, [selected, focusIndex])

  const registeredTub = useMemo(
    () => replayOptions.tubs.find((tub) => tub.path === path),
    [path, replayOptions.tubs],
  )

  useDebouncedEffect(() => {
    if (tab === 'debug' || tab === 'replay') return
    if (!path || previewIndexes.length === 0) {
      setPreview(null)
      setBatch([])
      return
    }
    let cancelled = false
    setPreviewError(null)

    const useAug = tab === 'augment'
    const useCrop = tab === 'crop' || tab === 'augment'
    const activeTransforms =
      exportProfile === 'cv_control' ? cvPreprocess : transformations
    const useMask =
      tab === 'mask' || (tab === 'augment' && activeTransforms.includes('REGION_MASK'))

    const body = {
      path,
      indexes: tab === 'mask' && focusIndex != null ? [focusIndex] : previewIndexes,
      augmentations: useAug ? stack : [],
      transformations: useCrop || useMask ? [...activeTransforms] : [],
      post_transformations:
        useCrop && exportProfile === 'training' ? postTransformations : [],
      roi,
      mask_metadata_path: useMask ? masksPath : null,
      apply_aug: useAug,
      mask_data: tab === 'mask' ? maskData : null,
    }

    // Ensure REGION_MASK in transform list when on mask tab
    if (tab === 'mask' && !body.transformations.includes('REGION_MASK')) {
      body.transformations = [...body.transformations, 'REGION_MASK']
    }

    void api
      .preview(body)
      .then((res) => {
        if (cancelled) return
        setBatch(res.results)
        const focus = focusIndex ?? previewIndexes[0]
        setPreview(res.results.find((r) => r.index === focus) ?? res.results[0] ?? null)
      })
      .catch((e: Error) => {
        if (!cancelled) setPreviewError(e.message)
      })
    return () => {
      cancelled = true
    }
  }, [
    path,
    previewIndexes,
    stack,
    focusIndex,
    tab,
    transformations,
    cvPreprocess,
    exportProfile,
    postTransformations,
    roi,
    masksPath,
    maskData,
  ], PREVIEW_DEBOUNCE_MS)

  useDebouncedEffect(() => {
    if (tab !== 'debug' || !path || previewIndexes.length === 0) {
      if (tab === 'debug') setCvPreview(null)
      return
    }
    let cancelled = false
    setPreviewError(null)
    void api
      .previewCv({
        path,
        indexes: previewIndexes,
        cv_preprocess: cvPreprocess,
        cv_debug_transformations: cvDebugTransformations,
        cv_params: cvParams,
        roi,
      })
      .then((response) => {
        if (cancelled) return
        const focus = focusIndex ?? previewIndexes[0]
        setCvPreview(
          response.results.find((result) => result.index === focus) ??
            response.results[0] ??
            null,
        )
      })
      .catch((error: Error) => {
        if (!cancelled) setPreviewError(error.message)
      })
    return () => {
      cancelled = true
    }
  }, [
    tab,
    path,
    previewIndexes,
    focusIndex,
    cvPreprocess,
    cvDebugTransformations,
    cvParams,
    roi,
  ], PREVIEW_DEBOUNCE_MS)

  async function handleAugmentExport() {
    setBusyExport(true)
    try {
      const res = await api.exportConfig({ augmentations: stack })
      setSnippet(res.snippet)
    } catch (e) {
      setPreviewError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusyExport(false)
    }
  }

  async function handleCropExport() {
    setBusyExport(true)
    try {
      const res = await api.exportConfig({
        augmentations: [],
        profile: exportProfile,
        transformations,
        post_transformations: postTransformations,
        cv_preprocess: cvPreprocess,
        cv_debug_transformations: cvDebugTransformations,
        cv_params: cvParams,
        roi,
      })
      setSnippet(res.snippet)
    } catch (e) {
      setPreviewError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusyExport(false)
    }
  }

  async function handleDebugExport() {
    setBusyExport(true)
    try {
      const res = await api.exportConfig({
        profile: 'cv_control',
        cv_preprocess: cvPreprocess,
        cv_debug_transformations: cvDebugTransformations,
        cv_params: cvParams,
        roi,
      })
      setSnippet(res.snippet)
    } catch (error) {
      setPreviewError(error instanceof Error ? error.message : String(error))
    } finally {
      setBusyExport(false)
    }
  }

  async function handleCurateExport() {
    setBusyExport(true)
    try {
      const res = await api.exportCuration(excludesPath)
      setSnippet(res.snippet)
    } catch (e) {
      setPreviewError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusyExport(false)
    }
  }

  const applyAugment = useCallback(
    (myconfigPath: string) =>
      api.applyConfig({ myconfig_path: myconfigPath, augmentations: stack }),
    [stack],
  )

  const applyCrop = useCallback(
    (myconfigPath: string) =>
      api.applyConfig({
        myconfig_path: myconfigPath,
        profile: exportProfile,
        transformations,
        post_transformations: postTransformations,
        cv_preprocess: cvPreprocess,
        cv_debug_transformations: cvDebugTransformations,
        cv_params: cvParams,
        roi,
      }),
    [
      exportProfile,
      transformations,
      postTransformations,
      cvPreprocess,
      cvDebugTransformations,
      cvParams,
      roi,
    ],
  )

  const applyDebug = useCallback(
    (configPath: string) =>
      api.applyConfig({
        myconfig_path: configPath,
        profile: 'cv_control',
        cv_preprocess: cvPreprocess,
        cv_debug_transformations: cvDebugTransformations,
        cv_params: cvParams,
        roi,
      }),
    [cvPreprocess, cvDebugTransformations, cvParams, roi],
  )

  const applyCurate = useCallback(
    (myconfigPath: string) =>
      api.applyConfig({ myconfig_path: myconfigPath, excludes_path: excludesPath }),
    [excludesPath],
  )

  const applyMask = useCallback(
    (configPath: string) =>
      api.applyConfig({
        myconfig_path: configPath,
        profile: exportProfile,
        transformations: transformations.includes('REGION_MASK')
          ? transformations
          : [...transformations, 'REGION_MASK'],
        post_transformations: postTransformations,
        cv_preprocess: cvPreprocess.includes('REGION_MASK')
          ? cvPreprocess
          : [...cvPreprocess, 'REGION_MASK'],
        cv_debug_transformations: cvDebugTransformations,
        cv_params: cvParams,
        roi,
        masks_path: masksPath,
      }),
    [
      exportProfile,
      transformations,
      postTransformations,
      cvPreprocess,
      cvDebugTransformations,
      cvParams,
      roi,
      masksPath,
    ],
  )

  async function handleMaskExport() {
    setBusyExport(true)
    try {
      const res = await api.exportConfig({
        augmentations: [],
        profile: exportProfile,
        transformations: transformations.includes('REGION_MASK')
          ? transformations
          : [...transformations, 'REGION_MASK'],
        post_transformations: postTransformations,
        cv_preprocess: cvPreprocess.includes('REGION_MASK')
          ? cvPreprocess
          : [...cvPreprocess, 'REGION_MASK'],
        cv_debug_transformations: cvDebugTransformations,
        cv_params: cvParams,
        roi,
        masks_path: masksPath,
      })
      setSnippet(res.snippet)
    } catch (e) {
      setPreviewError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusyExport(false)
    }
  }

  return (
    <div className="app lok">
      <header className="app-header">
        <h1>LOK</h1>
        <nav className="tabs">
          {(
            [
              ['augment', 'Augment'],
              ['crop', 'Crop / ROI'],
              ['debug', 'Debug / Edges'],
              ['curate', 'Curate'],
              ['mask', 'Mask'],
              ['replay', 'Replay'],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              className={tab === id ? 'active' : 'ghost'}
              onClick={() => setTab(id)}
            >
              {label}
            </button>
          ))}
        </nav>
        <div className="header-config">
          <label>
            Target
            <select
              value={exportProfile}
              onChange={(event) => setExportProfile(event.target.value as ExportProfile)}
            >
              <option value="cv_control">CV Control</option>
              <option value="training">Training / Complete</option>
            </select>
          </label>
          <label>
            myconfig.py
            <input
              type="text"
              value={myconfigPath}
              onChange={(event) => {
                setMyconfigPath(event.target.value)
                localStorage.setItem(MYCONFIG_STORAGE_KEY, event.target.value)
              }}
            />
          </label>
          <button type="button" className="ghost" onClick={() => void importMyconfig(myconfigPath)}>
            Import
          </button>
          {status && <span className="config-status">{status}</span>}
        </div>
      </header>

      <TubBrowser
        path={path}
        total={total}
        images={images}
        selected={selected}
        offset={offset}
        limit={PAGE_SIZE}
        loading={loadingTub}
        error={tubError}
        onOpen={(p) => void openTub(p)}
        onPage={(o) => void loadPage(path, o)}
        onToggle={toggleSelect}
        onSelectAllVisible={() => {
          const ids = images.map((i) => i.index)
          setSelected(ids)
          if (ids.length) setFocusIndex(ids[0])
        }}
        onClearSelection={() => setSelected([])}
        canEvaluate={Boolean(registeredTub)}
        evaluateHint={
          registeredTub
            ? `Evaluate ${registeredTub.label}`
            : 'Register this tub path in config/tubs.json to evaluate it'
        }
        onEvaluate={() => {
          if (!registeredTub) return
          setRequestedReplayTubId(registeredTub.id)
          setTab('replay')
        }}
      />

      <div className="lok-body">
        {tab === 'augment' && (
          <AugmentTab
            catalog={catalog}
            stack={stack}
            onStackChange={setStack}
            preview={preview}
            batch={batch}
            previewError={previewError}
            snippet={snippet}
            trainingProb={trainingProb}
            busyExport={busyExport}
            onExport={handleAugmentExport}
            onApply={applyAugment}
          />
        )}
        {tab === 'crop' && (
          <CropTab
            transformCatalog={transformCatalog}
            roiDefaults={roiDefaults}
            transformations={exportProfile === 'cv_control' ? cvPreprocess : transformations}
            postTransformations={
              exportProfile === 'cv_control' ? [] : postTransformations
            }
            roi={roi}
            onTransformationsChange={
              exportProfile === 'cv_control' ? setCvPreprocess : setTransformations
            }
            onPostTransformationsChange={
              exportProfile === 'cv_control' ? () => undefined : setPostTransformations
            }
            onRoiChange={setRoi}
            preview={preview}
            previewError={previewError}
            snippet={snippet}
            busyExport={busyExport}
            onExport={handleCropExport}
            onApply={applyCrop}
            imageWidth={preview?.width ?? 160}
            imageHeight={preview?.height ?? 120}
            allowPostTransformations={exportProfile === 'training'}
          />
        )}
        {tab === 'debug' && (
          <DebugTab
            preview={cvPreview}
            error={previewError}
            cvPreprocess={cvPreprocess}
            debugTransforms={cvDebugTransformations}
            cvParams={cvParams}
            onDebugTransformsChange={setCvDebugTransformations}
            onCvParamsChange={setCvParams}
            snippet={snippet}
            busy={busyExport}
            onExport={handleDebugExport}
            onApply={applyDebug}
          />
        )}
        {tab === 'curate' && (
          <CurateTab
            images={images}
            excluded={excluded}
            onToggleExclude={(index) => {
              setExcluded((prev) => {
                const next = new Set(prev)
                if (next.has(index)) next.delete(index)
                else next.add(index)
                return next
              })
              setFocusIndex(index)
            }}
            onExcludeVisible={() => {
              setExcluded((prev) => {
                const next = new Set(prev)
                images.forEach((i) => next.add(i.index))
                return next
              })
            }}
            onKeepVisible={() => {
              setExcluded((prev) => {
                const next = new Set(prev)
                images.forEach((i) => next.delete(i.index))
                return next
              })
            }}
            excludesPath={excludesPath}
            onExcludesPathChange={setExcludesPath}
            onLoad={async () => {
              try {
                const data = await api.loadCuration(excludesPath)
                setExcluded(new Set(data.excluded_indexes))
                setStatus(`Loaded ${data.excluded_indexes.length} excludes`)
                await loadPage(path, offset)
              } catch (e) {
                setPreviewError(e instanceof Error ? e.message : String(e))
              }
            }}
            onSave={async () => {
              try {
                await api.saveCuration(excludesPath, path, [...excluded])
                setStatus(`Saved ${excluded.size} excludes → ${excludesPath}`)
                await loadPage(path, offset)
              } catch (e) {
                setPreviewError(e instanceof Error ? e.message : String(e))
              }
            }}
            snippet={snippet}
            busy={busyExport}
            onExport={handleCurateExport}
            onApply={applyCurate}
            error={previewError}
            status={status}
          />
        )}
        {tab === 'mask' && (
          <MaskTab
            masksPath={masksPath}
            onMasksPathChange={setMasksPath}
            maskData={maskData}
            onMaskDataChange={setMaskData}
            focusIndex={focusIndex}
            preview={preview}
            previewError={previewError}
            snippet={snippet}
            busy={busyExport}
            onLoad={async () => {
              try {
                const data = await api.loadMasks(masksPath)
                setMaskData(data)
                setStatus('Masks loaded')
              } catch (e) {
                setPreviewError(e instanceof Error ? e.message : String(e))
              }
            }}
            onSave={async () => {
              try {
                await api.saveMasks(masksPath, path, maskData)
                setStatus(`Saved masks → ${masksPath}`)
              } catch (e) {
                setPreviewError(e instanceof Error ? e.message : String(e))
              }
            }}
            onExport={handleMaskExport}
            onApply={applyMask}
            status={status}
          />
        )}
        {tab === 'replay' && (
          <ReplayTab
            options={replayOptions}
            initialTubId={requestedReplayTubId}
            currentTubPath={path}
            myconfigPath={myconfigPath}
          />
        )}
      </div>
    </div>
  )
}
