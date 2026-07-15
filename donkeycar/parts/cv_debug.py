"""
CV debug helpers for Track 2: edge/mask preview without feeding Canny into
color-based controllers like LineFollower.
"""

import logging

import numpy as np

from donkeycar.parts.image_transformations import ImageTransformations

logger = logging.getLogger(__name__)


def to_rgb_ui_image(image):
    """
    Ensure an image is HxWx3 uint8 for the web UI.
    Expands single-channel (gray / Canny) images to RGB.
    """
    if image is None:
        return None
    arr = np.asarray(image)
    if arr.ndim == 2:
        return np.stack([arr, arr, arr], axis=-1)
    if arr.ndim == 3 and arr.shape[2] == 1:
        return np.repeat(arr, 3, axis=2)
    return arr


class CvDebugPipeline:
    """
    Run a configured transformation list (typically gray → blur → Canny)
    and emit a 3-channel image suitable for the web UI.
    """

    def __init__(self, cfg, transformations_attr='CV_DEBUG_TRANSFORMATIONS'):
        names = getattr(cfg, transformations_attr, None) or []
        self.enabled = len(names) > 0
        self.pipeline = None
        if self.enabled:
            self.pipeline = ImageTransformations(cfg, transformations_attr)
            logger.info("CvDebugPipeline enabled: %s", names)

    def run(self, image):
        if not self.enabled or image is None or self.pipeline is None:
            return None
        out = self.pipeline.run(image)
        return to_rgb_ui_image(out)

    def shutdown(self):
        pass


class CvUiImage:
    """
    Pick which CV image the web UI shows in pilot/overlay mode.

    When show_debug is True and a debug frame is available, prefer it;
    otherwise pass through the controller overlay image.
    """

    def __init__(self, show_debug=False):
        self.show_debug = bool(show_debug)

    def run(self, overlay_image=None, debug_image=None):
        if self.show_debug and debug_image is not None:
            return debug_image
        return overlay_image

    def shutdown(self):
        pass
