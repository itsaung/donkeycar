import runpy
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
from simple_pid import PID

from lane_following_controller_sungsan import LaneFollower


def make_cfg(side="left", **overrides):
    values = dict(
        LANE_SIDE=side,
        CV_INPUT_COLOR_ORDER="BGR",
        IMAGE_W=160,
        IMAGE_H=120,
        LANE_SCAN_Y=68,
        LANE_SCAN_HEIGHT=8,
        LANE_SCAN_COUNT=4,
        LANE_SCAN_STEP=12,
        LANE_YELLOW_THRESHOLD_LOW=(18, 45, 45),
        LANE_YELLOW_THRESHOLD_HIGH=(35, 255, 255),
        LANE_WHITE_THRESHOLD_LOW=(0, 0, 135),
        LANE_WHITE_THRESHOLD_HIGH=(180, 70, 255),
        LANE_YELLOW_MIN_DOMINANCE=15,
        LANE_YELLOW_MAX_RG_DIFF=40,
        LANE_WHITE_MAX_CHANNEL_SPREAD=70,
        LANE_MIN_COMPONENT_AREA_PX=3,
        LANE_MAX_MARKING_WIDTH_PX=18,
        LANE_WHITE_MAX_MARKING_WIDTH_PX=70,
        LANE_NOMINAL_WIDTH_PX=52,
        LANE_WIDTH_REFERENCE_Y=82,
        LANE_MIN_WIDTH_PX=20,
        LANE_MAX_WIDTH_PX=75,
        LANE_ACQUIRE_BOUNDARY_DISTANCE_PX=32,
        LANE_CURVE_REACQUIRE_DISTANCE_PX=75,
        LANE_MAX_CENTER_JUMP_PX=30,
        LANE_MAX_BOUNDARY_JUMP_PX=30,
        LANE_MAX_BAND_CENTER_DEVIATION_PX=28,
        LANE_CENTER_SMOOTHING=0.0,
        LANE_STEERING_LIMIT=0.65,
        LANE_MAX_STEERING_STEP=0.20,
        LANE_NO_LINE_STOP_FRAMES=5,
        LANE_REACQUIRE_AFTER_FRAMES=5,
        TARGET_PIXEL=None,
        TARGET_THRESHOLD=10,
        THROTTLE_MIN=0.25,
        THROTTLE_INITIAL=0.25,
        THROTTLE_MAX=0.35,
        THROTTLE_STEP=0.02,
        LANE_NO_LINE_THROTTLE_STEP=0.05,
        LANE_SINGLE_BOUNDARY_THROTTLE=0.20,
        OVERLAY_IMAGE=True,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def controller(side="left", **overrides):
    return LaneFollower(PID(-0.01, 0.0, -0.0001), make_cfg(side, **overrides))


def lane_image(side="left", scale=1.0, blue_tape=False):
    width, height = int(160 * scale), int(120 * scale)
    image = np.full((height, width, 3), (92, 92, 92), dtype=np.uint8)

    def point(x, y):
        return int(x * scale), int(y * scale)

    thickness = max(2, int(round(3 * scale)))
    if side == "left":
        white_top, white_bottom = point(58, 42), point(34, 119)
        yellow_top, yellow_bottom = point(102, 42), point(126, 119)
    else:
        yellow_top, yellow_bottom = point(58, 42), point(34, 119)
        white_top, white_bottom = point(102, 42), point(126, 119)

    cv2.line(image, white_top, white_bottom, (235, 235, 235), thickness)
    for y0 in (42, 66, 90):
        ratio0 = (y0 - 42) / 77
        ratio1 = (min(y0 + 14, 119) - 42) / 77
        x0 = yellow_top[0] / scale + ratio0 * (
            yellow_bottom[0] / scale - yellow_top[0] / scale
        )
        x1 = yellow_top[0] / scale + ratio1 * (
            yellow_bottom[0] / scale - yellow_top[0] / scale
        )
        cv2.line(
            image,
            point(x0, y0),
            point(x1, min(y0 + 14, 119)),
            (0, 225, 225),
            thickness,
        )

    if blue_tape:
        cv2.rectangle(image, point(68, 86), point(94, 112), (255, 0, 0), -1)
    return image


def shifted_lane_image(side, scale, shift_ref):
    image = lane_image(side, scale=scale)
    matrix = np.float32([[1, 0, shift_ref * scale], [0, 1, 0]])
    return cv2.warpAffine(
        image,
        matrix,
        (image.shape[1], image.shape[0]),
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(92, 92, 92),
    )


def white_only_sharp_curve():
    image = np.full((120, 160, 3), (92, 92, 92), dtype=np.uint8)
    points = np.asarray(
        [(0, 112), (42, 102), (88, 91), (128, 82), (159, 75)],
        dtype=np.int32,
    )
    cv2.polylines(image, [points], False, (235, 235, 235), 3)
    return image


def test_left_lane_uses_white_left_and_yellow_right():
    follower = controller("left")
    steering, throttle, overlay = follower.run(lane_image("left"))

    assert follower._debug["center"] is not None
    assert abs(follower._debug["center"] - 80) < 6
    assert any(item.paired for item in follower._debug["observations"])
    assert abs(steering) < 0.1
    assert throttle > 0.25
    assert overlay.shape == (120, 160, 3)


def test_right_lane_uses_yellow_left_and_white_right():
    follower = controller("right")
    steering, _, _ = follower.run(lane_image("right"))

    assert follower._debug["center"] is not None
    assert abs(follower._debug["center"] - 80) < 6
    assert any(item.paired for item in follower._debug["observations"])
    assert abs(steering) < 0.1


def test_blue_tape_is_ignored_for_both_lanes():
    for side in ("left", "right"):
        follower = controller(side)
        follower.run(lane_image(side, blue_tape=True))
        assert follower._debug["center"] is not None
        assert abs(follower._debug["center"] - 80) < 6


def test_resolution_scaling_preserves_lane_center():
    follower = controller("right")
    follower.run(lane_image("right", scale=4.0))

    assert follower._debug["center"] is not None
    assert abs(follower._debug["center"] - 320) < 24


def test_pid_steering_is_resolution_invariant():
    low = LaneFollower(PID(-0.01, 0.0, 0.0), make_cfg("left"))
    high = LaneFollower(PID(-0.01, 0.0, 0.0), make_cfg("left"))

    low_steering, _, _ = low.run(shifted_lane_image("left", 1.0, 8))
    high_steering, _, _ = high.run(shifted_lane_image("left", 4.0, 8))

    assert 0.04 < abs(low_steering) < 0.15
    assert abs(low_steering - high_steering) < 0.02


def test_far_yellow_candidate_cannot_replace_left_lane_divider():
    image = lane_image("left")
    yellow_pixels = (
        (image[:, :, 0] < 20)
        & (image[:, :, 1] > 200)
        & (image[:, :, 2] > 200)
    )
    image[yellow_pixels] = (92, 92, 92)
    cv2.line(image, (145, 42), (150, 119), (30, 180, 180), 3)

    follower = controller("left")
    follower.run(image)

    assert follower._debug["center"] is not None
    assert follower._debug["center"] < 90
    assert all(
        item.yellow_x is None for item in follower._debug["observations"]
    )


def test_left_lane_reacquires_wide_white_boundary_on_sharp_curve():
    follower = controller("left")
    follower.run(lane_image("left"))
    blank = np.full((120, 160, 3), (92, 92, 92), dtype=np.uint8)
    for _ in range(5):
        follower.run(blank)

    steering, throttle, _ = follower.run(white_only_sharp_curve())

    assert follower._debug["center"] is not None
    assert follower.lost_frames == 0
    assert follower._debug["observations"]
    assert all(
        item.white_x is not None and item.yellow_x is None
        for item in follower._debug["observations"]
    )
    assert 0.0 < abs(steering) <= 0.20
    assert throttle == 0.20


def test_single_yellow_boundary_bridges_a_white_gap():
    image = lane_image("left")
    white = np.all(image == (235, 235, 235), axis=2)
    image[white] = (92, 92, 92)
    follower = controller("left")
    follower.run(image)

    assert follower._debug["center"] is not None
    assert all(not item.paired for item in follower._debug["observations"])


def test_missing_lane_decelerates_then_stops_safely():
    follower = controller("left")
    follower.run(lane_image("left"))
    blank = np.full((120, 160, 3), 92, dtype=np.uint8)

    for _ in range(5):
        steering, throttle, _ = follower.run(blank)

    assert steering == 0.0
    assert throttle == 0.0
    assert follower.lost_frames == 5


def test_blue_only_scene_never_becomes_a_lane():
    follower = controller("right")
    image = np.full((120, 160, 3), 92, dtype=np.uint8)
    cv2.rectangle(image, (10, 45), (150, 118), (255, 0, 0), -1)
    follower.run(image)

    assert follower._debug["center"] is None
    assert follower.lost_frames == 1


def test_wrong_side_white_edge_is_not_used_after_yellow_gap():
    follower = controller("left")
    follower.run(lane_image("left"))
    image = np.full((120, 160, 3), 92, dtype=np.uint8)
    cv2.line(image, (135, 45), (145, 119), (235, 235, 235), 3)
    follower.run(image)

    assert follower._debug["center"] is None
    assert follower.lost_frames == 1


def test_personal_config_finally_selects_lane_controller():
    config_path = Path(__file__).with_name("myconfig_lane_following_sungsan.py")
    values = runpy.run_path(str(config_path))

    assert values["CV_CONTROLLER_MODULE"] == "lane_following_controller_sungsan"
    assert values["WEB_CONTROL_PORT"] == 8893
    assert values["DATA_PATH"].endswith("data_lane_following_sungsan")
    assert values["CV_INPUT_COLOR_ORDER"] == "BGR"
    assert values["OAKD_DEPTH"] is False
    assert values["USE_JOYSTICK_AS_DEFAULT"] is False
    assert values["LANE_YELLOW_THRESHOLD_LOW"] == (18, 45, 45)
    assert values["LANE_STEERING_LIMIT"] == 0.65
    assert values["LANE_WHITE_MAX_MARKING_WIDTH_PX"] == 70
    assert values["LANE_CURVE_REACQUIRE_DISTANCE_PX"] == 75


def test_invalid_lane_side_is_rejected():
    try:
        controller("middle")
    except ValueError as exc:
        assert "LANE_SIDE" in str(exc)
    else:
        raise AssertionError("invalid lane side should fail")
