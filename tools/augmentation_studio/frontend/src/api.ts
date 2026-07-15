export type AugParamSpec = {
  name: string
  type: string
  default: number | number[] | string
  min?: number
  max?: number
  step?: number
  description?: string
}

export type AugmentationSpec = {
  name: string
  description: string
  params: AugParamSpec[]
}

export type RegistryResponse = {
  augmentations: AugmentationSpec[]
  training_prob: number
  config_key: string
}

export type TransformSpec = AugmentationSpec

export type TransformsResponse = {
  transforms: TransformSpec[]
  config_keys: string[]
  roi_defaults: Record<string, number>
}

export type TubImageMeta = {
  index: number
  image_file: string
  angle?: number
  throttle?: number
  thumb_b64?: string | null
  excluded?: boolean
}

export type AugEntry = {
  name: string
  params: Record<string, number | number[] | string>
}

export type PreviewResult = {
  index: number
  original_b64: string
  augmented_b64: string
  width: number
  height: number
}

export type CvPreviewResult = {
  index: number
  original_b64: string
  preprocessed_b64: string
  edges_b64: string
  width: number
  height: number
}

export type LineFollowerPreviewResult = {
  index: number
  original_b64: string
  preprocessed_b64: string
  overlay_b64: string
  max_yellow: number
  confidence: number
  steering: number
  throttle: number
  scan_y: number
  scan_height: number
  target_pixel: number
  line_detected: boolean
  width: number
  height: number
}

export type CvParams = {
  CANNY_LOW_THRESHOLD: number
  CANNY_HIGH_THRESHOLD: number
  CANNY_APERTURE: number
  BLUR_KERNEL: number
  BLUR_KERNEL_Y: number | null
  BLUR_GAUSSIAN: boolean
  CV_SHOW_DEBUG_PIPELINE: boolean
}

export type HsvTuple = [number, number, number]

export type LineFollowerParams = {
  SCAN_Y: number
  SCAN_HEIGHT: number
  COLOR_THRESHOLD_LOW: HsvTuple
  COLOR_THRESHOLD_HIGH: HsvTuple
  TARGET_PIXEL: number | null
  TARGET_THRESHOLD: number
  CONFIDENCE_THRESHOLD: number
  THROTTLE_MAX: number
  THROTTLE_MIN: number
  THROTTLE_INITIAL: number
  THROTTLE_STEP: number
  PID_P: number
  PID_I: number
  PID_D: number
}

export type ImportedCvConfig = {
  path: string
  cv_preprocess: string[]
  cv_debug_transformations: string[]
  cv_params: CvParams
  line_follower: LineFollowerParams
  roi: RoiState
  mask_metadata_path?: string | null
  mask_preset?: string | null
}

export type MaskRegion =
  | { type: 'rect'; x: number; y: number; w: number; h: number }
  | { type: 'poly'; points: number[][] }

export type MaskData = {
  version: number
  tub_path?: string | null
  presets: Record<string, MaskRegion[]>
  by_index: Record<string, MaskRegion[]>
  default_preset: string | null
}

export type RoiState = Record<string, number>

export type ApplyResult = {
  path: string
  backup_path: string
  updated: string[]
  added: string[]
  blocks_replaced: number
  changed: boolean
}

export type ReplayModelOption = {
  id: string
  label: string
  path: string
}

export type ReplayTubOption = {
  id: string
  label: string
  path: string
  tag: 'train' | 'holdout'
}

export type ReplayOptions = {
  models: ReplayModelOption[]
  tubs: ReplayTubOption[]
}

export type ReplayRecord = {
  frame_id: number
  actual_angle: number
  actual_throttle: number
  pred_angle: number
  pred_throttle: number
  image_path: string
}

export type ReplayResponse = {
  tub_id: string
  tub_path: string
  model_id: string
  model_label: string
  tag: 'train' | 'holdout'
  training_warning: boolean
  cache_hit: boolean
  records: ReplayRecord[]
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail ?? JSON.stringify(body)
    } catch {
      /* ignore */
    }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return res.json() as Promise<T>
}

export function b64Url(b64: string, mime = 'image/jpeg'): string {
  return `data:${mime};base64,${b64}`
}

export function tubImageUrl(path: string, index: number): string {
  return `/api/tub/image/${index}?path=${encodeURIComponent(path)}&format=jpeg`
}

export const api = {
  getAugmentations: () => request<RegistryResponse>('/api/augmentations'),
  getTransforms: () => request<TransformsResponse>('/api/transforms'),
  getReplayOptions: () => request<ReplayOptions>('/api/replay/options'),

  getReplay: (tubId: string, model: string) =>
    request<ReplayResponse>(
      `/api/replay/${encodeURIComponent(tubId)}?model=${encodeURIComponent(model)}`,
    ),

  getCvReplay: (tubPath: string, myconfigPath?: string) =>
    request<ReplayResponse>('/api/cv/replay', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        tub_path: tubPath,
        myconfig_path: myconfigPath || null,
      }),
    }),

  openTub: (path: string) =>
    request<{ path: string; total: number; image_key: string; inputs: string[] }>(
      '/api/tub/open',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path }),
      },
    ),

  listImages: (path: string, offset = 0, limit = 48, thumb = true, excludesPath?: string) => {
    let url =
      `/api/tub/images?path=${encodeURIComponent(path)}&offset=${offset}&limit=${limit}&thumb=${thumb}`
    if (excludesPath) url += `&excludes_path=${encodeURIComponent(excludesPath)}`
    return request<{
      path: string
      total: number
      offset: number
      limit: number
      images: TubImageMeta[]
    }>(url)
  },

  preview: (body: {
    path: string
    indexes: number[]
    augmentations?: AugEntry[]
    transformations?: string[]
    post_transformations?: string[]
    roi?: RoiState
    mask_metadata_path?: string | null
    mask_preset?: string | null
    apply_aug?: boolean
    mask_data?: MaskData | null
  }) =>
    request<{ results: PreviewResult[]; preview_prob: number }>('/api/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),

  previewCv: (body: {
    path: string
    indexes: number[]
    cv_preprocess: string[]
    cv_debug_transformations: string[]
    cv_params: CvParams
    roi: RoiState
  }) =>
    request<{ results: CvPreviewResult[] }>('/api/cv/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),

  previewLineFollower: (body: {
    path: string
    indexes: number[]
    cv_preprocess: string[]
    roi: RoiState
    line_follower: LineFollowerParams
  }) =>
    request<{ results: LineFollowerPreviewResult[] }>('/api/cv/linefollower/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),

  exportConfig: (body: Record<string, unknown>) =>
    request<{ snippet: string }>('/api/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),

  applyConfig: (body: Record<string, unknown>) =>
    request<ApplyResult>('/api/config/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),

  importConfig: (myconfigPath: string) =>
    request<ImportedCvConfig>('/api/config/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ myconfig_path: myconfigPath }),
    }),

  loadCuration: (path: string) =>
    request<{ version: number; tub_path: string | null; excluded_indexes: number[] }>(
      '/api/curation/load',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path }),
      },
    ),

  saveCuration: (path: string, tubPath: string, excludedIndexes: number[]) =>
    request('/api/curation/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        path,
        tub_path: tubPath,
        excluded_indexes: excludedIndexes,
      }),
    }),

  exportCuration: (path: string) =>
    request<{ snippet: string }>('/api/curation/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    }),

  loadMasks: (path: string) =>
    request<MaskData>('/api/masks/load', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    }),

  saveMasks: (path: string, tubPath: string, data: MaskData) =>
    request('/api/masks/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, tub_path: tubPath, data }),
    }),
}
