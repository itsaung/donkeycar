from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from simple_pid import PID

from donkeycar.parts.line_follower import LineFollower


def make_cfg(**overrides):
    values = dict(
        OVERLAY_IMAGE=True,
        IMAGE_W=160,
        IMAGE_H=120,
        SCAN_Y=70,
        SCAN_HEIGHT=20,
        SCAN_EXTRA_ROWS=0,
        COLOR_THRESHOLD_LOW=(15, 80, 80),
        COLOR_THRESHOLD_HIGH=(40, 255, 255),
        COLOR_THRESHOLD_LOW_2=(80, 60, 80),
        COLOR_THRESHOLD_HIGH_2=(100, 255, 255),
        TARGET_PIXEL=None,
        TARGET_THRESHOLD=10,
        CONFIDENCE_THRESHOLD=0.05,
        MAX_LINE_WIDTH_PX=25,
        MIN_LINE_ASPECT_RATIO=0.55,
        MIN_LINE_AREA_PX=6,
        MASK_MORPH_KERNEL_PX=1,
        MAX_LINE_JUMP_PX=25,
        REACQUIRE_LINE_AFTER_FRAMES=3,
        LINE_POSITION_SMOOTHING=1.0,
        THROTTLE_INITIAL=0.15,
        THROTTLE_STEP=0.05,
        THROTTLE_MAX=0.3,
        THROTTLE_MIN=0.15,
        NO_LINE_STOP_FRAMES=3,
        NO_LINE_THROTTLE_STEP=0.05,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def hsv_rgb(hue, saturation=180, value=220):
    hsv = np.uint8([[[hue, saturation, value]]])
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)[0, 0]


def test_scales_scan_and_detects_secondary_colour():
    image = np.zeros((480, 640, 3), dtype=np.uint8)
    image[280:360, 316:325] = hsv_rgb(90)
    controller = LineFollower(PID(-0.01, 0.0, 0.0), make_cfg())

    steering, throttle, overlay = controller.run(image)

    assert controller._geometry == (280, 80)
    assert controller.target_pixel == 320
    assert abs(steering) < 0.02
    assert throttle == 0.2
    assert overlay.shape == image.shape


def test_target_defaults_to_center_not_first_detection():
    image = np.zeros((120, 160, 3), dtype=np.uint8)
    image[70:90, 38:43] = hsv_rgb(90)
    controller = LineFollower(PID(-0.01, 0.0, 0.0), make_cfg())

    steering, _throttle, _overlay = controller.run(image)

    assert controller.target_pixel == 80
    assert steering < 0.0


def test_confidence_is_normalized_fraction():
    image = np.zeros((120, 160, 3), dtype=np.uint8)
    image[70:80, 80:83] = hsv_rgb(90)
    controller = LineFollower(PID(-0.01, 0.0, 0.0), make_cfg())

    line_x, confidence, _mask = controller.get_i_color(image)

    assert 80 <= line_x <= 82
    assert confidence == 0.5


def test_stops_safely_after_consecutive_misses():
    image = np.zeros((120, 160, 3), dtype=np.uint8)
    controller = LineFollower(
        PID(-0.01, 0.0, 0.0),
        make_cfg(THROTTLE_INITIAL=0.15, NO_LINE_STOP_FRAMES=3),
    )
    controller.steering = 0.4

    first = controller.run(image)
    second = controller.run(image)
    third = controller.run(image)

    assert first[1] == pytest.approx(0.10)
    assert second[1] == pytest.approx(0.05)
    assert third[0] == 0.0
    assert third[1] == 0.0


def test_rejects_broad_background_colour_region():
    image = np.zeros((480, 640, 3), dtype=np.uint8)
    colour = hsv_rgb(90)
    image[280:360, 0:130] = colour
    image[280:360, 445:465] = colour
    controller = LineFollower(PID(-0.01, 0.0, 0.0), make_cfg())

    line_x, confidence, _mask = controller.get_i_color(image)

    assert 445 <= line_x <= 464
    assert confidence > 0.5


def test_rejects_speckles_and_far_wall_while_tracking_line():
    colour = hsv_rgb(90)
    controller = LineFollower(PID(-0.01, 0.0, 0.0), make_cfg())

    first = np.zeros((120, 160, 3), dtype=np.uint8)
    first[70:90, 77:83] = colour
    first_x, first_confidence, _mask = controller.get_i_color(first)
    assert 77 <= first_x <= 82
    assert first_confidence > 0.5

    second = np.zeros((120, 160, 3), dtype=np.uint8)
    second[70:90, 80:86] = colour
    second[70:90, 145:149] = colour  # wall-coloured vertical edge
    second[72:74, 20:22] = colour    # isolated camera speckle
    line_x, confidence, _mask = controller.get_i_color(second)

    assert 80 <= line_x <= 85
    assert confidence > 0.5


def test_rejects_only_candidate_when_it_jumps_to_far_wall():
    colour = hsv_rgb(90)
    controller = LineFollower(PID(-0.01, 0.0, 0.0), make_cfg())

    first = np.zeros((120, 160, 3), dtype=np.uint8)
    first[70:90, 77:83] = colour
    controller.get_i_color(first)

    wall_only = np.zeros((120, 160, 3), dtype=np.uint8)
    wall_only[70:90, 145:149] = colour
    line_x, confidence, _mask = controller.get_i_color(wall_only)

    assert line_x == 0
    assert confidence == 0.0


def test_overlay_keeps_camera_visible_under_detection_mask():
    colour = hsv_rgb(90)
    image = np.full((120, 160, 3), 60, dtype=np.uint8)
    image[70:90, 77:83] = colour
    controller = LineFollower(PID(-0.01, 0.0, 0.0), make_cfg())

    _steering, _throttle, overlay = controller.run(image)

    # The old overlay replaced the whole scan band with black/white pixels.
    assert np.all(overlay[75, 10] != 0)
    assert np.any(overlay[75, 80] != 255)
