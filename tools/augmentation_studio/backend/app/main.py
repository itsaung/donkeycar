"""FastAPI entrypoint for LOK."""

from __future__ import annotations

import base64
import os
import sys
from typing import Any, Dict, List, Optional, Union

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_REPO_ROOT = os.path.abspath(os.path.join(_BACKEND_DIR, '..', '..', '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app import apply as apply_mod  # noqa: E402
from app import config_writer  # noqa: E402
from app import curation  # noqa: E402
from app import cv_config  # noqa: E402
from app import cv_replay  # noqa: E402
from app import export as export_mod  # noqa: E402
from app import masks as masks_mod  # noqa: E402
from app import replay as replay_mod  # noqa: E402
from app import registry  # noqa: E402
from app import transforms  # noqa: E402
from app import tub_loader  # noqa: E402

app = FastAPI(title='LOK', version='0.2.0')
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        'http://localhost:5173',
        'http://127.0.0.1:5173',
        'http://localhost:3000',
        'http://127.0.0.1:3000',
    ],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)


class TubOpenRequest(BaseModel):
    path: str


class AugEntry(BaseModel):
    name: str
    params: Dict[str, Union[float, int, List[float], str]] = Field(
        default_factory=dict
    )


class PreviewRequest(BaseModel):
    path: str
    indexes: List[int]
    augmentations: List[AugEntry] = Field(default_factory=list)
    transformations: List[str] = Field(default_factory=list)
    post_transformations: List[str] = Field(default_factory=list)
    roi: Dict[str, int] = Field(default_factory=dict)
    mask_metadata_path: Optional[str] = None
    mask_preset: Optional[str] = None
    apply_aug: bool = True
    mask_data: Optional[Dict[str, Any]] = None


class CvPreviewRequest(BaseModel):
    path: str
    indexes: List[int]
    cv_preprocess: List[str] = Field(default_factory=list)
    cv_debug_transformations: List[str] = Field(
        default_factory=lambda: ['RGB2GRAY', 'BLUR', 'CANNY']
    )
    cv_params: Dict[str, Any] = Field(default_factory=dict)
    roi: Dict[str, int] = Field(default_factory=dict)


class ExportRequest(BaseModel):
    augmentations: List[AugEntry] = Field(default_factory=list)
    transformations: Optional[List[str]] = None
    post_transformations: Optional[List[str]] = None
    roi: Optional[Dict[str, int]] = None
    excludes_path: Optional[str] = None
    masks_path: Optional[str] = None
    mask_preset: Optional[str] = None
    profile: str = 'training'
    cv_preprocess: Optional[List[str]] = None
    cv_debug_transformations: Optional[List[str]] = None
    cv_params: Optional[Dict[str, Any]] = None


class ConfigApplyRequest(BaseModel):
    myconfig_path: str
    augmentations: Optional[List[AugEntry]] = None
    transformations: Optional[List[str]] = None
    post_transformations: Optional[List[str]] = None
    roi: Optional[Dict[str, int]] = None
    excludes_path: Optional[str] = None
    masks_path: Optional[str] = None
    mask_preset: Optional[str] = None
    profile: str = 'training'
    cv_preprocess: Optional[List[str]] = None
    cv_debug_transformations: Optional[List[str]] = None
    cv_params: Optional[Dict[str, Any]] = None


class ConfigImportRequest(BaseModel):
    myconfig_path: str


class CvReplayRequest(BaseModel):
    tub_path: str
    myconfig_path: Optional[str] = None
    controller_module: Optional[str] = None
    controller_class: Optional[str] = None


class CurationLoadRequest(BaseModel):
    path: str


class CurationSaveRequest(BaseModel):
    path: str
    tub_path: str
    excluded_indexes: List[int]


class MasksLoadRequest(BaseModel):
    path: str


class MasksSaveRequest(BaseModel):
    path: str
    tub_path: str
    data: Dict[str, Any]


def _arr_to_b64(arr, fmt: str = 'JPEG', quality: int = 90,
                max_size=None) -> str:
    raw = tub_loader.encode_image(arr, fmt=fmt, quality=quality,
                                  max_size=max_size)
    return base64.b64encode(raw).decode('ascii')


@app.get('/api/health')
def health():
    return {'ok': True, 'app': 'lok'}


@app.get('/api/augmentations')
def get_augmentations():
    return registry.list_augmentations()


@app.get('/api/transforms')
def get_transforms():
    return transforms.list_transforms()


@app.get('/api/replay/options')
def replay_options():
    try:
        return replay_mod.list_options()
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get('/api/replay/{tub_id}')
def replay_tub(tub_id: str, model: str = Query(...)):
    try:
        return replay_mod.get_replay(tub_id, model)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e.args[0])) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post('/api/cv/replay')
def replay_cv_controller(body: CvReplayRequest):
    try:
        return cv_replay.run_replay(
            body.tub_path,
            myconfig_path=body.myconfig_path,
            controller_module=body.controller_module,
            controller_class=body.controller_class,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (AttributeError, ImportError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post('/api/tub/open')
def tub_open(body: TubOpenRequest):
    try:
        session = tub_loader.open_tub(body.path)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        'path': session.path,
        'total': len(session.records),
        'image_key': session.image_key,
        'inputs': session.inputs,
    }


@app.get('/api/tub/images')
def tub_images(
    path: str = Query(...),
    offset: int = Query(0, ge=0),
    limit: int = Query(48, ge=1, le=200),
    thumb: bool = Query(True),
    excludes_path: Optional[str] = Query(None),
):
    try:
        listing = tub_loader.list_images(path, offset=offset, limit=limit)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    excluded = set()
    if excludes_path:
        try:
            excluded = curation.excluded_set(excludes_path)
        except Exception:
            excluded = set()

    if thumb:
        for item in listing['images']:
            item['excluded'] = item['index'] in excluded
            try:
                arr = tub_loader.load_image_array(path, item['index'])
                item['thumb_b64'] = _arr_to_b64(
                    arr, quality=70, max_size=(160, 120)
                )
            except Exception:
                item['thumb_b64'] = None
    else:
        for item in listing['images']:
            item['excluded'] = item['index'] in excluded
    return listing


@app.get('/api/tub/image/{index}')
def tub_image(
    index: int,
    path: str = Query(...),
    format: str = Query('jpeg'),
):
    try:
        arr = tub_loader.load_image_array(path, index)
    except (FileNotFoundError, KeyError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    fmt = 'JPEG' if format.lower() in ('jpg', 'jpeg') else 'PNG'
    media = 'image/jpeg' if fmt == 'JPEG' else 'image/png'
    return Response(
        content=tub_loader.encode_image(arr, fmt=fmt, quality=92),
        media_type=media,
    )


@app.post('/api/preview')
def preview(body: PreviewRequest):
    if not body.indexes:
        raise HTTPException(status_code=400, detail='indexes must be non-empty')
    try:
        augs = [e.model_dump() for e in body.augmentations]
        results = apply_mod.preview_indexes(
            body.path,
            body.indexes,
            augs,
            prob=1.0,
            transformations=body.transformations,
            post_transformations=body.post_transformations,
            roi=body.roi,
            mask_metadata_path=body.mask_metadata_path,
            mask_preset=body.mask_preset,
            apply_aug=body.apply_aug,
            mask_data=body.mask_data,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (FileNotFoundError, KeyError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    out = []
    for r in results:
        out.append({
            'index': r['index'],
            'original_b64': _arr_to_b64(r['original']),
            'augmented_b64': _arr_to_b64(r['augmented']),
            'width': int(r['original'].shape[1]),
            'height': int(r['original'].shape[0]),
        })
    return {'results': out, 'preview_prob': 1.0}


@app.post('/api/cv/preview')
def cv_preview(body: CvPreviewRequest):
    if not body.indexes:
        raise HTTPException(status_code=400, detail='indexes must be non-empty')
    try:
        results = cv_config.preview_indexes(
            body.path,
            body.indexes,
            cv_preprocess=body.cv_preprocess,
            cv_debug_transformations=body.cv_debug_transformations,
            cv_params=body.cv_params,
            roi=body.roi,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (FileNotFoundError, KeyError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return {
        'results': [{
            'index': result['index'],
            'original_b64': _arr_to_b64(result['original']),
            'preprocessed_b64': _arr_to_b64(result['preprocessed']),
            'edges_b64': _arr_to_b64(result['edges']),
            'width': int(result['original'].shape[1]),
            'height': int(result['original'].shape[0]),
        } for result in results],
    }


@app.post('/api/export')
def export_config(body: ExportRequest):
    try:
        augs = [e.model_dump() for e in body.augmentations]
        if (body.transformations is not None
                or body.post_transformations is not None
                or body.roi is not None
                or body.excludes_path
                or body.masks_path
                or body.profile == 'cv_control'
                or body.cv_preprocess is not None
                or body.cv_debug_transformations is not None
                or body.cv_params is not None):
            snippet = export_mod.export_full_snippet(
                augmentations=augs,
                transformations=body.transformations,
                post_transformations=body.post_transformations,
                roi=body.roi,
                excludes_path=body.excludes_path,
                masks_path=body.masks_path,
                mask_preset=body.mask_preset,
                profile=body.profile,
                cv_preprocess=body.cv_preprocess,
                cv_debug_transformations=body.cv_debug_transformations,
                cv_params=body.cv_params,
            )
        else:
            snippet = export_mod.export_snippet(augs)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {'snippet': snippet}


@app.post('/api/config/apply')
def config_apply(body: ConfigApplyRequest):
    try:
        augs = (
            [e.model_dump() for e in body.augmentations]
            if body.augmentations is not None else None
        )
        built = export_mod.build_full_settings(
            augmentations=augs,
            transformations=body.transformations,
            post_transformations=body.post_transformations,
            roi=body.roi,
            excludes_path=body.excludes_path,
            masks_path=body.masks_path,
            mask_preset=body.mask_preset,
            profile=body.profile,
            cv_preprocess=body.cv_preprocess,
            cv_debug_transformations=body.cv_debug_transformations,
            cv_params=body.cv_params,
        )
        if not built['settings'] and not built['raw_blocks']:
            raise HTTPException(
                status_code=400, detail='Nothing to apply — tune something first'
            )
        result = config_writer.apply_settings(
            body.myconfig_path,
            built['settings'],
            raw_blocks=built['raw_blocks'],
        )
    except HTTPException:
        raise
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return result


@app.post('/api/config/import')
def config_import(body: ConfigImportRequest):
    try:
        return cv_config.load_myconfig(body.myconfig_path)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (SyntaxError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post('/api/curation/load')
def curation_load(body: CurationLoadRequest):
    try:
        return curation.load_excludes(body.path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post('/api/curation/save')
def curation_save(body: CurationSaveRequest):
    try:
        return curation.save_excludes(
            body.path, body.tub_path, body.excluded_indexes
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post('/api/curation/export')
def curation_export(body: CurationLoadRequest):
    try:
        return {'snippet': curation.export_train_filter_snippet(body.path)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post('/api/masks/load')
def masks_load(body: MasksLoadRequest):
    try:
        return masks_mod.load_masks(body.path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post('/api/masks/save')
def masks_save(body: MasksSaveRequest):
    try:
        return masks_mod.save_masks(body.path, body.tub_path, body.data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
