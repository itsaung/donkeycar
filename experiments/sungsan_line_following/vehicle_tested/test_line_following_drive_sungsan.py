import importlib.util
from pathlib import Path

import numpy as np


MODULE_PATH = Path(__file__).with_name("line_following_drive_sungsan.py")
SPEC = importlib.util.spec_from_file_location("sungsan_drive_watchdog", MODULE_PATH)
DRIVE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DRIVE)


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class FakeCamera:
    def __init__(self):
        self.frame_count = 0
        self.color_image = None


class FakeVehicle:
    def __init__(self):
        self.on = True


def watchdog(timeout=0.5, startup_timeout=5.0):
    clock = FakeClock()
    camera = FakeCamera()
    vehicle = FakeVehicle()
    part = DRIVE.CameraFrameWatchdog(
        camera,
        vehicle,
        timeout_seconds=timeout,
        startup_timeout_seconds=startup_timeout,
        time_fn=clock,
    )
    return part, clock, camera, vehicle


def test_waits_safely_for_initial_camera_frame():
    part, clock, _camera, vehicle = watchdog()

    steering, throttle, image = part.run(0.4, 0.27, None)

    assert (steering, throttle, image) == (0.0, 0.0, None)
    assert vehicle.on is True

    clock.now = 5.0
    steering, throttle, image = part.run(0.4, 0.27, None)

    assert (steering, throttle, image) == (0.0, 0.0, None)
    assert vehicle.on is False
    assert part.triggered is True


def test_fresh_camera_counter_allows_commands_then_stops_when_stale():
    part, clock, camera, vehicle = watchdog()
    overlay = np.zeros((120, 160, 3), dtype=np.uint8)
    camera.color_image = overlay
    camera.frame_count = 1

    steering, throttle, image = part.run(-0.2, 0.27, overlay)

    assert steering == -0.2
    assert throttle == 0.27
    assert image is overlay
    assert part.received_frame is True

    clock.now = 0.49
    steering, throttle, _image = part.run(-0.2, 0.27, overlay)
    assert steering == -0.2
    assert throttle == 0.27
    assert vehicle.on is True

    clock.now = 0.51
    steering, throttle, stopped_image = part.run(-0.2, 0.27, overlay)

    assert steering == 0.0
    assert throttle == 0.0
    assert vehicle.on is False
    assert stopped_image is not overlay
    assert np.any(stopped_image != overlay)


def test_new_frame_resets_stale_timer():
    part, clock, camera, vehicle = watchdog()
    image = np.zeros((120, 160, 3), dtype=np.uint8)
    camera.color_image = image
    camera.frame_count = 1
    part.run(0.1, 0.2, image)

    clock.now = 0.40
    camera.frame_count = 2
    steering, throttle, _image = part.run(0.1, 0.2, image)

    assert (steering, throttle) == (0.1, 0.2)
    assert vehicle.on is True

    clock.now = 0.85
    steering, throttle, _image = part.run(0.1, 0.2, image)
    assert (steering, throttle) == (0.1, 0.2)
    assert vehicle.on is True
