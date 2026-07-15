#!/usr/bin/env python3
"""
Offline CV pipeline lab for Track 2 Phase 0.

Tune CROP / TRAPEZE / CANNY on a saved camera frame without running the car.

Example:
  python tools/cv_pipeline_lab.py --image frame.jpg --out /tmp/cv_lab \\
    --preprocess CROP,TRAPEZE_EDGE --debug RGB2GRAY,BLUR,CANNY
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np
from PIL import Image

# Allow running from repo root without install.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from donkeycar.config import Config
from donkeycar.parts.cv_debug import to_rgb_ui_image
from donkeycar.parts.image_transformations import ImageTransformations, image_transformer


def _parse_list(value: str):
    if not value:
        return []
    return [part.strip() for part in value.split(',') if part.strip()]


def _default_cfg() -> Config:
    cfg = Config()
    cfg.CV_PREPROCESS = []
    cfg.CV_DEBUG_TRANSFORMATIONS = ['RGB2GRAY', 'BLUR', 'CANNY']
    cfg.ROI_CROP_TOP = 45
    cfg.ROI_CROP_BOTTOM = 0
    cfg.ROI_CROP_RIGHT = 0
    cfg.ROI_CROP_LEFT = 0
    cfg.ROI_TRAPEZE_LL = 0
    cfg.ROI_TRAPEZE_LR = 160
    cfg.ROI_TRAPEZE_UL = 20
    cfg.ROI_TRAPEZE_UR = 140
    cfg.ROI_TRAPEZE_MIN_Y = 60
    cfg.ROI_TRAPEZE_MAX_Y = 120
    cfg.CANNY_LOW_THRESHOLD = 60
    cfg.CANNY_HIGH_THRESHOLD = 110
    cfg.CANNY_APERTURE = 3
    cfg.BLUR_KERNEL = 5
    cfg.BLUR_KERNEL_Y = None
    cfg.BLUR_GAUSSIAN = True
    return cfg


def _load_image(path: str) -> np.ndarray:
    img = Image.open(path).convert('RGB')
    return np.asarray(img)


def _save_image(path: str, arr: np.ndarray) -> None:
    arr = to_rgb_ui_image(arr)
    if arr is None:
        raise ValueError(f"nothing to save for {path}")
    Image.fromarray(np.asarray(arr, dtype=np.uint8)).save(path)


def _side_by_side(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    left = to_rgb_ui_image(left)
    right = to_rgb_ui_image(right)
    if left.shape[0] != right.shape[0]:
        # Resize right height to match left via simple PIL.
        right_img = Image.fromarray(right.astype(np.uint8)).resize(
            (right.shape[1], left.shape[0]))
        right = np.asarray(right_img)
    return np.concatenate([left, right], axis=1)


def run_lab(image_path: str, out_dir: str, preprocess, debug, cfg: Config):
    os.makedirs(out_dir, exist_ok=True)
    original = _load_image(image_path)
    _save_image(os.path.join(out_dir, '00_original.jpg'), original)

    current = original
    step = 1
    for name in preprocess:
        transformer = image_transformer(name, cfg)
        current = transformer.run(current)
        _save_image(
            os.path.join(out_dir, f'{step:02d}_preprocess_{name}.jpg'),
            current)
        step += 1

    preprocessed = current
    if preprocess:
        _save_image(os.path.join(out_dir, 'preprocessed.jpg'), preprocessed)

    debug_img = preprocessed
    for name in debug:
        transformer = image_transformer(name, cfg)
        debug_img = transformer.run(debug_img)
        _save_image(
            os.path.join(out_dir, f'{step:02d}_debug_{name}.jpg'), debug_img)
        step += 1

    if debug:
        debug_rgb = to_rgb_ui_image(debug_img)
        _save_image(os.path.join(out_dir, 'debug_final.jpg'), debug_rgb)
        combo = _side_by_side(original, debug_rgb)
        _save_image(os.path.join(out_dir, 'compare_original_vs_debug.jpg'),
                    combo)

    # Also exercise ImageTransformations composition (same as drive path).
    if preprocess:
        cfg.CV_PREPROCESS = list(preprocess)
        composed = ImageTransformations(cfg, 'CV_PREPROCESS').run(original)
        _save_image(os.path.join(out_dir, 'composed_preprocess.jpg'), composed)

    print(f"Wrote CV lab outputs to {out_dir}")
    print("Copy tuned knobs into myconfig.py (ROI_*, CANNY_*, BLUR_*, CV_*).")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Offline DonkeyCar CV pipeline lab (crop / trapeze / Canny)')
    parser.add_argument('--image', required=True, help='Input RGB image path')
    parser.add_argument('--out', default='/tmp/cv_lab', help='Output directory')
    parser.add_argument(
        '--preprocess', default='CROP',
        help='Comma-separated preprocess transforms (RGB-safe). '
             'Example: CROP,TRAPEZE_EDGE')
    parser.add_argument(
        '--debug', default='RGB2GRAY,BLUR,CANNY',
        help='Comma-separated debug transforms. '
             'Example: RGB2GRAY,BLUR,CANNY')
    parser.add_argument('--config', default=None,
                        help='Optional config.py / myconfig.py to load knobs from')
    parser.add_argument('--canny-low', type=int, default=None)
    parser.add_argument('--canny-high', type=int, default=None)
    parser.add_argument('--crop-top', type=int, default=None)
    parser.add_argument('--crop-bottom', type=int, default=None)
    args = parser.parse_args(argv)

    if args.config:
        cfg = Config()
        cfg.from_pyfile(args.config)
    else:
        cfg = _default_cfg()

    if args.canny_low is not None:
        cfg.CANNY_LOW_THRESHOLD = args.canny_low
    if args.canny_high is not None:
        cfg.CANNY_HIGH_THRESHOLD = args.canny_high
    if args.crop_top is not None:
        cfg.ROI_CROP_TOP = args.crop_top
    if args.crop_bottom is not None:
        cfg.ROI_CROP_BOTTOM = args.crop_bottom

    run_lab(
        args.image,
        args.out,
        _parse_list(args.preprocess),
        _parse_list(args.debug),
        cfg,
    )


if __name__ == '__main__':
    main()
