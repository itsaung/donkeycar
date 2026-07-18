import json
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
    str(Path(__file__).with_name("line_following_controller_sungsan.py")),
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
        MASK_MORPH_KERNEL_PX=1,
        MAX_LINE_JUMP_PX=25,
        ACQUIRE_MAX_DISTANCE_PX=30,
        REACQUIRE_LINE_AFTER_FRAMES=5,
        LINE_POSITION_SMOOTHING=0.65,
        THROTTLE_INITIAL=0.25,
        THROTTLE_STEP=0.02,
        THROTTLE_MAX=0.35,
        THROTTLE_MIN=0.25,
        NO_LINE_STOP_FRAMES=5,
        NO_LINE_THROTTLE_STEP=0.05,
        CV_DEBUG_CAPTURE=False,
        CV_DEBUG_CAPTURE_DIR="/private/tmp/unused_debug_capture",
        CV_DEBUG_CAPTURE_EVERY_N_FRAMES=10,
        CV_DEBUG_CAPTURE_SAVE_OVERLAY=True,
        CV_DEBUG_CAPTURE_JPEG_QUALITY=85,
        CV_DEBUG_CAPTURE_QUEUE_SIZE=8,
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


def test_detects_horizontal_yellow_curve_dash():
    image = np.full((120, 160, 3), 90, dtype=np.uint8)
    image[103:111, 96:118] = bgr_from_hsv(25, 110, 220)

    line_x, confidence, _mask = controller().get_i_color(image)

    assert 100 <= line_x <= 113
    assert confidence >= 0.20


def test_prefers_deeper_curve_dash_over_centered_far_dash():
    image = np.full((120, 160, 3), 90, dtype=np.uint8)
    yellow = bgr_from_hsv(25, 110, 220)
    image[75:79, 77:86] = yellow
    image[103:111, 96:118] = yellow

    line_x, confidence, _mask = controller().get_i_color(image)

    assert 100 <= line_x <= 113
    assert confidence >= 0.20


def test_rejects_gray_cyan_and_far_initial_candidate():
    image = np.full((120, 160, 3), 90, dtype=np.uint8)
    image[70:98, 76:84] = (120, 120, 120)
    image[70:98, 88:96] = bgr_from_hsv(90, 120, 180)
    image[70:98, 140:148] = bgr_from_hsv(25, 110, 220)

    line_x, confidence, _mask = controller().get_i_color(image)

    assert line_x == 0
    assert confidence == 0.0


def test_overlay_converts_oak_bgr_to_web_rgb():
    image = np.full((120, 160, 3), (10, 20, 30), dtype=np.uint8)
    image[103:111, 96:118] = bgr_from_hsv(25, 110, 220)
    control = controller()

    _steering, _throttle, overlay = control.run(image)

    assert tuple(overlay[119, 159]) == (30, 20, 10)


def test_automatic_debug_capture_saves_pairs_and_metadata(tmp_path):
    cfg = make_cfg(
        CV_DEBUG_CAPTURE=True,
        CV_DEBUG_CAPTURE_DIR=str(tmp_path),
        CV_DEBUG_CAPTURE_EVERY_N_FRAMES=2,
    )
    image = np.full((120, 160, 3), 90, dtype=np.uint8)
    image[103:111, 96:118] = bgr_from_hsv(25, 110, 220)
    control = controller(cfg)

    for _index in range(5):
        control.run(image)
    control.shutdown()

    sessions = list(tmp_path.glob("session_*"))
    assert len(sessions) == 1
    session = sessions[0]
    raw_files = sorted(session.glob("*_raw.jpg"))
    overlay_files = sorted(session.glob("*_overlay.jpg"))
    assert len(raw_files) == 3
    assert len(overlay_files) == 3
    assert (session / "session.json").exists()
    records = [
        json.loads(line)
        for line in (session / "frames.jsonl").read_text().splitlines()
    ]
    assert len(records) == 3
    assert records[0]["reason"] == ["line_state_changed"]
    assert records[0]["line_detected"] is True
    assert records[0]["raw_file"].endswith("_raw.jpg")
    assert records[0]["overlay_file"].endswith("_overlay.jpg")
