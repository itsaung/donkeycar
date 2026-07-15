# -*- coding: utf-8 -*-
import numpy as np

from donkeycar.config import Config
from donkeycar.parts.cv import ImgCanny, ImgCropMask, ImgTrapezoidalEdgeMask
from donkeycar.parts.cv_debug import CvDebugPipeline, CvUiImage, to_rgb_ui_image
from donkeycar.parts.image_transformations import ImageTransformations


def _solid_image(h=120, w=160, color=(10, 20, 30)):
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:, :] = color
    return img


def _cfg_with_defaults():
    cfg = Config()
    cfg.ROI_CROP_TOP = 20
    cfg.ROI_CROP_BOTTOM = 10
    cfg.ROI_CROP_LEFT = 5
    cfg.ROI_CROP_RIGHT = 5
    cfg.ROI_TRAPEZE_UL = 20
    cfg.ROI_TRAPEZE_UR = 20
    cfg.ROI_TRAPEZE_LL = 0
    cfg.ROI_TRAPEZE_LR = 0
    cfg.ROI_TRAPEZE_MIN_Y = 40
    cfg.ROI_TRAPEZE_MAX_Y = 100
    cfg.CANNY_LOW_THRESHOLD = 50
    cfg.CANNY_HIGH_THRESHOLD = 100
    cfg.CANNY_APERTURE = 3
    cfg.BLUR_KERNEL = 5
    cfg.BLUR_KERNEL_Y = None
    cfg.BLUR_GAUSSIAN = True
    cfg.CV_DEBUG_TRANSFORMATIONS = ['RGB2GRAY', 'BLUR', 'CANNY']
    return cfg


def test_img_crop_mask_zeros_borders():
    img = _solid_image(color=(255, 255, 255))
    out = ImgCropMask(left=5, top=20, right=5, bottom=10).run(img)
    assert out is not None
    # Cropped borders should be zero (bool mask multiply).
    # Use a margin inside the masked bands — OpenCV poly edges can be inclusive.
    assert out[:15, :, :].sum() == 0
    assert out[-5:, :, :].sum() == 0
    assert out[:, :3, :].sum() == 0
    assert out[:, -3:, :].sum() == 0
    # Interior should keep original white.
    assert out[40, 80, 0] == 255


def test_trapezoidal_edge_mask_keeps_center():
    img = _solid_image(color=(200, 200, 200))
    out = ImgTrapezoidalEdgeMask(
        upper_left=20, upper_right=20, lower_left=0, lower_right=0,
        top=40, bottom=20).run(img)
    assert out is not None
    # Top band outside trapeze should be masked out.
    assert out[10, 80, :].sum() == 0
    # Center of road ROI should remain.
    assert out[70, 80, 0] == 200


def test_img_canny_shape():
    # Vertical edge so Canny has something to detect.
    img = np.zeros((60, 80), dtype=np.uint8)
    img[:, 40:] = 255
    edges = ImgCanny(50, 100, 3).run(img)
    assert edges is not None
    assert edges.shape == (60, 80)
    assert edges.dtype == np.uint8
    assert edges.max() > 0


def test_image_transformations_end_to_end():
    cfg = _cfg_with_defaults()
    cfg.TRANSFORMATIONS = ['CROP', 'RGB2GRAY', 'CANNY']
    pipe = ImageTransformations(cfg, 'TRANSFORMATIONS')
    out = pipe.run(_solid_image())
    assert out is not None
    # Canny yields 2D; crop+gray+canny should still be HxW.
    assert out.ndim == 2
    assert out.shape[0] == 120
    assert out.shape[1] == 160


def test_to_rgb_ui_image_expands_gray():
    gray = np.zeros((10, 12), dtype=np.uint8)
    rgb = to_rgb_ui_image(gray)
    assert rgb.shape == (10, 12, 3)


def test_cv_debug_pipeline_returns_3_channel():
    cfg = _cfg_with_defaults()
    # Add a vertical edge so Canny is non-trivial.
    img = _solid_image()
    img[:, 80:] = (255, 255, 255)
    debug = CvDebugPipeline(cfg)
    out = debug.run(img)
    assert out is not None
    assert out.ndim == 3
    assert out.shape[2] == 3


def test_cv_debug_pipeline_disabled_when_empty():
    cfg = _cfg_with_defaults()
    cfg.CV_DEBUG_TRANSFORMATIONS = []
    debug = CvDebugPipeline(cfg)
    assert debug.run(_solid_image()) is None


def test_cv_ui_image_picker():
    overlay = _solid_image(color=(1, 2, 3))
    dbg = _solid_image(color=(9, 9, 9))
    picker = CvUiImage(show_debug=False)
    assert picker.run(overlay, dbg) is overlay
    picker_dbg = CvUiImage(show_debug=True)
    assert picker_dbg.run(overlay, dbg) is dbg
    assert picker_dbg.run(overlay, None) is overlay
