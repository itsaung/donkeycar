# Sungsan Line-Following Experiment

This directory preserves the isolated line-following setup used on the Team 2
DonkeyCar. It does not replace the team's shared `myconfig.py`,
`line_follower.py`, `lane_follow.py`, or `lane_follower_part.py` files.

## Directory layout

- `vehicle_tested/` preserves the controller and configuration from the
  successful physical-car test on July 17, 2026. On July 20, its personal
  launcher was updated to isolate the stable DonkeyCar 5.3.0 package from a
  conflicting local 5.3.dev1 checkout. The launcher update passed a 40-frame
  OAK-D test with a mock drivetrain; it did not change the vision behavior.
- `experimental_debug_capture/` starts from the same controller and settings,
  then adds asynchronous diagnostic image capture. Its unit tests pass, but
  this capture-enabled variant has not yet completed a physical driving test.

## Vehicle-tested behavior

The preserved configuration includes:

- OAK-D input treated as BGR (`CV_INPUT_COLOR_ORDER = "BGR"`)
- stable virtual-environment DonkeyCar package isolation in the personal
  launcher, while retaining access to `line_following_controller_sungsan.py`
- BGR-to-HSV conversion for line detection
- yellow-tape HSV range `(18, 18, 35)` through `(35, 255, 255)`
- yellow color-dominance filtering to reject gray and cyan candidates
- resolution-aware scan bands with an extra lower/upper scan row
- connected-component filtering for speckles and broad wall regions
- acquisition and tracking distance limits
- deeper-road candidate preference for curves
- smoothed line position and safe stopping after five missed frames
- physically tested PID and throttle settings

## Restore the vehicle-tested files to the Raspberry Pi

Back up any existing personal files first, then copy the three files from
`vehicle_tested/` into `/home/pi/mycar`. These filenames are intentionally
Sungsan-specific so the team files remain untouched.

Run from the Raspberry Pi with:

```bash
cd /home/pi/mycar
source /home/pi/env/bin/activate
python line_following_drive_sungsan.py drive \
  --myconfig=myconfig_line_following_sungsan.py \
  --log=INFO
```

The personal web controller uses port `8892`.

Before driving, confirm that no teammate is using the OAK-D camera:

```bash
pgrep -af "python.*(drive|follow)"
```

Only one driving process should use the camera. Test with the wheels raised
before placing the car on the track.

## Experimental diagnostic capture

The `experimental_debug_capture/` controller saves diagnostic data in a
background thread so image writing does not block the control loop. The
configuration records about two samples per second at a 20 Hz loop and also
records line-lost and line-reacquired transitions.

Each session creates:

- `*_raw.jpg`: original BGR camera frame
- `*_overlay.jpg`: web/debug overlay
- `frames.jsonl`: line position, confidence, steering, throttle, and state
- `session.json`: capture and vision settings

The configured output root is:

```text
/home/pi/mycar/data_line_following_sungsan/debug_captures
```

Run its portable unit tests from this directory with:

```bash
python -m pytest -q test_line_following_controller_sungsan.py
```

Do not label the automatic-capture variant as vehicle-tested until it has
completed a controlled wheels-up check and a physical track run.

## Integrity

`vehicle_tested/SHA256.txt` records the SHA-256 hashes read on the Raspberry Pi
and verified again after transfer.

Both variants include portable synthetic-image tests. The integrity hashes
cover only the three live personal files copied from the Raspberry Pi.
The verbatim snapshot intentionally retains any legacy trailing whitespace in
those files so that its hashes continue to match the working Pi copies.
