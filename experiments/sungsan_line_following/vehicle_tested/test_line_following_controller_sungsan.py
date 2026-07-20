import importlib.util
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
from simple_pid import PID


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


line_follower = load_module(
    "line_following_controller_sungsan",
    str(Path(__file__).with_name(
        "line_following_controller_sungsan.py"
    )),
)


def make_cfg(**overrides):
    values = dict(
        OVERLAY_IMAGE=True,
        IMAGE_W=160,
        IMAGE_H=120,
        SCAN_Y=70,
        SCAN_HEIGHT=28,
        SCAN_EXTRA_ROWS=1,
        CV_INPUT_COLOR_ORDER="BGR",
        COLOR_THRESHOLD_LOW=(18, 18, 35),
        COLOR_THRESHOLD_HIGH=(35, 255, 255),
        COLOR_THRESHOLD_LOW_2=None,
        COLOR_THRESHOLD_HIGH_2=None,
        COLOR_DOMINANCE_MODE="YELLOW",
        COLOR_MIN_DOMINANCE=8,
        COLOR_MAX_CHANNEL_DIFF=30,
        TARGET_PIXEL=None,
        TARGET_THRESHOLD=10,
        CONFIDENCE_THRESHOLD=0.05,
        MAX_LINE_WIDTH_PX=25,
        MIN_LINE_ASPECT_RATIO=0.15,
        MIN_LINE_AREA_PX=6,
        MIN_TAPE_QUALITY=0.55,
        TAPE_WIDTH_REFERENCE_PX=9,
        TAPE_AREA_REFERENCE_PX=18,
        TAPE_SATURATION_REFERENCE=90,
        TAPE_VALUE_REFERENCE=220,
        MASK_MORPH_KERNEL_PX=1,
        MAX_LINE_JUMP_PX=40,
        ACQUIRE_MAX_DISTANCE_PX=75,
        MIN_TRACKED_SIZE_RATIO=0.45,
        LINE_VELOCITY_SMOOTHING=0.5,
        LINE_PREDICTION_FRAMES=2.0,
        MAX_PREDICTED_SHIFT_PX=18,
        LINE_VELOCITY_DECAY=0.8,
        SIDE_REVERSAL_MARGIN_PX=8,
        REACQUIRE_LINE_AFTER_FRAMES=5,
        LINE_POSITION_SMOOTHING=0.65,
        THROTTLE_INITIAL=0.25,
        THROTTLE_STEP=0.02,
        THROTTLE_MAX=0.35,
        THROTTLE_MIN=0.25,
        NO_LINE_STOP_FRAMES=5,
        NO_LINE_THROTTLE_STEP=0.05,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def bgr_from_hsv(hue, saturation=180, value=200):
    hsv = np.uint8([[[hue, saturation, value]]])
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)[0, 0]


def controller(cfg=None):
    return line_follower.LineFollower(
        PID(-0.01, 0.0, -0.0001), cfg or make_cfg()
    )


def test_prefers_deeper_curve_dash_over_centered_far_dash():
    image = np.full((120, 160, 3), 90, dtype=np.uint8)
    yellow = bgr_from_hsv(25, 110, 220)
    image[75:79, 77:86] = yellow
    image[103:111, 96:118] = yellow

    line_x, confidence, _mask = controller().get_i_color(image)

    assert 100 <= line_x <= 113
    assert confidence >= 0.20


def test_rejects_gray_cyan_and_small_yellow_leaf():
    image = np.full((120, 160, 3), 90, dtype=np.uint8)
    image[70:98, 76:84] = (120, 120, 120)
    image[70:98, 88:96] = bgr_from_hsv(90, 120, 180)
    image[104:107, 92:95] = bgr_from_hsv(25, 110, 220)

    line_x, confidence, _mask = controller().get_i_color(image)

    assert line_x == 0
    assert confidence == 0.0


def test_prefers_far_curve_tape_over_small_near_leaf():
    yellow = bgr_from_hsv(25, 110, 220)
    control = controller()

    first = np.full((120, 160, 3), 90, dtype=np.uint8)
    first[98:108, 84:96] = yellow
    control.get_i_color(first)

    second = np.full((120, 160, 3), 90, dtype=np.uint8)
    second[96:106, 100:112] = yellow
    control.get_i_color(second)

    curve = np.full((120, 160, 3), 90, dtype=np.uint8)
    curve[104:107, 92:95] = yellow  # small yellow leaf near center
    curve[88:97, 135:151] = yellow  # real dash on the sharp right curve

    line_x, confidence, _mask = control.get_i_color(curve)

    # The selected raw dash is centered near x=143; position smoothing keeps
    # the control output from jumping there in a single frame.
    assert 120 <= line_x <= 140
    assert confidence >= 0.20


def test_does_not_reverse_from_right_curve_to_left_leaf():
    yellow = bgr_from_hsv(25, 110, 220)
    control = controller()

    line = np.full((120, 160, 3), 90, dtype=np.uint8)
    line[96:108, 105:121] = yellow
    control.get_i_color(line)

    left_leaf = np.full((120, 160, 3), 90, dtype=np.uint8)
    left_leaf[96:104, 45:57] = yellow

    line_x, confidence, _mask = control.get_i_color(left_leaf)

    assert line_x == 0
    assert confidence == 0.0


def test_overlay_converts_oak_bgr_to_web_rgb():
    image = np.full((120, 160, 3), (10, 20, 30), dtype=np.uint8)
    image[103:111, 96:118] = bgr_from_hsv(25, 110, 220)

    _steering, _throttle, overlay = controller().run(image)

    assert tuple(overlay[119, 159]) == (30, 20, 10)


def test_stops_after_five_missed_frames():
    control = controller()
    blank = np.full((120, 160, 3), 90, dtype=np.uint8)
    control.steering = 0.4

    for _index in range(5):
        steering, throttle, _overlay = control.run(blank)

    assert steering == 0.0
    assert throttle == 0.0
