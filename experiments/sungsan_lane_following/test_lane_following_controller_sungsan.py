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
        LANE_SCAN_Y=52,
        LANE_SCAN_HEIGHT=10,
        LANE_SCAN_COUNT=4,
        LANE_SCAN_STEP=15,
        LANE_YELLOW_THRESHOLD_LOW=(18, 18, 35),
        LANE_YELLOW_THRESHOLD_HIGH=(35, 255, 255),
        LANE_WHITE_THRESHOLD_LOW=(0, 0, 135),
        LANE_WHITE_THRESHOLD_HIGH=(180, 70, 255),
        LANE_YELLOW_MIN_DOMINANCE=8,
        LANE_YELLOW_MAX_RG_DIFF=35,
        LANE_WHITE_MAX_CHANNEL_SPREAD=70,
        LANE_MIN_COMPONENT_AREA_PX=3,
        LANE_MAX_MARKING_WIDTH_PX=18,
        LANE_NOMINAL_WIDTH_PX=52,
        LANE_WIDTH_REFERENCE_Y=82,
        LANE_MIN_WIDTH_PX=20,
        LANE_MAX_WIDTH_PX=90,
        LANE_ACQUIRE_BOUNDARY_DISTANCE_PX=32,
        LANE_MAX_CENTER_JUMP_PX=30,
        LANE_MAX_BOUNDARY_JUMP_PX=30,
        LANE_MAX_BAND_CENTER_DEVIATION_PX=28,
        LANE_CENTER_SMOOTHING=0.0,
        LANE_NO_LINE_STOP_FRAMES=5,
        LANE_REACQUIRE_AFTER_FRAMES=5,
        TARGET_PIXEL=None,
        TARGET_THRESHOLD=10,
        THROTTLE_MIN=0.25,
        THROTTLE_INITIAL=0.25,
        THROTTLE_MAX=0.35,
        THROTTLE_STEP=0.02,
        LANE_NO_LINE_THROTTLE_STEP=0.05,
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


def test_invalid_lane_side_is_rejected():
    try:
        controller("middle")
    except ValueError as exc:
        assert "LANE_SIDE" in str(exc)
    else:
        raise AssertionError("invalid lane side should fail")
