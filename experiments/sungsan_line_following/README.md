# Sungsan Line-Following Experiment

This directory preserves the isolated line-following setup used on the Team 2
DonkeyCar. It does not replace the team's shared `myconfig.py`,
`line_follower.py`, `lane_follow.py`, or `lane_follower_part.py` files.

## Directory layout

- `vehicle_tested/` started from the controller and configuration used in the
  successful physical-car test on July 17, 2026. On July 20, its personal
  launcher was updated to isolate stable DonkeyCar 5.3.0, and its controller
  received the leaf-safe, adaptive day/night, sharp-curve, and curve-speed
  updates described below. The latest version passed recorded-frame replay,
  synthetic regression tests, and live OAK-D processing with a mock
  drivetrain. It still requires a controlled physical pass after the latest
  speed change before being labelled fully track-validated.
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
- smoothed line position and safe stopping after three missed frames
- multi-piece path fitting so isolated leaves and painted patches do not win
- relative illumination-change detection without changing the night HSV range
- gradual acceleration to 0.27 on straights and early braking toward 0.21 on
  curves, using both steering demand and the fitted tape-path slope
- stricter three-frame, saturation, and path-support checks only when
  reacquiring after a complete loss
- bounded asynchronous raw/overlay diagnostic capture
- the physically tested PID settings, with a new conservative throttle policy

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

Sixteen synthetic-image tests pass, including stable day/night detection,
leaf and painted-patch rejection, illumination-transition stopping, sharp
curve motion, edge reacquisition, curve-aware braking, safe stopping, and
bounded diagnostic capture. Live OAK-D
frames from the daylight test initially exposed two false-candidate bugs; the
final candidate tracked the center tape at x=352 and x=342 while ignoring the
right leaf and left vegetation. The controller averaged about 13 ms at 20 Hz
with a mock drivetrain. A later repeated camera restart produced an OAK-D
X_LINK transport error, after which the device returned normally as
X_LINK_UNBOOTED; this was not a controller exception.

## July 20 recorded-run curve and speed update

The saved driving session showed that the difficult corner was not primarily
an exposure failure: road brightness stayed roughly stable while throttle had
already risen to 0.35. At frame 179, three visible yellow tape pieces formed a
steep path, but the old path-slope limit of 1.5 split them apart. The car
briefly reacquired the tape at frame 185, too late to make the turn, and by
frame 200 the yellow line was almost outside the camera view.

The current update therefore:

- raises the geometric path-slope limit from 1.5 to 3.5 without changing the
  calibrated day/night HSV thresholds
- rejects low-saturation wall or white-paint fragments during reacquisition
- requires three connected pieces before reacquiring a far-edge candidate,
  while normal ongoing tracking can still follow a real edge curve
- starts strict reacquisition as soon as the three-frame stop point is reached
  and requires three consistent frames before moving again
- caps straight throttle at 0.27, starts at 0.22, and targets 0.21 on curves
- accelerates by only 0.005 per loop but brakes by 0.02 per loop
- uses both steering magnitude and fitted path slope to slow before the
  steering error becomes large
- removes throttle by 0.09 per missed frame and fully stops after three misses

Offline replay of the original failed frame now selects the connected yellow
path at x=413 with three-piece support and a fitted slope near -1.97, instead
of the low-saturation wall fragments at x=46. Ambiguous two-piece far-edge
candidates stop safely; a three-piece far-edge yellow path can reacquire.

The exact candidate then completed 60 OAK-D frames at 20 Hz with a MOCK
drivetrain, averaging about 16 ms in the controller. The first test metadata
confirmed the earlier conservative values `THROTTLE_STRAIGHT=0.22`,
`THROTTLE_CURVE=0.16`, and `PATH_MAX_SLOPE=3.5`. The drivetrain was never
connected during this test.

## July 20 drivetrain torque follow-up

A physical screenshot after the conservative speed update showed
`CONF=0.512`, `LOST=0`, `CURVE=1.00`, and `THROTTLE=0.16`. The vision system
was confidently tracking the yellow tape, but the car did not move. This
isolated the stop as a drivetrain breakaway-torque issue rather than another
line-detection failure: 0.16 was too low to start the car while its front
wheels were turned.

The current balanced values are:

- 0.22 initial throttle
- 0.27 maximum straight throttle
- 0.21 curve and low-confidence throttle
- 0.005 acceleration step and 0.02 braking step
- 0.09 reduction per missed frame, still stopping after three misses

These remain below the earlier fast 0.35 straight speed, while the 0.21 curve
command is intended to stay above the observed 0.16 drivetrain dead zone.
The exact breakaway threshold can vary with battery charge and steering load,
so the current values still require a controlled physical lap.

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
- `frames.jsonl`: line position, confidence, steering, throttle, fitted path
  slope, curve strength, desired throttle, and state
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
higher-rate capture-only variant. Do not label the latest curve-speed version
as fully vehicle-tested until it completes a controlled physical track run;
daylight and nighttime rechecks are still recommended.

## Integrity

`vehicle_tested/SHA256.txt` records the SHA-256 hashes read on the Raspberry Pi
and verified again after transfer.

Both variants include portable synthetic-image tests. The integrity hashes
cover only the three live personal files copied from the Raspberry Pi.
The verbatim snapshot intentionally retains any legacy trailing whitespace in
those files so that its hashes continue to match the working Pi copies.
