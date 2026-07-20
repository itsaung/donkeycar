import importlib.util
import json
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
        MAX_LINE_JUMP_PX=20,
        ACQUIRE_MAX_DISTANCE_PX=75,
        MIN_TRACKED_SIZE_RATIO=0.45,
        LINE_VELOCITY_SMOOTHING=0.5,
        LINE_PREDICTION_FRAMES=2.0,
        MAX_PREDICTED_SHIFT_PX=10,
        LINE_VELOCITY_DECAY=0.8,
        SIDE_REVERSAL_MARGIN_PX=8,
        PATH_MIN_COMPONENTS=2,
        PATH_X_TOLERANCE_PX=8,
        PATH_MAX_SLOPE=3.5,
        PATH_MIN_VERTICAL_GAP_PX=4,
        PATH_FIT_RESIDUAL_PX=6,
        PATH_SUPPORT_WEIGHT=2.0,
        PATH_ALIGNMENT_WEIGHT=0.75,
        REACQUIRE_MIN_PATH_ALIGNMENT=0.20,
        JUMP_MIN_PATH_ALIGNMENT=0.30,
        PATH_ALIGNMENT_JUMP_THRESHOLD_PX=8,
        ISOLATED_TRACK_DISTANCE_PX=8,
        EDGE_REACQUIRE_DISTANCE_PX=45,
        EDGE_REACQUIRE_MIN_COMPONENTS=3,
        EDGE_REACQUIRE_HISTORY_DISTANCE_PX=25,
        EDGE_REACQUIRE_HISTORY_MIN_COMPONENTS=2,
        EDGE_REACQUIRE_HISTORY_MIN_TAPE_QUALITY=0.90,
        REACQUIRE_MIN_SATURATION=35,
        REACQUIRE_LINE_AFTER_FRAMES=3,
        REACQUIRE_CONFIRM_FRAMES=3,
        REACQUIRE_CONFIRM_DISTANCE_PX=18,
        LINE_POSITION_SMOOTHING=0.65,
        ILLUMINATION_GUARD_ENABLED=True,
        ILLUMINATION_CHANGE_THRESHOLD=35,
        ILLUMINATION_STABLE_THRESHOLD=8,
        ILLUMINATION_HOLD_FRAMES=4,
        CV_DEBUG_CAPTURE=False,
        CV_DEBUG_CAPTURE_DIR="/private/tmp/unused_debug_capture",
        CV_DEBUG_CAPTURE_EVERY_N_FRAMES=40,
        CV_DEBUG_CAPTURE_SAVE_OVERLAY=True,
        CV_DEBUG_CAPTURE_JPEG_QUALITY=85,
        CV_DEBUG_CAPTURE_QUEUE_SIZE=16,
        CV_DEBUG_CAPTURE_MAX_FRAMES=500,
        THROTTLE_INITIAL=0.22,
        THROTTLE_STEP=0.02,
        THROTTLE_MAX=0.27,
        THROTTLE_MIN=0.21,
        THROTTLE_STRAIGHT=0.27,
        THROTTLE_CURVE=0.21,
        THROTTLE_ACCEL_STEP=0.005,
        THROTTLE_DECEL_STEP=0.02,
        CURVE_STEERING_START=0.08,
        CURVE_STEERING_FULL=0.25,
        CURVE_PATH_SLOPE_START=0.8,
        CURVE_PATH_SLOPE_FULL=2.5,
        LOW_CONFIDENCE_THRESHOLD=0.15,
        LOW_CONFIDENCE_THROTTLE=0.21,
        NO_LINE_STOP_FRAMES=3,
        NO_LINE_THROTTLE_STEP=0.09,
        NO_LINE_GRACE_FRAMES=1,
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


def confirmed_detection(control, image):
    result = None
    for _index in range(control.reacquire_confirm_frames):
        result = control.get_i_color(image)
    return result


def test_prefers_deeper_curve_dash_over_centered_far_dash():
    image = np.full((120, 160, 3), 90, dtype=np.uint8)
    yellow = bgr_from_hsv(25, 110, 220)
    image[75:79, 77:86] = yellow
    image[103:111, 96:118] = yellow

    control = controller()
    line_x, confidence, _mask = confirmed_detection(control, image)

    assert 100 <= line_x <= 113
    assert confidence >= 0.20


def test_rejects_gray_cyan_and_small_yellow_leaf():
    image = np.full((120, 160, 3), 90, dtype=np.uint8)
    image[70:98, 76:84] = (120, 120, 120)
    image[70:98, 88:96] = bgr_from_hsv(90, 120, 180)
    image[104:107, 92:95] = bgr_from_hsv(25, 110, 220)

    control = controller()
    line_x, confidence, _mask = confirmed_detection(control, image)

    assert line_x == 0
    assert confidence == 0.0


def test_prefers_far_curve_tape_over_small_near_leaf():
    yellow = bgr_from_hsv(25, 110, 220)
    control = controller()

    first = np.full((120, 160, 3), 90, dtype=np.uint8)
    first[98:108, 84:96] = yellow
    first[76:83, 79:88] = yellow
    confirmed_detection(control, first)

    second = np.full((120, 160, 3), 90, dtype=np.uint8)
    second[96:106, 100:112] = yellow
    second[74:81, 91:100] = yellow
    control.get_i_color(second)

    third = np.full((120, 160, 3), 90, dtype=np.uint8)
    third[94:104, 116:128] = yellow
    third[72:79, 106:116] = yellow
    control.get_i_color(third)

    curve = np.full((120, 160, 3), 90, dtype=np.uint8)
    curve[104:107, 92:95] = yellow  # small yellow leaf near center
    curve[88:97, 135:151] = yellow  # real dash on the sharp right curve
    curve[70:78, 124:135] = yellow  # supporting dash on the same curve

    line_x, confidence, _mask = control.get_i_color(curve)

    # The selected raw dash is centered near x=143; position smoothing keeps
    # the control output from jumping there in a single frame.
    assert 118 <= line_x <= 140
    assert confidence >= 0.20


def test_does_not_reverse_from_right_curve_to_left_leaf():
    yellow = bgr_from_hsv(25, 110, 220)
    control = controller()

    line = np.full((120, 160, 3), 90, dtype=np.uint8)
    line[96:108, 105:121] = yellow
    line[73:81, 96:106] = yellow
    confirmed_detection(control, line)

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


def test_stops_after_three_missed_frames():
    control = controller()
    blank = np.full((120, 160, 3), 90, dtype=np.uint8)
    control.steering = 0.4

    for _index in range(3):
        steering, throttle, _overlay = control.run(blank)

    assert steering == 0.0
    assert throttle == 0.0


def test_links_steep_curve_tape_instead_of_gray_vertical_distractor():
    image = np.full((120, 160, 3), 180, dtype=np.uint8)
    yellow = bgr_from_hsv(25, 90, 230)
    gray_beige = bgr_from_hsv(25, 32, 200)
    # Three pieces from a sharp bend (about 2 reference pixels sideways for
    # every reference pixel upward), matching the failed physical frame.
    image[100:110, 56:66] = yellow
    image[83:92, 90:101] = yellow
    image[70:78, 116:127] = yellow
    # Low-saturation wall/paint fragments that used to win after a loss.
    image[100:109, 43:52] = gray_beige
    image[76:84, 43:52] = gray_beige

    control = controller()
    line_x, confidence, _ = confirmed_detection(control, image)

    assert 55 <= line_x <= 70
    assert confidence >= 0.20
    assert control.selected_path_support >= 3
    assert abs(control.selected_path_slope) > 1.5


def test_reacquire_rejects_low_saturation_wall_fragments():
    image = np.full((120, 160, 3), 180, dtype=np.uint8)
    gray_beige = bgr_from_hsv(25, 32, 200)
    image[100:110, 76:86] = gray_beige
    image[82:91, 76:86] = gray_beige
    image[70:78, 76:86] = gray_beige

    line_x, confidence, _ = confirmed_detection(controller(), image)

    assert line_x == 0
    assert confidence == 0.0


def test_far_edge_needs_three_connected_tape_pieces_to_reacquire():
    yellow = bgr_from_hsv(25, 120, 230)
    two_piece = np.full((120, 160, 3), 180, dtype=np.uint8)
    two_piece[100:110, 145:155] = yellow
    two_piece[76:85, 140:150] = yellow
    line_x, confidence, _ = confirmed_detection(controller(), two_piece)
    assert line_x == 0
    assert confidence == 0.0

    three_piece = two_piece.copy()
    three_piece[70:75, 135:145] = yellow
    control = controller()
    line_x, confidence, _ = confirmed_detection(control, three_piece)
    assert 140 <= line_x <= 155
    assert confidence >= 0.20
    assert control.selected_path_support >= 3


def test_far_edge_two_piece_path_can_reacquire_near_tracking_history():
    cfg = make_cfg(ILLUMINATION_GUARD_ENABLED=False)
    control = controller(cfg)
    yellow = bgr_from_hsv(25, 120, 230)
    three_piece = np.full((120, 160, 3), 180, dtype=np.uint8)
    three_piece[100:110, 145:155] = yellow
    three_piece[76:85, 140:150] = yellow
    three_piece[70:75, 135:145] = yellow

    for _index in range(control.reacquire_confirm_frames):
        control.run(three_piece)
    assert control.previous_line_x >= 140

    blank = np.full((120, 160, 3), 180, dtype=np.uint8)
    for _index in range(control.no_line_stop_frames):
        control.run(blank)
    assert control.throttle == 0.0

    two_piece = np.full((120, 160, 3), 180, dtype=np.uint8)
    two_piece[100:110, 145:155] = yellow
    two_piece[76:85, 140:150] = yellow
    for _index in range(control.reacquire_confirm_frames - 1):
        _steering, throttle, _ = control.run(two_piece)
        assert throttle == 0.0

    _steering, throttle, _ = control.run(two_piece)
    assert throttle == control.throttle_min
    assert control.selected_path_support == 2


def test_tracking_history_does_not_accept_two_weak_edge_blobs():
    cfg = make_cfg(ILLUMINATION_GUARD_ENABLED=False)
    control = controller(cfg)
    yellow = bgr_from_hsv(25, 120, 230)
    three_piece = np.full((120, 160, 3), 180, dtype=np.uint8)
    three_piece[100:110, 145:155] = yellow
    three_piece[76:85, 140:150] = yellow
    three_piece[70:75, 135:145] = yellow
    for _index in range(control.reacquire_confirm_frames):
        control.run(three_piece)

    blank = np.full((120, 160, 3), 180, dtype=np.uint8)
    for _index in range(control.no_line_stop_frames):
        control.run(blank)

    weak_blobs = np.full((120, 160, 3), 180, dtype=np.uint8)
    weak_blobs[102:106, 147:151] = yellow
    weak_blobs[78:82, 142:146] = yellow
    for _index in range(control.reacquire_confirm_frames + 1):
        steering, throttle, _ = control.run(weak_blobs)

    assert steering == 0.0
    assert throttle == 0.0


def test_curve_path_brakes_before_large_steering_error():
    cfg = make_cfg(ILLUMINATION_GUARD_ENABLED=False)
    control = controller(cfg)
    yellow = bgr_from_hsv(25, 120, 230)
    straight = np.full((120, 160, 3), 180, dtype=np.uint8)
    straight[100:110, 76:86] = yellow
    straight[72:81, 76:86] = yellow

    for _index in range(15):
        _steering, throttle, _ = control.run(straight)
    assert 0.265 <= throttle <= 0.27

    curve = np.full((120, 160, 3), 180, dtype=np.uint8)
    curve[100:110, 79:89] = yellow
    curve[72:81, 142:152] = yellow
    for _index in range(3):
        _steering, throttle, _ = control.run(curve)

    assert control.curve_strength >= 0.75
    assert 0.20 <= throttle <= 0.225


def test_one_missed_frame_keeps_drivable_curve_throttle():
    cfg = make_cfg(ILLUMINATION_GUARD_ENABLED=False)
    control = controller(cfg)
    yellow = bgr_from_hsv(25, 120, 230)
    line = np.full((120, 160, 3), 180, dtype=np.uint8)
    line[100:110, 76:86] = yellow
    line[72:81, 76:86] = yellow
    for _index in range(15):
        control.run(line)
    assert control.throttle >= 0.265

    blank = np.full((120, 160, 3), 180, dtype=np.uint8)
    _steering, throttle, _ = control.run(blank)

    assert control.no_line_count == 1
    assert throttle == control.throttle_curve


def test_stopped_car_needs_three_consistent_frames_to_restart():
    cfg = make_cfg(ILLUMINATION_GUARD_ENABLED=False)
    control = controller(cfg)
    yellow = bgr_from_hsv(25, 120, 230)
    line = np.full((120, 160, 3), 180, dtype=np.uint8)
    line[100:110, 76:86] = yellow
    line[72:81, 76:86] = yellow
    blank = np.full((120, 160, 3), 180, dtype=np.uint8)

    for _index in range(control.reacquire_confirm_frames):
        control.run(line)
    for _index in range(control.no_line_stop_frames):
        control.run(blank)

    for _index in range(control.reacquire_confirm_frames - 1):
        steering, throttle, _ = control.run(line)
        assert steering == 0.0
        assert throttle == 0.0

    _steering, throttle, _ = control.run(line)
    assert throttle == control.throttle_min


def test_detects_the_same_tape_path_in_day_and_night():
    day = np.full((120, 160, 3), 205, dtype=np.uint8)
    night = np.full((120, 160, 3), 22, dtype=np.uint8)
    day_yellow = bgr_from_hsv(25, 145, 235)
    night_yellow = bgr_from_hsv(25, 145, 105)
    for image, yellow in ((day, day_yellow), (night, night_yellow)):
        image[98:110, 72:88] = yellow
        image[72:81, 66:77] = yellow

    day_control = controller()
    night_control = controller()
    day_x, day_confidence, _ = confirmed_detection(day_control, day)
    night_x, night_confidence, _ = confirmed_detection(night_control, night)

    assert abs(day_x - night_x) <= 1
    assert day_confidence >= 0.20
    assert night_confidence >= 0.20


def test_path_beats_large_isolated_yellow_patch_after_loss():
    image = np.full((120, 160, 3), 210, dtype=np.uint8)
    yellow = bgr_from_hsv(25, 145, 235)
    image[98:110, 52:68] = yellow
    image[72:81, 60:71] = yellow
    image[96:111, 132:154] = yellow  # isolated paint/leaf distraction

    control = controller()
    line_x, confidence, _ = confirmed_detection(control, image)

    assert 52 <= line_x <= 72
    assert confidence >= 0.20


def test_illumination_transition_stops_without_corrupting_tracker():
    control = controller()
    night = np.full((120, 160, 3), 30, dtype=np.uint8)
    yellow_night = bgr_from_hsv(25, 145, 105)
    night[98:110, 72:88] = yellow_night
    night[72:81, 66:77] = yellow_night

    for _index in range(control.reacquire_confirm_frames):
        control.run(night)
    tracked_x = control.previous_line_x
    assert tracked_x is not None

    bright = np.full((120, 160, 3), 220, dtype=np.uint8)
    yellow_day = bgr_from_hsv(25, 145, 235)
    bright[98:110, 72:88] = yellow_day
    bright[72:81, 66:77] = yellow_day
    bright[96:111, 132:154] = yellow_day

    steering, throttle, _ = control.run(bright)

    assert steering == 0.0
    assert throttle == 0.0
    assert control.illumination_hold_remaining > 0
    assert control.previous_line_x == tracked_x


def test_steady_night_does_not_trigger_illumination_guard():
    control = controller()
    night = np.full((120, 160, 3), 30, dtype=np.uint8)
    yellow = bgr_from_hsv(25, 145, 105)
    night[98:110, 72:88] = yellow
    night[72:81, 66:77] = yellow

    for _index in range(control.reacquire_confirm_frames):
        control.run(night)

    assert control.illumination_hold_remaining == 0
    assert control.previous_line_x is not None


def test_bounded_debug_capture_saves_raw_overlay_and_metadata(tmp_path):
    cfg = make_cfg(
        CV_DEBUG_CAPTURE=True,
        CV_DEBUG_CAPTURE_DIR=str(tmp_path),
        CV_DEBUG_CAPTURE_EVERY_N_FRAMES=2,
        CV_DEBUG_CAPTURE_MAX_FRAMES=3,
    )
    image = np.full((120, 160, 3), 90, dtype=np.uint8)
    yellow = bgr_from_hsv(25, 110, 220)
    image[98:110, 72:88] = yellow
    image[72:81, 66:77] = yellow
    control = controller(cfg)

    for _index in range(8):
        control.run(image)
    control.shutdown()

    sessions = list(tmp_path.glob("session_*"))
    assert len(sessions) == 1
    session = sessions[0]
    assert len(list(session.glob("*_raw.jpg"))) == 3
    assert len(list(session.glob("*_overlay.jpg"))) == 3
    records = [
        json.loads(line)
        for line in (session / "frames.jsonl").read_text().splitlines()
    ]
    assert len(records) == 3
    assert any(record["line_detected"] for record in records)
    assert all("scene_brightness" in record for record in records)
    assert (session / "session.json").exists()
