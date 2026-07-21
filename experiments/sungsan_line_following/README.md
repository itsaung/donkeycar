# Sungsan Line-Following Experiment

This directory preserves the isolated line-following setup used on the Team 2
DonkeyCar. It does not replace the team's shared `myconfig.py`,
`line_follower.py`, `lane_follow.py`, or `lane_follower_part.py` files.

## Directory layout

- `vehicle_tested/` started from the controller and configuration used in the
  successful physical-car test on July 17, 2026. On July 20, its personal
  launcher was updated to isolate stable DonkeyCar 5.3.0, and its controller
  received the leaf-safe, adaptive day/night, sharp-curve, and curve-speed
  updates described below. The July 21 version also separates yellow tape
  from yellow-brown pavement under artificial light and uses a 426x240 OAK-D
  stream for this non-deep-learning controller. It passed recorded-frame replay,
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
- scan-band adaptive saturation masking that separates night pavement from
  the more saturated yellow tape before connected-component analysis
- 426x240 OAK-D RGB preview for the classical-CV controller, while retaining
  the original 160x120 calibration coordinate system for threshold scaling
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

Twenty-eight controller and launcher tests pass, including stable day/night detection,
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

## July 20 two-piece edge recovery follow-up

The next physical run stopped with `CONF=0`, `THROTTLE=0`, and `LOST=179`
even though two yellow dashes were still visible at the right edge. The saved
session showed successful tracking at `x=605` shortly before the loss. Once
the lowest dash left the camera ROI, only two strong tape components remained:
the replayed stop frame contained candidates near x=580 and x=656 with tape
quality 1.00/0.99 and saturation 119/78. The old far-edge rule required three
components after any complete loss, so it rejected both forever.

The revised rule keeps the three-component requirement when starting without
history. After recent tracking, it may accept two components only when the
candidate stays within 25 reference pixels of the last tracked line and has
at least 0.90 tape quality. The normal three-frame confirmation is still
required before moving. Replaying the physical stop frame now selects the
real x=580 tape with history, while the same two-piece frame remains rejected
without history.

The run also exposed frequent isolated one-frame misses that reduced throttle
from 0.21 to 0.12, below the drivetrain threshold. One missed frame now keeps
the conservative 0.21 curve throttle; the car still decelerates on the second
miss and fully stops on the third. This removes single-frame motor dropouts
without extending the three-frame safety stop.

## July 20 tape-shape and stale-steering update

Recorded frames from the blue-rectangle section showed that the blue paint was
not classified as yellow. The actual false candidates were low-saturation
beige pavement textures, scattered yellow leaves, and vegetation beside the
track. Those fragments sometimes formed a geometrically plausible path. After
one was selected, the controller also retained the previous left steering
command during missed frames, which made the car continue leaving the track.

The selection stage now requires the anchor component to have at least 50 mean
saturation, a 0.45 component fill ratio, and a sufficiently low position in
the road ROI. These checks reject sparse leaf clusters and pavement texture
without narrowing the calibrated day/night HSV range. Farther tape pieces can
still support path fitting; the stricter shape checks apply to the selected
anchor that controls steering.

The evening stop frame contained one clean, centered yellow dash with mean
saturation 78.5 and fill ratio 0.89. A narrow exception now allows one such
high-quality centered dash to begin the normal three-frame confirmation. It
does not allow an arbitrary single yellow object: it must be within 12
reference pixels of the target, have at least 0.90 tape quality and 25
reference-pixel area, and pass the saturation, fill, and lower-ROI checks.

When no valid line is found, steering now decays by 65 percent per frame while
the existing throttle policy remains unchanged: one missed frame retains the
curve throttle, the second slows, and the third stops. For example, a stale
-0.47 left command becomes approximately -0.16, then -0.06, then zero instead
of continuing the turn.

Offline replay selects the centered evening dash at x=346, rejects the two
documented leaf clusters, chooses the actual yellow edge tape at x=644 instead
of left-side vegetation, and safely rejects the ambiguous blue-rectangle
approach frame. The previously fixed sharp curve at x=413 and history-aware
two-piece edge recovery at x=580 still pass.

## July 20 frozen-camera watchdog update

One evening run kept displaying the same frame while the Python process stayed
alive. Diagnostic capture stopped at frame 240 at 20:03:28, and the OAK-D
background thread stopped advancing even though the 20 Hz vehicle loop and web
server continued. The stock threaded OAK-D interface returns its last image
when no new frame is available, so the old overlay still showed throttle 0.27.
This was a DepthAI/USB frame-stream stall, not a yellow-line threshold failure.

The personal launcher now watches the OAK-D `frame_count` after `DriveMode` and
before the drivetrain. Commands remain at zero while the camera is starting.
After the first valid frame, if the counter is unchanged for 0.5 seconds, the
watchdog forces both steering and throttle to zero, marks the displayed image
as `CAMERA STALE - MOTOR STOP`, and ends the vehicle loop so normal part
shutdown can release the camera. A five-second startup timeout handles a
camera that never produces its first frame.

Three launcher tests verify startup blocking, normal command pass-through,
timer reset on a new frame, and the stale-frame stop. A motor-free live OAK-D
test armed the watchdog at frame 3 and processed 120 vehicle loops in 5.96
seconds without a false stop.

## July 21 artificial-light and 426x240 camera update

The evening recording showed a different failure from the earlier leaf and
blue-paint cases. Under the courtyard lights, the brown-gray pavement moved
inside the broad yellow HSV range. The road and the real tape then became one
very wide connected component. Width filtering correctly rejected that large
component, but because the tape was already merged into it, no tape candidate
remained and the car stayed stopped with `CONF=0`.

The mask now estimates the median saturation of every road scan band and
raises that band's minimum saturation by a bounded margin. At night the
effective mask threshold was typically 73-80, which removed the pavement
while retaining tape with roughly 94-127 mean saturation. In daylight the
same calculation naturally fell to roughly 20-31. This is one adaptive
day/night controller; it does not require separate afternoon and evening
configuration files.

Replaying all 22 readable evening samples at the requested 426x240 output
found the center tape after normal reacquisition confirmation and tracked it
through the remaining samples, including the motion-blurred frame. The saved
daylight leaf frames remained rejected, history-aware edge recovery still
selected the real tape, and the documented daylight edge tape remained
detectable. A synthetic 426x240 scaling regression was added as the 25th
controller test; the three launcher watchdog tests bring the total to 28.

For the non-deep-learning line follower, `IMAGE_W=426` and `IMAGE_H=240`.
`CV_REFERENCE_IMAGE_W=160` and `CV_REFERENCE_IMAGE_H=120` preserve all of the
existing scan, jump, and tape-size calibration by scaling it at runtime. The
OAK-D part now receives `IMAGE_W` and `IMAGE_H` from the vehicle template and
uses its on-device RGB preview output, avoiding transfer of a much larger ISP
frame merely to resize it on the Raspberry Pi. If a separate deep-learning
pipeline is introduced, its model input should be configured independently at
384x216 rather than changing this classical-CV controller's reference grid.

A motor-free hardware check returned eight distinct OAK-D frames, each with
shape `(240, 426, 3)`. The full launcher then completed 120 loops at 20 Hz with
a MOCK drivetrain; the camera watchdog armed at frame 2, the line follower
averaged 9.70 ms (12.94 ms maximum), and no stale-camera stop occurred.

## Restore the vehicle-tested files to the Raspberry Pi

Back up any existing personal files first, then copy the three files from
`vehicle_tested/` into `/home/sungsan/mycar`. The OAK-D resolution update also
requires the corresponding `donkeycar/parts/oak_d.py` and
`donkeycar/templates/complete.py` changes from this branch. The dedicated
Sungsan account is now the deployment target.

Run from the Raspberry Pi with:

```bash
cd /home/sungsan/mycar
source /home/sungsan/env/bin/activate
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
/home/sungsan/mycar/data_line_following_sungsan/debug_captures
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
