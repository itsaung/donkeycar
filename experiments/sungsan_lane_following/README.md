# Sungsan Two-Lane Following

This is an isolated lane-following experiment for the UCSD DonkeyCar track. It
does not replace the team's shared `myconfig.py`, `lane_follow.py`,
`lane_follower_part.py`, or the earlier Sungsan single-line experiment.

## Track model

The physical dashed yellow line divides two lanes. Each lane is bounded by the
yellow divider on one side and a solid white line on the other:

- `left`: white boundary on the left, yellow divider on the right
- `right`: yellow divider on the left, white boundary on the right

The controller detects markings in four perspective bands and fits a white and
yellow boundary track across those bands. The two tracks are evaluated at one
shared lookahead row, so dashed yellow and solid white evidence from different
heights can still define the selected lane centre. Implausible lane widths,
sudden jumps, and brown low-saturation ground evidence are rejected. The blue
rectangular tape satisfies neither the physical-yellow nor low-saturation-white
tests.

When one boundary is briefly hidden, the controller estimates the lane centre
from the remaining boundary and the calibrated lane width. When both boundaries
are lost, it decelerates and stops after five frames.

On a sharp curve the solid white boundary can appear almost horizontal and much
wider inside a scan band than it does on a straight. White components therefore
have a separate curve-aware width allowance. Autonomous throttle stays at zero
until a dual-boundary model is valid for three consecutive frames. After that
lock, a fitted solid-white track may bridge a short yellow gap using the most
recent measured lane width, capped at `0.20` throttle. Yellow-only evidence is
never allowed to drive, and the single-boundary permission expires after 40
frames without renewed dual-boundary evidence.

## Files

- `lane_following_controller_sungsan.py`: left/right lane detector and PID input
- `lane_following_drive_sungsan.py`: isolated DonkeyCar drive entry point
- `myconfig_lane_following_sungsan.py`: vehicle configuration, port, data path,
  thresholds, track geometry, PID, and conservative throttle
- `test_lane_following_controller_sungsan.py`: portable synthetic tests
- `validate_recorded_frames_sungsan.py`: replay tool for saved OAK-D frames

Personal runtime resources are also isolated:

```text
web port: 8893
data path: /home/pi/mycar/data_lane_following_sungsan
```

## Offline validation

The controller was validated without opening the camera, VESC, or motors:

- left and right lane-centre tests
- 160x120 and scaled OAK-D-resolution tests
- dashed yellow gap with single-boundary fallback
- blue-tape rejection and blue-only rejection
- wrong-side white-boundary rejection
- five-frame safe-stop behavior
- effective personal-config selection
- the supplied track photo
- four real OAK-D Tub sequences from the same physical track

Across 800 consecutive stored OAK-D frames (four 200-frame sequences), valid
lane estimates were produced for 749/800 left-lane frames and 748/800 right-lane
frames. Those frames were originally recorded for prior track work, so this is
an offline detector regression result, not a claim of completed physical
autonomous-lane testing.

## Install on the Raspberry Pi

Copy only these three new files to `/home/pi/mycar`:

```text
lane_following_controller_sungsan.py
lane_following_drive_sungsan.py
myconfig_lane_following_sungsan.py
```

Do not rename them and do not overwrite the shared team files.

## Run one selected lane

Make sure no other drive process owns the OAK-D camera or VESC. Start with the
wheels raised and AI steering only.

Left lane:

```bash
cd /home/pi/mycar
source /home/pi/env/bin/activate

python lane_following_drive_sungsan.py drive \
  --myconfig=myconfig_lane_following_sungsan.py \
  --lane=left \
  --log=INFO
```

Right lane:

```bash
python lane_following_drive_sungsan.py drive \
  --myconfig=myconfig_lane_following_sungsan.py \
  --lane=right \
  --log=INFO
```

Open `http://ucsdrobocar-DSC-T2.local:8893`. Use `local_angle` first: AI controls
steering and a human controls throttle. The overlay shows yellow boundary points,
white boundary points, cyan per-band lane centres, the final red lane centre,
and the green target. Switch to full `local` mode only after steering direction,
both lane selections, and line-loss stopping have been checked at raised-wheel
and low-speed physical tests.

The second overlay line reports the detected centre, camera target, number of
same-band yellow/white pairs, and the steering error normalized to the 160px PID
reference. The third line reports the cross-band model, drive lock, and age of
the last dual-boundary model. `MODEL:dual-tracks` is valid even when `PAIRS:0`
because it fits white and yellow tracks from different scan heights. A lone dot
must produce `MODEL:none`, `LOCK:0`, and zero autonomous throttle. If yellow
points appear on gravel, a wall, or the opposite outer white line, return to
`user` mode immediately and capture the overlay before tuning.

Web control is the default so a disconnected gamepad cannot stop the camera test.
Pass `--js` explicitly when the F710 is connected and should be used. The drive
entry point also applies an isolated DonkeyCar 5.3 OakD compatibility layer that
uses the 640x480 RGB preview and never opens a disabled depth stream.

## Replay stored frames

```bash
python validate_recorded_frames_sungsan.py /path/to/tub/images \
  --lane=left \
  --count=200
```

Use `--standard-jpeg` only for normal photos. Stored Tub frames from this OAK-D
setup need the default channel reconstruction.
