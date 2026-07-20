# Sungsan Line-Following Experiment

This directory preserves the isolated line-following setup used on the Team 2
DonkeyCar. It does not replace the team's shared `myconfig.py`,
`line_follower.py`, `lane_follow.py`, or `lane_follower_part.py` files.

## Directory layout

- `vehicle_tested/` started from the controller and configuration used in the
  successful physical-car test on July 17, 2026. On July 20, its personal
  launcher was updated to isolate stable DonkeyCar 5.3.0, and its controller
  received the leaf-safe and adaptive day/night updates described below. The
  latest version passed synthetic regression tests and live OAK-D processing
  with a mock drivetrain. It still requires controlled physical passes in
  daylight and at night before being labelled fully track-validated.
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
- multi-piece path fitting so isolated leaves and painted patches do not win
- relative illumination-change detection without changing the night HSV range
- bounded asynchronous raw/overlay diagnostic capture
- physically tested PID and throttle settings

## July 20 leaf-safe sharp-curve update

Daylight screenshots showed that yellow leaves near the center of the image
could outscore the real tape when the tape moved far right on a sharp curve.
The update adds:

- tape-quality scoring based on component width, area, saturation, and value
- a wider acquisition window for the real tape on sharp curves
- short-horizon line-motion prediction
- rejection of sudden opposite-side candidate jumps
- rejection of abrupt transitions from a tracked dash to a much smaller blob
- a lower near-road score weight so proximity to the camera alone cannot make
  a leaf win

The later adaptive update keeps the calibrated night HSV and dominance values
unchanged. It merges overlapping scan bands into one road ROI, fits compatible
tape pieces to a path, rejects low-consistency reacquisition candidates, and
requires two matching frames after a complete loss. Large movements also need
path-direction consistency, while close single-piece tracking remains allowed
for brief low-visibility nighttime gaps.

The illumination guard measures relative brightness change inside the road
ROI. A dark-to-light or light-to-dark transition stops throttle and steering
for a short exposure-recovery window instead of steering toward a transient
false candidate. It is not a daylight-only brightness threshold.

Eleven synthetic-image tests pass, including stable day/night detection,
leaf and painted-patch rejection, illumination-transition stopping, sharp
curve motion, safe stopping, and bounded diagnostic capture. Live OAK-D
frames from the daylight test initially exposed two false-candidate bugs; the
final candidate tracked the center tape at x=352 and x=342 while ignoring the
right leaf and left vegetation. The controller averaged about 13 ms at 20 Hz
with a mock drivetrain. A later repeated camera restart produced an OAK-D
X_LINK transport error, after which the device returned normally as
X_LINK_UNBOOTED; this was not a controller exception.

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

## Diagnostic capture

The current personal controller saves diagnostic data in a background thread
so image writing does not block the control loop. At 20 Hz it records one
periodic sample every 40 frames (about one sample every two seconds), plus
line-state and illumination transitions. Each run is capped at 500 samples.

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

The older `experimental_debug_capture/` directory remains as a historical,
higher-rate capture-only variant. Do not label the latest adaptive controller
as fully vehicle-tested until it completes controlled daylight and nighttime
track runs.

## Integrity

`vehicle_tested/SHA256.txt` records the SHA-256 hashes read on the Raspberry Pi
and verified again after transfer.

Both variants include portable synthetic-image tests. The integrity hashes
cover only the three live personal files copied from the Raspberry Pi.
The verbatim snapshot intentionally retains any legacy trailing whitespace in
those files so that its hashes continue to match the working Pi copies.
